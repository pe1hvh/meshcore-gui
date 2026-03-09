"""
Contact cleaner service for MeshCore GUI.

Provides business logic for bulk-deleting unpinned contacts from the
MeshCore device.  All decision logic (which contacts to purge, counting
pinned vs unpinned) lives here — the GUI only calls this service and
displays results.

Thread safety
~~~~~~~~~~~~~
Methods read from SharedData (thread-safe) and PinStore (thread-safe).
No mutable state is stored in this service.
"""

from dataclasses import dataclass
from typing import Dict, List, Set

from meshcore_gui.services.pin_store import PinStore


@dataclass
class PurgeStats:
    """Statistics for a planned contact purge operation.

    Attributes:
        unpinned_keys: Public keys of contacts that will be removed.
        pinned_count:  Number of pinned contacts that will be kept.
        total_count:   Total number of contacts on the device.
    """

    unpinned_keys: List[str]
    pinned_count: int
    total_count: int

    @property
    def unpinned_count(self) -> int:
        """Number of contacts that will be removed."""
        return len(self.unpinned_keys)


class ContactCleanerService:
    """Business logic for bulk-deleting unpinned contacts.

    Args:
        pin_store: PinStore instance for checking pin status.
    """

    def __init__(self, pin_store: PinStore) -> None:
        self._pin_store = pin_store

    def get_purge_stats(self, contacts: Dict) -> PurgeStats:
        """Calculate which contacts would be purged.

        Iterates all contacts and separates them into pinned (kept)
        and unpinned (to be removed).

        Args:
            contacts: Contacts dict from SharedData snapshot
                      (``{pubkey: contact_dict}``).

        Returns:
            PurgeStats with the list of unpinned keys and counts.
        """
        pinned_keys: Set[str] = self._pin_store.get_pinned()
        unpinned_keys: List[str] = []

        for pubkey in contacts:
            if pubkey not in pinned_keys:
                unpinned_keys.append(pubkey)

        return PurgeStats(
            unpinned_keys=unpinned_keys,
            pinned_count=len(contacts) - len(unpinned_keys),
            total_count=len(contacts),
        )
