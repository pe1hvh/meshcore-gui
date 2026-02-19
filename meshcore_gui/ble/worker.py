"""
BLE communication worker for MeshCore GUI.

Runs in a separate thread with its own asyncio event loop.  Connects
to the MeshCore device, wires up collaborators, and runs the command
processing loop.

Responsibilities deliberately kept narrow (SRP):
    - Thread lifecycle and asyncio loop
    - BLE connection and initial data loading
    - Wiring CommandHandler and EventHandler
    - PIN pairing via built-in D-Bus agent
    - Disconnect detection and automatic reconnect

Command execution  → :mod:`meshcore_gui.ble.commands`
Event handling     → :mod:`meshcore_gui.ble.events`
Packet decoding    → :mod:`meshcore_gui.ble.packet_decoder`
PIN agent          → :mod:`meshcore_gui.ble.ble_agent`
Reconnect logic    → :mod:`meshcore_gui.ble.ble_reconnect`
Bot logic          → :mod:`meshcore_gui.services.bot`
Deduplication      → :mod:`meshcore_gui.services.dedup`
Cache              → :mod:`meshcore_gui.services.cache`

v5.2 changes (BLE stability)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Built-in D-Bus PIN agent: eliminates ``bt-agent.service``.
- Automatic bond removal on startup (clean slate).
- Disconnect detection in the main loop with auto-reconnect.
- Bond cleanup before each reconnect attempt (fixes "PIN or Key
  Missing" errors from stale BlueZ bonds).
- Linear backoff reconnect (configurable via ``RECONNECT_*`` settings).

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
import sys
import threading
import time
from typing import Dict, List, Optional, Set

from meshcore import MeshCore, EventType

import meshcore_gui.config as _config
from meshcore_gui.config import (
    BLE_DEFAULT_TIMEOUT,
    BLE_LIB_DEBUG,
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
from meshcore_gui.ble.ble_agent import BleAgentManager
from meshcore_gui.ble.ble_reconnect import reconnect_loop, remove_bond
from meshcore_gui.ble.commands import CommandHandler
from meshcore_gui.ble.events import EventHandler
from meshcore_gui.ble.packet_decoder import PacketDecoder
from meshcore_gui.services.bot import BotConfig, MeshBot
from meshcore_gui.services.cache import DeviceCache
from meshcore_gui.services.dedup import DualDeduplicator


# Seconds between background retry attempts for missing channel keys.
KEY_RETRY_INTERVAL: float = 30.0

# Seconds between periodic cleanup of old archived data (24 hours).
CLEANUP_INTERVAL: float = 86400.0


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
        self._disconnected = False

        # BLE PIN agent (replaces external bt-agent.service)
        self._agent = BleAgentManager(pin=_config.BLE_PIN)

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

        # Dynamically discovered channels from device
        self._channels: List[Dict] = []

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
        # ── Step 1: Start PIN agent (BEFORE any BLE connection) ──
        await self._agent.start()

        # ── Step 1b: Warn if PIN agent failed (Linux only) ──
        if not self._agent.is_registered and sys.platform == "linux":
            print(
                "BLE: ❌ PIN agent is NOT registered — BLE pairing "
                "will fail with 'Not Paired'."
            )
            print("BLE: ──────────────────────────────────────────")
            print("BLE: Fix: install the D-Bus policy file:")
            print("BLE:   bash install_ble_stable.sh")
            print("BLE: Or manually:")
            print(
                "BLE:   sudo tee /etc/dbus-1/system.d/"
                "meshcore-ble.conf << EOF"
            )
            print("BLE:   <busconfig>")
            print('BLE:     <policy user="YOUR_USER">')
            print(
                'BLE:       <allow send_destination="org.bluez"/>'
            )
            print(
                'BLE:       <allow send_interface='
                '"org.bluez.Agent1"/>'
            )
            print(
                'BLE:       <allow send_interface='
                '"org.bluez.AgentManager1"/>'
            )
            print("BLE:     </policy>")
            print("BLE:   </busconfig>")
            print("BLE:   EOF")
            print("BLE: Then restart the application.")
            print("BLE: ──────────────────────────────────────────")
            # Also log to file so it survives terminal scroll
            debug_print(
                "PIN agent NOT registered — D-Bus policy file "
                "likely missing. BLE pairing will fail. "
                "Install /etc/dbus-1/system.d/meshcore-ble.conf "
                "or run: bash install_ble_stable.sh"
            )
            self.shared.set_status(
                "❌ BLE PIN agent failed — "
                "see terminal for fix instructions"
            )

        # ── Step 2: Remove stale bond (clean slate) ──
        await remove_bond(self.address)
        await asyncio.sleep(1)

        # ── Step 3: Connect + main loop (with reconnect wrapper) ──
        try:
            while self.running:
                self._disconnected = False
                await self._connect()

                if not self.mc:
                    # Initial connect failed — wait and retry
                    print("BLE: Initial connection failed, retrying in 30s...")
                    debug_print("Initial connection failed, retrying in 30s")
                    self.shared.set_status("⚠️ Connection failed — retrying...")
                    await asyncio.sleep(30)
                    await remove_bond(self.address)
                    await asyncio.sleep(1)
                    continue

                # ── Main loop ──
                last_contact_refresh = time.time()
                last_key_retry = time.time()
                last_cleanup = time.time()

                while self.running and not self._disconnected:
                    try:
                        await self._cmd_handler.process_all()
                    except Exception as e:
                        error_str = str(e).lower()
                        if any(
                            kw in error_str
                            for kw in (
                                "not connected",
                                "disconnected",
                                "dbus",
                                "pin or key missing",
                                "connection reset",
                                "broken pipe",
                                "failed to discover",
                                "service discovery",
                            )
                        ):
                            print(f"BLE: ⚠️  Connection error detected: {e}")
                            debug_print(f"Connection error detected: {e}")
                            self._disconnected = True
                            break
                        debug_print(f"Command processing error: {e}")

                    now = time.time()

                    # Periodic contact refresh
                    if now - last_contact_refresh > CONTACT_REFRESH_SECONDS:
                        await self._refresh_contacts()
                        last_contact_refresh = now

                    # Background key retry for missing channels
                    if (
                        self._pending_keys
                        and now - last_key_retry > KEY_RETRY_INTERVAL
                    ):
                        await self._retry_missing_keys()
                        last_key_retry = now

                    # Periodic cleanup of old data (daily)
                    if now - last_cleanup > CLEANUP_INTERVAL:
                        await self._cleanup_old_data()
                        last_cleanup = now

                    await asyncio.sleep(0.1)

                # ── Disconnect detected — reconnect ──
                if self._disconnected and self.running:
                    self.shared.set_connected(False)
                    self.shared.set_status(
                        "🔄 Connection lost — reconnecting..."
                    )
                    print("BLE: Connection lost, starting reconnect...")
                    debug_print("Connection lost, starting reconnect")
                    self.mc = None

                    async def _create_fresh_connection() -> MeshCore:
                        return await MeshCore.create_ble(
                            self.address,
                            auto_reconnect=False,
                            default_timeout=BLE_DEFAULT_TIMEOUT,
                            debug=BLE_LIB_DEBUG,
                        )

                    new_mc = await reconnect_loop(
                        _create_fresh_connection,
                        self.address,
                        max_retries=RECONNECT_MAX_RETRIES,
                        base_delay=RECONNECT_BASE_DELAY,
                    )

                    if new_mc:
                        self.mc = new_mc
                        await asyncio.sleep(1)
                        # Re-wire collaborators with new connection
                        self._evt_handler = EventHandler(
                            shared=self.shared,
                            decoder=self._decoder,
                            dedup=self._dedup,
                            bot=self._bot,
                        )
                        self._cmd_handler = CommandHandler(
                            mc=self.mc,
                            shared=self.shared,
                            cache=self._cache,
                        )
                        self._cmd_handler.set_load_data_callback(
                            self._load_data
                        )

                        # Re-subscribe events
                        self.mc.subscribe(
                            EventType.CHANNEL_MSG_RECV,
                            self._evt_handler.on_channel_msg,
                        )
                        self.mc.subscribe(
                            EventType.CONTACT_MSG_RECV,
                            self._evt_handler.on_contact_msg,
                        )
                        self.mc.subscribe(
                            EventType.RX_LOG_DATA,
                            self._evt_handler.on_rx_log,
                        )
                        self.mc.subscribe(
                            EventType.LOGIN_SUCCESS,
                            self._on_login_success,
                        )

                        # Reload data and resume
                        await self._load_data()
                        await self.mc.start_auto_message_fetching()
                        self.shared.set_connected(True)
                        self.shared.set_status("✅ Reconnected")
                        print("BLE: ✅ Reconnected and operational")
                        debug_print("Reconnected and operational")
                    else:
                        self.shared.set_status(
                            "❌ Reconnect failed — restart required"
                        )
                        print(
                            "BLE: ❌ Cannot reconnect — "
                            "waiting 60s and trying again..."
                        )
                        debug_print(
                            "Reconnect failed after all attempts, "
                            "waiting 60s before next cycle"
                        )
                        await asyncio.sleep(60)
                        await remove_bond(self.address)
                        await asyncio.sleep(1)
        finally:
            # ── Cleanup: stop PIN agent ──
            await self._agent.stop()

    # ------------------------------------------------------------------
    # Connection (cache-first)
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        # Phase 1: Load cache → GUI is instantly populated
        if self._cache.load():
            self._apply_cache()
            print("BLE: Cache loaded — GUI populated from disk")
            debug_print("Cache loaded from disk")
        else:
            print("BLE: No cache found — waiting for BLE data")
            debug_print("No cache found")

        # Phase 2: Connect BLE
        self.shared.set_status(f"🔄 Connecting to {self.address}...")
        try:
            print(f"BLE: Connecting to {self.address}...")
            debug_print(f"Connecting to {self.address}")
            self.mc = await MeshCore.create_ble(self.address, auto_reconnect=False, default_timeout=BLE_DEFAULT_TIMEOUT, debug=BLE_LIB_DEBUG)
            print("BLE: Connected!")
            debug_print(f"Connected to {self.address}")

            await asyncio.sleep(1)
            debug_print("Post-connection sleep done, wiring collaborators")

            # Wire collaborators now that mc is available
            self._evt_handler = EventHandler(
                shared=self.shared,
                decoder=self._decoder,
                dedup=self._dedup,
                bot=self._bot,
            )
            self._cmd_handler = CommandHandler(mc=self.mc, shared=self.shared, cache=self._cache)
            self._cmd_handler.set_load_data_callback(self._load_data)

            # Subscribe to events
            self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._evt_handler.on_channel_msg)
            self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._evt_handler.on_contact_msg)
            self.mc.subscribe(EventType.RX_LOG_DATA, self._evt_handler.on_rx_log)
            self.mc.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)

            # Phase 3: Load data from device (includes channel discovery + keys)
            await self._load_data()
            await self.mc.start_auto_message_fetching()

            self.shared.set_connected(True)
            self.shared.set_status("✅ Connected")
            print("BLE: Ready!")

            if self._pending_keys:
                pending_names = [
                    f"[{ch['idx']}] {ch['name']}"
                    for ch in self._channels
                    if ch['idx'] in self._pending_keys
                ]
                print(
                    f"BLE: ⏳ Background retry active for: "
                    f"{', '.join(pending_names)} "
                    f"(every {KEY_RETRY_INTERVAL:.0f}s)"
                )

        except Exception as e:
            print(f"BLE: Connection error: {e}")
            debug_print(f"Connection error: {e}")
            if "not paired" in str(e).lower() or "authentication" in str(e).lower():
                debug_print(
                    "Pairing failure detected — likely cause: "
                    "D-Bus policy file missing or bluetooth group "
                    "not configured. Check install instructions."
                )
            if self._cache.has_cache:
                self.shared.set_status(f"⚠️ Offline — using cached data ({e})")
            else:
                self.shared.set_status(f"❌ {e}")

    # ------------------------------------------------------------------
    # LOGIN_SUCCESS handler (Room Server)
    # ------------------------------------------------------------------

    def _on_login_success(self, event) -> None:
        """Handle LOGIN_SUCCESS from a Room Server.

        After login the Room Server pushes stored messages over RF using
        round-robin.  Each message travels via LoRa to the companion
        radio, which buffers it and emits ``MESSAGES_WAITING``.  The
        library's ``auto_message_fetching`` already handles that event,
        so no extra polling is needed here.

        Note: the login state is updated by ``_cmd_login_room`` via
        ``wait_for_event``, so we do NOT set it here to avoid creating
        a second entry with a different key (prefix vs full pubkey).
        """
        payload = event.payload or {}
        pubkey = payload.get('pubkey_prefix', '')
        is_admin = payload.get('is_admin', False)
        debug_print(
            f"LOGIN_SUCCESS received: pubkey={pubkey}, "
            f"admin={is_admin}"
        )

        self.shared.set_status(
            "✅ Room login OK — messages arriving over RF…"
        )

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

        # Only load channels from cache when channel caching is enabled
        if CHANNEL_CACHE_ENABLED:
            channels = self._cache.get_channels()
            if channels:
                self._channels = channels
                self.shared.set_channels(channels)
                debug_print(f"Cache → channels: {[c['name'] for c in channels]}")
        else:
            debug_print("Channel cache disabled — skipping cached channels")

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

        # Restore original device name (if BOT was active when app closed)
        cached_orig_name = self._cache.get_original_device_name()
        if cached_orig_name:
            self.shared.set_original_device_name(cached_orig_name)
            debug_print(f"Cache → original device name: {cached_orig_name}")

        # Load recent archived messages for immediate display on main page
        count = self.shared.load_recent_from_archive(limit=100)
        if count:
            debug_print(f"Cache → {count} recent messages from archive")

    # ------------------------------------------------------------------
    # Initial data loading (refreshes cache)
    # ------------------------------------------------------------------

    async def _load_data(self) -> None:
        """Load device info, channels and contacts from device.

        Updates both SharedData (for GUI) and the disk cache.

        Key insight: ``MeshCore.connect()`` already sends ``send_appstart``
        internally and stores the result in ``self.mc.self_info``.  We reuse
        that instead of sending a duplicate command that is likely to fail
        on a busy mesh network.  Only ``send_device_query`` needs a fresh
        BLE round-trip.
        """
        # ----------------------------------------------------------
        # send_appstart — reuse result from MeshCore.connect()
        # ----------------------------------------------------------
        self.shared.set_status("🔄 Device info...")

        cached_info = self.mc.self_info  # Filled by connect() → send_appstart()
        if cached_info and cached_info.get("name"):
            print(f"BLE: send_appstart OK (from connect): {cached_info.get('name')}")
            self.shared.update_from_appstart(cached_info)
            self._cache.set_device(cached_info)
        else:
            # Fallback: device info not populated by connect() — retry manually
            debug_print(
                "self_info empty after connect(), falling back to manual send_appstart"
            )
            appstart_ok = False
            for i in range(3):
                debug_print(f"send_appstart fallback attempt {i + 1}/3")
                try:
                    r = await self.mc.commands.send_appstart()
                    if r is None:
                        debug_print(
                            f"send_appstart fallback {i + 1}: received None, retrying"
                        )
                        await asyncio.sleep(2.0)
                        continue
                    if r.type != EventType.ERROR:
                        print(
                            f"BLE: send_appstart OK: {r.payload.get('name')} "
                            f"(fallback attempt {i + 1})"
                        )
                        self.shared.update_from_appstart(r.payload)
                        self._cache.set_device(r.payload)
                        appstart_ok = True
                        break
                    else:
                        debug_print(
                            f"send_appstart fallback {i + 1}: "
                            f"ERROR — payload={pp(r.payload)}"
                        )
                except Exception as exc:
                    debug_print(f"send_appstart fallback {i + 1} exception: {exc}")
                await asyncio.sleep(2.0)

            if not appstart_ok:
                print("BLE: ⚠️  send_appstart failed after 3 fallback attempts")

        # ----------------------------------------------------------
        # send_device_query — no internal cache, must query device
        # Fewer attempts (5) with longer delays (2s) to give the
        # firmware time to process between mesh traffic bursts.
        # ----------------------------------------------------------
        for i in range(5):
            debug_print(f"send_device_query attempt {i + 1}/5")
            try:
                r = await self.mc.commands.send_device_query()
                if r is None:
                    debug_print(
                        f"send_device_query attempt {i + 1}: "
                        f"received None response, retrying"
                    )
                    await asyncio.sleep(2.0)
                    continue
                if r.type != EventType.ERROR:
                    fw = r.payload.get("ver", "")
                    print(f"BLE: send_device_query OK: {fw} (attempt {i + 1})")
                    self.shared.update_from_device_query(r.payload)
                    if fw:
                        self._cache.set_firmware_version(fw)
                    break
                else:
                    debug_print(
                        f"send_device_query attempt {i + 1}: "
                        f"ERROR response — payload={pp(r.payload)}"
                    )
            except Exception as exc:
                debug_print(f"send_device_query attempt {i + 1} exception: {exc}")
            await asyncio.sleep(2.0)

        # ----------------------------------------------------------
        # Channels (dynamic discovery from device)
        # ----------------------------------------------------------
        await self._discover_channels()

        # ----------------------------------------------------------
        # Contacts (merge with cache)
        # ----------------------------------------------------------
        self.shared.set_status("🔄 Contacts...")
        debug_print("get_contacts starting")
        try:
            r = await self.mc.commands.get_contacts()
            debug_print(f"get_contacts result: type={r.type if r else None}")
            if r and r.payload:
                debug_data("get_contacts payload", r.payload)
            if r is None:
                debug_print(
                    "BLE: get_contacts returned None, "
                    "keeping cached contacts"
                )
            elif r.type != EventType.ERROR:
                merged = self._cache.merge_contacts(r.payload)
                self.shared.set_contacts(merged)
                print(
                    f"BLE: Contacts — {len(r.payload)} from device, "
                    f"{len(merged)} total (with cache)"
                )
            else:
                debug_print(
                    "BLE: get_contacts failed — "
                    f"payload={pp(r.payload)}, keeping cached contacts"
                )
        except Exception as exc:
            debug_print(f"BLE: get_contacts exception: {exc}")

    # ------------------------------------------------------------------
    # Channel key loading (quick startup + background retry)
    # ------------------------------------------------------------------

    async def _discover_channels(self) -> None:
        """Discover channels and load their keys from the device.

        Probes channel indices 0..MAX_CHANNELS-1 via ``get_channel()``.
        Each successful response provides both the channel name and the
        encryption key, so discovery and key loading happen in a single
        pass.

        Speed strategy: single attempt per slot with short delays.
        Channels whose keys fail are retried in the background every
        ``KEY_RETRY_INTERVAL`` seconds.

        When ``CHANNEL_CACHE_ENABLED`` is True the discovered channel
        list is persisted to disk cache.  Channel keys are always
        cached regardless of this setting (they are needed for packet
        decoding on next startup).
        """
        self.shared.set_status("🔄 Discovering channels...")
        discovered: List[Dict] = []
        cached_keys = self._cache.get_channel_keys()

        confirmed: list[str] = []
        from_cache: list[str] = []
        derived: list[str] = []

        consecutive_errors = 0

        for idx in range(MAX_CHANNELS):
            # Two attempts per slot to handle transient BLE timeouts,
            # especially on slower mobile connections.
            payload = await self._try_get_channel_info(
                idx, max_attempts=2, delay=1.0,
            )

            if payload is None:
                consecutive_errors += 1
                # After 3 consecutive empty slots, assume no more channels.
                # Raised from 2 to 3: a single BLE hiccup no longer causes
                # the entire discovery to abort prematurely.
                if consecutive_errors >= 3:
                    debug_print(
                        f"Channel discovery: {consecutive_errors} consecutive "
                        f"empty slots at idx {idx}, stopping"
                    )
                    break
                continue

            # Reset consecutive error counter on success
            consecutive_errors = 0

            # Extract channel name (try common field names)
            name = (
                payload.get('name')
                or payload.get('channel_name')
                or ''
            )

            # Skip undefined/empty channel slots
            if not name.strip():
                debug_print(
                    f"Channel [{idx}]: response OK but no name — "
                    f"skipping (undefined slot)"
                )
                continue

            discovered.append({'idx': idx, 'name': name})

            # Extract key in the same pass
            secret = payload.get('channel_secret')
            secret_bytes = self._extract_secret(secret)

            if secret_bytes:
                self._decoder.add_channel_key(idx, secret_bytes, source="device")
                self._cache.set_channel_key(idx, secret_bytes.hex())
                self._pending_keys.discard(idx)
                confirmed.append(f"[{idx}] {name}")
            elif str(idx) in cached_keys:
                # Cache has the key — use it, don't overwrite
                from_cache.append(f"[{idx}] {name}")
                print(f"BLE: 📦 Channel [{idx}] '{name}' — using cached key")
            else:
                # No device key, no cache key — derive from name
                self._decoder.add_channel_key_from_name(idx, name)
                self._pending_keys.add(idx)
                derived.append(f"[{idx}] {name}")
                print(
                    f"BLE: ⚠️  Channel [{idx}] '{name}' — "
                    f"name-derived key (will retry)"
                )

            # Pause between channels to avoid BLE congestion.
            # Increased from 0.15s to 0.3s: mobile BLE stacks need
            # more time between consecutive GATT operations.
            await asyncio.sleep(0.3)

        # Fallback: if nothing discovered, add Public as default
        if not discovered:
            discovered = [{'idx': 0, 'name': 'Public'}]
            print("BLE: ⚠️ No channels discovered, using default Public channel")

        # Store discovered channels
        self._channels = discovered
        self.shared.set_channels(discovered)
        if CHANNEL_CACHE_ENABLED:
            self._cache.set_channels(discovered)
            debug_print("Channel list cached to disk")

        print(f"BLE: Channels discovered: {[c['name'] for c in discovered]}")

        # Key summary
        print(f"BLE: PacketDecoder ready — has_keys={self._decoder.has_keys}")
        if confirmed:
            print(f"BLE: ✅ Keys from device: {', '.join(confirmed)}")
        if from_cache:
            print(f"BLE: 📦 Keys from cache: {', '.join(from_cache)}")
        if derived:
            print(f"BLE: ⚠️  Name-derived keys: {', '.join(derived)}")

    async def _try_get_channel_info(
        self,
        idx: int,
        max_attempts: int,
        delay: float,
    ) -> Optional[Dict]:
        """Try to get channel info from the device.

        Returns the response payload dict on success, or None if the
        channel does not exist or could not be read after all attempts.
        """
        for attempt in range(max_attempts):
            try:
                r = await self.mc.commands.get_channel(idx)

                if r is None:
                    debug_print(
                        f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                        f"received None response, retrying"
                    )
                    await asyncio.sleep(delay)
                    continue

                if r.type == EventType.ERROR:
                    debug_print(
                        f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                        f"ERROR response — payload={pp(r.payload)}"
                    )
                    await asyncio.sleep(delay)
                    continue

                debug_print(
                    f"get_channel({idx}) attempt {attempt + 1}/{max_attempts}: "
                    f"OK — keys={list(r.payload.keys())}"
                )
                return r.payload

            except Exception as exc:
                debug_print(
                    f"get_channel({idx}) attempt {attempt + 1}/{max_attempts} "
                    f"error: {exc}"
                )
                await asyncio.sleep(delay)

        return None

    async def _try_load_channel_key(
        self,
        idx: int,
        name: str,
        max_attempts: int,
        delay: float,
    ) -> bool:
        """Try to load a single channel key from the device.

        Returns True if the key was successfully loaded and cached.
        Used by background retry for channels that failed during
        initial discovery.
        """
        payload = await self._try_get_channel_info(idx, max_attempts, delay)
        if payload is None:
            return False

        secret = payload.get('channel_secret')
        secret_bytes = self._extract_secret(secret)

        if secret_bytes:
            self._decoder.add_channel_key(idx, secret_bytes, source="device")
            self._cache.set_channel_key(idx, secret_bytes.hex())
            print(
                f"BLE: ✅ Channel [{idx}] '{name}' — "
                f"key from device (background retry)"
            )
            self._pending_keys.discard(idx)
            return True

        debug_print(
            f"get_channel({idx}): response OK but secret unusable"
        )
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
        ch_map = {ch['idx']: ch['name'] for ch in self._channels}

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

    # ------------------------------------------------------------------
    # Periodic cleanup
    # ------------------------------------------------------------------

    async def _cleanup_old_data(self) -> None:
        """Periodic cleanup of old archived data and contacts."""
        try:
            # Cleanup archived messages and rxlog
            if self.shared.archive:
                self.shared.archive.cleanup_old_data()
                stats = self.shared.archive.get_stats()
                debug_print(
                    f"Cleanup: archive now has {stats['total_messages']} messages, "
                    f"{stats['total_rxlog']} rxlog entries"
                )
            
            # Prune old contacts from cache
            removed = self._cache.prune_old_contacts()
            if removed > 0:
                # Reload contacts to SharedData after pruning
                contacts = self._cache.get_contacts()
                self.shared.set_contacts(contacts)
                debug_print(f"Cleanup: pruned {removed} old contacts")
            
        except Exception as exc:
            debug_print(f"Periodic cleanup failed: {exc}")

