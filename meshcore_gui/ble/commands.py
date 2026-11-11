"""
Device command handlers for MeshCore GUI.

Extracted from ``SerialWorker`` so that each command is an isolated unit
of work.  New commands can be registered without modifying existing
code (Open/Closed Principle).

Regions
~~~~~~~
``send_message`` accepts an optional ``region`` key (a per-message
override).  Without it the channel default from the
:class:`~meshcore_gui.services.region_service.RegionService` applies.  When
a region results, the device send override is set for this send only and
reset afterwards, because the firmware applies that override to every
flood packet — including DMs sent later.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Set

from meshcore import MeshCore, EventType
from meshcore.packets import CommandType

from meshcore_gui.config import (
    BOT_DEVICE_NAME,
    DEVICE_NAME,
    DM_FLOOD_AFTER,
    DM_MAX_ATTEMPTS,
    debug_print,
)
from meshcore_gui.core.models import Message
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.services.cache import DeviceCache
from meshcore_gui.services.region_service import (
    RegionService,
    default_scope_payload,
    region_key,
)


@dataclass
class _DmDelivery:
    """One DM reply being delivered part by part to one recipient.

    Attributes:
        pubkey:       Recipient key as given in the ``send_dm`` command
                      (full key or prefix, hex).
        contact_name: Label used in log lines.
        chunks:       Parts of the reply, each within ``MAX_DM_TEXT_BYTES``.
        index:        Index of the part currently being delivered.
        attempt:      Number of send attempts already made for that part.
        timestamp:    Sender timestamp of that part (Unix seconds); kept
                      for every retry so the receiver sees the same message.
        acks:         Expected ACK codes (8 hex characters) of all attempts
                      of that part; an ACK of any attempt confirms it.
        waiting:      True while a sent part awaits its ACK.
        deadline:     ``time.monotonic()`` value after which the waiting
                      part counts as not confirmed.
    """

    pubkey: str
    contact_name: str
    chunks: List[str]
    index: int = 0
    attempt: int = 0
    timestamp: int = 0
    acks: Set[str] = field(default_factory=set)
    waiting: bool = False
    deadline: float = 0.0


class CommandHandler:
    """Dispatches and executes commands sent from the GUI.

    Args:
        mc:              Connected MeshCore instance.
        shared:          SharedDataWriter for storing results.
        cache:           DeviceCache for persistent storage.
        repeater_poller: Poller used by the manual REPEATERS poll button.
                         Optional; the command is ignored when absent.
        region_service:  Decides the send region of channel messages.
                         Optional; without it messages are sent exactly
                         as before (device default scope).
        channel_name_lookup: Returns the channel name for a channel index;
                         needed to find the channel default region.
    """

    MAX_REPLY_LEN: int = 180
    """Chunk limit in characters for channel messages (``send_message``)."""

    MAX_DM_TEXT_BYTES: int = 160
    """Chunk limit in UTF-8 bytes for direct messages (``send_dm``).

    Equals ``MAX_TEXT_LEN`` (10 x 16 bytes) of the MeshCore firmware: a
    longer DM text is refused by the device with ``ERR_CODE_TABLE_FULL``
    (``BaseChatMesh::composeMsgPacket`` returns no packet).
    """

    def __init__(
        self,
        mc: MeshCore,
        shared: SharedDataWriter,
        cache: Optional[DeviceCache] = None,
        repeater_poller: Optional[object] = None,
        region_service: Optional[RegionService] = None,
        channel_name_lookup: Optional[Callable[[int], str]] = None,
    ) -> None:
        self._mc = mc
        self._shared = shared
        self._cache = cache
        self._repeater_poller = repeater_poller
        self._region_service = region_service
        self._channel_name_lookup = channel_name_lookup
        self._default_scope_reader = None

        # DM replies in delivery, one queue per recipient (key = pubkey in
        # lower case).  Only the head of each queue is active; see
        # ``process_dm_deliveries``.
        self._dm_queues: Dict[str, Deque[_DmDelivery]] = {}

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
            'del_channel': self._cmd_del_channel,
            'move_channel': self._cmd_move_channel,
            'poll_repeater': self._cmd_poll_repeater,
            'set_default_region': self._cmd_set_default_region,
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

    def _split_reply(
        self, text: str, max_bytes: Optional[int] = None,
    ) -> List[str]:
        """Split long replies into transport-safe chunks on line boundaries.

        Lines are joined with ``\\n`` as long as the chunk fits; a single
        line that does not fit on its own is cut hard.

        Args:
            text:      Reply text, possibly multi-line.
            max_bytes: Chunk limit in UTF-8 bytes.  ``None`` keeps the
                       character limit ``MAX_REPLY_LEN``.  With a byte
                       limit a hard cut never splits a multi-byte
                       character.

        Returns:
            List of chunks in send order; empty for empty *text*.
        """
        if not text:
            return []

        def fits(part: str) -> bool:
            """Return True when *part* is within the active limit.

            Args:
                part: Candidate chunk text.

            Returns:
                True if *part* fits in one chunk.
            """
            if max_bytes is None:
                return len(part) <= self.MAX_REPLY_LEN
            return len(part.encode("utf-8")) <= max_bytes

        def head(part: str) -> str:
            """Return the longest leading piece of *part* that fits.

            Args:
                part: Line that does not fit as a whole.

            Returns:
                Leading piece of *part*; at least one character, so the
                caller always makes progress.
            """
            if max_bytes is None:
                return part[:self.MAX_REPLY_LEN]
            cut = part.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
            return cut or part[:1]

        lines = str(text).splitlines() or [str(text)]
        chunks: List[str] = []
        current = ""
        for line in lines:
            line = line.rstrip()
            candidate = line if not current else f"{current}\n{line}"
            if fits(candidate):
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            while not fits(line):
                piece = head(line)
                chunks.append(piece)
                line = line[len(piece):]
            current = line
        if current:
            chunks.append(current)
        return chunks

    # ------------------------------------------------------------------
    # Individual command handlers
    # ------------------------------------------------------------------

    async def _cmd_poll_repeater(self, cmd: Dict) -> None:
        """Poll a single repeater on request from the REPEATERS panel.

        The poller records the result — success or failure — so nothing
        needs to be reported back through SharedData.

        Args:
            cmd: Command dict with a ``pubkey`` key.
        """
        pubkey = cmd.get('pubkey', '')
        if not pubkey:
            debug_print("poll_repeater: no pubkey in command")
            return
        if self._repeater_poller is None:
            debug_print("poll_repeater: no poller wired, ignoring")
            return
        await self._repeater_poller.poll_now(self._mc, pubkey)

    async def _set_send_scope(self, region: str) -> bool:
        """Set the device send override to *region* (empty = reset).

        Args:
            region: Region name, or an empty string to reset the override
                    so the device default scope applies again.

        Returns:
            True when the device accepted the command.
        """
        scope = region_key(region) if region else None
        try:
            result = await self._mc.commands.set_flood_scope(scope)
        except Exception as exc:
            debug_print(f"set_flood_scope({region or 'reset'}) exception: {exc}")
            return False
        if result is None or result.type == EventType.ERROR:
            debug_print(
                f"set_flood_scope({region or 'reset'}) failed: "
                f"{result.payload if result else 'no response'}"
            )
            return False
        return True

    def _resolve_send_region(self, cmd: Dict) -> str:
        """Return the region a ``send_message`` command must use.

        Args:
            cmd: Command dict with ``channel`` and optional ``region``.

        Returns:
            Region name for the send override, or an empty string.
        """
        if self._region_service is None:
            return ""
        channel_name = ""
        if self._channel_name_lookup is not None:
            channel_name = self._channel_name_lookup(cmd.get('channel', 0)) or ""
        return self._region_service.resolve_send_region(
            channel_name, cmd.get('region'),
        )

    async def _cmd_set_default_region(self, cmd: Dict) -> None:
        """Set or clear the device default region (flood scope).

        The frame is built by :func:`default_scope_payload`; an empty
        ``region`` clears the default.  Afterwards the value is read back
        from the device (callback set by the worker) so the GUI shows what
        the radio actually stores.

        Args:
            cmd: Command dict with a ``region`` key.
        """
        region = cmd.get('region', '') or ''
        try:
            payload = default_scope_payload(region)
        except ValueError as exc:
            self._shared.set_status(f"⚠️ Default region: {exc}")
            return
        frame = bytes([CommandType.SET_DEFAULT_FLOOD_SCOPE.value]) + payload
        try:
            result = await self._mc.commands.send(
                frame, [EventType.OK, EventType.ERROR],
            )
        except Exception as exc:
            debug_print(f"set_default_region exception: {exc}")
            result = None
        if result is None or result.type == EventType.ERROR:
            self._shared.set_status("⚠️ Default region not accepted by device")
            debug_print(
                f"set_default_region({region!r}) failed: "
                f"{result.payload if result else 'no response'}"
            )
        else:
            self._shared.set_status(
                f"✅ Default region: {('#' + region.lstrip('#')) if region else 'none'}"
            )
        if self._default_scope_reader is not None:
            await self._default_scope_reader()

    def set_default_scope_reader(self, callback) -> None:
        """Register the coroutine that re-reads the device default region.

        Args:
            callback: Async callable without arguments (worker method).
        """
        self._default_scope_reader = callback

    async def _cmd_send_message(self, cmd: Dict) -> None:
        channel = cmd.get('channel', 0)
        text = cmd.get('text', '')
        is_bot = cmd.get('_bot', False)
        if text:
            region = self._resolve_send_region(cmd)
            scoped = bool(region) and await self._set_send_scope(region)
            try:
                chunks = self._split_reply(text)
                for idx, chunk in enumerate(chunks):
                    await self._mc.commands.send_chan_msg(channel, chunk)
                    if idx + 1 < len(chunks):
                        await asyncio.sleep(0.2)
            finally:
                if scoped:
                    await self._set_send_scope("")
            if not is_bot:
                label = ""
                if self._region_service is not None:
                    label = self._region_service.label_for_sent(
                        region if scoped else ""
                    )
                self._shared.add_message(
                    Message.outgoing(text, channel, region=label)
                )
            debug_print(
                f"{'BOT' if is_bot else 'Sent'} message to "
                f"channel {channel}"
                f"{f' (region #{region})' if scoped else ''}: {text[:30]}"
            )

    async def _cmd_send_dm(self, cmd: Dict) -> None:
        """Queue a DM for delivery according to the MeshCore DM protocol.

        The text is split into parts of at most ``MAX_DM_TEXT_BYTES``.
        Nothing is sent here: ``process_dm_deliveries`` (called by the
        worker main loop) sends one part at a time and the next part only
        after the ACK of the previous one.

        Args:
            cmd: Command dict with ``pubkey``, ``text`` and optional
                 ``contact_name``.
        """
        pubkey = cmd.get('pubkey', '')
        text = cmd.get('text', '')
        contact_name = cmd.get('contact_name', pubkey[:8])
        if text and pubkey:
            chunks = self._split_reply(text, max_bytes=self.MAX_DM_TEXT_BYTES)
            queue = self._dm_queues.setdefault(pubkey.lower(), deque())
            queue.append(_DmDelivery(
                pubkey=pubkey, contact_name=contact_name, chunks=chunks,
            ))
            self._shared.add_message(Message.outgoing(text, None, sender_pubkey=pubkey))
            debug_print(
                f"DM to {contact_name} queued ({len(chunks)} part(s)): {text[:30]}"
            )

    # ------------------------------------------------------------------
    # DM delivery (ACK-driven, one queue per recipient)
    # ------------------------------------------------------------------

    def has_dm_deliveries(self) -> bool:
        """Return True while any DM reply is still being delivered.

        Returns:
            True if at least one recipient queue is not empty.
        """
        return any(self._dm_queues.values())

    def on_ack(self, event) -> None:
        """Confirm the DM part whose expected ACK code matches *event*.

        Subscribed to ``EventType.ACK`` by the worker.  Only marks the
        part as confirmed; the next part is sent by
        ``process_dm_deliveries``.

        Args:
            event: MeshCore event whose payload holds ``code`` (8 hex
                characters).
        """
        payload = event.payload if isinstance(event.payload, dict) else {}
        code = str(payload.get('code', '')).lower()
        if not code:
            return
        for queue in self._dm_queues.values():
            if not queue:
                continue
            delivery = queue[0]
            if delivery.waiting and code in delivery.acks:
                debug_print(
                    f"DM to {delivery.contact_name} part "
                    f"{delivery.index + 1}/{len(delivery.chunks)} confirmed"
                )
                delivery.waiting = False
                delivery.index += 1
                delivery.attempt = 0
                delivery.acks.clear()
                return

    async def process_dm_deliveries(self) -> None:
        """Advance every recipient queue by at most one step.

        Called once per worker main-loop iteration; never waits for an
        ACK itself, so other commands keep flowing.  Per queue head:

        - part confirmed or not yet sent: send the next part, or finish
          the reply when all parts are confirmed;
        - waiting and deadline passed: send the same part again (same
          timestamp, next attempt number), resetting the path to flood
          before attempt ``DM_FLOOD_AFTER + 1``; after
          ``DM_MAX_ATTEMPTS`` the rest of the reply is dropped.
        """
        now = time.monotonic()
        for key in list(self._dm_queues):
            queue = self._dm_queues[key]
            if not queue:
                del self._dm_queues[key]
                continue
            delivery = queue[0]
            if delivery.waiting:
                if now < delivery.deadline:
                    continue
                delivery.waiting = False
                delivery.attempt += 1
                debug_print(
                    f"DM to {delivery.contact_name} part "
                    f"{delivery.index + 1}/{len(delivery.chunks)}: no ACK"
                )
            if delivery.index >= len(delivery.chunks):
                debug_print(
                    f"DM to {delivery.contact_name} delivered "
                    f"({len(delivery.chunks)} part(s))"
                )
                queue.popleft()
                continue
            if delivery.attempt >= DM_MAX_ATTEMPTS:
                debug_print(
                    f"DM to {delivery.contact_name} failed at part "
                    f"{delivery.index + 1}/{len(delivery.chunks)} after "
                    f"{delivery.attempt} attempt(s); remaining parts dropped"
                )
                queue.popleft()
                continue
            await self._send_dm_part(delivery)

    async def _send_dm_part(self, delivery: _DmDelivery) -> None:
        """Send the current part of *delivery* once and start waiting.

        Args:
            delivery: Queue head whose part ``index`` is sent with attempt
                number ``attempt``.
        """
        if delivery.attempt == 0:
            delivery.timestamp = int(time.time())
        elif delivery.attempt == DM_FLOOD_AFTER:
            await self._reset_dm_path(delivery)
        chunk = delivery.chunks[delivery.index]
        result = await self._mc.commands.send_msg(
            delivery.pubkey, chunk,
            timestamp=delivery.timestamp, attempt=delivery.attempt,
        )
        label = (
            f"DM to {delivery.contact_name} part "
            f"{delivery.index + 1}/{len(delivery.chunks)} "
            f"attempt {delivery.attempt + 1}"
        )
        if result is None or result.type == EventType.ERROR:
            # Counts as a failed attempt; retried on the next iteration.
            delivery.attempt += 1
            debug_print(
                f"{label} refused by device: "
                f"{result.payload if result else 'no response'}"
            )
            return
        expected = result.payload.get('expected_ack', b'')
        if isinstance(expected, (bytes, bytearray)):
            expected = expected.hex()
        timeout_ms = result.payload.get('suggested_timeout', 0) or 0
        delivery.acks.add(str(expected).lower())
        delivery.waiting = True
        delivery.deadline = time.monotonic() + timeout_ms / 1000 * 1.2
        debug_print(f"{label} sent, ACK {expected}, timeout {timeout_ms} ms")

    async def _reset_dm_path(self, delivery: _DmDelivery) -> None:
        """Reset the device path to the recipient so the next part floods.

        ``reset_path`` needs the full 32-byte key; the BBS passes only a
        prefix, so the full key is taken from the contact list.

        Args:
            delivery: Delivery whose recipient path is reset.
        """
        full_key = delivery.pubkey
        if len(full_key) < 64:
            contact = self._shared.get_contact_by_prefix(delivery.pubkey) or {}
            full_key = str(contact.get('public_key', '') or '')
        if len(full_key) < 64:
            debug_print(
                f"DM to {delivery.contact_name}: full key unknown, path not reset"
            )
            return
        result = await self._mc.commands.reset_path(full_key)
        if result is None or result.type == EventType.ERROR:
            debug_print(f"DM to {delivery.contact_name}: reset_path failed")
        else:
            debug_print(f"DM to {delivery.contact_name}: path reset to flood")

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

    async def _cmd_del_channel(self, cmd: Dict) -> None:
        """Delete a channel slot on the MeshCore device and re-index higher slots.

        After deleting index N, all channels with index > N are moved down
        by one to close any gap in the channel list.

        Expected command dict::

            {
                'action':   'del_channel',
                'idx':      int,        # channel slot to delete (1-99)
                'channels': List[Dict], # snapshot of current channel list
            }

        Re-indexing uses secrets from the DeviceCache so private channel
        keys are preserved when slots are renumbered.
        """
        idx: int = int(cmd.get('idx', 0))
        channels: List[Dict] = cmd.get('channels', [])

        if not idx:
            debug_print('del_channel: no index provided, skipping')
            return

        # Retrieve cached secrets for re-indexing (JSON keys stored as str)
        cache_keys: dict = {}
        if self._cache:
            cache_keys = self._cache.get_channel_keys()

        async def _clear_slot(slot: int) -> bool:
            """Clear a device channel slot.

            Tries ``del_channel`` first; falls back to overwriting with an
            empty name when the pymeshcore library does not expose that
            command yet.  Returns ``True`` on success.
            """
            try:
                r = await self._mc.commands.del_channel(slot)
                if r is not None and r.type == EventType.ERROR:
                    debug_print(f'del_channel: _clear_slot ERROR for [{slot}]')
                    return False
                return True
            except AttributeError:
                # pymeshcore does not expose del_channel; clear by writing
                # an empty-name slot which the firmware treats as removed.
                debug_print(
                    f'del_channel: del_channel() not in library, '
                    f'falling back to set_channel("", None) for [{slot}]'
                )
                try:
                    await self._mc.commands.set_channel(slot, '', None)
                    return True
                except Exception as fb_exc:
                    debug_print(f'del_channel: fallback clear failed [{slot}]: {fb_exc}')
                    return False

        try:
            # Step 1: clear the target slot on the device
            ok = await _clear_slot(idx)
            if not ok:
                self._shared.set_status(f"⚠️ Failed to delete channel [{idx}]")
                return

            debug_print(f'del_channel: cleared slot [{idx}]')

            # Step 2: re-index all channels above the deleted slot
            higher = sorted(
                [ch for ch in channels if int(ch.get('idx', 0)) > idx],
                key=lambda c: int(c['idx']),
            )

            for ch in higher:
                old_idx: int = int(ch['idx'])
                new_idx: int = old_idx - 1
                name: str = ch.get('name', '')

                # JSON stores channel-key indices as strings
                raw_hex: str = (
                    cache_keys.get(str(old_idx), '')
                    or cache_keys.get(old_idx, '')  # type: ignore[call-overload]
                )
                secret_bytes: Optional[bytes] = None
                if raw_hex:
                    try:
                        secret_bytes = bytes.fromhex(raw_hex)
                    except ValueError:
                        debug_print(f'del_channel: bad cached secret for [{old_idx}]')

                try:
                    # Move channel to its new (lower) index
                    r2 = await self._mc.commands.set_channel(new_idx, name, secret_bytes)
                    if r2 is not None and r2.type == EventType.ERROR:
                        debug_print(
                            f'del_channel: re-index ERROR [{old_idx}] -> [{new_idx}]'
                        )
                        continue

                    # Persist new key mapping in cache and remove stale old entry
                    if self._cache and raw_hex:
                        self._cache.set_channel_key(new_idx, raw_hex)
                        self._cache.remove_channel_key(old_idx)

                    # Clear the now-vacated original slot
                    await _clear_slot(old_idx)
                    debug_print(
                        f'del_channel: moved [{old_idx}] -> [{new_idx}] ({name})'
                    )

                except Exception as exc:
                    debug_print(f'del_channel: re-index exception [{old_idx}]: {exc}')

            self._shared.set_status(f"🗑️ Channel [{idx}] deleted")

            # Small settle delay: the device needs a moment to commit all
            # slot changes before re-discovery reads them back.  Without
            # this, _discover_channels may see channels at both the old and
            # new indices, producing duplicate entries in the channel list.
            await asyncio.sleep(0.5)

            # Trigger a full channel re-discovery so the GUI is in sync
            if self._load_data_callback:
                await self._load_data_callback()

        except Exception as exc:
            self._shared.set_status(f'⚠️ Delete channel error: {exc}')
            debug_print(f'del_channel exception: {exc}')

    async def _cmd_move_channel(self, cmd: Dict) -> None:
        """Move a channel slot to a different index on the MeshCore device.

        Reads the channel secret from the DeviceCache (or fetches it from
        the device as fallback), writes it to the new index, and clears
        the old slot.  Both cache entries are updated atomically.

        Expected command dict::

            {
                'action':   'move_channel',
                'old_idx':  int,   # current channel slot
                'new_idx':  int,   # target channel slot
                'name':     str,   # channel name (from channel list)
            }
        """
        old_idx: int = int(cmd.get('old_idx', 0))
        new_idx: int = int(cmd.get('new_idx', 0))
        name: str = (cmd.get('name') or '').strip()

        if not name or old_idx == new_idx:
            debug_print(
                f'move_channel: invalid args old={old_idx} new={new_idx} name={name!r}'
            )
            return

        # Resolve secret — prefer cache, fall back to device query
        cache_keys: dict = self._cache.get_channel_keys() if self._cache else {}
        raw_hex: str = (
            cache_keys.get(str(old_idx), '')
            or cache_keys.get(old_idx, '')  # type: ignore[call-overload]
        )
        secret_bytes: Optional[bytes] = None

        if raw_hex:
            try:
                secret_bytes = bytes.fromhex(raw_hex)
            except ValueError:
                debug_print(f'move_channel: bad cached secret for [{old_idx}]')
                raw_hex = ''

        if not secret_bytes:
            # Fetch secret directly from the device
            debug_print(
                f'move_channel: no cached key for [{old_idx}], fetching from device'
            )
            try:
                r = await self._mc.commands.get_channel(old_idx)
                if r is not None and r.type != EventType.ERROR:
                    secret = r.payload.get('channel_secret')
                    if secret and isinstance(secret, bytes) and len(secret) >= 16:
                        secret_bytes = secret[:16]
                        raw_hex = secret_bytes.hex()
                    elif secret and isinstance(secret, str) and len(secret) >= 32:
                        try:
                            secret_bytes = bytes.fromhex(secret)[:16]
                            raw_hex = secret_bytes.hex()
                        except ValueError:
                            pass
            except Exception as exc:
                debug_print(f'move_channel: get_channel({old_idx}) failed: {exc}')

        try:
            # Write channel to new slot
            r2 = await self._mc.commands.set_channel(new_idx, name, secret_bytes)
            if r2 is not None and r2.type == EventType.ERROR:
                self._shared.set_status(
                    f"\u26a0\ufe0f Failed to move channel [{old_idx}] to [{new_idx}]"
                )
                debug_print(f'move_channel: set_channel({new_idx}) ERROR')
                return

            # Clear old slot
            try:
                await self._mc.commands.del_channel(old_idx)
            except AttributeError:
                await self._mc.commands.set_channel(old_idx, '', None)

            # Update cache: write new index, remove stale old index
            if self._cache:
                if raw_hex:
                    self._cache.set_channel_key(new_idx, raw_hex)
                self._cache.remove_channel_key(old_idx)

            self._shared.set_status(
                f"\u2705 Channel [{old_idx}] \'{name}\' moved to [{new_idx}]"
            )
            debug_print(f'move_channel: [{old_idx}] -> [{new_idx}] ({name})')

            # Let device settle before re-discovery
            await asyncio.sleep(0.5)
            if self._load_data_callback:
                await self._load_data_callback()

        except Exception as exc:
            self._shared.set_status(f'\u26a0\ufe0f Move channel error: {exc}')
            debug_print(f'move_channel exception: {exc}')



    # ------------------------------------------------------------------
    # Callback for refresh (set by SerialWorker after construction)
    # ------------------------------------------------------------------

    _load_data_callback = None

    def set_load_data_callback(self, callback) -> None:
        """Register the worker's ``_load_data`` coroutine for refresh."""
        self._load_data_callback = callback
