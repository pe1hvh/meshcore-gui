"""
Packet decoder for MeshCore GUI — single-source approach.

Wraps ``meshcoredecoder`` to decode raw LoRa packets from RX_LOG_DATA
events.  A single raw packet contains **everything**: message_hash,
path hashes, hop count, and (with channel keys) the decrypted text
and sender name.

No correlation with CHANNEL_MSG_RECV events is needed.

Channel attribution
~~~~~~~~~~~~~~~~~~~
The channel a message belongs to is determined by **which registered key
successfully decrypts the payload** — not by any channel index or the
``channel_hash`` embedded in the packet header.  The firmware-embedded
``channel_hash`` is ignored for attribution because ``ChannelCrypto``
and the firmware may compute it differently, making hash-based lookup
unreliable.

Decryption is therefore attempted per-key (one ``MeshCoreDecoder.decode``
call per registered channel).  For a typical deployment with fewer than
ten channels this cost is negligible, and the correct channel is always
identified deterministically.

Channel decryption keys are loaded at startup (fetched from the device
via ``get_channel()`` or derived from the channel name as fallback).
"""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Dict, List, Optional

from meshcoredecoder import MeshCoreDecoder
from meshcoredecoder.crypto.key_manager import MeshCoreKeyStore
from meshcoredecoder.types.crypto import DecryptionOptions
from meshcoredecoder.types.enums import PayloadType
from meshcoredecoder.utils.enum_names import get_payload_type_name

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
        channel_idx:   Channel index (GroupText only, resolved by key match).
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
    """Decode raw LoRa packets with per-key channel attribution.

    Channel attribution is done by key matching: the registered secret that
    successfully decrypts a GroupText packet identifies its channel.  This
    avoids relying on the ``channel_hash`` mechanism, which requires the
    MeshCore firmware and ``meshcoredecoder`` to compute identical hashes —
    a dependency that cannot always be guaranteed.

    Usage::

        decoder = PacketDecoder()
        decoder.add_channel_key(0, secret_bytes)        # from device
        decoder.add_channel_key_from_name(1, "#test")   # fallback

        result = decoder.decode(payload_hex)
        if result and result.is_decrypted:
            print(result.sender, result.text, result.channel_idx)
    """

    def __init__(self) -> None:
        # secret_hex → channel_idx  (primary channel attribution map)
        self._secret_to_idx: Dict[str, int] = {}

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
        self._secret_to_idx[secret_hex] = channel_idx
        debug_print(
            f"PacketDecoder: key registered for ch{channel_idx} "
            f"(source={source}, secret={secret_hex[:8]}…)"
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

    def remove_channel_key(self, channel_idx: int) -> None:
        """Remove every registered key whose mapping points at *channel_idx*.

        Used by the BLE worker after channel discovery to drop stale entries
        for slots that are no longer active on the device (e.g. after a
        delete or move).  Removing all mappings for the index — instead of a
        specific secret — keeps the decoder consistent even when the same
        slot was previously registered with multiple secrets across the
        session (cache load + device confirmation may both succeed and leave
        two entries for the same idx if the secret bytes differ).

        Args:
            channel_idx: Channel index to evict from the decoder.
        """
        stale = [s for s, idx in self._secret_to_idx.items() if idx == channel_idx]
        for secret_hex in stale:
            del self._secret_to_idx[secret_hex]
        if stale:
            debug_print(
                f"PacketDecoder: removed {len(stale)} key(s) for ch{channel_idx}"
            )

    @property
    def has_keys(self) -> bool:
        """True if at least one channel key has been registered."""
        return bool(self._secret_to_idx)

    # ------------------------------------------------------------------
    # Decode
    # ------------------------------------------------------------------

    def decode(self, payload_hex: str) -> Optional[DecodedPacket]:
        """Decode a raw LoRa packet hex string.

        Two-phase approach:

        1. Decode packet **structure** without any key: extracts
           ``message_hash``, ``payload_type``, ``path_length`` and
           ``path_hashes``.  These fields are in the unencrypted header.

        2. For GroupText packets, attempt decryption with each registered
           key individually.  The key that produces a valid decryption
           **is** the channel identifier — ``channel_idx`` is set directly
           from the matching key's registration.

        Args:
            payload_hex: Hex string from the RX_LOG_DATA event's
                         ``payload`` field.

        Returns:
            :class:`DecodedPacket` on success, ``None`` if the data
            is invalid or too short.
        """
        if not payload_hex:
            return None

        # ── Phase 1: structural decode (no key required) ──────────────
        try:
            packet = MeshCoreDecoder.decode(payload_hex, None)
        except Exception as exc:
            debug_print(f"PacketDecoder: structural decode error: {exc}")
            return None

        if not packet.is_valid:
            debug_print(f"PacketDecoder: invalid packet: {packet.errors}")
            return None

        result = DecodedPacket(
            message_hash=packet.message_hash,
            payload_type=packet.payload_type,
            path_length=packet.path_length,
            path_hashes=list(packet.path) if packet.path else [],
        )

        # ── Phase 2: per-key decryption (GroupText only) ──────────────
        if packet.payload_type == PayloadType.GroupText and self._secret_to_idx:
            for secret_hex, idx in self._secret_to_idx.items():
                try:
                    ks = MeshCoreKeyStore()
                    ks.add_channel_secrets([secret_hex])
                    opts = DecryptionOptions(key_store=ks)
                    dec_pkt = MeshCoreDecoder.decode(payload_hex, opts)
                    if not dec_pkt.is_valid:
                        continue
                    dec_payload = dec_pkt.payload.get("decoded")
                    if dec_payload and dec_payload.decrypted:
                        d = dec_payload.decrypted
                        result.sender = d.get("sender", "") or ""
                        result.text = d.get("message", "") or ""
                        result.timestamp = d.get("timestamp", 0)
                        result.channel_idx = idx
                        result.is_decrypted = True
                        debug_print(
                            f"PacketDecoder: GroupText OK — "
                            f"hash={result.message_hash}, "
                            f"sender={result.sender!r}, "
                            f"ch={result.channel_idx} (key-matched), "
                            f"path={result.path_hashes}, "
                            f"text={result.text[:40]!r}"
                        )
                        break
                except Exception as exc:
                    debug_print(
                        f"PacketDecoder: key for ch{idx} error: {exc}"
                    )
                    continue

            if not result.is_decrypted:
                debug_print(
                    f"PacketDecoder: GroupText NOT decrypted "
                    f"(hash={result.message_hash}, "
                    f"{len(self._secret_to_idx)} keys tried)"
                )

        return result

    def get_payload_type_text(self, payload_type: PayloadType) -> str:
        """Get human-friendly name for a PayloadType enum value."""
        return get_payload_type_name(payload_type)
