"""
Channel discovery result model and cache-merge logic.

A channel scan walks the device slot by slot.  Each slot can end in one
of three states, and the difference between them is what protects the
persisted channel names:

- **Answered with a name** — the device confirmed an active channel.
- **Answered without a name** — the device confirmed the slot is empty.
  This is authoritative: a channel deleted on the device must disappear
  from the cache as well.
- **Not answered** — the request timed out, returned ``ERROR``, or the
  slot was never reached because the scan aborted early.  Nothing is
  known about this slot, so any cached name for it must be kept.

Treating the last two cases alike is what allowed an unresponsive (or
wrong) device to overwrite the cached channel names with a bare
``{0: "Public"}``.  Because ``CHANNEL_CACHE_ENABLED`` is off by default,
those names are the only channel source at startup, so the loss was
permanent.

No GUI, BLE or filesystem dependencies — pure data transformation, safe
to import from any layer.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class ChannelDiscoveryResult:
    """Outcome of a single channel-discovery scan.

    Attributes:
        channels: Active channels found on the device, as
            ``{"idx": int, "name": str}`` dicts in ascending slot order.
        answered: Slot indices for which the device returned a usable
            response, whether or not that slot held a channel.  Only
            these indices carry authority over the cache.
        complete: True when the scan ran to a natural end.  False when it
            aborted early after consecutive unanswered slots, which means
            higher indices were never probed.
    """

    channels: List[Dict] = field(default_factory=list)
    answered: Set[int] = field(default_factory=set)
    complete: bool = True

    @property
    def is_empty(self) -> bool:
        """True when the device confirmed nothing at all.

        Distinguishes a genuinely channel-less device from a device that
        never answered: the former has entries in ``answered``, the
        latter does not.
        """
        return not self.answered

    def name_map(self) -> Dict[int, str]:
        """Return the discovered channels as an ``{idx: name}`` mapping."""
        return {int(ch["idx"]): ch["name"] for ch in self.channels}


def merge_with_cached_names(
    result: ChannelDiscoveryResult,
    cached_names: Dict[int, str],
) -> Dict[int, str]:
    """Merge a discovery result with the previously cached channel names.

    The device wins for every slot it answered for; the cache is retained
    for every slot it did not.  A slot the device reported as empty is
    dropped from the result, so channels deleted on the device do not
    reappear on the next startup.

    Args:
        result:       Outcome of the scan.
        cached_names: Previously persisted ``{idx: name}`` mapping.

    Returns:
        A new ``{idx: name}`` mapping safe to persist.  Never smaller
        than the set of slots the device actually answered for.
    """
    merged: Dict[int, str] = {
        idx: name
        for idx, name in cached_names.items()
        if idx not in result.answered
    }
    merged.update(result.name_map())
    return merged


def name_map_to_channels(names: Dict[int, str]) -> List[Dict]:
    """Convert an ``{idx: name}`` mapping to the channel-dict list format.

    Args:
        names: Mapping of slot index to channel name.

    Returns:
        List of ``{"idx": int, "name": str}`` dicts in ascending index
        order — the shape expected by ``SharedData.set_channels()``.
    """
    return [{"idx": idx, "name": names[idx]} for idx in sorted(names)]


def stale_key_indices(
    result: ChannelDiscoveryResult,
    cached_key_indices: Set[int],
) -> Set[int]:
    """Return cached key indices the device confirmed as vacant.

    A key is only stale when the device answered for its slot and
    reported no channel there.  Indices the device stayed silent about
    are left alone, so a failed scan cannot strip decryption keys for
    channels that are still configured.

    Args:
        result:             Outcome of the scan.
        cached_key_indices: Slot indices currently holding a cached key.

    Returns:
        Indices whose cached key and decoder entry should be removed.
    """
    active = set(result.name_map())
    return {
        idx
        for idx in cached_key_indices
        if idx in result.answered and idx not in active
    }
