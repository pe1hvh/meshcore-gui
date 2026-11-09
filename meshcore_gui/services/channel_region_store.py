"""
Per-device region (flood scope) store for MeshCore GUI.

Persists, per device:

- the default region of each channel (keyed by channel **name**, so the
  setting follows a channel through a move / reindex);
- the list of known region names, used to attribute received transport
  codes and to fill the region selects;
- the device default scope as last read from the device, so the GUI can
  show it before the worker has reconnected (cache-first).

Region names are stored without the leading ``#``.

Storage location
~~~~~~~~~~~~~~~~
``~/.meshcore-gui/regions/<ADDRESS>_regions.json``

Thread safety
~~~~~~~~~~~~~
All methods use an internal lock.  One instance is shared by the GUI
(writes channel defaults) and the worker (reads them when sending and
when attributing received packets).
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict, List

from meshcore_gui.config import debug_print
from meshcore_gui.services.region_service import normalize_region_name

REGIONS_DIR = Path.home() / ".meshcore-gui" / "regions"


class ChannelRegionStore:
    """Persistent storage for channel default regions and known regions.

    Args:
        device_id: Device identifier string (used to derive the filename).
    """

    def __init__(self, device_id: str) -> None:
        self._lock = threading.Lock()

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        )
        self._path = REGIONS_DIR / f"{safe_name}_regions.json"
        self._channels: Dict[str, str] = {}
        self._known: List[str] = []
        self._device_default: str = ""

        self._load()

    # ------------------------------------------------------------------
    # Channel defaults
    # ------------------------------------------------------------------

    def get_channel_region(self, channel_name: str) -> str:
        """Return the default region stored for a channel.

        Args:
            channel_name: Channel name as reported by the device.

        Returns:
            Region name, or an empty string when the channel has none.
        """
        with self._lock:
            return self._channels.get(channel_name, "")

    def set_channel_region(self, channel_name: str, region: str) -> None:
        """Set or clear the default region of a channel.

        A non-empty region is also added to the known regions.

        Args:
            channel_name: Channel name as reported by the device.
            region:       Region name; empty string clears the default.
        """
        region = normalize_region_name(region)
        with self._lock:
            if region:
                self._channels[channel_name] = region
                self._add_known_locked(region)
            else:
                self._channels.pop(channel_name, None)
            self._save()
        debug_print(
            f"ChannelRegionStore: channel {channel_name!r} → "
            f"{('#' + region) if region else '(device default)'}"
        )

    # ------------------------------------------------------------------
    # Known regions
    # ------------------------------------------------------------------

    def get_known_regions(self) -> List[str]:
        """Return all known region names, including the device default.

        Returns:
            Sorted list of unique region names (case-insensitive order).
        """
        with self._lock:
            names = set(self._known)
            if self._device_default:
                names.add(self._device_default)
            return sorted(names, key=str.lower)

    def add_known_region(self, region: str) -> None:
        """Add a region name to the known regions.

        Args:
            region: Region name, with or without leading ``#``.
        """
        region = normalize_region_name(region)
        if not region:
            return
        with self._lock:
            if self._add_known_locked(region):
                self._save()

    # ------------------------------------------------------------------
    # Device default scope
    # ------------------------------------------------------------------

    def get_device_default(self) -> str:
        """Return the device default scope as last read from the device.

        Returns:
            Region name, or an empty string when none is set or unknown.
        """
        with self._lock:
            return self._device_default

    def set_device_default(self, region: str) -> None:
        """Record the device default scope read from the device.

        Args:
            region: Region name; empty string when the device has none.
        """
        region = normalize_region_name(region)
        with self._lock:
            if region == self._device_default:
                return
            self._device_default = region
            self._save()
        debug_print(
            f"ChannelRegionStore: device default scope = "
            f"{('#' + region) if region else '(none)'}"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _add_known_locked(self, region: str) -> bool:
        """Add *region* to the known list; caller must hold the lock.

        Args:
            region: Normalized region name.

        Returns:
            True when the list changed.
        """
        if region in self._known:
            return False
        self._known.append(region)
        return True

    def _load(self) -> None:
        """Load the store from disk."""
        if not self._path.exists():
            debug_print(f"ChannelRegionStore: no file at {self._path}")
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._channels = {
                str(k): normalize_region_name(str(v))
                for k, v in data.get("channels", {}).items()
                if normalize_region_name(str(v))
            }
            self._known = [
                normalize_region_name(str(r))
                for r in data.get("known_regions", [])
                if normalize_region_name(str(r))
            ]
            self._device_default = normalize_region_name(
                str(data.get("device_default", ""))
            )
            debug_print(
                f"ChannelRegionStore: loaded {len(self._channels)} channel "
                f"defaults, {len(self._known)} known regions"
            )
        except (json.JSONDecodeError, OSError, AttributeError) as exc:
            debug_print(f"ChannelRegionStore: load error: {exc}")
            self._channels = {}
            self._known = []
            self._device_default = ""

    def _save(self) -> None:
        """Write the store to disk atomically (temp file + rename).

        Caller must hold the lock.
        """
        data = {
            "channels": dict(self._channels),
            "known_regions": list(self._known),
            "device_default": self._device_default,
        }
        tmp_path = self._path.with_suffix(".json.tmp")
        try:
            REGIONS_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp_path, self._path)
        except OSError as exc:
            debug_print(f"ChannelRegionStore: save error: {exc}")
