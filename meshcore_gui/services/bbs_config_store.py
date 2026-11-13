"""
BBS board configuration store for MeshCore GUI.

Persists BBS board configuration to
``~/.meshcore-gui/bbs/bbs_config.json``.

Design (v1.14.0 redesign)
~~~~~~~~~~~~~~~~~~~~~~~~~
One node = one board.  The settings UI exposes a single channel selector;
the board id is always ``ch{channel_idx}`` and the name is taken from the
device channel.  There is no Create/Delete UI — the board is saved or
cleared through :meth:`configure_board` / :meth:`clear_board`.

Multiple-board storage is retained internally so that the storage layer
(``bbs_service.py``) and :meth:`get_board_for_channel` remain unchanged.

Config version history
~~~~~~~~~~~~~~~~~~~~~~
v1  — per-channel config (list of channels with enabled flag).
v2  — board-based config (list of boards, each with a channels list).
      Automatic migration from v1 on first load.

Thread safety
~~~~~~~~~~~~~
All public methods acquire an internal ``threading.Lock``.

Disk consistency (v1.25.1)
~~~~~~~~~~~~~~~~~~~~~~~~~~
Several independent instances read and write the same file: the worker
(DM / channel command routing), the dashboard panel, the settings page,
and — with multiple devices on one host — other application processes.
Every public method therefore re-reads the file first when its
modification time differs from the last load or save, so a change made
by one instance is seen by all others without a restart and a write
never overwrites a newer state with stale in-memory data.

Retention per category (v1.26.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Each board keeps a retention period in days per category
(``category_retention_days``) plus a fallback for categories without an
entry and for messages whose category is no longer configured
(``default_retention_days``).  ``0`` means *keep forever*.  Older config
files only have ``retention_hours``; they are read as a default
retention of ``ceil(retention_hours / 24)`` days.  ``retention_hours``
is still written (see :func:`legacy_retention_hours`) so that an older
meshcore-gui version reading the same file never deletes a message that
this version keeps.
"""

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

BBS_DIR: Path = Path.home() / ".meshcore-gui" / "bbs"
BBS_CONFIG_PATH: Path = BBS_DIR / "bbs_config.json"

CONFIG_VERSION: int = 2

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: List[str] = ["STATUS", "ALGEMEEN"]
DEFAULT_REGIONS: List[str] = []
DEFAULT_RETENTION_HOURS: int = 48

DEFAULT_RETENTION_DAYS: int = 90
"""Default retention in days for a new board and for categories without
an own entry (v1.26.0).  ``0`` would mean *keep forever*."""

KEEP_FOREVER_HOURS: int = 100 * 365 * 24
"""``retention_hours`` written for older versions when a board keeps
messages forever: 876 000 hours (100 years).  Older versions treat
``retention_hours`` literally, so ``0`` there would delete everything."""


# ---------------------------------------------------------------------------
# Retention helpers (v1.26.0)
# ---------------------------------------------------------------------------

def clean_retention_days(value: object, fallback: int) -> int:
    """Return *value* as a valid retention in days.

    Args:
        value:    Raw value from the config file or the settings page
                  (``int``, numeric ``str`` or anything else).
        fallback: Value returned when ``int(value)`` fails or gives a
                  negative number.  A float is truncated (``2.7`` → ``2``),
                  not rejected.

    Returns:
        Retention in days, ``>= 0``; ``0`` means *keep forever*.
    """
    try:
        days = int(value)
    except (TypeError, ValueError):
        return fallback
    return days if days >= 0 else fallback


def hours_to_days(hours: object) -> int:
    """Convert a legacy ``retention_hours`` value to whole days.

    Rounds up, so a board never loses messages earlier than before:
    48 h → 2 days, 2160 h → 90 days, 1 h → 1 day.  Values for which
    ``int()`` fails or gives ``<= 0`` give :data:`DEFAULT_RETENTION_DAYS`;
    a float is truncated first.

    Args:
        hours: Legacy ``retention_hours`` value.

    Returns:
        Retention in days, ``>= 1``.
    """
    try:
        value = int(hours)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
    if value <= 0:
        return DEFAULT_RETENTION_DAYS
    return math.ceil(value / 24)


