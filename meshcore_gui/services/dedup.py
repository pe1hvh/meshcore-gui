"""
Message deduplication for MeshCore GUI.

Extracted from SerialWorker to satisfy the Single Responsibility Principle.
Provides bounded-size deduplication via message hash and content keys.

Two strategies are used because the two event sources carry different
identifiers:

1. **Hash-based** — ``RX_LOG_DATA`` events produce a deterministic
   ``message_hash``.  When ``CHANNEL_MSG_RECV`` arrives for the same
   packet, it is suppressed.

2. **Content-based** — ``CHANNEL_MSG_RECV`` events do *not* include
   ``message_hash``, so a composite key of ``channel:sender:text`` is
   used as a fallback.

3. **DM attempt-based** — a sender that gets no ``ACK`` sends the same DM
   again with a higher attempt number.  Every attempt is a different
   packet, so the firmware delivers each one as its own
   ``CONTACT_MSG_RECV``.  All attempts share ``pubkey_prefix``,
   ``sender_timestamp`` and text, which together form the key.  Used by
   the BBS route so a resent command (e.g. ``!p``) is handled once.

All stores are bounded to prevent unbounded memory growth.
"""

from collections import OrderedDict


class MessageDeduplicator:
    """Bounded-size message deduplication store.

    Uses an :class:`OrderedDict` as an LRU-style bounded set.
    Oldest entries are evicted when the store exceeds ``max_size``.

    Args:
        max_size: Maximum number of keys to retain.  200 is generous
                  for the typical message rate of a mesh network.
    """

    def __init__(self, max_size: int = 200) -> None:
        self._max = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()

    def is_seen(self, key: str) -> bool:
        """Check if a key has already been recorded."""
        return key in self._seen

    def mark(self, key: str) -> None:
        """Record a key.  Evicts the oldest entry if at capacity."""
        if key in self._seen:
            # Move to end (most recent)
            self._seen.move_to_end(key)
            return
        self._seen[key] = None
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)

    def clear(self) -> None:
        """Remove all recorded keys."""
        self._seen.clear()

    def __len__(self) -> int:
        return len(self._seen)


class DualDeduplicator:
    """Combined hash-based and content-based deduplication.

    Wraps three :class:`MessageDeduplicator` instances — one for
    message hashes, one for content keys and one for DM attempt keys —
    behind a single interface.  The class keeps its name for backward
    compatibility.

    Args:
        max_size: Maximum entries per store.
    """

    def __init__(self, max_size: int = 200) -> None:
        self._by_hash = MessageDeduplicator(max_size)
        self._by_content = MessageDeduplicator(max_size)
        self._by_dm = MessageDeduplicator(max_size)
        """Keys ``dm:<pubkey>:<sender_timestamp>:<text>`` of handled DMs."""

    # -- Hash-based --

    def mark_hash(self, message_hash: str) -> None:
        """Record a message hash as processed."""
        if message_hash:
            self._by_hash.mark(message_hash)

    def is_hash_seen(self, message_hash: str) -> bool:
        """Check if a message hash has already been processed."""
        return bool(message_hash) and self._by_hash.is_seen(message_hash)

    # -- Content-based --

    def mark_content(self, sender: str, channel, text: str) -> None:
        """Record a content key as processed."""
        key = self._content_key(sender, channel, text)
        self._by_content.mark(key)

    def is_content_seen(self, sender: str, channel, text: str) -> bool:
        """Check if a content key has already been processed."""
        key = self._content_key(sender, channel, text)
        return self._by_content.is_seen(key)

    # -- DM attempt-based --

    def mark_dm(self, pubkey: str, sender_timestamp: int, text: str) -> None:
        """Record a DM as handled.

        Args:
            pubkey: ``pubkey_prefix`` of the sender (12 hex chars).
            sender_timestamp: Sender's clock at sending, Unix seconds; the
                same for every attempt of one DM.
            text: DM text.
        """
        self._by_dm.mark(self._dm_key(pubkey, sender_timestamp, text))

    def is_dm_seen(self, pubkey: str, sender_timestamp: int, text: str) -> bool:
        """Check if an attempt of this DM was already handled.

        Args:
            pubkey: ``pubkey_prefix`` of the sender (12 hex chars).
            sender_timestamp: Sender's clock at sending, Unix seconds.
            text: DM text.

        Returns:
            ``True`` when :meth:`mark_dm` recorded the same sender,
            timestamp and text and the key has not been evicted yet
            (at most ``max_size`` keys are kept).
        """
        return self._by_dm.is_seen(self._dm_key(pubkey, sender_timestamp, text))

    # -- Bulk --

    def clear(self) -> None:
        """Clear all stores."""
        self._by_hash.clear()
        self._by_content.clear()
        self._by_dm.clear()

    @staticmethod
    def _content_key(sender: str, channel, text: str) -> str:
        return f"{channel}:{sender}:{text}"

    @staticmethod
    def _dm_key(pubkey: str, sender_timestamp: int, text: str) -> str:
        """Build the key of one DM.

        The ``dm:`` prefix keeps these keys apart from content keys.

        Args:
            pubkey: ``pubkey_prefix`` of the sender.
            sender_timestamp: Sender's clock at sending, Unix seconds.
            text: DM text.

        Returns:
            ``dm:<pubkey>:<sender_timestamp>:<text>``.
        """
        return f"dm:{pubkey}:{sender_timestamp}:{text}"
