"""
Device event callbacks for MeshCore GUI.

Handles ``CHANNEL_MSG_RECV``, ``CONTACT_MSG_RECV`` and ``RX_LOG_DATA``
events from the MeshCore library.  Extracted from ``SerialWorker`` so the
worker only deals with connection lifecycle.
"""

from typing import Dict, Optional

from meshcore_gui.config import debug_print
from meshcore_gui.core.models import Message, RxLogEntry
from meshcore_gui.core.protocols import SharedDataWriter
from meshcore_gui.ble.packet_decoder import PacketDecoder, PayloadType
from meshcore_gui.services.bot import MeshBot
from meshcore_gui.services.dedup import DualDeduplicator


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
    ) -> None:
        self._shared = shared
        self._decoder = decoder
        self._dedup = dedup
        self._bot = bot

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

        Room Server messages arrive as ``CONTACT_MSG_RECV`` with
        ``txt_type == 2``.  The ``pubkey_prefix`` is the Room Server's
        key and the ``signature`` field contains the original author's
        pubkey prefix.  We resolve the author name from ``signature``
        so the UI shows who actually wrote the message.
        """
        payload = event.payload
        pubkey = payload.get('pubkey_prefix', '')
        txt_type = payload.get('txt_type', 0)
        signature = payload.get('signature', '')

        debug_print(f"DM payload keys: {list(payload.keys())}")

        # Common fields for both Room and DM messages
        msg_hash = payload.get('message_hash', '')
        path_hashes = self._path_cache.pop(msg_hash, []) if msg_hash else []
        path_names = self._resolve_path_names(path_hashes)

        # DM payloads may report path_len=255 (0xFF) meaning "unknown";
        # treat as 0 when no actual path data is available.
        raw_path_len = payload.get('path_len', 0)
        path_len = raw_path_len if raw_path_len < 255 else 0
        if path_hashes:
            # Trust actual decoded hashes over the raw header value
            path_len = len(path_hashes)

        # --- Room Server message (txt_type 2) ---
        if txt_type == 2 and signature:
            # Resolve actual author from signature (author pubkey prefix)
            author = self._shared.get_contact_name_by_prefix(signature)
            if not author:
                author = signature[:8] if signature else '?'

            self._shared.add_message(Message.incoming(
                author,
                payload.get('text', ''),
                None,
                snr=self._extract_snr(payload),
                path_len=path_len,
                sender_pubkey=pubkey,
                path_hashes=path_hashes,
                path_names=path_names,
                message_hash=msg_hash,
            ))
            debug_print(
                f"Room msg from {author} (sig={signature}) "
                f"via room {pubkey[:12]}: "
                f"{payload.get('text', '')[:30]}"
            )
            return

        # --- Regular DM ---
        sender = ''
        if pubkey:
            sender = self._shared.get_contact_name_by_prefix(pubkey)
        if not sender:
            sender = pubkey[:8] if pubkey else ''

        self._shared.add_message(Message.incoming(
            sender,
            payload.get('text', ''),
            None,
            snr=self._extract_snr(payload),
            path_len=path_len,
            sender_pubkey=pubkey,
            path_hashes=path_hashes,
            path_names=path_names,
            message_hash=msg_hash,
        ))
        debug_print(f"DM received from {sender}: {payload.get('text', '')[:30]}")

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
