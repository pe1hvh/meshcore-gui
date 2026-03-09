"""
Persistent Room Server password store for MeshCore GUI.

Stores passwords and configuration for Room Server contacts per device.
Passwords are stored outside the repository under
``~/.meshcore-gui/room_passwords/<ADDRESS>.json``.

Thread safety
~~~~~~~~~~~~~
All methods use an internal lock for thread-safe operation.
"""

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

ROOM_PASSWORDS_DIR = Path.home() / ".meshcore-gui" / "room_passwords"


@dataclass
class RoomServerEntry:
    """Stored configuration for a single Room Server.

    Attributes:
        pubkey:   Full public key (hex string).
        name:     Display name of the Room Server.
        password: Stored password (plaintext — local file only).
    """

    pubkey: str
    name: str = ""
    password: str = ""


class RoomPasswordStore:
    """Persistent storage for Room Server passwords.

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
        self._path = ROOM_PASSWORDS_DIR / f"{safe_name}_rooms.json"
        self._rooms: Dict[str, RoomServerEntry] = {}

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_rooms(self) -> List[RoomServerEntry]:
        """Return a list of all configured Room Server entries.

        Returns:
            List of RoomServerEntry instances (copies).
        """
        with self._lock:
            return list(self._rooms.values())

    def get_room(self, pubkey: str) -> Optional[RoomServerEntry]:
        """Get a specific Room Server entry by public key.

        Args:
            pubkey: Full public key (hex string).

        Returns:
            RoomServerEntry if found, None otherwise.
        """
        with self._lock:
            entry = self._rooms.get(pubkey)
            if entry:
                return RoomServerEntry(
                    pubkey=entry.pubkey,
                    name=entry.name,
                    password=entry.password,
                )
            return None

    def has_room(self, pubkey: str) -> bool:
        """Check if a Room Server is configured.

        Args:
            pubkey: Full public key (hex string).

        Returns:
            True if the Room Server is in the store.
        """
        with self._lock:
            return pubkey in self._rooms

    def add_room(self, pubkey: str, name: str, password: str = "") -> None:
        """Add or update a Room Server entry.

        Args:
            pubkey:   Full public key (hex string).
            name:     Display name.
            password: Password (empty string if not yet set).
        """
        with self._lock:
            self._rooms[pubkey] = RoomServerEntry(
                pubkey=pubkey,
                name=name,
                password=password,
            )
            self._save()
            debug_print(
                f"RoomPasswordStore: added/updated {name} "
                f"({pubkey[:16]})"
            )

    def update_password(self, pubkey: str, password: str) -> None:
        """Update the password for an existing Room Server.

        Args:
            pubkey:   Full public key (hex string).
            password: New password.
        """
        with self._lock:
            if pubkey in self._rooms:
                self._rooms[pubkey].password = password
                self._save()
                debug_print(
                    f"RoomPasswordStore: password updated for "
                    f"{pubkey[:16]}"
                )

    def remove_room(self, pubkey: str) -> None:
        """Remove a Room Server entry.

        Args:
            pubkey: Full public key (hex string).
        """
        with self._lock:
            if pubkey in self._rooms:
                name = self._rooms[pubkey].name
                del self._rooms[pubkey]
                self._save()
                debug_print(
                    f"RoomPasswordStore: removed {name} "
                    f"({pubkey[:16]})"
                )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load Room Server entries from disk."""
        if not self._path.exists():
            debug_print(f"RoomPasswordStore: no file at {self._path}")
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            rooms = data.get("rooms", {})
            for pubkey, entry_dict in rooms.items():
                self._rooms[pubkey] = RoomServerEntry(
                    pubkey=pubkey,
                    name=entry_dict.get("name", ""),
                    password=entry_dict.get("password", ""),
                )
            debug_print(
                f"RoomPasswordStore: loaded {len(self._rooms)} rooms"
            )
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"RoomPasswordStore: load error: {exc}")
            self._rooms = {}

    def _save(self) -> None:
        """Write Room Server entries to disk."""
        try:
            ROOM_PASSWORDS_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "rooms": {
                    pubkey: asdict(entry)
                    for pubkey, entry in self._rooms.items()
                }
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_print(
                f"RoomPasswordStore: saved {len(self._rooms)} rooms"
            )
        except OSError as exc:
            debug_print(f"RoomPasswordStore: save error: {exc}")
