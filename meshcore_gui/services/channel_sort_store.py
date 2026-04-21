"""
Channel sort preference store for MeshCore GUI.

Persists the user's choice of drawer channel-list sort order so that it
survives application restarts. The preference is a GUI-only concern
and is intentionally not stored on the device.

The sort mode is a single global setting (not per-device): the drawer
submenus for Messages and Archive share the same preference, matching
the user's mental model of "how do I want to see my channel list".

Storage location
~~~~~~~~~~~~~~~~
``~/.meshcore-gui/channel_sort.json``

Thread safety
~~~~~~~~~~~~~
All methods use an internal lock for thread-safe operation.
"""

import json
import threading
from pathlib import Path

from meshcore_gui.config import CHANNEL_SORT_MODE_DEFAULT, debug_print

# Valid sort-mode values. Kept as module-level constants so callers do
# not have to rely on string literals when comparing or dispatching.
SORT_BY_INDEX: str = "index"
SORT_BY_NAME: str = "name"

_VALID_MODES = frozenset({SORT_BY_INDEX, SORT_BY_NAME})

_STORE_DIR = Path.home() / ".meshcore-gui"
_STORE_PATH = _STORE_DIR / "channel_sort.json"


class ChannelSortStore:
    """Persistent storage for the drawer channel-list sort mode.

    A single sort mode (``"index"`` or ``"name"``) is shared by every
    drawer channel submenu. The preference is reloaded on instantiation
    and written to disk on every successful mutation.

    Args:
        default_mode: Sort mode to use when no stored file exists or the
            stored value is invalid. Defaults to
            :data:`~meshcore_gui.config.CHANNEL_SORT_MODE_DEFAULT`.
    """

    def __init__(self, default_mode: str = CHANNEL_SORT_MODE_DEFAULT) -> None:
        self._lock = threading.Lock()
        self._mode: str = (
            default_mode if default_mode in _VALID_MODES else SORT_BY_INDEX
        )
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_mode(self) -> str:
        """Return the current sort mode.

        Returns:
            Either :data:`SORT_BY_INDEX` or :data:`SORT_BY_NAME`.
        """
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> None:
        """Set and persist the sort mode.

        Invalid values are silently ignored to keep the stored file in a
        known-good state.

        Args:
            mode: Must be :data:`SORT_BY_INDEX` or :data:`SORT_BY_NAME`.
        """
        if mode not in _VALID_MODES:
            debug_print(f"ChannelSortStore: rejecting invalid mode '{mode}'")
            return
        with self._lock:
            if self._mode == mode:
                return
            self._mode = mode
            self._save()
            debug_print(f"ChannelSortStore: set mode -> {mode}")

    def toggle_mode(self) -> str:
        """Flip between the two sort modes and persist the new value.

        Returns:
            The new sort mode after toggling.
        """
        with self._lock:
            new_mode = SORT_BY_NAME if self._mode == SORT_BY_INDEX else SORT_BY_INDEX
            self._mode = new_mode
            self._save()
            debug_print(f"ChannelSortStore: toggled mode -> {new_mode}")
            return new_mode

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the stored sort mode from disk, if present."""
        if not _STORE_PATH.exists():
            debug_print(f"ChannelSortStore: no file at {_STORE_PATH}")
            return
        try:
            data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
            stored = data.get("mode")
            if stored in _VALID_MODES:
                self._mode = stored
                debug_print(f"ChannelSortStore: loaded mode '{stored}'")
            else:
                debug_print(
                    f"ChannelSortStore: ignoring invalid stored mode '{stored}'"
                )
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"ChannelSortStore: load error: {exc}")

    def _save(self) -> None:
        """Write the current sort mode to disk."""
        try:
            _STORE_DIR.mkdir(parents=True, exist_ok=True)
            _STORE_PATH.write_text(
                json.dumps({"mode": self._mode}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            debug_print(f"ChannelSortStore: save error: {exc}")
