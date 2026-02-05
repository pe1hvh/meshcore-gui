"""
Local JSON cache for device info, channels and contacts.

Loads instantly on startup so the GUI is immediately populated with
the last known state.  Background BLE refreshes update the cache
incrementally.

Cache location
~~~~~~~~~~~~~~
``~/.meshcore-gui/cache/<ADDRESS>.json``

One file per BLE device address, so multiple devices are supported
without conflict.

Merge strategy (contacts)
~~~~~~~~~~~~~~~~~~~~~~~~~
- New contacts from device → added to cache with ``last_seen`` timestamp
- Existing contacts → updated (fresh data wins)
- Contacts only in cache (node offline) → kept
- Optional pruning of contacts not seen for > N days (not yet implemented)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

CACHE_VERSION = 1
CACHE_DIR = Path.home() / ".meshcore-gui" / "cache"


class DeviceCache:
    """Read/write JSON cache for a single BLE device.

    Args:
        ble_address: BLE address string (used to derive filename).
    """

    def __init__(self, ble_address: str) -> None:
        self._address = ble_address
        safe_name = (
            ble_address
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        )
        self._path = CACHE_DIR / f"{safe_name}.json"
        self._data: Dict = {}

    @property
    def path(self) -> Path:
        """Path to the cache file on disk."""
        return self._path

    @property
    def has_cache(self) -> bool:
        """True if a cache file exists on disk."""
        return self._path.exists()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load cache from disk.

        Returns:
            True if a valid cache was loaded, False otherwise.
        """
        if not self._path.exists():
            debug_print(f"Cache: no file at {self._path}")
            return False

        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"Cache: load error: {exc}")
            self._data = {}
            return False

        if self._data.get("version") != CACHE_VERSION:
            debug_print("Cache: version mismatch, ignoring")
            self._data = {}
            return False

        last = self._data.get("last_updated", "?")
        debug_print(f"Cache: loaded from {self._path} (last_updated={last})")
        return True

    def save(self) -> None:
        """Write current state to disk."""
        self._data["version"] = CACHE_VERSION
        self._data["address"] = self._address
        self._data["last_updated"] = datetime.now(timezone.utc).isoformat()

        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_print(f"Cache: saved to {self._path}")
        except OSError as exc:
            debug_print(f"Cache: save error: {exc}")

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def get_device(self) -> Optional[Dict]:
        """Return cached device info dict, or None."""
        return self._data.get("device")

    def set_device(self, payload: Dict) -> None:
        """Store device info and persist to disk."""
        self._data["device"] = payload.copy()
        self.save()

    def set_firmware_version(self, version: str) -> None:
        """Update firmware version in the cached device info."""
        device = self._data.get("device", {})
        device["firmware_version"] = version
        self._data["device"] = device
        self.save()

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def get_channels(self) -> List[Dict]:
        """Return cached channel list (may be empty)."""
        return self._data.get("channels", [])

    def set_channels(self, channels: List[Dict]) -> None:
        """Store channel list and persist to disk."""
        self._data["channels"] = [ch.copy() for ch in channels]
        self.save()

    # ------------------------------------------------------------------
    # Channel keys
    # ------------------------------------------------------------------

    def get_channel_keys(self) -> Dict[int, str]:
        """Return cached channel keys as ``{idx: secret_hex}``."""
        return self._data.get("channel_keys", {})

    def set_channel_key(self, channel_idx: int, secret_hex: str) -> None:
        """Store a single channel key (hex string) and persist."""
        keys = self._data.get("channel_keys", {})
        keys[str(channel_idx)] = secret_hex
        self._data["channel_keys"] = keys
        self.save()

    # ------------------------------------------------------------------
    # Contacts (merge strategy)
    # ------------------------------------------------------------------

    def get_contacts(self) -> Dict:
        """Return cached contacts dict (may be empty)."""
        return self._data.get("contacts", {})

    def merge_contacts(self, fresh: Dict) -> Dict:
        """Merge fresh contacts into cache and persist.

        Strategy:
        - New contacts in ``fresh`` → added with ``last_seen``
        - Existing contacts → updated (fresh data wins)
        - Contacts only in cache → kept (node may be offline)

        Args:
            fresh: Contacts dict from ``get_contacts()`` BLE response.

        Returns:
            The merged contacts dict (superset of cached + fresh).
        """
        cached = self._data.get("contacts", {})
        now = datetime.now(timezone.utc).isoformat()

        for key, contact in fresh.items():
            contact_copy = contact.copy()
            contact_copy["last_seen"] = now
            cached[key] = contact_copy

        self._data["contacts"] = cached
        self.save()

        debug_print(
            f"Cache: contacts merged — "
            f"{len(fresh)} fresh, {len(cached)} total"
        )
        return cached

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_last_updated(self) -> Optional[str]:
        """Return ISO timestamp of last cache update, or None."""
        return self._data.get("last_updated")
