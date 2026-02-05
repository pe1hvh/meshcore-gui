"""
BLE communication worker for MeshCore GUI.

Runs in a separate thread with its own asyncio event loop.  Connects
to the MeshCore device, wires up collaborators, and runs the command
processing loop.

Responsibilities deliberately kept narrow (SRP):
    - Thread lifecycle and asyncio loop
    - BLE connection and initial data loading
    - Wiring CommandHandler and EventHandler

Command execution  → :mod:`meshcore_gui.ble.commands`
Event handling     → :mod:`meshcore_gui.ble.events`
Packet decoding    → :mod:`meshcore_gui.ble.packet_decoder`
Bot logic          → :mod:`meshcore_gui.services.bot`
Deduplication      → :mod:`meshcore_gui.services.dedup`
Cache              → :mod:`meshcore_gui.services.cache`

v5.1 changes
~~~~~~~~~~~~~
- Cache-first startup: GUI is populated instantly from disk cache.
- Background BLE refresh updates cache + SharedData incrementally.
- Periodic contact refresh every ``CONTACT_REFRESH_SECONDS``.
- Channel keys are cached to disk for instant packet decoding.
- Background key retry: missing channel keys are retried every
  ``KEY_RETRY_INTERVAL`` seconds until all keys are loaded.
"""

import asyncio
import threading
import time
from typing import Optional, Set

from meshcore import MeshCore, EventType

from meshcore_gui.config import (
    CHANNELS_CONFIG,
    CONTACT_REFRESH_SECONDS,
    debug_print,
)
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.ble.commands import CommandHandler
from meshcore_gui.ble.events import EventHandler
from meshcore_gui.ble.packet_decoder import PacketDecoder
from meshcore_gui.services.bot import BotConfig, MeshBot
from meshcore_gui.services.cache import DeviceCache
from meshcore_gui.services.dedup import DualDeduplicator


# Seconds between background retry attempts for missing channel keys.
KEY_RETRY_INTERVAL: float = 30.0


