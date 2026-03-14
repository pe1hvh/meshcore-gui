"""
Offline Bulletin Board System (BBS) service for MeshCore GUI.

Stores BBS messages in a local SQLite database.  Messages are keyed by
their originating MeshCore channel index.  A **board** (see
:class:`~meshcore_gui.services.bbs_config_store.BbsBoard`) maps one or
more channel indices to a single bulletin board, so queries are always
issued as ``WHERE channel IN (...)``.

Architecture
~~~~~~~~~~~~
- ``BbsService``        -- persistence layer (SQLite, retention, queries).
- ``BbsCommandHandler`` -- parses incoming ``!bbs`` text commands and
                           delegates to ``BbsService``.  Returns reply text.

Thread safety
~~~~~~~~~~~~~
SQLite WAL-mode + busy_timeout=3 s: safe for concurrent access by
multiple application instances (e.g. 800 MHz + 433 MHz on one Pi).

Storage
~~~~~~~
``~/.meshcore-gui/bbs/bbs_messages.db``
``~/.meshcore-gui/bbs/bbs_config.json``  (via BbsConfigStore)
"""

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

BBS_DIR = Path.home() / ".meshcore-gui" / "bbs"
BBS_DB_PATH = BBS_DIR / "bbs_messages.db"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BbsMessage:
    """A single BBS message.

    Attributes:
        id:           Database row id (``None`` before insert).
        channel:      MeshCore channel index the message arrived on.
        region:       Region tag (empty string when board has no regions).
        category:     Category tag.
        sender:       Display name of the sender.
        sender_key:   Public key of the sender (hex string).
        text:         Message body.
        timestamp:    UTC ISO-8601 timestamp string.
    """

    channel: int
    region: str
    category: str
    sender: str
    sender_key: str
    text: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BbsService:
    """SQLite-backed BBS storage service.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path = BBS_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create the database directory and schema if not present."""
        BBS_DIR.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bbs_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel     INTEGER NOT NULL,
                    region      TEXT    NOT NULL DEFAULT '',
                    category    TEXT    NOT NULL,
                    sender      TEXT    NOT NULL,
                    sender_key  TEXT    NOT NULL DEFAULT '',
                    text        TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel ON bbs_messages(channel)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON bbs_messages(timestamp)"
            )
            conn.commit()
        debug_print(f"BBS: database ready at {self._db_path}")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), check_same_thread=False)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def post_message(self, msg: BbsMessage) -> int:
        """Insert a BBS message and return its row id.

        Args:
            msg: ``BbsMessage`` dataclass to persist.

        Returns:
            Assigned ``rowid`` (also set on ``msg.id``).
        """
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """INSERT INTO bbs_messages
                       (channel, region, category, sender, sender_key, text, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (msg.channel, msg.region, msg.category,
                     msg.sender, msg.sender_key, msg.text, msg.timestamp),
                )
                conn.commit()
                msg.id = cur.lastrowid
                debug_print(
                    f"BBS: posted id={msg.id} ch={msg.channel} "
                    f"cat={msg.category} sender={msg.sender}"
                )
                return msg.id

    # ------------------------------------------------------------------
    # Read  (channels is a list to support multi-channel boards)
    # ------------------------------------------------------------------

    def get_messages(
        self,
        channels: List[int],
        region: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[BbsMessage]:
        """Return the *limit* most recent messages for a set of channels.

        Args:
            channels: MeshCore channel indices to query (board's channel list).
            region:   Optional region filter.
            category: Optional category filter.
            limit:    Maximum number of messages to return.

        Returns:
            List of ``BbsMessage`` objects, newest first.
        """
        if not channels:
            return []
        placeholders = ",".join("?" * len(channels))
        query = (
            f"SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            f"FROM bbs_messages WHERE channel IN ({placeholders})"
        )
        params: list = list(channels)
        if region:
            query += " AND region = ?"
            params.append(region)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def get_all_messages(
        self,
        channels: List[int],
        region: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[BbsMessage]:
        """Return all messages for a set of channels (oldest first).

        Args:
            channels: MeshCore channel indices to query.
            region:   Optional region filter.
            category: Optional category filter.

        Returns:
            List of ``BbsMessage`` objects, oldest first.
        """
        if not channels:
            return []
        placeholders = ",".join("?" * len(channels))
        query = (
            f"SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            f"FROM bbs_messages WHERE channel IN ({placeholders})"
        )
        params: list = list(channels)
        if region:
            query += " AND region = ?"
            params.append(region)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY timestamp ASC"

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [self._row_to_msg(r) for r in rows]

    @staticmethod
    def _row_to_msg(row: tuple) -> BbsMessage:
        return BbsMessage(
            id=row[0], channel=row[1], region=row[2], category=row[3],
            sender=row[4], sender_key=row[5], text=row[6], timestamp=row[7],
        )

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def purge_expired(self, channels: List[int], retention_hours: int) -> int:
        """Delete messages older than *retention_hours* for a set of channels.

        Args:
            channels:        MeshCore channel indices to purge.
            retention_hours: Messages older than this are deleted.

        Returns:
            Number of rows deleted.
        """
        if not channels:
            return 0
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        ).isoformat()
        placeholders = ",".join("?" * len(channels))
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    f"DELETE FROM bbs_messages WHERE channel IN ({placeholders}) AND timestamp < ?",
                    list(channels) + [cutoff],
                )
                conn.commit()
                deleted = cur.rowcount
                if deleted:
                    debug_print(
                        f"BBS: purged {deleted} expired messages from ch={channels}"
                    )
                return deleted

    def purge_all_expired(self, boards) -> None:
        """Run retention cleanup for all boards.

        Args:
            boards: Iterable of ``BbsBoard`` instances.
        """
        for board in boards:
            self.purge_expired(board.channels, board.retention_hours)


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------

class BbsCommandHandler:
    """Parses ``!bbs`` mesh commands and delegates to :class:`BbsService`.

    Looks up the board for the incoming channel via ``BbsConfigStore``
    so that a single board spanning multiple channels handles commands
    from all of them.

    Args:
        service:      Shared ``BbsService`` instance.
        config_store: ``BbsConfigStore`` instance for live board config.
    """

    READ_LIMIT: int = 5

    def __init__(self, service: BbsService, config_store) -> None:
        self._service = service
        self._config_store = config_store

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle(
        self,
        channel_idx: int,
        sender: str,
        sender_key: str,
        text: str,
    ) -> Optional[str]:
        """Parse an incoming message and return a reply string (or ``None``).

        Args:
            channel_idx: MeshCore channel index the message arrived on.
            sender:      Display name of the sender.
            sender_key:  Public key of the sender (hex string).
            text:        Raw message text.

        Returns:
            Reply string, or ``None`` if no reply should be sent.
        """
        text = (text or "").strip()
        if not text.lower().startswith("!bbs"):
            return None

        board = self._config_store.get_board_for_channel(channel_idx)
        if board is None:
            return None

        # Whitelist check
        if board.allowed_keys and sender_key not in board.allowed_keys:
            debug_print(
                f"BBS: silently dropping msg from {sender} "
                f"(key not in whitelist for board '{board.id}')"
            )
            return None

        parts = text.split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""
        return self._dispatch(board, channel_idx, sender, sender_key, args)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, board, channel_idx, sender, sender_key, args):
        sub = args.split(None, 1)[0].lower() if args else ""
        rest = args.split(None, 1)[1] if len(args.split(None, 1)) > 1 else ""
        if sub == "post":
            return self._handle_post(board, channel_idx, sender, sender_key, rest)
        if sub == "read":
            return self._handle_read(board, rest)
        if sub == "help" or not sub:
            return self._handle_help(board)
        return f"Unknown command '{sub}'. {self._handle_help(board)}"

    # ------------------------------------------------------------------
    # post
    # ------------------------------------------------------------------

    def _handle_post(self, board, channel_idx, sender, sender_key, args):
        regions = board.regions
        categories = board.categories
        tokens = args.split(None, 2) if args else []

        if regions:
            if len(tokens) < 3:
                return (
                    f"Usage: !bbs post [region] [category] [text] | "
                    f"Regions: {', '.join(regions)} | "
                    f"Categories: {', '.join(categories)}"
                )
            region, category, text = tokens[0], tokens[1], tokens[2]
            valid_r = [r.upper() for r in regions]
            if region.upper() not in valid_r:
                return f"Invalid region '{region}'. Valid: {', '.join(regions)}"
            region = regions[valid_r.index(region.upper())]
            valid_c = [c.upper() for c in categories]
            if category.upper() not in valid_c:
                return f"Invalid category '{category}'. Valid: {', '.join(categories)}"
            category = categories[valid_c.index(category.upper())]
        else:
            if len(tokens) < 2:
                return (
                    f"Usage: !bbs post [category] [text] | "
                    f"Categories: {', '.join(categories)}"
                )
            region = ""
            category, text = tokens[0], tokens[1]
            valid_c = [c.upper() for c in categories]
            if category.upper() not in valid_c:
                return f"Invalid category '{category}'. Valid: {', '.join(categories)}"
            category = categories[valid_c.index(category.upper())]

        msg = BbsMessage(
            channel=channel_idx,
            region=region, category=category,
            sender=sender, sender_key=sender_key, text=text,
        )
        self._service.post_message(msg)
        region_label = f" [{region}]" if region else ""
        return f"Posted [{category}]{region_label}: {text[:60]}"

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def _handle_read(self, board, args):
        regions = board.regions
        categories = board.categories
        tokens = args.split() if args else []
        region = None
        category = None

        if regions:
            valid_r = [r.upper() for r in regions]
            valid_c = [c.upper() for c in categories]
            if tokens:
                if tokens[0].upper() in valid_r:
                    region = regions[valid_r.index(tokens[0].upper())]
                    if len(tokens) >= 2:
                        if tokens[1].upper() in valid_c:
                            category = categories[valid_c.index(tokens[1].upper())]
                        else:
                            return f"Invalid category '{tokens[1]}'. Valid: {', '.join(categories)}"
                else:
                    return f"Invalid region '{tokens[0]}'. Valid: {', '.join(regions)}"
        else:
            valid_c = [c.upper() for c in categories]
            if tokens:
                if tokens[0].upper() in valid_c:
                    category = categories[valid_c.index(tokens[0].upper())]
                else:
                    return f"Invalid category '{tokens[0]}'. Valid: {', '.join(categories)}"

        messages = self._service.get_messages(
            board.channels, region=region, category=category, limit=self.READ_LIMIT,
        )
        if not messages:
            return "BBS: no messages found."
        lines = []
        for m in messages:
            ts = m.timestamp[:16].replace("T", " ")
            region_label = f"[{m.region}] " if m.region else ""
            lines.append(f"{ts} {m.sender} [{m.category}] {region_label}{m.text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # help
    # ------------------------------------------------------------------

    def _handle_help(self, board) -> str:
        cats = ", ".join(board.categories)
        if board.regions:
            regs = ", ".join(board.regions)
            return (
                f"BBS [{board.name}] | "
                f"!bbs post [region] [cat] [text] | "
                f"!bbs read [region] [cat] | "
                f"Regions: {regs} | Categories: {cats}"
            )
        return (
            f"BBS [{board.name}] | "
            f"!bbs post [cat] [text] | "
            f"!bbs read [cat] | "
            f"Categories: {cats}"
        )
