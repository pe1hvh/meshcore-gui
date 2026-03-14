"""
BBS channel configuration store for MeshCore GUI.

Persists BBS channel configuration to
``~/.meshcore-gui/bbs/bbs_config.json`` so that settings survive
restarts and are managed outside of ``config.py``.

On first use the file is created with an empty channel list.
The GUI populates it when the user enables BBS on a device channel.

Thread safety
~~~~~~~~~~~~~
All methods acquire an internal ``threading.Lock``.
"""

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

# ---------------------------------------------------------------------------
# Storage location
# ---------------------------------------------------------------------------

BBS_DIR: Path = Path.home() / ".meshcore-gui" / "bbs"
BBS_CONFIG_PATH: Path = BBS_DIR / "bbs_config.json"

CONFIG_VERSION: int = 1

# ---------------------------------------------------------------------------
# Default values applied when a channel is first enabled
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: List[str] = ["STATUS", "ALGEMEEN"]
DEFAULT_REGIONS: List[str] = []
DEFAULT_RETENTION_HOURS: int = 48


class BbsConfigStore:
    """Persistent store for BBS channel configuration.

    Args:
        config_path: Path to the JSON config file.
                     Defaults to ``~/.meshcore-gui/bbs/bbs_config.json``.
    """

    def __init__(self, config_path: Path = BBS_CONFIG_PATH) -> None:
        self._path = config_path
        self._lock = threading.Lock()
        self._data: Dict = {"version": CONFIG_VERSION, "channels": []}
        self._load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load config from disk; create defaults if file is absent."""
        BBS_DIR.mkdir(parents=True, exist_ok=True)

        if not self._path.exists():
            self._save_unlocked()
            debug_print("BBS config: created new config file")
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if data.get("version") == CONFIG_VERSION:
                self._data = data
                debug_print(
                    f"BBS config: loaded {len(self._data.get('channels', []))} channels"
                )
            else:
                debug_print(
                    f"BBS config: version mismatch "
                    f"(got {data.get('version')}, expected {CONFIG_VERSION}) — using defaults"
                )
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"BBS config: load error ({exc}) — using defaults")

    def _save_unlocked(self) -> None:
        """Write config to disk.  MUST be called with self._lock held."""
        BBS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def save(self) -> None:
        """Flush current configuration to disk."""
        with self._lock:
            self._save_unlocked()

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    def get_channels(self) -> List[Dict]:
        """Return a copy of all configured channels (enabled and disabled).

        Returns:
            List of channel config dicts.
        """
        with self._lock:
            return [ch.copy() for ch in self._data.get("channels", [])]

    def get_enabled_channels(self) -> List[Dict]:
        """Return only channels with ``enabled: true``.

        Returns:
            List of enabled channel config dicts.
        """
        with self._lock:
            return [
                ch.copy()
                for ch in self._data.get("channels", [])
                if ch.get("enabled", False)
            ]

    def get_channel(self, channel_idx: int) -> Optional[Dict]:
        """Return config for a single channel index, or ``None``.

        Args:
            channel_idx: MeshCore channel index.

        Returns:
            Channel config dict copy, or ``None`` if not found.
        """
        with self._lock:
            for ch in self._data.get("channels", []):
                if ch.get("channel") == channel_idx:
                    return ch.copy()
        return None

    def set_channel(self, channel_cfg: Dict) -> None:
        """Insert or update a channel configuration entry.

        The channel is identified by the ``channel`` key in *channel_cfg*.
        If an entry with the same index exists it is replaced; otherwise
        a new entry is appended.

        Args:
            channel_cfg: Channel config dict (must contain ``'channel'``).
        """
        idx = channel_cfg["channel"]
        with self._lock:
            channels = self._data.setdefault("channels", [])
            for i, ch in enumerate(channels):
                if ch.get("channel") == idx:
                    channels[i] = channel_cfg.copy()
                    self._save_unlocked()
                    debug_print(f"BBS config: updated ch={idx}")
                    return
            channels.append(channel_cfg.copy())
            self._save_unlocked()
            debug_print(f"BBS config: added ch={idx}")

    def enable_channel(
        self,
        channel_idx: int,
        name: str,
        *,
        categories: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        allowed_keys: Optional[List[str]] = None,
    ) -> None:
        """Enable BBS on a device channel, creating a default config if needed.

        If the channel already exists its ``enabled`` flag is set to
        ``True`` and other fields are left as-is.  Pass explicit keyword
        arguments to override any field on a new channel.

        Args:
            channel_idx:     MeshCore channel index.
            name:            Human-readable channel name.
            categories:      Category list (defaults to ``DEFAULT_CATEGORIES``).
            regions:         Region list (defaults to empty — no regions).
            retention_hours: Retention in hours (default 48).
            allowed_keys:    Sender key whitelist (default empty = all allowed).
        """
        existing = self.get_channel(channel_idx)
        if existing:
            existing["enabled"] = True
            self.set_channel(existing)
        else:
            self.set_channel({
                "channel": channel_idx,
                "name": name,
                "enabled": True,
                "categories": categories if categories is not None else list(DEFAULT_CATEGORIES),
                "regions": regions if regions is not None else list(DEFAULT_REGIONS),
                "retention_hours": retention_hours,
                "allowed_keys": allowed_keys if allowed_keys is not None else [],
            })

    def disable_channel(self, channel_idx: int) -> None:
        """Set ``enabled: false`` for a channel without removing its config.

        Args:
            channel_idx: MeshCore channel index.
        """
        existing = self.get_channel(channel_idx)
        if existing:
            existing["enabled"] = False
            self.set_channel(existing)
            debug_print(f"BBS config: disabled ch={channel_idx}")

    def update_channel_field(
        self, channel_idx: int, field: str, value
    ) -> bool:
        """Update a single field on an existing channel entry.

        Args:
            channel_idx: MeshCore channel index.
            field:       Field name to update.
            value:       New value.

        Returns:
            ``True`` if the channel was found and updated, ``False`` otherwise.
        """
        existing = self.get_channel(channel_idx)
        if not existing:
            return False
        existing[field] = value
        self.set_channel(existing)
        return True
