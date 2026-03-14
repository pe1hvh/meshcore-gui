"""
Device event callbacks for MeshCore GUI.

Handles ``CHANNEL_MSG_RECV``, ``CONTACT_MSG_RECV`` and ``RX_LOG_DATA``
events from the MeshCore library.  Extracted from ``SerialWorker`` so the
worker only deals with connection lifecycle.

BBS routing
~~~~~~~~~~~
Direct Messages (``CONTACT_MSG_RECV``) whose text starts with ``!`` are
forwarded to :class:`~meshcore_gui.services.bbs_service.BbsCommandHandler`
**before** any other DM processing.  This path is completely independent of
:class:`~meshcore_gui.services.bot.MeshBot`.
"""

from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from meshcore_gui.config import debug_print
from meshcore_gui.core.models import Message, RxLogEntry
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.ble.packet_decoder import PacketDecoder, PayloadType
from meshcore_gui.services.bot import MeshBot
from meshcore_gui.services.dedup import DualDeduplicator

if TYPE_CHECKING:
    from meshcore_gui.services.bbs_service import BbsCommandHandler


class EventHandler:
    """Processes device events and writes results to shared data.

    Args:
        shared:  SharedDataWriter for storing messages and RX log.
        decoder: PacketDecoder for raw LoRa packet decryption.
        dedup:   DualDeduplicator for message deduplication.
        bot:     MeshBot for auto-reply logic.
    """

    # Maximum entries in the path cache before oldest are evicted.
    _PATH_CACHE_MAX = 200

    def __init__(
        self,
        shared: SharedDataWriter,
        decoder: PacketDecoder,
        dedup: DualDeduplicator,
        bot: MeshBot,
        bbs_handler: Optional["BbsCommandHandler"] = None,
        command_sink: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self._shared = shared
        self._decoder = decoder
        self._dedup = dedup
        self._bot = bot
        self._bbs_handler = bbs_handler
        self._command_sink = command_sink

        # Cache: message_hash → path_hashes (from RX_LOG decode).
        # Used by on_channel_msg fallback to recover hashes that the
        # CHANNEL_MSG_RECV event does not provide.
        self._path_cache: Dict[str, list] = {}

    # ------------------------------------------------------------------
    # Helpers — resolve names at receive time
    # ------------------------------------------------------------------

    def _resolve_path_names(self, path_hashes: list) -> list:
        """Resolve 2-char path hashes to display names.

        Performs a contact lookup for each hash *now* so the names are
        captured at receive time and stored in the archive.

        Args:
            path_hashes: List of 2-char hex strings.

        Returns:
            List of display names (same length as *path_hashes*).
            Unknown hashes become their uppercase hex value.
        """
        names = []
        for h in path_hashes:
            if not h or len(h) < 2:
                names.append('-')
                continue
            name = self._shared.get_contact_name_by_prefix(h)
            # get_contact_name_by_prefix returns h[:8] as fallback,
            # normalise to uppercase hex for 2-char hashes.
            if name and name != h[:8]:
                names.append(name)
            else:
                names.append(h.upper())
        return names

    @staticmethod
    def _looks_like_hex_identifier(value: str) -> bool:
        """Return True when *value* looks like a pubkey/hash prefix."""
        if not value:
            return False
        probe = str(value).strip()
        if len(probe) < 6:
            return False
        return all(ch in '0123456789abcdefABCDEF' for ch in probe)

    # ------------------------------------------------------------------
    # RX_LOG_DATA — the single source of truth for path info
    # ------------------------------------------------------------------

    def on_rx_log(self, event) -> None:
        """Handle RX log data events."""
        payload = event.payload

        # Extract basic RX log info
        time_str = Message.now_timestamp()
        snr = payload.get('snr', 0)
        rssi = payload.get('rssi', 0)
        payload_type = '?'
        hops = payload.get('path_len', 0)
        
        # Try to decode payload to get message_hash
        message_hash = ""
        rx_path_hashes: list = []
        rx_path_names: list = []
        rx_sender: str = ""
        rx_receiver: str = self._shared.get_device_name() or ""
        payload_hex = payload.get('payload', '')
        decoded = None
        if payload_hex:
            decoded = self._decoder.decode(payload_hex)
            if decoded is not None:
                message_hash = decoded.message_hash
                payload_type = self._decoder.get_payload_type_text(decoded.payload_type)

                # Capture path info for all packet types
                if decoded.path_hashes:
                    rx_path_hashes = decoded.path_hashes
                    rx_path_names = self._resolve_path_names(decoded.path_hashes)

                # Use decoded path_length (from packet body) — more
                # reliable than the frame-header path_len which can be 0.
                if decoded.path_length:
                    hops = decoded.path_length

                # Capture sender name when available (GroupText only)
                if decoded.sender:
                    rx_sender = decoded.sender

                # Cache path_hashes for correlation with on_channel_msg
                if decoded.path_hashes and message_hash:
                    self._path_cache[message_hash] = decoded.path_hashes
                    # Evict oldest entries if cache is too large
                    if len(self._path_cache) > self._PATH_CACHE_MAX:
                        oldest = next(iter(self._path_cache))
                        del self._path_cache[oldest]
                
                # Process decoded message if it's a group text
                if decoded.payload_type == PayloadType.GroupText and decoded.is_decrypted:
                    if decoded.channel_idx is None:
                        # The channel hash could not be resolved to a channel index
                        # (PacketDecoder._hash_to_idx lookup returned None).
                        # Marking dedup here would suppress on_channel_msg, which
                        # carries a valid channel_idx from the device event — the only
                        # path through which the bot can pass Guard 2 and respond.
                        # Skip the entire block; on_channel_msg handles message + bot.
                        # Path info is already in _path_cache for on_channel_msg to use.
                        debug_print(
                            f"RX_LOG → GroupText decrypted but channel_idx unresolved "
                            f"(hash={decoded.message_hash}); deferring to on_channel_msg"
                        )
                    else:
                        self._dedup.mark_hash(decoded.message_hash)
                        self._dedup.mark_content(
                            decoded.sender, decoded.channel_idx, decoded.text,
                        )

                        sender_pubkey = ''
                        if decoded.sender:
                            match = self._shared.get_contact_by_name(decoded.sender)
                            if match:
                                sender_pubkey, _contact = match

                        snr_msg = self._extract_snr(payload)

                        self._shared.add_message(Message.incoming(
                            decoded.sender,
                            decoded.text,
                            decoded.channel_idx,
                            time=time_str,
                            snr=snr_msg,
                            path_len=decoded.path_length,
                            sender_pubkey=sender_pubkey,
                            path_hashes=decoded.path_hashes,
                            path_names=rx_path_names,
                            message_hash=decoded.message_hash,
                        ))

                        debug_print(
                            f"RX_LOG → message: hash={decoded.message_hash}, "
                            f"sender={decoded.sender!r}, ch={decoded.channel_idx}, "
                            f"path={decoded.path_hashes}, "
                            f"path_names={rx_path_names}"
                        )

                        self._bot.check_and_reply(
                            sender=decoded.sender,
                            text=decoded.text,
                            channel_idx=decoded.channel_idx,
                            snr=snr_msg,
                            path_len=decoded.path_length,
                            path_hashes=decoded.path_hashes,
                        )
        
        # Add RX log entry with message_hash and path info (if available)
        # ── Fase 1 Observer: raw packet metadata ──
        raw_packet_len = len(payload_hex) // 2 if payload_hex else 0
        raw_payload_len = max(0, raw_packet_len - 1 - hops) if payload_hex else 0
        raw_route_type = "D" if hops > 0 else ("F" if payload_hex else "")
        raw_packet_type_num = -1
        if payload_hex and decoded is not None:
            try:
                raw_packet_type_num = decoded.payload_type.value
            except (AttributeError, ValueError):
                pass

        self._shared.add_rx_log(RxLogEntry(
            time=time_str,
            snr=snr,
            rssi=rssi,
            payload_type=payload_type,
            hops=hops,
            message_hash=message_hash,
            path_hashes=rx_path_hashes,
            path_names=rx_path_names,
            sender=rx_sender,
            receiver=rx_receiver,
            raw_payload=payload_hex,
            packet_len=raw_packet_len,
            payload_len=raw_payload_len,
            route_type=raw_route_type,
            packet_type_num=raw_packet_type_num,
        ))

    # ------------------------------------------------------------------
    # CHANNEL_MSG_RECV — fallback when RX_LOG decode missed it
    # ------------------------------------------------------------------

    def on_channel_msg(self, event) -> None:
        """Handle channel message events."""
        payload = event.payload

        debug_print(f"Channel msg payload keys: {list(payload.keys())}")

        # Dedup via hash
        msg_hash = payload.get('message_hash', '')
        if msg_hash and self._dedup.is_hash_seen(msg_hash):
            debug_print(f"Channel msg suppressed (hash): {msg_hash}")
            return

        # Parse sender from "SenderName: message body" format
        raw_text = payload.get('text', '')
        sender, msg_text = '', raw_text
        if ': ' in raw_text:
            name_part, body_part = raw_text.split(': ', 1)
            sender = name_part.strip()
            msg_text = body_part
        elif raw_text:
            msg_text = raw_text

        # Dedup via content
        ch_idx = payload.get('channel_idx')
        if self._dedup.is_content_seen(sender, ch_idx, msg_text):
            debug_print(f"Channel msg suppressed (content): {sender!r}")
            return

        debug_print(
            f"Channel msg (fallback): sender={sender!r}, "
            f"text={msg_text[:40]!r}"
        )

        sender_pubkey = ''
        if sender:
            match = self._shared.get_contact_by_name(sender)
            if match:
                sender_pubkey, _contact = match

        snr = self._extract_snr(payload)

        # Recover path_hashes from RX_LOG cache (CHANNEL_MSG_RECV
        # does not carry them, but the preceding RX_LOG decode does).
        path_hashes = self._path_cache.pop(msg_hash, []) if msg_hash else []
        path_names = self._resolve_path_names(path_hashes)

        self._shared.add_message(Message.incoming(
            sender,
            msg_text,
            ch_idx,
            snr=snr,
            path_len=payload.get('path_len', 0),
            sender_pubkey=sender_pubkey,
            path_hashes=path_hashes,
            path_names=path_names,
            message_hash=msg_hash,
        ))

        self._bot.check_and_reply(
            sender=sender,
            text=msg_text,
            channel_idx=ch_idx,
            snr=snr,
            path_len=payload.get('path_len', 0),
        )

    # ------------------------------------------------------------------
    # CONTACT_MSG_RECV — DMs
    # ------------------------------------------------------------------

    def on_contact_msg(self, event) -> None:
        """Handle direct message and room message events.

        Room Server traffic also arrives as ``CONTACT_MSG_RECV``.
        In practice the payload is not stable enough to rely only on
        ``signature`` + ``pubkey_prefix``.  Incoming room messages from
        *other* participants may omit ``signature`` and may carry the
        room key in receiver-style fields instead of ``pubkey_prefix``.

        To keep the rest of the GUI unchanged, room messages are stored
        with ``sender`` = actual author name and ``sender_pubkey`` = room
        public key.  The Room Server panel already filters on
        ``sender_pubkey`` to decide to which room a message belongs.
        """
        payload = event.payload or {}
        pubkey = payload.get('pubkey_prefix', '')
        txt_type = payload.get('txt_type', 0)
        signature = payload.get('signature', '')

        debug_print(
            "DM payload keys: "
            f"{list(payload.keys())}; txt_type={txt_type}; "
            f"pubkey_prefix={pubkey[:12]}; "
            f"receiver={(payload.get('receiver') or '')[:12]}; "
            f"room_pubkey={(payload.get('room_pubkey') or '')[:12]}; "
            f"signature={(signature or '')[:12]}"
        )

        # Common fields for both Room and DM messages
        msg_hash = payload.get('message_hash', '')
        path_hashes = self._path_cache.pop(msg_hash, []) if msg_hash else []
        path_names = self._resolve_path_names(path_hashes)

        raw_path_len = payload.get('path_len', 0)
        path_len = raw_path_len if raw_path_len < 255 else 0
        if path_hashes:
            path_len = len(path_hashes)

        room_pubkey = (
            payload.get('room_pubkey')
            or payload.get('receiver')
            or payload.get('receiver_pubkey')
            or payload.get('receiver_pubkey_prefix')
            or pubkey
            or ''
        )

        is_room_message = txt_type == 2

        if is_room_message:
            author = ''
            explicit_name = (
                payload.get('author')
                or payload.get('sender_name')
                or payload.get('name')
                or ''
            )
            if explicit_name and not self._looks_like_hex_identifier(explicit_name):
                author = explicit_name

            sender_field = str(payload.get('sender') or '').strip()
            if not author and sender_field and not self._looks_like_hex_identifier(sender_field):
                author = sender_field

            author_key = (
                signature
                or payload.get('sender_pubkey')
                or payload.get('author_pubkey')
                or (sender_field if self._looks_like_hex_identifier(sender_field) else '')
                or ''
            )
            if not author and author_key:
                author = self._shared.get_contact_name_by_prefix(author_key)
            if not author:
                author = (
                    explicit_name
                    or sender_field
                    or (author_key[:8] if author_key else '')
                    or '?'
                )

            self._shared.add_message(Message.incoming(
                author,
                payload.get('text', ''),
                None,
                snr=self._extract_snr(payload),
                path_len=path_len,
                sender_pubkey=room_pubkey,
                path_hashes=path_hashes,
                path_names=path_names,
                message_hash=msg_hash,
            ))
            debug_print(
                f"Room msg from {author} via room {room_pubkey[:12]} "
                f"(sig={signature[:12] if signature else '-'}): "
                f"{payload.get('text', '')[:30]}"
            )
            return

        # --- Regular DM ---
        sender = ''
        if pubkey:
            sender = self._shared.get_contact_name_by_prefix(pubkey)
        if not sender:
            sender = (
                payload.get('name')
                or payload.get('sender')
                or (pubkey[:8] if pubkey else '')
            )

        dm_text = payload.get('text', '')

        # BBS routing: DMs starting with '!' go directly to BbsCommandHandler.
        # This path is independent of the bot (MeshBot is for channel messages only).
        if (
            self._bbs_handler is not None
            and self._command_sink is not None
            and dm_text.strip().startswith("!")
        ):
            bbs_reply = self._bbs_handler.handle_dm(
                sender=sender,
                sender_key=pubkey,
                text=dm_text,
            )
            if bbs_reply is not None:
                debug_print(f"BBS DM reply to {sender} ({pubkey[:8]}): {bbs_reply[:60]}")
                self._command_sink({
                    "action": "send_dm",
                    "pubkey": pubkey,
                    "text": bbs_reply,
                })
            # Always store the incoming DM in the message archive too
            self._shared.add_message(Message.incoming(
                sender,
                dm_text,
                None,
                snr=self._extract_snr(payload),
                path_len=path_len,
                sender_pubkey=pubkey,
                path_hashes=path_hashes,
                path_names=path_names,
                message_hash=msg_hash,
            ))
            debug_print(f"BBS DM stored from {sender}: {dm_text[:30]}")
            return

        self._shared.add_message(Message.incoming(
            sender,
            dm_text,
            None,
            snr=self._extract_snr(payload),
            path_len=path_len,
            sender_pubkey=pubkey,
            path_hashes=path_hashes,
            path_names=path_names,
            message_hash=msg_hash,
        ))
        debug_print(f"DM received from {sender}: {dm_text[:30]}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_snr(payload: Dict) -> Optional[float]:
        """Extract SNR from a payload dict (handles 'SNR' and 'snr' keys)."""
        raw = payload.get('SNR') or payload.get('snr')
        if raw is not None:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
        return None
