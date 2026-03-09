"""
Core bridge logic: message monitoring, forwarding and loop prevention.

BridgeEngine polls two SharedData stores and forwards messages on the
configured bridge channel from one instance to the other.  Loop
prevention is achieved via a bounded set of forwarded message hashes
and by filtering outbound (direction='out') messages.

Thread safety: all SharedData access goes through the existing lock
mechanism in SharedData.  BridgeEngine itself is called from a single
asyncio task (the polling loop in __main__).
"""

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from meshcore_gui.core.models import Message
from meshcore_gui.core.shared_data import SharedData

from meshcore_bridge.config import BridgeConfig


@dataclass
class ForwardedEntry:
    """Record of a forwarded message for the bridge log."""

    time: str
    direction: str          # "A→B" or "B→A"
    sender: str
    text: str
    channel: Optional[int]


class BridgeEngine:
    """Core bridge logic: poll, filter, forward and deduplicate.

    Monitors two SharedData instances for new incoming messages on the
    configured bridge channel and forwards them to the opposite instance
    via put_command().

    Attributes:
        stats: Runtime statistics dict exposed to the GUI dashboard.
    """

    def __init__(
        self,
        shared_a: SharedData,
        shared_b: SharedData,
        config: BridgeConfig,
    ) -> None:
        self._a = shared_a
        self._b = shared_b
        self._cfg = config

        # Channel indices per device
        self._ch_idx_a = config.channel_idx_a
        self._ch_idx_b = config.channel_idx_b

        # Loop prevention: bounded set of forwarded hashes
        self._forwarded_hashes: OrderedDict = OrderedDict()
        self._max_cache = config.max_forwarded_cache

        # Tracking last seen message count per side
        self._last_count_a: int = 0
        self._last_count_b: int = 0

        # Forwarded message log (for dashboard)
        self._log: List[ForwardedEntry] = []
        self._max_log: int = 200

        # Runtime statistics
        self.stats = {
            "forwarded_a_to_b": 0,
            "forwarded_b_to_a": 0,
            "duplicates_blocked": 0,
            "last_forward_time": "",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_seconds": 0,
        }
        self._start_time = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_and_forward(self) -> int:
        """Check both stores for new bridge-channel messages and forward.

        Returns:
            Number of messages forwarded in this poll cycle.
        """
        self.stats["uptime_seconds"] = int(time.time() - self._start_time)
        count = 0

        # A → B
        count += self._poll_side(
            source=self._a,
            target=self._b,
            source_ch=self._ch_idx_a,
            target_ch=self._ch_idx_b,
            direction_label="A→B",
            last_count_attr="_last_count_a",
            stat_key="forwarded_a_to_b",
        )

        # B → A
        count += self._poll_side(
            source=self._b,
            target=self._a,
            source_ch=self._ch_idx_b,
            target_ch=self._ch_idx_a,
            direction_label="B→A",
            last_count_attr="_last_count_b",
            stat_key="forwarded_b_to_a",
        )

        return count

    def get_log(self) -> List[ForwardedEntry]:
        """Return a copy of the forwarded message log (newest first)."""
        return list(reversed(self._log))

    def get_total_forwarded(self) -> int:
        """Total number of messages forwarded since start."""
        return (
            self.stats["forwarded_a_to_b"]
            + self.stats["forwarded_b_to_a"]
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_side(
        self,
        source: SharedData,
        target: SharedData,
        source_ch: int,
        target_ch: int,
        direction_label: str,
        last_count_attr: str,
        stat_key: str,
    ) -> int:
        """Poll one side for new messages and forward to the other.

        Args:
            source:           SharedData to read from.
            target:           SharedData to write to.
            source_ch:        Channel index on the source device.
            target_ch:        Channel index on the target device.
            direction_label:  "A→B" or "B→A" for logging.
            last_count_attr:  Name of the self._last_count_* attribute.
            stat_key:         Key in self.stats to increment.

        Returns:
            Number of messages forwarded.
        """
        forwarded = 0
        snapshot = source.get_snapshot()
        msgs = snapshot["messages"]
        last_count = getattr(self, last_count_attr)

        # Detect list shrinkage (e.g. after reconnect/reload)
        if len(msgs) < last_count:
            setattr(self, last_count_attr, 0)
            last_count = 0

        new_msgs = msgs[last_count:]
        setattr(self, last_count_attr, len(msgs))

        for msg in new_msgs:
            if self._should_forward(msg, source_ch):
                self._forward(msg, target, target_ch, direction_label)
                self.stats[stat_key] += 1
                forwarded += 1

        return forwarded

    def _should_forward(self, msg: Message, expected_channel: int) -> bool:
        """Determine whether a message should be forwarded.

        Filtering rules:
        1. Channel must match the bridge channel for this side.
        2. Outbound messages (direction='out') are never forwarded
           — they are our own transmissions (including previous forwards).
        3. Messages whose hash is already in the forwarded set are
           duplicates (loop prevention).

        Args:
            msg:              Message to evaluate.
            expected_channel: Bridge channel index on this device.

        Returns:
            True if the message should be forwarded.
        """
        # Rule 1: channel filter
        if msg.channel != expected_channel:
            return False

        # Rule 2: never forward our own transmissions
        if msg.direction == "out":
            return False

        # Rule 3: loop prevention via hash set
        msg_hash = self._compute_hash(msg)
        if msg_hash in self._forwarded_hashes:
            self.stats["duplicates_blocked"] += 1
            return False

        return True

    def _forward(
        self,
        msg: Message,
        target: SharedData,
        target_ch: int,
        direction_label: str,
    ) -> None:
        """Forward a message to the target SharedData via put_command().

        Args:
            msg:             Message to forward.
            target:          Target SharedData instance.
            target_ch:       Channel index on the target device.
            direction_label: "A→B" or "B→A" for logging.
        """
        msg_hash = self._compute_hash(msg)

        # Register hash for loop prevention
        self._forwarded_hashes[msg_hash] = True
        if len(self._forwarded_hashes) > self._max_cache:
            self._forwarded_hashes.popitem(last=False)

        # Also register the hash of the text we're about to send so
        # the *other* direction won't re-forward our forwarded message
        # if it appears on the target device's bridge channel.
        forward_text = self._build_forward_text(msg)
        echo_hash = self._text_hash(forward_text)
        self._forwarded_hashes[echo_hash] = True
        if len(self._forwarded_hashes) > self._max_cache:
            self._forwarded_hashes.popitem(last=False)

        # Inject send command into the target's command queue
        target.put_command({
            "action": "send_message",
            "channel": target_ch,
            "text": forward_text,
            "_bot": True,  # suppress outgoing Message creation in CommandHandler
        })

        # Update stats and log
        now = datetime.now().strftime("%H:%M:%S")
        self.stats["last_forward_time"] = now

        entry = ForwardedEntry(
            time=now,
            direction=direction_label,
            sender=msg.sender,
            text=msg.text,
            channel=msg.channel,
        )
        self._log.append(entry)
        if len(self._log) > self._max_log:
            self._log.pop(0)

    def _build_forward_text(self, msg: Message) -> str:
        """Build the text to transmit on the target device.

        When forward_prefix is enabled, the original sender name is
        prepended so recipients can identify the origin.

        Args:
            msg: Original message.

        Returns:
            Text string to send.
        """
        if self._cfg.forward_prefix:
            return f"[{msg.sender}] {msg.text}"
        return msg.text

    @staticmethod
    def _compute_hash(msg: Message) -> str:
        """Compute a deduplication hash for a message.

        Uses the message_hash field when available (deterministic
        packet ID from MeshCore firmware).  Falls back to a SHA-256
        digest of channel + sender + text.

        Args:
            msg: Message to hash.

        Returns:
            Hash string.
        """
        if msg.message_hash:
            return f"mh:{msg.message_hash}"
        raw = f"{msg.channel}:{msg.sender}:{msg.text}"
        return f"ct:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    @staticmethod
    def _text_hash(text: str) -> str:
        """Hash a plain text string for echo suppression.

        Args:
            text: Text to hash.

        Returns:
            Hash string.
        """
        return f"tx:{hashlib.sha256(text.encode()).hexdigest()[:16]}"