def category_days_for(
    categories: List[str], days: Dict[str, int], fallback: int,
) -> Dict[str, int]:
    """Return the retention entries of *days* that belong to *categories*.

    Args:
        categories: Configured category names (any case).
        days:       Retention in days per category name (any case).
        fallback:   Value for entries that are not a whole number ``>= 0``.

    Returns:
        Mapping upper-case category name → days, only for names in
        *categories*.
    """
    configured = {c.upper() for c in categories}
    return {
        str(cat).upper(): clean_retention_days(value, fallback)
        for cat, value in days.items()
        if str(cat).upper() in configured
    }


def legacy_retention_hours(
    default_days: int, category_days: Dict[str, int],
) -> int:
    """Return the ``retention_hours`` to write for older versions.

    Older versions purge every category with this single value, so it
    is the *longest* retention of the board: ``KEEP_FOREVER_HOURS`` if
    any period (default or category) is ``0``, otherwise the largest
    period in days × 24.

    Args:
        default_days:  Board default retention in days.
        category_days: Retention in days per category.

    Returns:
        Retention in hours, ``>= 24`` (or ``KEEP_FOREVER_HOURS``).
    """
    periods = [default_days, *category_days.values()]
    if any(days == 0 for days in periods):
        return KEEP_FOREVER_HOURS
    return max(periods) * 24


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BbsBoard:  # pylint: disable=too-many-instance-attributes  # one field per JSON key
    """A BBS board grouping one or more MeshCore channels.

    Attributes:
        id:              Unique identifier (slug, e.g. ``'noodnet_zwolle'``).
        name:            Human-readable board name.
        channels:        List of MeshCore channel indices assigned to this board.
        categories:      Valid category tags for this board.
        regions:         Optional region tags; empty = no region filtering.
        retention_hours: Legacy single retention in hours (before v1.26.0).
                         Used only to derive ``default_retention_days``
                         when that key is absent from the file; not used
                         by the purge and not written back as is
                         (``to_dict`` writes :func:`legacy_retention_hours`
                         instead).
        allowed_keys:    Sender public key whitelist for DM-BBS access.
        default_retention_days:  Retention in days for categories without
                                 an entry in ``category_retention_days``
                                 and for unconfigured categories;
                                 ``0`` = keep forever (v1.26.0).
        category_retention_days: Retention in days per category name
                                 (upper case); ``0`` = keep forever
                                 (v1.26.0).
    """

    id: str
    name: str
    channels: List[int] = field(default_factory=list)
    categories: List[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    regions: List[str] = field(default_factory=list)
    retention_hours: int = DEFAULT_RETENTION_HOURS
    allowed_keys: List[str] = field(default_factory=list)
    default_retention_days: int = DEFAULT_RETENTION_DAYS
    category_retention_days: Dict[str, int] = field(default_factory=dict)

    def retention_days_for(self, category: str) -> int:
        """Return the retention in days that applies to *category*.

        Args:
            category: Category name; matched case-insensitively.

        Returns:
            Days from ``category_retention_days`` when the category is
            configured and has an entry, otherwise
            ``default_retention_days``.  ``0`` means *keep forever*.
        """
        key = (category or "").upper()
        if key in (c.upper() for c in self.categories):
            for name, days in self.category_retention_days.items():
                if name.upper() == key:
                    return days
        return self.default_retention_days

    def to_dict(self) -> Dict:
        """Serialise to a JSON-compatible dict.

        ``retention_hours`` is written as :func:`legacy_retention_hours`
        of the day fields, not as the stored attribute, so older
        versions sharing the file never purge more than this version.

        Returns:
            Dict with all board fields, ready for ``json.dumps``.
        """
        return {
            "id": self.id,
            "name": self.name,
            "channels": list(self.channels),
            "categories": list(self.categories),
            "regions": list(self.regions),
            "retention_hours": legacy_retention_hours(
                self.default_retention_days, self.category_retention_days,
            ),
            "allowed_keys": list(self.allowed_keys),
            "default_retention_days": self.default_retention_days,
            "category_retention_days": dict(self.category_retention_days),
        }

    @staticmethod
    def from_dict(d: Dict) -> "BbsBoard":
        """Deserialise from a config dict.

        A dict without ``default_retention_days`` (config written before
        v1.26.0) is migrated: the default becomes
        :func:`hours_to_days` of ``retention_hours``.  An invalid or
        negative ``default_retention_days`` becomes
        :data:`DEFAULT_RETENTION_DAYS`; an invalid or negative category
        entry becomes the board's default.  Category keys are stored
        upper case.

        Args:
            d: Board dict as stored in ``bbs_config.json``.

        Returns:
            New ``BbsBoard`` instance.

        Raises:
            ValueError: ``retention_hours`` is a string ``int()`` cannot
                convert (unchanged behaviour since before v1.26.0).
            TypeError: ``retention_hours`` is of a type ``int()`` does not
                accept, e.g. ``None`` or a list.
            AttributeError: ``category_retention_days`` is present but not
                a dict.
        """
        retention_hours = d.get("retention_hours", DEFAULT_RETENTION_HOURS)
        if "default_retention_days" in d:
            default_days = clean_retention_days(
                d["default_retention_days"], DEFAULT_RETENTION_DAYS,
            )
        else:
            default_days = hours_to_days(retention_hours)
        category_days = {
            str(name).upper(): clean_retention_days(days, default_days)
            for name, days in (d.get("category_retention_days") or {}).items()
        }
        return BbsBoard(
            id=d.get("id", ""),
            name=d.get("name", ""),
            channels=list(d.get("channels", [])),
            categories=list(d.get("categories", DEFAULT_CATEGORIES)),
            regions=list(d.get("regions", [])),
            retention_hours=int(retention_hours),
            allowed_keys=list(d.get("allowed_keys", [])),
            default_retention_days=default_days,
            category_retention_days=category_days,
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class BbsConfigStore:
    """Persistent store for BBS board configuration.

    Args:
        config_path: Path to the JSON config file.
                     Defaults to ``~/.meshcore-gui/bbs/bbs_config.json``.
    """

    def __init__(self, config_path: Path = BBS_CONFIG_PATH) -> None:
        self._path = config_path
        self._lock = threading.Lock()
        self._boards: List[BbsBoard] = []
        self._mtime_ns: Optional[int] = None
        self._load()
        self._mtime_ns = self._current_mtime_ns()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load config from disk; migrate v1 → v2 if needed."""
        BBS_DIR.mkdir(parents=True, exist_ok=True)

        if not self._path.exists():
            self._save_unlocked()
            debug_print("BBS config: created new config file (v2)")
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            version = data.get("version", 1)

            if version == CONFIG_VERSION:
                self._boards = [
                    BbsBoard.from_dict(b) for b in data.get("boards", [])
                ]
                debug_print(f"BBS config: loaded {len(self._boards)} boards")

            elif version == 1:
                # Migrate: each v1 channel → one board
                self._boards = self._migrate_v1(data.get("channels", []))
                self._save_unlocked()
                debug_print(
                    f"BBS config: migrated v1 → v2 ({len(self._boards)} boards)"
                )
            else:
                debug_print(
                    f"BBS config: unknown version {version}, using empty config"
                )

        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"BBS config: load error ({exc}), using empty config")

    @staticmethod
    def _migrate_v1(v1_channels: List[Dict]) -> List["BbsBoard"]:
        """Convert v1 per-channel entries to v2 boards.

        Only enabled channels are migrated.

        Args:
            v1_channels: List of v1 channel config dicts.

        Returns:
            List of ``BbsBoard`` instances.
        """
        boards = []
        for ch in v1_channels:
            if not ch.get("enabled", False):
                continue
            idx = ch.get("channel", 0)
            board_id = f"ch{idx}"
            boards.append(BbsBoard(
                id=board_id,
                name=ch.get("name", f"Channel {idx}"),
                channels=[idx],
                categories=list(ch.get("categories", DEFAULT_CATEGORIES)),
                regions=list(ch.get("regions", [])),
                retention_hours=int(ch.get("retention_hours", DEFAULT_RETENTION_HOURS)),
                allowed_keys=list(ch.get("allowed_keys", [])),
                default_retention_days=hours_to_days(
                    ch.get("retention_hours", DEFAULT_RETENTION_HOURS)
                ),
            ))
        return boards

    def _save_unlocked(self) -> None:
        """Write config to disk.  MUST be called with self._lock held."""
        BBS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "version": CONFIG_VERSION,
            "boards": [b.to_dict() for b in self._boards],
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._path)
        self._mtime_ns = self._current_mtime_ns()

    def _current_mtime_ns(self) -> Optional[int]:
        """Return the modification time of the config file in nanoseconds.

        Returns:
            Modification time, or ``None`` when the file cannot be read.
        """
        try:
            return self._path.stat().st_mtime_ns
        except OSError:
            return None

    def _reload_if_changed_unlocked(self) -> None:
        """Re-read the config file when it changed on disk.

        MUST be called with ``self._lock`` held.  The file is written
        atomically (temp file + replace), so a changed modification time
        always refers to a complete file.  On a read or parse error, or
        an unexpected config version, the in-memory state is kept.
        """
        mtime = self._current_mtime_ns()
        if mtime is None or mtime == self._mtime_ns:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"BBS config: reload error ({exc}), keeping current config")
            return
        if data.get("version", 1) != CONFIG_VERSION:
            debug_print(
                f"BBS config: reload skipped, version {data.get('version')} "
                f"!= {CONFIG_VERSION}"
            )
            return
        self._boards = [BbsBoard.from_dict(b) for b in data.get("boards", [])]
        self._mtime_ns = mtime
        debug_print(
            f"BBS config: reloaded {len(self._boards)} boards (changed on disk)"
        )

    def save(self) -> None:
        """Flush current configuration to disk."""
        with self._lock:
            self._save_unlocked()

    # ------------------------------------------------------------------
    # Board queries
    # ------------------------------------------------------------------

    def get_boards(self) -> List[BbsBoard]:
        """Return a copy of all configured boards.

        Returns:
            List of ``BbsBoard`` instances.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            return list(self._boards)

    def get_board(self, board_id: str) -> Optional[BbsBoard]:
        """Return a board by its id, or ``None``.

        Args:
            board_id: Board identifier string.

        Returns:
            ``BbsBoard`` instance or ``None``.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            for b in self._boards:
                if b.id == board_id:
                    return BbsBoard.from_dict(b.to_dict())
        return None

    def get_board_for_channel(self, channel_idx: int) -> Optional[BbsBoard]:
        """Return the first board that includes *channel_idx*, or ``None``.

        Used by ``BbsCommandHandler`` to route incoming mesh commands.

        Args:
            channel_idx: MeshCore channel index.

        Returns:
            ``BbsBoard`` instance or ``None``.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            for b in self._boards:
                if channel_idx in b.channels:
                    return BbsBoard.from_dict(b.to_dict())
        return None

    # ------------------------------------------------------------------
    # Board management
    # ------------------------------------------------------------------

    def set_board(self, board: BbsBoard) -> None:
        """Insert or replace a board (matched by ``board.id``).

        Args:
            board: ``BbsBoard`` to persist.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            for i, b in enumerate(self._boards):
                if b.id == board.id:
                    self._boards[i] = BbsBoard.from_dict(board.to_dict())
                    self._save_unlocked()
                    debug_print(f"BBS config: updated board '{board.id}'")
                    return
            self._boards.append(BbsBoard.from_dict(board.to_dict()))
            self._save_unlocked()
            debug_print(f"BBS config: added board '{board.id}'")

    def delete_board(self, board_id: str) -> bool:
        """Remove a board by id.

        Args:
            board_id: Board identifier to remove.

        Returns:
            ``True`` if removed, ``False`` if not found.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            before = len(self._boards)
            self._boards = [b for b in self._boards if b.id != board_id]
            if len(self._boards) < before:
                self._save_unlocked()
                debug_print(f"BBS config: deleted board '{board_id}'")
                return True
        return False

    def board_id_exists(self, board_id: str) -> bool:
        """Check whether a board id is already in use.

        Args:
            board_id: Board identifier to check.

        Returns:
            ``True`` if a board with this id exists.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            return any(b.id == board_id for b in self._boards)

    # ------------------------------------------------------------------
    # Board API (v1.14.0 redesign)
    # ------------------------------------------------------------------

    def get_single_board(self) -> Optional[BbsBoard]:
        """Return the configured board, or ``None`` if none exists.

        Returns:
            The first ``BbsBoard`` in the store, or ``None``.
        """
        with self._lock:
            self._reload_if_changed_unlocked()
            if self._boards:
                return BbsBoard.from_dict(self._boards[0].to_dict())
        return None

    # Public API since v1.14.0; v1.26.0 only appends optional arguments,
    # so the argument count cannot be reduced without breaking callers.
    def configure_board(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        channel_indices: List[int],
        channel_names: Dict[int, str],
        categories: List[str],
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        regions: Optional[List[str]] = None,
        allowed_keys: Optional[List[str]] = None,
        default_retention_days: Optional[int] = None,
        category_retention_days: Optional[Dict[str, int]] = None,
    ) -> None:
        """Save the board configuration.

        Multiple channels can be assigned. DM-BBS access is controlled by the
        whitelist; senders are added only through the explicit ``!bbs``
        bootstrap on the linked channel.

        The board id is always ``'bbs_board'``.  The board name is built
        from the channel names in *channel_names*.

        Args:
            channel_indices: MeshCore channel indices to assign.
            channel_names:   Mapping ``idx → display name`` for labelling.
            categories:      Category tag list.
            retention_hours: Legacy retention in hours; only used to
                             derive ``default_retention_days`` when that
                             argument is ``None``.
            regions:         Optional region tags.
            allowed_keys:    Manual sender key whitelist seed.
            default_retention_days:  Retention in days for categories
                                     without an entry; ``0`` = keep
                                     forever.  ``None`` →
                                     :func:`hours_to_days` of
                                     *retention_hours*; invalid or
                                     negative → ``DEFAULT_RETENTION_DAYS``
                                     (v1.26.0).
            category_retention_days: Retention in days per category;
                                     ``0`` = keep forever.  Only
                                     entries for names in *categories*
                                     are kept; keys are stored upper
                                     case; invalid or negative entries
                                     get the default days.  ``None`` =
                                     no own entries (v1.26.0).
        """
        name = ", ".join(
            channel_names.get(i, f"Ch {i}") for i in sorted(channel_indices)
        ) or "BBS"

        # Preserve existing auto-learned keys unless caller supplies a new list
        existing = self.get_single_board()
        merged_keys = list(allowed_keys) if allowed_keys is not None else (
            existing.allowed_keys if existing else []
        )

        default_days = (
            hours_to_days(retention_hours) if default_retention_days is None
            else clean_retention_days(default_retention_days, DEFAULT_RETENTION_DAYS)
        )

        board = BbsBoard(
            id="bbs_board",
            name=name,
            channels=sorted(channel_indices),
            categories=list(categories),
            regions=list(regions) if regions else [],
            retention_hours=retention_hours,
            allowed_keys=merged_keys,
            default_retention_days=default_days,
            category_retention_days=category_days_for(
                categories, category_retention_days or {}, default_days,
            ),
        )
        with self._lock:
            self._reload_if_changed_unlocked()
            self._boards = [board]
            self._save_unlocked()
            debug_print(
                f"BBS config: board configured → channels={sorted(channel_indices)} "
                f"name='{name}'"
            )

    def clear_board(self) -> None:
        """Remove the configured board (disable BBS on this node)."""
        with self._lock:
            self._reload_if_changed_unlocked()
            self._boards = []
            self._save_unlocked()
            debug_print("BBS config: board cleared")

    def add_allowed_key(self, sender_key: str) -> bool:
        """Add *sender_key* to the board's allowed_keys whitelist.

        Called when the explicit ``!bbs`` bootstrap is received on the linked
        BBS channel. No-op if the key is already present
        or if no board is configured.

        Args:
            sender_key: Public key hex string of the sender.

        Returns:
            ``True`` if the key was newly added, ``False`` otherwise.
        """
        if not sender_key:
            return False
        with self._lock:
            self._reload_if_changed_unlocked()
            if not self._boards:
                return False
            board = self._boards[0]
            if sender_key in board.allowed_keys:
                return False
            board.allowed_keys.append(sender_key)
            self._save_unlocked()
            debug_print(f"BBS config: auto-whitelisted key {sender_key[:12]}…")
            return True
