"""
Channel backup store for MeshCore GUI.

Persists a snapshot of the device's channel table — names + PSKs — to a
local JSON file so channels can be recreated after a firmware reflash,
NVS erase or device replacement.

File location
~~~~~~~~~~~~~
``~/.meshcore-gui/channel_backups/_<safe_dev_id>_channels.json``

The filename convention mirrors :class:`BotConfigStore` and
:class:`PinStore` so each device gets its own backup file.  Example for
``/dev/ttyUSB1``::

    ~/.meshcore-gui/channel_backups/_dev_ttyUSB1_channels.json

Data sources
~~~~~~~~~~~~
- Channel names & slot indices → :class:`DeviceCache` (``channel_names``)
- Channel PSKs (16-byte AES keys) → :class:`DeviceCache` (``channel_keys``)
- Firmware version for context → :class:`DeviceCache` (``device.firmware_version``)

Privacy note
~~~~~~~~~~~~
Unlike ``public_api_service``, this backup *intentionally* stores every
channel — including private ones — because the whole point is to let the
operator restore their full channel table after a flash.  The file lives
only on the local machine (`~/.meshcore-gui/`) and is never exposed via
the public API, so the domca.nl privacy rule is not violated.

Thread safety
~~~~~~~~~~~~~
All public methods acquire an internal ``threading.Lock``.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import DATA_DIR, debug_print
from meshcore_gui.services.cache import DeviceCache


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKUP_DIR: Path = DATA_DIR / "channel_backups"

# On-disk schema version.  Bump when adding non-backward-compatible fields.
BACKUP_SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ChannelBackupEntry:
    """Single channel entry in a backup file.

    Attributes:
        slot_idx:   Channel slot index on the device (0–99).
        name:       Channel name as stored on the device.
        psk_hex:    32-character lowercase hex PSK.  Empty for channels
                    whose key was never cached (rare — typically only for
                    slot 0 on devices where ``get_channel()`` was never
                    issued).
    """

    slot_idx: int
    name: str
    psk_hex: str = ""


@dataclass
class ChannelBackup:
    """Full backup snapshot for one device.

    Attributes:
        schema_version:     On-disk schema version.
        device_id:          Device identifier this backup was taken from.
        firmware_version:   Firmware version at the time of backup (may be empty).
        exported_at:        ISO-8601 UTC timestamp of export.
        channels:           Sorted-by-slot list of channel entries.
    """

    schema_version: int = BACKUP_SCHEMA_VERSION
    device_id: str = ""
    firmware_version: str = ""
    exported_at: str = ""
    channels: List[ChannelBackupEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ChannelBackupStore:
    """Persistent per-device channel backup.

    Args:
        device_id: Device identifier string used to derive the filename.
                   May be empty for a device-agnostic default store.
    """

    def __init__(self, device_id: str = "") -> None:
        self._lock = threading.Lock()
        self._device_id = device_id

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        ) if device_id else "default"

        self._path: Path = BACKUP_DIR / f"_{safe_name}_channels.json"

    # ------------------------------------------------------------------
    # Public API — paths
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Path to the backup file on disk (may or may not exist)."""
        return self._path

    @property
    def exists(self) -> bool:
        """True when a backup file is present on disk."""
        return self._path.exists()

    # ------------------------------------------------------------------
    # Public API — export (backup)
    # ------------------------------------------------------------------

    def export_from_cache(
        self,
        cache: Optional[DeviceCache] = None,
        live_channels: Optional[List[Dict]] = None,
    ) -> ChannelBackup:
        """Build a backup snapshot from the device cache and persist it.

        The snapshot merges three data sources, in order of precedence:

        1. ``live_channels`` — the currently-displayed channel list from
           :class:`SharedData`.  Provides authoritative names and slot
           indices for slots that are currently active on the device.
        2. Cached channel names (``DeviceCache.get_channel_names()``) —
           fallback for slots that are not in the live snapshot but whose
           name was seen previously.
        3. Cached PSKs (``DeviceCache.get_channel_keys()``) — the only
           source for the 16-byte secrets.  Slots without a cached key
           are still exported with ``psk_hex=""`` so the user sees the
           gap; such entries cannot be restored without manual input.

        Args:
            cache:          Device cache to read from.  When ``None``, a
                            fresh :class:`DeviceCache` is instantiated
                            for ``self._device_id`` (this is the normal
                            case — the worker's cache writes to the same
                            file, so a re-read gets the latest state).
            live_channels:  Optional list of ``{'idx': int, 'name': str}``
                            dicts from the current ``SharedData`` snapshot.

        Returns:
            The :class:`ChannelBackup` that was written to disk.

        Raises:
            OSError: if the backup file cannot be written.
        """
        with self._lock:
            if cache is None:
                cache = DeviceCache(self._device_id)
                cache.load()

            # Names from cache (int → str) + PSKs (str key in JSON → hex)
            cached_names: Dict[int, str] = cache.get_channel_names()
            cached_keys_raw = cache.get_channel_keys()  # {str(idx): hex}

            # Overlay live channels (authoritative for current state)
            name_by_idx: Dict[int, str] = dict(cached_names)
            if live_channels:
                for ch in live_channels:
                    try:
                        name_by_idx[int(ch["idx"])] = ch.get("name", "") or ""
                    except (KeyError, ValueError, TypeError):
                        continue

            # Normalise PSK dict: JSON store uses str keys, int keys may sneak in
            psk_by_idx: Dict[int, str] = {}
            for k, v in cached_keys_raw.items():
                try:
                    psk_by_idx[int(k)] = (v or "").lower()
                except (ValueError, TypeError):
                    continue

            # Union of all indices we know about
            all_indices = sorted(set(name_by_idx) | set(psk_by_idx))

            entries: List[ChannelBackupEntry] = []
            for idx in all_indices:
                entries.append(
                    ChannelBackupEntry(
                        slot_idx=idx,
                        name=name_by_idx.get(idx, "") or "",
                        psk_hex=psk_by_idx.get(idx, "") or "",
                    )
                )

            # Pull firmware version from cached device info
            fw_version = ""
            dev = cache.get_device() or {}
            if isinstance(dev, dict):
                fw_version = str(dev.get("firmware_version", "") or "")

            backup = ChannelBackup(
                schema_version=BACKUP_SCHEMA_VERSION,
                device_id=self._device_id,
                firmware_version=fw_version,
                exported_at=datetime.now(timezone.utc).isoformat(),
                channels=entries,
            )

            self._save(backup)
            debug_print(
                f"ChannelBackupStore: exported {len(entries)} channels to "
                f"{self._path.name}"
            )
            return backup

    # ------------------------------------------------------------------
    # Public API — import (restore)
    # ------------------------------------------------------------------

    def load_backup(self) -> Optional[ChannelBackup]:
        """Load the backup file for this device, if any.

        Returns:
            :class:`ChannelBackup` instance, or ``None`` if no file exists
            or the file is unreadable / wrong schema.
        """
        with self._lock:
            if not self._path.exists():
                debug_print(
                    f"ChannelBackupStore: no file at {self._path.name}"
                )
                return None
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                debug_print(f"ChannelBackupStore: load error: {exc}")
                return None

            return self._parse(raw)

    def load_backup_from_path(self, path: Path) -> Optional[ChannelBackup]:
        """Load a backup file from an arbitrary path.

        Used by the Restore dialog to support cross-device restores
        (e.g. moving channels from an old node to a new one).

        Args:
            path: Absolute or relative filesystem path to the JSON file.

        Returns:
            :class:`ChannelBackup` instance, or ``None`` on error.
        """
        p = Path(path)
        if not p.exists():
            debug_print(f"ChannelBackupStore: file not found: {p}")
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"ChannelBackupStore: load error ({p}): {exc}")
            return None
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Public API — diffing helpers (for Restore preview)
    # ------------------------------------------------------------------

    @staticmethod
    def diff_against_device(
        backup: ChannelBackup,
        live_channels: List[Dict],
        cached_keys: Dict[int, str],
    ) -> Dict[str, List[ChannelBackupEntry]]:
        """Classify backup entries against the current device state.

        Helps the Restore preview show exactly what will happen:

        - ``restorable``   — backup has a PSK and slot is empty on device.
        - ``conflict``     — backup has a PSK but the slot is already in
                             use with a different name or different PSK.
        - ``identical``    — slot already matches the backup (no change).
        - ``skipped``      — backup entry has no PSK → cannot be written.

        Args:
            backup:        Parsed :class:`ChannelBackup`.
            live_channels: Current channel list (``[{idx,name},...]``).
            cached_keys:   Current PSK cache ``{int: hex_lower}``.

        Returns:
            Dict with four lists of :class:`ChannelBackupEntry`, keyed by
            the category names above.
        """
        live_by_idx: Dict[int, str] = {}
        for ch in live_channels or []:
            try:
                live_by_idx[int(ch["idx"])] = ch.get("name", "") or ""
            except (KeyError, ValueError, TypeError):
                continue

        out: Dict[str, List[ChannelBackupEntry]] = {
            "restorable": [],
            "conflict": [],
            "identical": [],
            "skipped": [],
        }

        for entry in backup.channels:
            if not entry.psk_hex:
                out["skipped"].append(entry)
                continue

            live_name = live_by_idx.get(entry.slot_idx)
            live_psk = cached_keys.get(entry.slot_idx, "").lower()

            if live_name is None:
                # Slot is empty on the device
                out["restorable"].append(entry)
            elif live_name == entry.name and live_psk == entry.psk_hex:
                out["identical"].append(entry)
            else:
                out["conflict"].append(entry)

        return out

    # ------------------------------------------------------------------
    # Internal — (de)serialisation
    # ------------------------------------------------------------------

    def _save(self, backup: ChannelBackup) -> None:
        """Write a backup snapshot to disk (caller holds the lock)."""
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "schema_version": backup.schema_version,
                "device_id": backup.device_id,
                "firmware_version": backup.firmware_version,
                "exported_at": backup.exported_at,
                "channels": [
                    {
                        "slot_idx": e.slot_idx,
                        "name": e.name,
                        "psk_hex": e.psk_hex,
                    }
                    for e in backup.channels
                ],
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_print(
                f"ChannelBackupStore: saved to {self._path.name}"
            )
        except OSError as exc:
            debug_print(f"ChannelBackupStore: save error: {exc}")
            raise

    @staticmethod
    def _parse(raw: Dict) -> Optional[ChannelBackup]:
        """Validate and convert raw JSON into a :class:`ChannelBackup`.

        Returns ``None`` when the schema version is unknown or the
        structure is malformed.
        """
        if not isinstance(raw, dict):
            return None

        schema = raw.get("schema_version", 0)
        if schema != BACKUP_SCHEMA_VERSION:
            debug_print(
                f"ChannelBackupStore: unsupported schema_version={schema}"
            )
            return None

        channels_raw = raw.get("channels", [])
        if not isinstance(channels_raw, list):
            return None

        entries: List[ChannelBackupEntry] = []
        for item in channels_raw:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(
                    ChannelBackupEntry(
                        slot_idx=int(item.get("slot_idx", -1)),
                        name=str(item.get("name", "") or ""),
                        psk_hex=str(item.get("psk_hex", "") or "").lower(),
                    )
                )
            except (ValueError, TypeError):
                continue

        # Sort by slot for consistent display regardless of file order
        entries.sort(key=lambda e: e.slot_idx)

        return ChannelBackup(
            schema_version=schema,
            device_id=str(raw.get("device_id", "") or ""),
            firmware_version=str(raw.get("firmware_version", "") or ""),
            exported_at=str(raw.get("exported_at", "") or ""),
            channels=entries,
        )
