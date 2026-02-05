"""
Packet decoder for MeshCore GUI — single-source approach.

Wraps ``meshcoredecoder`` to decode raw LoRa packets from RX_LOG_DATA
events.  A single raw packet contains **everything**: message_hash,
path hashes, hop count, and (with channel keys) the decrypted text
and sender name.

No correlation with CHANNEL_MSG_RECV events is needed.

Channel decryption keys are loaded at startup (fetched from the device
via ``get_channel()`` or derived from the channel name as fallback).
"""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Dict, List, Optional

from meshcoredecoder import MeshCoreDecoder
from meshcoredecoder.crypto.channel_crypto import ChannelCrypto
from meshcoredecoder.crypto.key_manager import MeshCoreKeyStore
from meshcoredecoder.types.crypto import DecryptionOptions
from meshcoredecoder.types.enums import PayloadType

from meshcore_gui.config import debug_print


# Re-export so other modules don't need to import meshcoredecoder
__all__ = ["PacketDecoder", "DecodedPacket", "PayloadType"]


# ---------------------------------------------------------------------------
# Decoded result
# ---------------------------------------------------------------------------

@dataclass
class DecodedPacket:
    """All data extracted from a single raw LoRa packet.

    Attributes:
        message_hash:  Deterministic packet identifier (hex string).
        payload_type:  Enum (GroupText, Advert, Ack, …).
        path_length:   Number of repeater hashes in the path.
        path_hashes:   2-char hex strings, one per repeater.
        sender:        Sender name (GroupText only, after decryption).
        text:          Message body (GroupText only, after decryption).
        channel_idx:   Channel index (GroupText only, via hash→idx map).
        timestamp:     Message timestamp (GroupText only).
        is_decrypted:  True if payload was successfully decrypted.
    """

    message_hash: str
    payload_type: PayloadType
    path_length: int
    path_hashes: List[str] = field(default_factory=list)

    # GroupText-specific (populated after successful decryption)
    sender: str = ""
    text: str = ""
    channel_idx: Optional[int] = None
    timestamp: int = 0
    is_decrypted: bool = False


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

class PacketDecoder:
    """Decode raw LoRa packets with channel-key decryption.

    Usage::

        decoder = PacketDecoder()
        decoder.add_channel_key(0, secret_bytes)        # from device
        decoder.add_channel_key_from_name(1, "#test")   # fallback

        result = decoder.decode(payload_hex)
        if result and result.is_decrypted:
            print(result.sender, result.text, result.path_hashes)
    """

    def __init__(self) -> None:
        self._key_store = MeshCoreKeyStore()
        self._options: Optional[DecryptionOptions] = None
        # channel_hash (2-char lower hex) → channel_idx
        self._hash_to_idx: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def add_channel_key(
        self,
        channel_idx: int,
        secret_bytes: bytes,
        source: str = "device",
    ) -> None:
        """Register a channel decryption key (16 raw bytes from device).

        Args:
            channel_idx:  Channel index (0-based).
            secret_bytes: 16-byte channel secret from ``get_channel()``.
            source:       Label for debug output (e.g. "device", "cache").
        """
        secret_hex = secret_bytes.hex()
        self._key_store.add_channel_secrets([secret_hex])
        self._rebuild_options()

        ch_hash = ChannelCrypto.calculate_channel_hash(secret_hex).lower()
        self._hash_to_idx[ch_hash] = channel_idx
        debug_print(
            f"PacketDecoder: key for ch{channel_idx} "
            f"(hash={ch_hash}, from {source})"
        )

    def add_channel_key_from_name(
        self, channel_idx: int, channel_name: str,
    ) -> None:
        """Derive a channel key from the channel name (fallback).

        MeshCore derives channel secrets as
        ``SHA-256(name.encode('utf-8'))[:16]``.

        Args:
            channel_idx:  Channel index (0-based).
            channel_name: Channel name string (e.g. ``"#test"``).
        """
        secret_bytes = sha256(channel_name.encode("utf-8")).digest()[:16]
        self.add_channel_key(channel_idx, secret_bytes, source=f"name '{channel_name}'")

    @property
    def has_keys(self) -> bool:
        """True if at least one channel key has been registered."""
        return self._options is not None

    # ------------------------------------------------------------------
    # Decode
    # ------------------------------------------------------------------

    def decode(self, payload_hex: str) -> Optional[DecodedPacket]:
        """Decode a raw LoRa packet hex string.

        Args:
            payload_hex: Hex string from the RX_LOG_DATA event's
                         ``payload`` field.

        Returns:
            :class:`DecodedPacket` on success, ``None`` if the data
            is invalid or too short.
        """
        if not payload_hex:
            return None

        try:
            packet = MeshCoreDecoder.decode(payload_hex, self._options)
        except Exception as exc:
            debug_print(f"PacketDecoder: decode error: {exc}")
            return None

        if not packet.is_valid:
            debug_print(f"PacketDecoder: invalid: {packet.errors}")
            return None

        result = DecodedPacket(
            message_hash=packet.message_hash,
            payload_type=packet.payload_type,
            path_length=packet.path_length,
            path_hashes=list(packet.path) if packet.path else [],
        )

        # --- GroupText decryption ---
        if packet.payload_type == PayloadType.GroupText:
            decoded_payload = packet.payload.get("decoded")
            if decoded_payload and decoded_payload.decrypted:
                d = decoded_payload.decrypted
                result.sender = d.get("sender", "") or ""
                result.text = d.get("message", "") or ""
                result.timestamp = d.get("timestamp", 0)
                result.is_decrypted = True

                # Resolve channel_hash → channel_idx
                ch_hash = decoded_payload.channel_hash.lower()
                result.channel_idx = self._hash_to_idx.get(ch_hash)

                debug_print(
                    f"PacketDecoder: GroupText OK — "
                    f"hash={result.message_hash}, "
                    f"sender={result.sender!r}, "
                    f"ch={result.channel_idx}, "
                    f"path={result.path_hashes}, "
                    f"text={result.text[:40]!r}"
                )
            else:
                debug_print(
                    f"PacketDecoder: GroupText NOT decrypted "
                    f"(hash={result.message_hash})"
                )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_options(self) -> None:
        """Recreate DecryptionOptions after a key change."""
        self._options = DecryptionOptions(key_store=self._key_store)
