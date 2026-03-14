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
"""

import json
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


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BbsBoard:
    """A BBS board grouping one or more MeshCore channels.

    Attributes:
        id:              Unique identifier (slug, e.g. ``'noodnet_zwolle'``).
        name:            Human-readable board name.
        channels:        List of MeshCore channel indices assigned to this board.
        categories:      Valid category tags for this board.
        regions:         Optional region tags; empty = no region filtering.
        retention_hours: Message retention period in hours.
        allowed_keys:    Sender public key whitelist (empty = all allowed).
    """

    id: str
    name: str
    channels: List[int] = field(default_factory=list)
    categories: List[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    regions: List[str] = field(default_factory=list)
    retention_hours: int = DEFAULT_RETENTION_HOURS
    allowed_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Serialise to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "channels": list(self.channels),
            "categories": list(self.categories),
            "regions": list(self.regions),
            "retention_hours": self.retention_hours,
            "allowed_keys": list(self.allowed_keys),
        }

    @staticmethod
    def from_dict(d: Dict) -> "BbsBoard":
        """Deserialise from a config dict."""
        return BbsBoard(
            id=d.get("id", ""),
            name=d.get("name", ""),
            channels=list(d.get("channels", [])),
            categories=list(d.get("categories", DEFAULT_CATEGORIES)),
            regions=list(d.get("regions", [])),
            retention_hours=int(d.get("retention_hours", DEFAULT_RETENTION_HOURS)),
            allowed_keys=list(d.get("allowed_keys", [])),
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
        self._load()

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
            return list(self._boards)

    def get_board(self, board_id: str) -> Optional[BbsBoard]:
        """Return a board by its id, or ``None``.

        Args:
            board_id: Board identifier string.

        Returns:
            ``BbsBoard`` instance or ``None``.
        """
        with self._lock:
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
            if self._boards:
                return BbsBoard.from_dict(self._boards[0].to_dict())
        return None

    def configure_board(
        self,
        channel_indices: List[int],
        channel_names: Dict[int, str],
        categories: List[str],
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        regions: Optional[List[str]] = None,
        allowed_keys: Optional[List[str]] = None,
    ) -> None:
        """Save the board configuration.

        Multiple channels can be assigned.  Every sender seen on any of
        these channels is automatically eligible for DM access (the
        worker calls :meth:`add_allowed_key` when it sees them).

        The board id is always ``'bbs_board'``.  The board name is built
        from the channel names in *channel_names*.

        Args:
            channel_indices: MeshCore channel indices to assign.
            channel_names:   Mapping ``idx → display name`` for labelling.
            categories:      Category tag list.
            retention_hours: Message retention period in hours.
            regions:         Optional region tags.
            allowed_keys:    Manual sender key whitelist seed (auto-learned
                             keys are added via :meth:`add_allowed_key`).
        """
        name = ", ".join(
            channel_names.get(i, f"Ch {i}") for i in sorted(channel_indices)
        ) or "BBS"

        # Preserve existing auto-learned keys unless caller supplies a new list
        existing = self.get_single_board()
        merged_keys = list(allowed_keys) if allowed_keys is not None else (
            existing.allowed_keys if existing else []
        )

        board = BbsBoard(
            id="bbs_board",
            name=name,
            channels=sorted(channel_indices),
            categories=list(categories),
            regions=list(regions) if regions else [],
            retention_hours=retention_hours,
            allowed_keys=merged_keys,
        )
        with self._lock:
            self._boards = [board]
            self._save_unlocked()
            debug_print(
                f"BBS config: board configured → channels={sorted(channel_indices)} "
                f"name='{name}'"
            )

    def clear_board(self) -> None:
        """Remove the configured board (disable BBS on this node)."""
        with self._lock:
            self._boards = []
            self._save_unlocked()
            debug_print("BBS config: board cleared")

    def add_allowed_key(self, sender_key: str) -> bool:
        """Add *sender_key* to the board's allowed_keys whitelist.

        Called automatically by the worker whenever a sender is seen on
        a configured BBS channel.  No-op if the key is already present
        or if no board is configured.

        Args:
            sender_key: Public key hex string of the sender.

        Returns:
            ``True`` if the key was newly added, ``False`` otherwise.
        """
        if not sender_key:
            return False
        with self._lock:
            if not self._boards:
                return False
            board = self._boards[0]
            if sender_key in board.allowed_keys:
                return False
            board.allowed_keys.append(sender_key)
            self._save_unlocked()
            debug_print(f"BBS config: auto-whitelisted key {sender_key[:12]}…")
            return True