class BLEWorker:
    """BLE communication worker that runs in a separate thread.

    Args:
        address: BLE MAC address (e.g. ``"literal:AA:BB:CC:DD:EE:FF"``).
        shared:  SharedDataWriter for thread-safe communication.
    """

    def __init__(self, address: str, shared: SharedDataWriter) -> None:
        self.address = address
        self.shared = shared
        self.mc: Optional[MeshCore] = None
        self.running = True

        # Local cache (one file per device)
        self._cache = DeviceCache(address)

        # Collaborators (created eagerly, wired after connection)
        self._decoder = PacketDecoder()
        self._dedup = DualDeduplicator(max_size=200)
        self._bot = MeshBot(
            config=BotConfig(),
            command_sink=shared.put_command,
            enabled_check=shared.is_bot_enabled,
        )

        # Channel indices that still need keys from device
        self._pending_keys: Set[int] = set()

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker in a new daemon thread."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        debug_print("BLE worker thread started")

    def _run(self) -> None:
        asyncio.run(self._async_main())

    async def _async_main(self) -> None:
        await self._connect()
        if self.mc:
            last_contact_refresh = time.time()
            last_key_retry = time.time()

            while self.running:
                await self._cmd_handler.process_all()

                now = time.time()

                # Periodic contact refresh
                if now - last_contact_refresh > CONTACT_REFRESH_SECONDS:
                    await self._refresh_contacts()
                    last_contact_refresh = now

                # Background key retry for missing channels
                if self._pending_keys and now - last_key_retry > KEY_RETRY_INTERVAL:
                    await self._retry_missing_keys()
                    last_key_retry = now

                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Connection (cache-first)
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        # Phase 1: Load cache → GUI is instantly populated
        if self._cache.load():
            self._apply_cache()
            print("BLE: Cache loaded — GUI populated from disk")
        else:
            print("BLE: No cache found — waiting for BLE data")

        # Phase 2: Connect BLE
        self.shared.set_status(f"🔄 Connecting to {self.address}...")
        try:
            print(f"BLE: Connecting to {self.address}...")
            self.mc = await MeshCore.create_ble(self.address)
            print("BLE: Connected!")

            await asyncio.sleep(1)

            # Wire collaborators now that mc is available
            self._evt_handler = EventHandler(
                shared=self.shared,
                decoder=self._decoder,
                dedup=self._dedup,
                bot=self._bot,
            )
            self._cmd_handler = CommandHandler(mc=self.mc, shared=self.shared)
            self._cmd_handler.set_load_data_callback(self._load_data)

            # Subscribe to events
            self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._evt_handler.on_channel_msg)
            self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._evt_handler.on_contact_msg)
            self.mc.subscribe(EventType.RX_LOG_DATA, self._evt_handler.on_rx_log)

            # Phase 3: Load data and keys from device (updates cache)
            await self._load_data()
            await self._load_channel_keys()
            await self.mc.start_auto_message_fetching()

            self.shared.set_connected(True)
            self.shared.set_status("✅ Connected")
            print("BLE: Ready!")

            if self._pending_keys:
                pending_names = [
                    f"[{ch['idx']}] {ch['name']}"
                    for ch in CHANNELS_CONFIG
                    if ch['idx'] in self._pending_keys
                ]
                print(
                    f"BLE: ⏳ Background retry active for: "
                    f"{', '.join(pending_names)} "
                    f"(every {KEY_RETRY_INTERVAL:.0f}s)"
                )

        except Exception as e:
            print(f"BLE: Connection error: {e}")
            if self._cache.has_cache:
                self.shared.set_status(f"⚠️ Offline — using cached data ({e})")
            else:
                self.shared.set_status(f"❌ {e}")

    # ------------------------------------------------------------------
    # Apply cache to SharedData
    # ------------------------------------------------------------------

    def _apply_cache(self) -> None:
        """Push cached data to SharedData so GUI renders immediately."""
        device = self._cache.get_device()
        if device:
            self.shared.update_from_appstart(device)
            # Firmware version may be stored under 'ver' or 'firmware_version'
            fw = device.get("firmware_version") or device.get("ver")
            if fw:
                self.shared.update_from_device_query({"ver": fw})
            self.shared.set_status("📦 Loaded from cache")
            debug_print(f"Cache → device info: {device.get('name', '?')}")

        channels = self._cache.get_channels()
        if channels:
            self.shared.set_channels(channels)
            debug_print(f"Cache → channels: {[c['name'] for c in channels]}")

        contacts = self._cache.get_contacts()
        if contacts:
            self.shared.set_contacts(contacts)
            debug_print(f"Cache → contacts: {len(contacts)}")

        # Restore channel keys for instant packet decoding
        cached_keys = self._cache.get_channel_keys()
        for idx_str, secret_hex in cached_keys.items():
            try:
                idx = int(idx_str)
                secret_bytes = bytes.fromhex(secret_hex)
                if len(secret_bytes) >= 16:
                    self._decoder.add_channel_key(idx, secret_bytes[:16], source="cache")
                    debug_print(f"Cache → channel key [{idx}]")
            except (ValueError, TypeError) as exc:
                debug_print(f"Cache → bad channel key [{idx_str}]: {exc}")

    # ------------------------------------------------------------------
    # Initial data loading (refreshes cache)
    # ------------------------------------------------------------------

    async def _load_data(self) -> None:
        """Load device info, channels and contacts from device.

        Updates both SharedData (for GUI) and the disk cache.
        Uses longer delays between retries because BLE command/response
        over the meshcore library is unreliable with short intervals.
        """
        # send_appstart (retries with longer delays)
        self.shared.set_status("🔄 Device info...")
        appstart_ok = False
        for i in range(10):
            debug_print(f"send_appstart attempt {i + 1}/10")
            try:
                r = await self.mc.commands.send_appstart()
                if r.type != EventType.ERROR:
                    print(f"BLE: send_appstart OK: {r.payload.get('name')} (attempt {i + 1})")
                    self.shared.update_from_appstart(r.payload)
                    self._cache.set_device(r.payload)
                    appstart_ok = True
                    break
            except Exception as exc:
                debug_print(f"send_appstart attempt {i + 1} exception: {exc}")
            await asyncio.sleep(1.0)

        if not appstart_ok:
            print("BLE: ⚠️  send_appstart failed after 10 attempts")

        # send_device_query (retries)
        for i in range(10):
            debug_print(f"send_device_query attempt {i + 1}/10")
            try:
                r = await self.mc.commands.send_device_query()
                if r.type != EventType.ERROR:
                    fw = r.payload.get("ver", "")
                    print(f"BLE: send_device_query OK: {fw} (attempt {i + 1})")
                    self.shared.update_from_device_query(r.payload)
                    if fw:
                        self._cache.set_firmware_version(fw)
                    break
            except Exception as exc:
                debug_print(f"send_device_query attempt {i + 1} exception: {exc}")
            await asyncio.sleep(1.0)

        # Channels (hardcoded — BLE get_channel is unreliable)
        self.shared.set_status("🔄 Channels...")
        self.shared.set_channels(CHANNELS_CONFIG)
        self._cache.set_channels(CHANNELS_CONFIG)
        print(f"BLE: Channels loaded: {[c['name'] for c in CHANNELS_CONFIG]}")

        # Contacts (merge with cache)
        self.shared.set_status("🔄 Contacts...")
        try:
            r = await self.mc.commands.get_contacts()
            if r.type != EventType.ERROR:
                merged = self._cache.merge_contacts(r.payload)
                self.shared.set_contacts(merged)
                print(
                    f"BLE: Contacts — {len(r.payload)} from device, "
                    f"{len(merged)} total (with cache)"
                )
            else:
                debug_print("BLE: get_contacts failed, keeping cached contacts")
        except Exception as exc:
            debug_print(f"BLE: get_contacts exception: {exc}")

    # ------------------------------------------------------------------
    # Channel key loading (quick startup + background retry)
    # ------------------------------------------------------------------

    async def _load_channel_keys(self) -> None:
        """Try to load channel keys from device — quick pass at startup.

        Each channel gets 2 quick attempts.  Channels that fail are
        added to ``_pending_keys`` for background retry every
        ``KEY_RETRY_INTERVAL`` seconds.

        Priority:
        1. Key from device (get_channel → channel_secret)
        2. Key already in cache (preserved, not overwritten)
        3. Key derived from channel name (last resort, only if no cache)
        """
        self.shared.set_status("🔄 Channel keys...")
        cached_keys = self._cache.get_channel_keys()

        confirmed: list[str] = []
        from_cache: list[str] = []
        pending: list[str] = []
        derived: list[str] = []

        for ch_num, ch in enumerate(CHANNELS_CONFIG):
            idx, name = ch['idx'], ch['name']

            # Quick startup attempt: 2 tries per channel
            loaded = await self._try_load_channel_key(idx, name, max_attempts=2, delay=1.0)

            if loaded:
                confirmed.append(f"[{idx}] {name}")
            elif str(idx) in cached_keys:
                # Cache has the key — don't overwrite with name-derived
                from_cache.append(f"[{idx}] {name}")
                print(f"BLE: 📦 Channel [{idx}] '{name}' — using cached key")
            else:
                # No device key, no cache key — derive from name as temporary fallback
                self._decoder.add_channel_key_from_name(idx, name)
                derived.append(f"[{idx}] {name}")
                # Mark for background retry
                self._pending_keys.add(idx)
                print(f"BLE: ⚠️  Channel [{idx}] '{name}' — name-derived key (will retry)")

            # Brief pause between channels
            if ch_num < len(CHANNELS_CONFIG) - 1:
                await asyncio.sleep(0.5)

        # Summary
        print(f"BLE: PacketDecoder ready — has_keys={self._decoder.has_keys}")
        if confirmed:
            print(f"BLE: ✅ From device: {', '.join(confirmed)}")
        if from_cache:
            print(f"BLE: 📦 From cache: {', '.join(from_cache)}")
        if derived:
            print(f"BLE: ⚠️  Name-derived: {', '.join(derived)}")

    async def _try_load_channel_key(
        self,
        idx: int,
        name: str,
        max_attempts: int,
        delay: float,
    ) -> bool:
        """Try to load a single channel key from the device.

        Returns True if the key was successfully loaded and cached.
        """
        for attempt in range(max_attempts):
            try:
                r = await self.mc.commands.get_channel(idx)

                if r.type == EventType.ERROR:
                    debug_print(
                        f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                        f"ERROR response"
                    )
                    await asyncio.sleep(delay)
                    continue

                secret = r.payload.get('channel_secret')
                debug_print(
                    f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                    f"type={type(secret).__name__}, "
                    f"len={len(secret) if secret else 0}, "
                    f"keys={list(r.payload.keys())}"
                )

                # Extract secret bytes (handles both bytes and hex string)
                secret_bytes = self._extract_secret(secret)
                if secret_bytes:
                    self._decoder.add_channel_key(idx, secret_bytes, source="device")
                    self._cache.set_channel_key(idx, secret_bytes.hex())
                    print(
                        f"BLE: ✅ Channel [{idx}] '{name}' — "
                        f"key from device (attempt {attempt + 1})"
                    )
                    # Remove from pending if it was there
                    self._pending_keys.discard(idx)
                    return True

                debug_print(
                    f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                    f"response OK but secret unusable"
                )

            except Exception as exc:
                debug_print(
                    f"get_channel({idx}) attempt {attempt + 1}/{max_attempts} "
                    f"error: {exc}"
                )

            await asyncio.sleep(delay)

        return False

    async def _retry_missing_keys(self) -> None:
        """Background retry for channels that failed during startup.

        Called periodically from the main loop.  Each missing channel
        gets one attempt per cycle.  Successfully loaded keys are
        removed from ``_pending_keys``.
        """
        if not self._pending_keys:
            return

        pending_copy = set(self._pending_keys)
        ch_map = {ch['idx']: ch['name'] for ch in CHANNELS_CONFIG}

        debug_print(
            f"Background key retry: trying {len(pending_copy)} channels"
        )

        for idx in pending_copy:
            name = ch_map.get(idx, f"ch{idx}")
            loaded = await self._try_load_channel_key(
                idx, name, max_attempts=1, delay=0.5,
            )
            if loaded:
                self._pending_keys.discard(idx)
            await asyncio.sleep(1.0)

        if not self._pending_keys:
            print("BLE: ✅ All channel keys now loaded!")
        else:
            remaining = [
                f"[{idx}] {ch_map.get(idx, '?')}"
                for idx in sorted(self._pending_keys)
            ]
            debug_print(f"Background retry: still pending: {', '.join(remaining)}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_secret(secret) -> Optional[bytes]:
        """Extract 16-byte secret from various formats.

        Handles:
        - bytes (normal case from BLE)
        - hex string (some firmware versions)

        Returns 16-byte secret or None if unusable.
        """
        if secret and isinstance(secret, bytes) and len(secret) >= 16:
            return secret[:16]

        if secret and isinstance(secret, str) and len(secret) >= 32:
            try:
                raw = bytes.fromhex(secret)
                if len(raw) >= 16:
                    return raw[:16]
            except ValueError:
                pass

        return None

    # ------------------------------------------------------------------
    # Periodic contact refresh
    # ------------------------------------------------------------------

    async def _refresh_contacts(self) -> None:
        """Periodic background contact refresh — merge new/changed."""
        try:
            r = await self.mc.commands.get_contacts()
            if r.type != EventType.ERROR:
                merged = self._cache.merge_contacts(r.payload)
                self.shared.set_contacts(merged)
                debug_print(
                    f"Periodic refresh: {len(r.payload)} from device, "
                    f"{len(merged)} total"
                )
        except Exception as exc:
            debug_print(f"Periodic contact refresh failed: {exc}")
