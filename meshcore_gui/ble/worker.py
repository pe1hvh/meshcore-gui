"""
Communication worker for MeshCore GUI (Serial + BLE).

Runs in a separate thread with its own asyncio event loop.  Connects
to the MeshCore device, wires up collaborators, and runs the command
processing loop.

Transport selection
~~~~~~~~~~~~~~~~~~~~
The :func:`create_worker` factory returns the appropriate worker class
based on the device identifier:

- ``/dev/ttyACM0``  → :class:`SerialWorker`  (USB serial)
- ``literal:AA:BB:CC:DD:EE:FF`` → :class:`BLEWorker`  (Bluetooth LE)

Both workers share the same base class (:class:`_BaseWorker`) which
implements the main loop, event wiring, data loading and caching.

Command execution  → :mod:`meshcore_gui.ble.commands`
Event handling     → :mod:`meshcore_gui.ble.events`
Packet decoding    → :mod:`meshcore_gui.ble.packet_decoder`
PIN agent (BLE)    → :mod:`meshcore_gui.ble.ble_agent`
Reconnect (BLE)    → :mod:`meshcore_gui.ble.ble_reconnect`
Bot logic          → :mod:`meshcore_gui.services.bot`
Deduplication      → :mod:`meshcore_gui.services.dedup`
Cache              → :mod:`meshcore_gui.services.cache`

                   Author: PE1HVH
  SPDX-License-Identifier: MIT
"""

import abc
import asyncio
import threading
import time
from typing import Dict, List, Optional, Set

from meshcore import MeshCore, EventType

import meshcore_gui.config as _config
from meshcore_gui.config import (
    DEFAULT_TIMEOUT,
    CHANNEL_CACHE_ENABLED,
    CONTACT_REFRESH_SECONDS,
    MAX_CHANNELS,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_RETRIES,
    debug_data,
    debug_print,
    pp,
)
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.ble.commands import CommandHandler
from meshcore_gui.ble.events import EventHandler
from meshcore_gui.ble.packet_decoder import PacketDecoder
from meshcore_gui.services.bot import BotConfig, MeshBot
from meshcore_gui.services.bbs_service import BbsCommandHandler, BbsService
from meshcore_gui.services.bbs_config_store import BbsConfigStore
from meshcore_gui.services.bot_config_store import BotConfigStore
from meshcore_gui.services.cache import DeviceCache
from meshcore_gui.services.dedup import DualDeduplicator
from meshcore_gui.services.device_identity import write_device_identity
from meshcore_gui.services.pin_store import PinStore


# Seconds between background retry attempts for missing channel keys.
KEY_RETRY_INTERVAL: float = 30.0

# Seconds between periodic cleanup of old archived data (24 hours).
CLEANUP_INTERVAL: float = 86400.0


# ======================================================================
# Factory
# ======================================================================

def create_worker(device_id: str, shared: SharedDataWriter, **kwargs):
    """Return the appropriate worker for *device_id*.

    Keyword arguments are forwarded to the worker constructor
    (e.g. ``baudrate``, ``cx_dly`` for serial, ``pin_store`` for all).
    """
    from meshcore_gui.config import is_ble_address

    if is_ble_address(device_id):
        return BLEWorker(device_id, shared, pin_store=kwargs.get("pin_store"))
    return SerialWorker(
        device_id,
        shared,
        baudrate=kwargs.get("baudrate", _config.SERIAL_BAUDRATE),
        cx_dly=kwargs.get("cx_dly", _config.SERIAL_CX_DELAY),
        pin_store=kwargs.get("pin_store"),
    )


# ======================================================================
# Base worker (shared by BLE and Serial)
# ======================================================================

