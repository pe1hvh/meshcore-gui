"""
Persistent pin store for MeshCore GUI.

Stores a set of pinned contact public keys per device.
Pin status is purely app-side and is not stored on the device.

Storage location
~~~~~~~~~~~~~~~~
``~/.meshcore-gui/pins/<ADDRESS>.json``

Thread safety
~~~~~~~~~~~~~
All methods use an internal lock for thread-safe operation.
"""

import json
import threading
from pathlib import Path
from typing import Set

from meshcore_gui.config import debug_print

PINS_DIR = Path.home() / ".meshcore-gui" / "pins"


class PinStore:
    """Persistent storage for pinned contact public keys.

    Args:
        device_id: Device identifier string (used to derive filename).
    """

    def __init__(self, device_id: str) -> None:
        self._lock = threading.Lock()

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        )
        self._path = PINS_DIR / f"{safe_name}_pins.json"
        self._pinned: Set[str] = set()

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_pinned(self, pubkey: str) -> bool:
        """Check if a contact is pinned.

        Args:
            pubkey: Full public key (hex string).

        Returns:
            True if the contact is pinned.
        """
        with self._lock:
            return pubkey in self._pinned

    def pin(self, pubkey: str) -> None:
        """Pin a contact.

        Args:
            pubkey: Full public key (hex string).
        """
        with self._lock:
            self._pinned.add(pubkey)
            self._save()
            debug_print(f"PinStore: pinned {pubkey[:16]}")

    def unpin(self, pubkey: str) -> None:
        """Unpin a contact.

        Args:
            pubkey: Full public key (hex string).
        """
        with self._lock:
            self._pinned.discard(pubkey)
            self._save()
            debug_print(f"PinStore: unpinned {pubkey[:16]}")

    def get_pinned(self) -> Set[str]:
        """Return a copy of the set of pinned public keys.

        Returns:
            Set of pinned public key hex strings.
        """
        with self._lock:
            return self._pinned.copy()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load pinned contacts from disk."""
        if not self._path.exists():
            debug_print(f"PinStore: no file at {self._path}")
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._pinned = set(data.get("pinned", []))
            debug_print(
                f"PinStore: loaded {len(self._pinned)} pinned contacts"
            )
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"PinStore: load error: {exc}")
            self._pinned = set()

    def _save(self) -> None:
        """Write pinned contacts to disk."""
        try:
            PINS_DIR.mkdir(parents=True, exist_ok=True)
            data = {"pinned": sorted(self._pinned)}
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_print(f"PinStore: saved {len(self._pinned)} pins")
        except OSError as exc:
            debug_print(f"PinStore: save error: {exc}")
