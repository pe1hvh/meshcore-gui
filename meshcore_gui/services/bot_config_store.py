"""
Bot configuration store for MeshCore GUI.

Persists bot settings to
``~/.meshcore-gui/bot/_<safe_dev_id>_bot.json``.

The filename mirrors the PinStore convention so configuration is
always bound to a specific device.

Example path for ``/dev/ttyUSB1``::

    ~/.meshcore-gui/bot/_dev_ttyUSB1_bot.json

Thread safety
~~~~~~~~~~~~~
All public methods acquire an internal ``threading.Lock``.
"""

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

from meshcore_gui.config import BOT_DIR, debug_print


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BotSettings:
    """Persistent bot settings for a single device.

    Attributes:
        enabled:      Whether the bot is active.
        private_mode: When True, bot only replies to pinned contacts.
        channels:     Set of channel indices the bot listens on.
                      Empty set means "use BotConfig defaults".
    """

    enabled: bool = False
    private_mode: bool = False
    channels: Set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class BotConfigStore:
    """Persistent storage for bot settings per device.

    Args:
        device_id: Device identifier string used to derive the filename.
                   May be empty for a device-agnostic default store.
    """

    def __init__(self, device_id: str = "") -> None:
        self._lock = threading.Lock()

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        ) if device_id else "default"

        self._path: Path = BOT_DIR / f"_{safe_name}_bot.json"
        self._settings: BotSettings = BotSettings()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_settings(self) -> BotSettings:
        """Return a shallow copy of the current bot settings.

        Returns:
            Copy of the stored :class:`BotSettings`.
        """
        with self._lock:
            return BotSettings(
                enabled=self._settings.enabled,
                private_mode=self._settings.private_mode,
                channels=set(self._settings.channels),
            )

    def set_enabled(self, value: bool) -> None:
        """Set the bot enabled flag and persist to disk.

        Args:
            value: New enabled state.
        """
        with self._lock:
            self._settings.enabled = value
            self._save()
            debug_print(f"BotConfigStore: enabled={value}")

    def set_private_mode(self, value: bool) -> None:
        """Set private mode and persist to disk.

        Args:
            value: New private mode state.
        """
        with self._lock:
            self._settings.private_mode = value
            self._save()
            debug_print(f"BotConfigStore: private_mode={value}")

    def set_channels(self, channels: Set[int]) -> None:
        """Set the bot channel set and persist to disk.

        Args:
            channels: Set of channel indices to respond on.
        """
        with self._lock:
            self._settings.channels = set(channels)
            self._save()
            debug_print(f"BotConfigStore: channels={sorted(channels)}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load settings from disk (called once at construction)."""
        if not self._path.exists():
            debug_print(f"BotConfigStore: no file at {self._path.name}")
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._settings = BotSettings(
                enabled=data.get("enabled", False),
                private_mode=data.get("private_mode", False),
                channels=set(data.get("channels", [])),
            )
            debug_print(
                f"BotConfigStore: loaded from {self._path.name} — "
                f"enabled={self._settings.enabled}, "
                f"private={self._settings.private_mode}, "
                f"channels={sorted(self._settings.channels)}"
            )
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"BotConfigStore: load error: {exc}")
            self._settings = BotSettings()

    def _save(self) -> None:
        """Write current settings to disk."""
        try:
            BOT_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "enabled": self._settings.enabled,
                "private_mode": self._settings.private_mode,
                "channels": sorted(self._settings.channels),
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_print(f"BotConfigStore: saved to {self._path.name}")
        except OSError as exc:
            debug_print(f"BotConfigStore: save error: {exc}")