class _BaseWorker(abc.ABC):
    """Abstract base for transport-specific workers.

    Subclasses must implement:

    - :pyattr:`_log_prefix` — ``"BLE"`` or ``"SERIAL"``
    - :meth:`_async_main` — transport-specific startup + main loop
    - :meth:`_connect` — create the :class:`MeshCore` connection
    - :meth:`_reconnect` — re-establish after a disconnect
    - :pyattr:`_disconnect_keywords` — error substrings that signal
      a broken connection
    """

    def __init__(self, device_id: str, shared: SharedDataWriter, pin_store: Optional[PinStore] = None) -> None:
        self.device_id = device_id
        self.shared = shared
        self.mc: Optional[MeshCore] = None
        self.running = True
        self._disconnected = False

        # Local cache (one file per device)
        self._cache = DeviceCache(device_id)

        # Bot config store — persists channel selection and private mode.
        self._bot_config_store = BotConfigStore(device_id)

        # Sync persisted bot-enabled flag to SharedData so the bot starts
        # in the correct state after a restart.  Without this, SharedData
        # defaults to bot_enabled=False every run regardless of what the
        # user saved in the BOT panel.
        if self._bot_config_store.get_settings().enabled:
            shared.set_bot_enabled(True)

        # Collaborators (created eagerly, wired after connection)
        self._decoder = PacketDecoder()
        self._dedup = DualDeduplicator(max_size=200)
        self._bot = MeshBot(
            config=BotConfig(),
            command_sink=shared.put_command,
            enabled_check=shared.is_bot_enabled,
            config_store=self._bot_config_store,
            pinned_check=pin_store.is_pinned if pin_store is not None else None,
        )

        # BBS handler — wired directly into EventHandler for DM routing.
        # Independent of the bot; uses a shared config store and service.
        _bbs_config = BbsConfigStore()
        _bbs_service = BbsService()
        self._bbs_handler = BbsCommandHandler(service=_bbs_service, config_store=_bbs_config)

        # Channel indices that still need keys from device
        self._pending_keys: Set[int] = set()

        # Dynamically discovered channels from device
        self._channels: List[Dict] = []

    # ── abstract properties / methods ─────────────────────────────

    @property
    @abc.abstractmethod
    def _log_prefix(self) -> str:
        """Short label for log messages, e.g. ``"BLE"`` or ``"SERIAL"``."""

    @property
    @abc.abstractmethod
    def _disconnect_keywords(self) -> tuple:
        """Lowercase substrings that indicate a transport disconnect."""

    @abc.abstractmethod
    async def _async_main(self) -> None:
        """Transport-specific startup + main loop."""

    @abc.abstractmethod
    async def _connect(self) -> None:
        """Create a fresh connection and wire collaborators."""

    @abc.abstractmethod
    async def _reconnect(self) -> Optional[MeshCore]:
        """Attempt to re-establish the connection after a disconnect."""

    # ── thread lifecycle ──────────────────────────────────────────

    def start(self) -> None:
        """Start the worker in a new daemon thread."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        debug_print(f"{self._log_prefix} worker thread started")

    def _run(self) -> None:
        asyncio.run(self._async_main())

    # ── shared main loop (called from subclass _async_main) ───────

    async def _main_loop(self) -> None:
        """Command processing + periodic tasks.

        Runs until ``self.running`` is cleared or a disconnect is
        detected.  Subclasses call this from their ``_async_main``.
        """
        last_contact_refresh = time.time()
        last_key_retry = time.time()
        last_cleanup = time.time()

        while self.running and not self._disconnected:
            try:
                await self._cmd_handler.process_all()
            except Exception as e:
                error_str = str(e).lower()
                if any(kw in error_str for kw in self._disconnect_keywords):
                    print(f"{self._log_prefix}: ⚠️  Connection error detected: {e}")
                    self._disconnected = True
                    break
                debug_print(f"Command processing error: {e}")

            now = time.time()

            if now - last_contact_refresh > CONTACT_REFRESH_SECONDS:
                await self._refresh_contacts()
                last_contact_refresh = now

            if self._pending_keys and now - last_key_retry > KEY_RETRY_INTERVAL:
                await self._retry_missing_keys()
                last_key_retry = now

            if now - last_cleanup > CLEANUP_INTERVAL:
                await self._cleanup_old_data()
                last_cleanup = now

            await asyncio.sleep(0.1)

    async def _handle_reconnect(self) -> bool:
        """Shared reconnect logic after a disconnect.

        Returns True if reconnection succeeded, False otherwise.
        """
        self.shared.set_connected(False)
        self.shared.set_status("🔄 Verbinding verloren — herverbinden...")
        print(f"{self._log_prefix}: Verbinding verloren, start reconnect...")
        self.mc = None

        new_mc = await self._reconnect()

        if new_mc:
            self.mc = new_mc
            await asyncio.sleep(1)
            self._wire_collaborators()
            await self._load_data()
            await self.mc.start_auto_message_fetching()
            self._seed_dedup_from_messages()
            self.shared.set_connected(True)
            self.shared.set_status("✅ Herverbonden")
            print(f"{self._log_prefix}: ✅ Herverbonden en operationeel")
            return True

        self.shared.set_status("❌ Herverbinding mislukt — herstart nodig")
        print(
            f"{self._log_prefix}: ❌ Kan niet herverbinden — "
            "wacht 60s en probeer opnieuw..."
        )
        return False

    # ── collaborator wiring ───────────────────────────────────────

    def _wire_collaborators(self) -> None:
        """(Re-)create handlers and subscribe to MeshCore events."""
        self._evt_handler = EventHandler(
            shared=self.shared,
            decoder=self._decoder,
            dedup=self._dedup,
            bot=self._bot,
            bbs_handler=self._bbs_handler,
            command_sink=self.shared.put_command,
        )
        self._cmd_handler = CommandHandler(
            mc=self.mc, shared=self.shared, cache=self._cache,
        )
        self._cmd_handler.set_load_data_callback(self._load_data)

        self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._evt_handler.on_channel_msg)
        self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._evt_handler.on_contact_msg)
        self.mc.subscribe(EventType.RX_LOG_DATA, self._evt_handler.on_rx_log)
        self.mc.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)

    # ── LOGIN_SUCCESS handler (Room Server) ───────────────────────

    def _on_login_success(self, event) -> None:
        """Handle Room Server login confirmation.

        This worker callback is the *only* definitive success path for room
        login.  The command layer sends the login request and leaves the final
        transition to ``ok`` to this subscriber so there is no competing
        timeout/success logic elsewhere.

        The device event may expose the room key under different fields.
        Update both the generic status line and the per-room login state,
        then refresh archived room history for the matched room.
        """
        payload = event.payload or {}
        pubkey = (
            payload.get("room_pubkey")
            or payload.get("receiver")
            or payload.get("receiver_pubkey")
            or payload.get("pubkey_prefix")
            or ""
        )
        is_admin = payload.get("is_admin", False)
        debug_print(
            f"LOGIN_SUCCESS received: pubkey={pubkey}, admin={is_admin}, "
            f"keys={list(payload.keys())}"
        )
        self.shared.set_status("✅ Room login OK — messages arriving over RF…")
        if pubkey:
            self.shared.set_room_login_state(
                pubkey, 'ok', f'Server confirmed login (admin={is_admin})',
            )
            self.shared.load_room_history(pubkey)
        else:
            debug_print('LOGIN_SUCCESS received without identifiable room pubkey')

    # ── apply cache ───────────────────────────────────────────────

    def _apply_cache(self) -> None:
        """Push cached data to SharedData so GUI renders immediately."""
        device = self._cache.get_device()
        if device:
            self.shared.update_from_appstart(device)
            fw = device.get("firmware_version") or device.get("ver")
            if fw:
                self.shared.update_from_device_query({"ver": fw})
            self.shared.set_status("📦 Loaded from cache")
            debug_print(f"Cache → device info: {device.get('name', '?')}")

        if CHANNEL_CACHE_ENABLED:
            channels = self._cache.get_channels()
            if channels:
                self._channels = channels
                self.shared.set_channels(channels)
                debug_print(f"Cache -> channels: {[c['name'] for c in channels]}")
        else:
            # CHANNEL_CACHE_ENABLED is off, but channel names are always cached
            # independently. Use them to pre-populate the GUI so channel names
            # are visible immediately, before BLE discovery completes.
            cached_names = self._cache.get_channel_names()
            if cached_names:
                name_channels = [
                    {"idx": idx, "name": name}
                    for idx, name in sorted(cached_names.items())
                ]
                self._channels = name_channels
                self.shared.set_channels(name_channels)
                debug_print(
                    f"Cache -> channel names (fallback): "
                    f"{[c['name'] for c in name_channels]}"
                )
            else:
                debug_print("Channel cache disabled and no cached names -- skipping")

        contacts = self._cache.get_contacts()
        if contacts:
            self.shared.set_contacts(contacts)
            debug_print(f"Cache → contacts: {len(contacts)}")

        cached_keys = self._cache.get_channel_keys()
        for idx_str, secret_hex in cached_keys.items():
            try:
                idx = int(idx_str)
                secret_bytes = bytes.fromhex(secret_hex)
                if len(secret_bytes) >= 16:
                    self._decoder.add_channel_key(idx, secret_bytes[:16], source="cache")
                    debug_print(f"Cache -> channel key [{idx}]")
            except (ValueError, TypeError) as exc:
                debug_print(f"Cache -> bad channel key [{idx_str}]: {exc}")

        # Derive decoder keys for hashtag channels from their cached names.
        # Hashtag keys are never stored in channel_keys (they are derived from
        # the name), so we reconstruct them here to ensure the decoder can
        # decrypt hashtag channel messages before BLE discovery completes.
        cached_names = self._cache.get_channel_names()
        cached_key_indices = {int(k) for k in self._cache.get_channel_keys()}
        for idx, name in cached_names.items():
            if name.startswith("#") and idx not in cached_key_indices:
                self._decoder.add_channel_key_from_name(idx, name)
                debug_print(f"Cache -> hashtag key derived for [{idx}] {name}")

        cached_orig_name = self._cache.get_original_device_name()
        if cached_orig_name:
            self.shared.set_original_device_name(cached_orig_name)
            debug_print(f"Cache → original device name: {cached_orig_name}")

        count = self.shared.load_recent_from_archive(limit=100)
        if count:
            debug_print(f"Cache → {count} recent messages from archive")

        self._seed_dedup_from_messages()

    # ── initial data loading ──────────────────────────────────────

    async def _export_device_identity(self) -> None:
        """Export device keys and write identity file for Observer.

        Calls ``export_private_key()`` on the device and writes the
        result to ``~/.meshcore-gui/device_identity.json`` so the
        MeshCore Observer can authenticate to the MQTT broker without
        manual key configuration.
        """
        pfx = self._log_prefix
        try:
            r = await self.mc.commands.export_private_key()
            if r is None:
                debug_print(f"{pfx}: export_private_key returned None")
                return

            if r.type == EventType.PRIVATE_KEY:
                prv_bytes = r.payload.get("private_key", b"")
                if len(prv_bytes) == 64:
                    # Gather device info for the identity file
                    pub_key = ""
                    dev_name = ""
                    fw_ver = ""
                    with self.shared.lock:
                        pub_key = self.shared.device.public_key
                        dev_name = self.shared.device.name
                        fw_ver = self.shared.device.firmware_version

                    write_device_identity(
                        public_key=pub_key,
                        private_key_bytes=prv_bytes,
                        device_name=dev_name,
                        firmware_version=fw_ver,
                        source_device=self.device_id,
                    )
                else:
                    debug_print(
                        f"{pfx}: export_private_key: unexpected "
                        f"length {len(prv_bytes)} bytes"
                    )

            elif r.type == EventType.DISABLED:
                print(
                    f"{pfx}: ℹ️  Private key export is disabled on device "
                    f"— manual key setup required for Observer MQTT"
                )
            else:
                debug_print(
                    f"{pfx}: export_private_key: unexpected "
                    f"response type {r.type}"
                )

        except Exception as exc:
            debug_print(f"{pfx}: export_private_key failed: {exc}")

    async def _load_data(self) -> None:
        """Load device info, channels and contacts from device."""
        pfx = self._log_prefix

        # send_appstart — reuse result from MeshCore.connect()
        self.shared.set_status("🔄 Device info...")
        cached_info = self.mc.self_info
        if cached_info and cached_info.get("name"):
            print(f"{pfx}: send_appstart OK (from connect): {cached_info.get('name')}")
            self.shared.update_from_appstart(cached_info)
            self._cache.set_device(cached_info)
        else:
            debug_print("self_info empty after connect(), falling back to manual send_appstart")
            appstart_ok = False
            for i in range(3):
                debug_print(f"send_appstart fallback attempt {i + 1}/3")
                try:
                    r = await self.mc.commands.send_appstart()
                    if r is None:
                        debug_print(f"send_appstart fallback {i + 1}: received None, retrying")
                        await asyncio.sleep(2.0)
                        continue
                    if r.type != EventType.ERROR:
                        print(f"{pfx}: send_appstart OK: {r.payload.get('name')} (fallback attempt {i + 1})")
                        self.shared.update_from_appstart(r.payload)
                        self._cache.set_device(r.payload)
                        appstart_ok = True
                        break
                    else:
                        debug_print(f"send_appstart fallback {i + 1}: ERROR — payload={pp(r.payload)}")
                except Exception as exc:
                    debug_print(f"send_appstart fallback {i + 1} exception: {exc}")
                await asyncio.sleep(2.0)
            if not appstart_ok:
                print(f"{pfx}: ⚠️  send_appstart failed after 3 fallback attempts")

        # send_device_query
        for i in range(5):
            debug_print(f"send_device_query attempt {i + 1}/5")
            try:
                r = await self.mc.commands.send_device_query()
                if r is None:
                    debug_print(f"send_device_query attempt {i + 1}: received None response, retrying")
                    await asyncio.sleep(2.0)
                    continue
                if r.type != EventType.ERROR:
                    fw = r.payload.get("ver", "")
                    print(f"{pfx}: send_device_query OK: {fw} (attempt {i + 1})")
                    self.shared.update_from_device_query(r.payload)
                    if fw:
                        self._cache.set_firmware_version(fw)
                    break
                else:
                    debug_print(f"send_device_query attempt {i + 1}: ERROR response — payload={pp(r.payload)}")
            except Exception as exc:
                debug_print(f"send_device_query attempt {i + 1} exception: {exc}")
            await asyncio.sleep(2.0)

        # Export device identity for MeshCore Observer
        await self._export_device_identity()

        # Channels
        await self._discover_channels()

        # Contacts
        self.shared.set_status("🔄 Contacts...")
        debug_print("get_contacts starting")
        try:
            r = await self._get_contacts_with_timeout()
            debug_print(f"get_contacts result: type={r.type if r else None}")
            if r and r.payload:
                try:
                    payload_len = len(r.payload)
                except Exception:
                    payload_len = None
                if payload_len is not None and payload_len > 10:
                    debug_print(f"get_contacts payload size={payload_len} (omitted)")
                else:
                    debug_data("get_contacts payload", r.payload)
            if r is None:
                debug_print(f"{pfx}: get_contacts returned None, keeping cached contacts")
            elif r.type != EventType.ERROR:
                merged = self._cache.merge_contacts(r.payload)
                self.shared.set_contacts(merged)
                print(f"{pfx}: Contacts — {len(r.payload)} from device, {len(merged)} total (with cache)")
            else:
                debug_print(f"{pfx}: get_contacts failed — payload={pp(r.payload)}, keeping cached contacts")
        except Exception as exc:
            debug_print(f"{pfx}: get_contacts exception: {exc}")

    async def _get_contacts_with_timeout(self):
        """Fetch contacts with a bounded timeout to avoid hanging refresh."""
        timeout = max(DEFAULT_TIMEOUT * 2, 10.0)
        try:
            return await asyncio.wait_for(
                self.mc.commands.get_contacts(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.shared.set_status("⚠️ Contacts timeout — using cached contacts")
            debug_print(f"get_contacts timeout after {timeout:.0f}s")
            return None

    # ── channel discovery ─────────────────────────────────────────

    async def _discover_channels(self) -> None:
        """Discover channels and load their keys from the device."""
        pfx = self._log_prefix
        self.shared.set_status("🔄 Discovering channels...")
        discovered: List[Dict] = []
        cached_keys = self._cache.get_channel_keys()

        confirmed: list[str] = []
        from_cache: list[str] = []
        derived: list[str] = []

        consecutive_errors = 0

        for idx in range(MAX_CHANNELS):
            payload = await self._try_get_channel_info(idx, max_attempts=2, delay=1.0)

            if payload is None:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    debug_print(
                        f"Channel discovery: {consecutive_errors} consecutive "
                        f"empty slots at idx {idx}, stopping"
                    )
                    break
                continue

            consecutive_errors = 0
            name = payload.get("name") or payload.get("channel_name") or ""
            if not name.strip():
                debug_print(f"Channel [{idx}]: response OK but no name — skipping (undefined slot)")
                continue

            discovered.append({"idx": idx, "name": name})

            secret = payload.get("channel_secret")
            secret_bytes = self._extract_secret(secret)

            if secret_bytes:
                self._decoder.add_channel_key(idx, secret_bytes, source="device")
                self._cache.set_channel_key(idx, secret_bytes.hex())
                self._pending_keys.discard(idx)
                confirmed.append(f"[{idx}] {name}")
            elif str(idx) in cached_keys:
                from_cache.append(f"[{idx}] {name}")
                print(f"{pfx}: 📦 Channel [{idx}] '{name}' — using cached key")
            else:
                self._decoder.add_channel_key_from_name(idx, name)
                self._pending_keys.add(idx)
                derived.append(f"[{idx}] {name}")
                print(f"{pfx}: ⚠️  Channel [{idx}] '{name}' — name-derived key (will retry)")

            await asyncio.sleep(0.3)

        if not discovered:
            discovered = [{"idx": 0, "name": "Public"}]
            print(f"{pfx}: ⚠️ No channels discovered, using default Public channel")

        self._channels = discovered
        self.shared.set_channels(discovered)
        # Always persist channel names regardless of CHANNEL_CACHE_ENABLED,
        # so the GUI can display them immediately on next startup.
        self._cache.set_channel_names({ch["idx"]: ch["name"] for ch in discovered})
        if CHANNEL_CACHE_ENABLED:
            self._cache.set_channels(discovered)
            debug_print("Channel list cached to disk")

        print(f"{pfx}: Channels discovered: {[c['name'] for c in discovered]}")
        print(f"{pfx}: PacketDecoder ready — has_keys={self._decoder.has_keys}")
        if confirmed:
            print(f"{pfx}: ✅ Keys from device: {', '.join(confirmed)}")
        if from_cache:
            print(f"{pfx}: 📦 Keys from cache: {', '.join(from_cache)}")
        if derived:
            print(f"{pfx}: ⚠️  Name-derived keys: {', '.join(derived)}")

    async def _try_get_channel_info(
        self, idx: int, max_attempts: int, delay: float,
    ) -> Optional[Dict]:
        for attempt in range(max_attempts):
            try:
                r = await self.mc.commands.get_channel(idx)
                if r is None:
                    debug_print(f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: received None response, retrying")
                    await asyncio.sleep(delay)
                    continue
                if r.type == EventType.ERROR:
                    debug_print(f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: ERROR response — payload={pp(r.payload)}")
                    await asyncio.sleep(delay)
                    continue
                debug_print(f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: OK — keys={list(r.payload.keys())}")
                return r.payload
            except Exception as exc:
                debug_print(f"get_channel({idx}) attempt {attempt + 1}/{max_attempts} error: {exc}")
                await asyncio.sleep(delay)
        return None

    async def _try_load_channel_key(
        self, idx: int, name: str, max_attempts: int, delay: float,
    ) -> bool:
        payload = await self._try_get_channel_info(idx, max_attempts, delay)
        if payload is None:
            return False
        secret = payload.get("channel_secret")
        secret_bytes = self._extract_secret(secret)
        if secret_bytes:
            self._decoder.add_channel_key(idx, secret_bytes, source="device")
            self._cache.set_channel_key(idx, secret_bytes.hex())
            print(f"{self._log_prefix}: ✅ Channel [{idx}] '{name}' — key from device (background retry)")
            self._pending_keys.discard(idx)
            return True
        debug_print(f"get_channel({idx}): response OK but secret unusable")
        return False

    async def _retry_missing_keys(self) -> None:
        if not self._pending_keys:
            return
        pending_copy = set(self._pending_keys)
        ch_map = {ch["idx"]: ch["name"] for ch in self._channels}
        debug_print(f"Background key retry: trying {len(pending_copy)} channels")
        for idx in pending_copy:
            name = ch_map.get(idx, f"ch{idx}")
            loaded = await self._try_load_channel_key(idx, name, max_attempts=1, delay=0.5)
            if loaded:
                self._pending_keys.discard(idx)
            await asyncio.sleep(1.0)
        if not self._pending_keys:
            print(f"{self._log_prefix}: ✅ All channel keys now loaded!")
        else:
            remaining = [f"[{idx}] {ch_map.get(idx, '?')}" for idx in sorted(self._pending_keys)]
            debug_print(f"Background retry: still pending: {', '.join(remaining)}")

    # ── helpers ────────────────────────────────────────────────────

    def _seed_dedup_from_messages(self) -> None:
        """Seed the deduplicator with messages already in SharedData."""
        snapshot = self.shared.get_snapshot()
        messages = snapshot.get("messages", [])
        seeded = 0
        for msg in messages:
            if msg.message_hash:
                self._dedup.mark_hash(msg.message_hash)
                seeded += 1
            if msg.sender and msg.text:
                self._dedup.mark_content(msg.sender, msg.channel, msg.text)
                seeded += 1
        debug_print(f"Dedup seeded with {seeded} entries from {len(messages)} messages")

    @staticmethod
    def _extract_secret(secret) -> Optional[bytes]:
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

    # ── periodic tasks ────────────────────────────────────────────

    async def _refresh_contacts(self) -> None:
        try:
            r = await self._get_contacts_with_timeout()
            if r is None:
                debug_print("Periodic refresh: get_contacts returned None, skipping")
                return
            if r.type != EventType.ERROR:
                merged = self._cache.merge_contacts(r.payload)
                self.shared.set_contacts(merged)
                debug_print(
                    f"Periodic refresh: {len(r.payload)} from device, "
                    f"{len(merged)} total"
                )
        except Exception as exc:
            debug_print(f"Periodic contact refresh failed: {exc}")

    async def _cleanup_old_data(self) -> None:
        try:
            if self.shared.archive:
                self.shared.archive.cleanup_old_data()
                stats = self.shared.archive.get_stats()
                debug_print(
                    f"Cleanup: archive now has {stats['total_messages']} messages, "
                    f"{stats['total_rxlog']} rxlog entries"
                )
            removed = self._cache.prune_old_contacts()
            if removed > 0:
                contacts = self._cache.get_contacts()
                self.shared.set_contacts(contacts)
                debug_print(f"Cleanup: pruned {removed} old contacts")
        except Exception as exc:
            debug_print(f"Periodic cleanup failed: {exc}")


# ======================================================================
# Serial worker
# ======================================================================

class SerialWorker(_BaseWorker):
    """Serial communication worker (USB/UART).

    Args:
        port:      Serial device path (e.g. ``"/dev/ttyUSB0"``).
        shared:    SharedDataWriter for thread-safe communication.
        baudrate:  Serial baudrate (default from config).
        cx_dly:    Connection delay for meshcore serial transport.
    """

    def __init__(
        self,
        port: str,
        shared: SharedDataWriter,
        baudrate: int = _config.SERIAL_BAUDRATE,
        cx_dly: float = _config.SERIAL_CX_DELAY,
        pin_store: Optional[PinStore] = None,
    ) -> None:
        super().__init__(port, shared, pin_store=pin_store)
        self.port = port
        self.baudrate = baudrate
        self.cx_dly = cx_dly

    @property
    def _log_prefix(self) -> str:
        return "SERIAL"

    @property
    def _disconnect_keywords(self) -> tuple:
        return (
            "not connected", "disconnected", "connection reset",
            "broken pipe", "i/o error", "read failed", "write failed",
            "port is closed", "port closed",
        )

    async def _async_main(self) -> None:
        try:
            while self.running:
                # ── Outer loop: (re)establish a fresh serial connection ──
                self._disconnected = False
                await self._connect()

                if not self.mc:
                    print("SERIAL: Initial connection failed, retrying in 30s...")
                    self.shared.set_status("⚠️ Connection failed — retrying...")
                    await asyncio.sleep(30)
                    continue

                # ── Inner loop: run + reconnect without calling _connect() again ──
                # _handle_reconnect() already creates a fresh MeshCore and loads
                # data — calling _connect() on top of that would attempt to open
                # the serial port a second time, causing an immediate disconnect.
                while self.running:
                    await self._main_loop()

                    if not self._disconnected or not self.running:
                        break

                    ok = await self._handle_reconnect()
                    if ok:
                        # Reconnected — reset flag and go back to _main_loop,
                        # NOT to the outer while (which would call _connect() again).
                        self._disconnected = False
                    else:
                        # All reconnect attempts exhausted — wait, then let the
                        # outer loop call _connect() for a clean fresh start.
                        await asyncio.sleep(60)
                        break
        finally:
            return

    async def _connect(self) -> None:
        if self._cache.load():
            self._apply_cache()
            print("SERIAL: Cache loaded — GUI populated from disk")
        else:
            print("SERIAL: No cache found — waiting for device data")

        self.shared.set_status(f"🔄 Connecting to {self.port}...")
        try:
            print(f"SERIAL: Connecting to {self.port}...")
            self.mc = await MeshCore.create_serial(
                self.port,
                baudrate=self.baudrate,
                auto_reconnect=False,
                default_timeout=DEFAULT_TIMEOUT,
                debug=_config.MESHCORE_LIB_DEBUG,
                cx_dly=self.cx_dly,
            )
            if self.mc is None:
                raise RuntimeError("No response from device over serial")
            print("SERIAL: Connected!")

            await asyncio.sleep(1)
            debug_print("Post-connection sleep done, wiring collaborators")
            self._wire_collaborators()
            await self._load_data()
            await self.mc.start_auto_message_fetching()

            self.shared.set_connected(True)
            self.shared.set_status("✅ Connected")
            print("SERIAL: Ready!")

            if self._pending_keys:
                pending_names = [
                    f"[{ch['idx']}] {ch['name']}"
                    for ch in self._channels
                    if ch["idx"] in self._pending_keys
                ]
                print(
                    f"SERIAL: ⏳ Background retry active for: "
                    f"{', '.join(pending_names)} (every {KEY_RETRY_INTERVAL:.0f}s)"
                )

        except Exception as e:
            print(f"SERIAL: Connection error: {e}")
            self.mc = None  # ensure _async_main sees connection as failed
            if self._cache.has_cache:
                self.shared.set_status(f"⚠️ Offline — using cached data ({e})")
            else:
                self.shared.set_status(f"❌ {e}")

    async def _reconnect(self) -> Optional[MeshCore]:
        for attempt in range(1, RECONNECT_MAX_RETRIES + 1):
            delay = RECONNECT_BASE_DELAY * attempt
            print(
                f"SERIAL: 🔄 Reconnect attempt {attempt}/{RECONNECT_MAX_RETRIES} "
                f"in {delay:.0f}s..."
            )
            await asyncio.sleep(delay)
            try:
                mc = await MeshCore.create_serial(
                    self.port,
                    baudrate=self.baudrate,
                    auto_reconnect=False,
                    default_timeout=DEFAULT_TIMEOUT,
                    debug=_config.MESHCORE_LIB_DEBUG,
                    cx_dly=self.cx_dly,
                )
                if mc is None:
                    raise RuntimeError("No response from device over serial")
                return mc
            except Exception as exc:
                print(f"SERIAL: ❌ Reconnect attempt {attempt} failed: {exc}")
        print(f"SERIAL: ❌ Reconnect failed after {RECONNECT_MAX_RETRIES} attempts")
        return None


# ======================================================================
# BLE worker
# ======================================================================

class BLEWorker(_BaseWorker):
    """BLE communication worker (Bluetooth Low Energy).

    Args:
        address:  BLE MAC address (e.g. ``"literal:AA:BB:CC:DD:EE:FF"``).
        shared:   SharedDataWriter for thread-safe communication.
    """

    def __init__(self, address: str, shared: SharedDataWriter, pin_store: Optional[PinStore] = None) -> None:
        super().__init__(address, shared, pin_store=pin_store)
        self.address = address

        # BLE PIN agent — imported lazily so serial-only installs
        # don't need dbus_fast / bleak.
        from meshcore_gui.ble.ble_agent import BleAgentManager
        self._agent = BleAgentManager(pin=_config.BLE_PIN)

    @property
    def _log_prefix(self) -> str:
        return "BLE"

    @property
    def _disconnect_keywords(self) -> tuple:
        return (
            "not connected", "disconnected", "dbus",
            "pin or key missing", "connection reset", "broken pipe",
            "failed to discover", "service discovery",
        )

    async def _async_main(self) -> None:
        from meshcore_gui.ble.ble_reconnect import remove_bond

        # Step 1: Start PIN agent BEFORE any BLE connection
        await self._agent.start()

        # Step 2: Remove stale bond (clean slate)
        await remove_bond(self.address)
        await asyncio.sleep(1)

        # Step 3: Connect + main loop
        try:
            while self.running:
                # ── Outer loop: (re)establish a fresh BLE connection ──
                self._disconnected = False
                await self._connect()

                if not self.mc:
                    print("BLE: Initial connection failed, retrying in 30s...")
                    self.shared.set_status("⚠️ Connection failed — retrying...")
                    await asyncio.sleep(30)
                    await remove_bond(self.address)
                    await asyncio.sleep(1)
                    continue

                # ── Inner loop: run + reconnect without calling _connect() again ──
                # _handle_reconnect() already creates a fresh MeshCore and loads
                # data — calling _connect() on top would open a second BLE session,
                # causing an immediate disconnect.
                while self.running:
                    await self._main_loop()

                    if not self._disconnected or not self.running:
                        break

                    ok = await self._handle_reconnect()
                    if ok:
                        # Reconnected — reset flag and go back to _main_loop,
                        # NOT to the outer while (which would call _connect() again).
                        self._disconnected = False
                    else:
                        await asyncio.sleep(60)
                        await remove_bond(self.address)
                        await asyncio.sleep(1)
                        break
        finally:
            await self._agent.stop()

    async def _connect(self) -> None:
        if self._cache.load():
            self._apply_cache()
            print("BLE: Cache loaded — GUI populated from disk")
        else:
            print("BLE: No cache found — waiting for BLE data")

        self.shared.set_status(f"🔄 Connecting to {self.address}...")
        try:
            print(f"BLE: Connecting to {self.address}...")
            self.mc = await MeshCore.create_ble(
                self.address,
                auto_reconnect=False,
                default_timeout=DEFAULT_TIMEOUT,
                debug=_config.MESHCORE_LIB_DEBUG,
            )
            print("BLE: Connected!")

            await asyncio.sleep(1)
            debug_print("Post-connection sleep done, wiring collaborators")
            self._wire_collaborators()
            await self._load_data()
            await self.mc.start_auto_message_fetching()

            self.shared.set_connected(True)
            self.shared.set_status("✅ Connected")
            print("BLE: Ready!")

            if self._pending_keys:
                pending_names = [
                    f"[{ch['idx']}] {ch['name']}"
                    for ch in self._channels
                    if ch["idx"] in self._pending_keys
                ]
                print(
                    f"BLE: ⏳ Background retry active for: "
                    f"{', '.join(pending_names)} (every {KEY_RETRY_INTERVAL:.0f}s)"
                )

        except Exception as e:
            print(f"BLE: Connection error: {e}")
            self.mc = None  # ensure _async_main sees connection as failed
            if self._cache.has_cache:
                self.shared.set_status(f"⚠️ Offline — using cached data ({e})")
            else:
                self.shared.set_status(f"❌ {e}")

    async def _reconnect(self) -> Optional[MeshCore]:
        from meshcore_gui.ble.ble_reconnect import reconnect_loop

        async def _create_fresh_connection() -> MeshCore:
            return await MeshCore.create_ble(
                self.address,
                auto_reconnect=False,
                default_timeout=DEFAULT_TIMEOUT,
                debug=_config.MESHCORE_LIB_DEBUG,
            )

        return await reconnect_loop(
            _create_fresh_connection,
            self.address,
            max_retries=RECONNECT_MAX_RETRIES,
            base_delay=RECONNECT_BASE_DELAY,
        )
