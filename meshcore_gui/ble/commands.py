"""
Device command handlers for MeshCore GUI.

Extracted from ``SerialWorker`` so that each command is an isolated unit
of work.  New commands can be registered without modifying existing
code (Open/Closed Principle).
"""

import asyncio
from typing import Dict, List, Optional

from meshcore import MeshCore, EventType

from meshcore_gui.config import BOT_DEVICE_NAME, DEVICE_NAME, debug_print
from meshcore_gui.core.models import Message
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.services.cache import DeviceCache


class CommandHandler:
    MAX_REPLY_LEN: int = 180

    """Dispatches and executes commands sent from the GUI.

    Args:
        mc:     Connected MeshCore instance.
        shared: SharedDataWriter for storing results.
        cache:  DeviceCache for persistent storage.
    """

    def __init__(
        self,
        mc: MeshCore,
        shared: SharedDataWriter,
        cache: Optional[DeviceCache] = None,
    ) -> None:
        self._mc = mc
        self._shared = shared
        self._cache = cache

        # Handler registry — add new commands here (OCP)
        self._handlers: Dict[str, object] = {
            'send_message': self._cmd_send_message,
            'send_dm': self._cmd_send_dm,
            'send_advert': self._cmd_send_advert,
            'refresh': self._cmd_refresh,
            'purge_unpinned': self._cmd_purge_unpinned,
            'set_auto_add': self._cmd_set_auto_add,
            'set_device_name': self._cmd_set_device_name,
            'login_room': self._cmd_login_room,
            'logout_room': self._cmd_logout_room,
            'send_room_msg': self._cmd_send_room_msg,
            'load_room_history': self._cmd_load_room_history,
            'add_channel': self._cmd_add_channel,
        }

    async def process_all(self) -> None:
        """Drain the command queue and dispatch each command."""
        while True:
            cmd = self._shared.get_next_command()
            if cmd is None:
                break
            await self._dispatch(cmd)

    async def _dispatch(self, cmd: Dict) -> None:
        action = cmd.get('action')
        handler = self._handlers.get(action)
        if handler:
            await handler(cmd)
        else:
            debug_print(f"Unknown command action: {action}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_reply(self, text: str) -> List[str]:
        """Split long replies into transport-safe chunks on line boundaries."""
        if not text:
            return []
        lines = str(text).splitlines() or [str(text)]
        chunks: List[str] = []
        current = ""
        for line in lines:
            line = line.rstrip()
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= self.MAX_REPLY_LEN:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            while len(line) > self.MAX_REPLY_LEN:
                chunks.append(line[:self.MAX_REPLY_LEN])
                line = line[self.MAX_REPLY_LEN:]
            current = line
        if current:
            chunks.append(current)
        return chunks

    # ------------------------------------------------------------------
    # Individual command handlers
    # ------------------------------------------------------------------

    async def _cmd_send_message(self, cmd: Dict) -> None:
        channel = cmd.get('channel', 0)
        text = cmd.get('text', '')
        is_bot = cmd.get('_bot', False)
        if text:
            chunks = self._split_reply(text)
            for idx, chunk in enumerate(chunks):
                await self._mc.commands.send_chan_msg(channel, chunk)
                if idx + 1 < len(chunks):
                    await asyncio.sleep(0.2)
            if not is_bot:
                self._shared.add_message(Message.outgoing(text, channel))
            debug_print(
                f"{'BOT' if is_bot else 'Sent'} message to "
                f"channel {channel}: {text[:30]}"
            )

    async def _cmd_send_dm(self, cmd: Dict) -> None:
        pubkey = cmd.get('pubkey', '')
        text = cmd.get('text', '')
        contact_name = cmd.get('contact_name', pubkey[:8])
        if text and pubkey:
            chunks = self._split_reply(text)
            for idx, chunk in enumerate(chunks):
                await self._mc.commands.send_msg(pubkey, chunk)
                if idx + 1 < len(chunks):
                    await asyncio.sleep(0.2)
            self._shared.add_message(Message.outgoing(text, None, sender_pubkey=pubkey))
            debug_print(f"Sent DM to {contact_name}: {text[:30]}")

    async def _cmd_send_advert(self, cmd: Dict) -> None:
        await self._mc.commands.send_advert(flood=True)
        self._shared.set_status("📢 Advert sent")
        debug_print("Advert sent")

    async def _cmd_refresh(self, cmd: Dict) -> None:
        debug_print("Refresh requested")
        # Delegate to the worker's _load_data via a callback
        if self._load_data_callback:
            try:
                self._shared.set_status("🔄 Refreshing...")
                await self._load_data_callback()
                self._shared.set_status("✅ Refreshed")
            except Exception as exc:
                self._shared.set_status(f"⚠️ Refresh error: {exc}")
                debug_print(f"Refresh failed: {exc}")

    async def _cmd_purge_unpinned(self, cmd: Dict) -> None:
        """Remove unpinned contacts from the MeshCore device.

        Iterates the list of public keys, calls ``remove_contact``
        for each one with a short delay between calls to avoid
        overwhelming the link.  After completion, triggers a
        full refresh so the GUI reflects the new state.

        If ``delete_from_history`` is True, also removes the
        contacts from the local device cache on disk.

        Expected command dict::

            {
                'action': 'purge_unpinned',
                'pubkeys': ['aabbcc...', ...],
                'delete_from_history': True/False,
            }
        """
        pubkeys: List[str] = cmd.get('pubkeys', [])
        delete_from_history: bool = cmd.get('delete_from_history', False)

        if not pubkeys:
            self._shared.set_status("⚠️ No contacts to remove")
            return

        total = len(pubkeys)
        removed = 0
        errors = 0

        self._shared.set_status(
            f"🗑️ Removing {total} contacts..."
        )
        debug_print(f"Purge: starting removal of {total} contacts")

        for i, pubkey in enumerate(pubkeys, 1):
            try:
                r = await self._mc.commands.remove_contact(pubkey)
                if r.type == EventType.ERROR:
                    errors += 1
                    debug_print(
                        f"Purge: remove_contact({pubkey[:16]}) "
                        f"returned ERROR"
                    )
                else:
                    removed += 1
                    debug_print(
                        f"Purge: removed {pubkey[:16]} "
                        f"({i}/{total})"
                    )
            except Exception as exc:
                errors += 1
                debug_print(
                    f"Purge: remove_contact({pubkey[:16]}) "
                    f"exception: {exc}"
                )

            # Update status with progress
            self._shared.set_status(
                f"🗑️ Removing... {i}/{total}"
            )

            # Brief pause between calls to avoid congestion
            if i < total:
                await asyncio.sleep(0.5)

        # Delete from local cache if requested
        if delete_from_history and self._cache:
            cache_removed = self._cache.remove_contacts(pubkeys)
            debug_print(
                f"Purge: removed {cache_removed} contacts "
                f"from local history"
            )

        # Summary
        if errors:
            status = (
                f"⚠️ {removed} contacts removed, "
                f"{errors} failed"
            )
        else:
            history_suffix = " and local history" if delete_from_history else ""
            status = f"✅ {removed} contacts removed from device{history_suffix}"

        self._shared.set_status(status)
        print(f"Purge: {status}")

        # Resync with device to confirm new state
        if self._load_data_callback:
            await self._load_data_callback()

    async def _cmd_set_auto_add(self, cmd: Dict) -> None:
        """Toggle auto-add contacts on the MeshCore device.

        The SDK function ``set_manual_add_contacts(true)`` means
        *manual mode* (auto-add OFF).  The UI toggle is inverted:
        toggle ON = auto-add ON = ``set_manual_add_contacts(false)``.

        On failure the SharedData flag is rolled back so the GUI
        checkbox reverts on the next update cycle.

        Note: some firmware/SDK versions raise ``KeyError`` (e.g.
        ``'telemetry_mode_base'``) when parsing the device response.
        The command itself was already sent successfully in that
        case, so we treat ``KeyError`` as *probable success* and keep
        the requested state instead of rolling back.

        Expected command dict::

            {
                'action': 'set_auto_add',
                'enabled': True/False,
            }
        """
        enabled: bool = cmd.get('enabled', False)
        # Invert: UI "auto-add ON" → manual_add = False
        manual_add = not enabled
        state = "ON" if enabled else "OFF"

        try:
            r = await self._mc.commands.set_manual_add_contacts(manual_add)
            if r.type == EventType.ERROR:
                # Rollback
                self._shared.set_auto_add_enabled(not enabled)
                self._shared.set_status(
                    "⚠️ Failed to change auto-add setting"
                )
                debug_print(
                    f"set_auto_add: ERROR response, rolled back to "
                    f"{'enabled' if not enabled else 'disabled'}"
                )
            else:
                self._shared.set_auto_add_enabled(enabled)
                self._shared.set_status(f"✅ Auto-add contacts: {state}")
                debug_print(f"set_auto_add: success → {state}")
        except KeyError as exc:
            # SDK response-parsing error (e.g. missing 'telemetry_mode_base').
            # The command was already transmitted; the device has likely
            # accepted the new setting.  Keep the requested state.
            self._shared.set_auto_add_enabled(enabled)
            self._shared.set_status(f"✅ Auto-add contacts: {state}")
            debug_print(
                f"set_auto_add: KeyError '{exc}' during response parse — "
                f"command sent, treating as success → {state}"
            )
        except Exception as exc:
            # Rollback
            self._shared.set_auto_add_enabled(not enabled)
            self._shared.set_status(
                f"⚠️ Auto-add error: {exc}"
            )
            debug_print(f"set_auto_add exception: {exc}")

    async def _cmd_set_device_name(self, cmd: Dict) -> None:
        """Set or restore the device name.

        Uses the fixed names from config.py unless an explicit name is provided:
            - Explicit name → set to that value
            - BOT enabled   → ``BOT_DEVICE_NAME``  (e.g. "NL-OV-ZWL-STDSHGN-WKC Bot")
            - BOT disabled  → ``DEVICE_NAME``       (e.g. "PE1HVH T1000e")

        This avoids the previous bug where the dynamically read device
        name could already be the bot name (e.g. after a restart while
        BOT was active), causing the original name to be overwritten
        with the bot name.

        On failure the bot_enabled flag is rolled back so the GUI
        checkbox reverts on the next update cycle.

        Expected command dict::

            {
                'action': 'set_device_name',
                'bot_enabled': True/False,
                'name': 'optional explicit name',
            }
        """
        explicit_name = cmd.get('name')
        has_explicit_name = explicit_name is not None and str(explicit_name).strip() != ""
        if has_explicit_name:
            target_name = str(explicit_name).strip()
            bot_enabled = self._shared.is_bot_enabled()
        else:
            bot_enabled = bool(cmd.get('bot_enabled', False))
            target_name = BOT_DEVICE_NAME if bot_enabled else DEVICE_NAME

        try:
            r = await self._mc.commands.set_name(target_name)
            if r.type == EventType.ERROR:
                # Rollback only when driven by BOT toggle
                if not has_explicit_name:
                    self._shared.set_bot_enabled(not bot_enabled)
                self._shared.set_status(
                    f"⚠️ Failed to set device name to '{target_name}'"
                )
                debug_print(
                    f"set_device_name: ERROR response for '{target_name}', "
                    f"{'rolled back bot_enabled to ' + str(not bot_enabled) if not has_explicit_name else 'no bot rollback'}"
                )
                return

            self._shared.set_status(f"✅ Device name → {target_name}")
            debug_print(f"set_device_name: success → '{target_name}'")

            # Send advert so the network sees the new name
            await self._mc.commands.send_advert(flood=True)
            debug_print("set_device_name: advert sent")

        except Exception as exc:
            # Rollback on exception (BOT toggle only)
            if not has_explicit_name:
                self._shared.set_bot_enabled(not bot_enabled)
            self._shared.set_status(f"⚠️ Device name error: {exc}")
            debug_print(f"set_device_name exception: {exc}")

    async def _cmd_login_room(self, cmd: Dict) -> None:
        """Send a Room Server login request.

        This command handler owns only the *send* side of the login flow:
        it queues archived room history for immediate UI display, marks the
        room state as ``pending`` and sends the login packet to the companion
        radio.

        The definitive ``LOGIN_SUCCESS`` handling is intentionally centralised
        in :mod:`meshcore_gui.ble.worker`, which already subscribes to the
        MeshCore event stream.  Keeping the success path in one place avoids a
        second competing wait/timeout path here in the command layer.

        Expected command dict::

            {
                'action': 'login_room',
                'pubkey': '<hex public key>',
                'password': '<room password>',
                'room_name': '<display name>',
            }
        """
        pubkey: str = cmd.get('pubkey', '')
        password: str = cmd.get('password', '')
        room_name: str = cmd.get('room_name', pubkey[:8])

        if not pubkey:
            self._shared.set_status("⚠️ Room login: no pubkey")
            return

        # Show archived room messages immediately while the radio/login path
        # continues asynchronously.
        self._shared.load_room_history(pubkey)
        self._shared.set_room_login_state(pubkey, 'pending', 'Sending login…')

        try:
            self._shared.set_status(f"🔄 Sending login to {room_name}…")
            r = await self._mc.commands.send_login(pubkey, password)

            if r is None:
                self._shared.set_room_login_state(
                    pubkey, 'fail', 'Login send returned no response',
                )
                self._shared.set_status(
                    f"⚠️ Room login failed: {room_name}"
                )
                debug_print(
                    f"login_room: send_login returned None for {room_name} "
                    f"({pubkey[:16]})"
                )
                return

            if r.type == EventType.ERROR:
                self._shared.set_room_login_state(
                    pubkey, 'fail', 'Login send failed',
                )
                self._shared.set_status(
                    f"⚠️ Room login failed: {room_name}"
                )
                debug_print(
                    f"login_room: send_login ERROR for {room_name} "
                    f"({pubkey[:16]})"
                )
                return

            suggested = (r.payload or {}).get('suggested_timeout', 96000)
            timeout_secs = max(suggested / 800, 30.0)
            self._shared.set_status(
                f"⏳ Waiting for room server response ({room_name})…"
            )
            debug_print(
                f"login_room: login packet accepted for {room_name}; "
                f"worker owns LOGIN_SUCCESS handling "
                f"(suggested timeout {timeout_secs:.0f}s)"
            )

        except Exception as exc:
            self._shared.set_room_login_state(pubkey, 'fail', str(exc))
            self._shared.set_status(f"⚠️ Room login error: {exc}")
            debug_print(f"login_room exception: {exc}")

    async def _cmd_logout_room(self, cmd: Dict) -> None:
        """Logout from a Room Server.

        Sends a logout command to the companion radio so it stops
        keep-alive pings and the room server deregisters the client.
        This resets the server-side ``sync_since`` state, ensuring
        that the next login will receive the full message history.

        Expected command dict::

            {
                'action': 'logout_room',
                'pubkey': '<hex public key>',
                'room_name': '<display name>',
            }
        """
        pubkey: str = cmd.get('pubkey', '')
        room_name: str = cmd.get('room_name', pubkey[:8])

        if not pubkey:
            return

        try:
            r = await self._mc.commands.send_logout(pubkey)
            if r.type == EventType.ERROR:
                debug_print(
                    f"logout_room: ERROR for {room_name} "
                    f"({pubkey[:16]})"
                )
            else:
                debug_print(
                    f"logout_room: OK for {room_name} "
                    f"({pubkey[:16]})"
                )
        except AttributeError:
            # Library may not have send_logout — fall back to silent
            debug_print(
                f"logout_room: send_logout not available in library, "
                f"skipping for {room_name}"
            )
        except Exception as exc:
            debug_print(f"logout_room exception: {exc}")

        self._shared.set_room_login_state(pubkey, 'logged_out')
        self._shared.set_status(
            f"Logged out from {room_name}"
        )

    async def _cmd_load_room_history(self, cmd: Dict) -> None:
        """Load archived room messages into the in-memory cache.

        Called when a room card is rendered so the panel can display
        historical messages even before login.  Also safe to call
        after login to refresh.

        Expected command dict::

            {
                'action': 'load_room_history',
                'pubkey': '<hex public key>',
            }
        """
        pubkey: str = cmd.get('pubkey', '')
        if pubkey:
            self._shared.load_room_history(pubkey)

    async def _cmd_send_room_msg(self, cmd: Dict) -> None:
        """Send a message to a Room Server (post to room).

        Uses ``send_msg`` with the Room Server's public key, which
        is the standard way to post a message to a room after login.

        Expected command dict::

            {
                'action': 'send_room_msg',
                'pubkey': '<hex public key>',
                'text': '<message text>',
                'room_name': '<display name>',
            }
        """
        pubkey: str = cmd.get('pubkey', '')
        text: str = cmd.get('text', '')
        room_name: str = cmd.get('room_name', pubkey[:8])

        if not text or not pubkey:
            return

        try:
            await self._mc.commands.send_msg(pubkey, text)
            self._shared.add_message(Message.outgoing(
                text, None, sender_pubkey=pubkey,
            ))
            debug_print(
                f"send_room_msg: sent to {room_name}: "
                f"{text[:30]}"
            )
        except Exception as exc:
            self._shared.set_status(
                f"⚠️ Room message error: {exc}"
            )
            debug_print(f"send_room_msg exception: {exc}")

    async def _cmd_add_channel(self, cmd: Dict) -> None:
        """Add or update a channel slot on the MeshCore device.

        Calls ``mc.commands.set_channel()`` and — on success — triggers a
        full channel re-discovery so the GUI immediately reflects the new
        channel in the submenu and filter checkboxes.

        The library's ``set_channel`` handles two cases automatically:
        - ``channel_name.startswith('#')`` or ``secret=None`` → key derived
          from ``SHA-256(name)[:16]`` (hashtag channel).
        - Explicit 16-byte ``secret`` → used verbatim (private channel).

        Expected command dict::

            {
                'action': 'add_channel',
                'idx': int,        # target channel slot (1–99)
                'name': str,       # channel name
                'secret_hex': str, # 32-char hex for private; '' for hashtag
            }
        """
        idx: int = int(cmd.get('idx', 1))
        name: str = (cmd.get('name') or '').strip()
        secret_hex: str = (cmd.get('secret_hex') or '').strip()

        if not name:
            debug_print('add_channel: no name provided, skipping')
            return

        # Resolve secret: empty string → None (library derives from name)
        secret_bytes: Optional[bytes] = None
        if secret_hex:
            try:
                secret_bytes = bytes.fromhex(secret_hex)
            except ValueError:
                self._shared.set_status('⚠️ Invalid channel secret (not valid hex)')
                debug_print(f'add_channel: bad hex secret for [{idx}] {name}')
                return

        try:
            r = await self._mc.commands.set_channel(idx, name, secret_bytes)
            if r.type == EventType.ERROR:
                self._shared.set_status(f"⚠️ Failed to add channel '{name}'")
                debug_print(f'add_channel: device returned ERROR for [{idx}] {name}')
            else:
                self._shared.set_status(f"✅ Channel [{idx}] '{name}' added")
                debug_print(f'add_channel: success [{idx}] {name}')
                # Re-discover channels so the GUI updates immediately
                if self._load_data_callback:
                    await self._load_data_callback()
        except Exception as exc:
            self._shared.set_status(f'⚠️ Add channel error: {exc}')
            debug_print(f'add_channel exception: {exc}')

    # ------------------------------------------------------------------
    # Callback for refresh (set by SerialWorker after construction)
    # ------------------------------------------------------------------

    _load_data_callback = None

    def set_load_data_callback(self, callback) -> None:
        """Register the worker's ``_load_data`` coroutine for refresh."""
        self._load_data_callback = callback
