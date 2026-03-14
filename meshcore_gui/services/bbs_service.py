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
    """Parses BBS commands arriving as DMs and delegates to :class:`BbsService`.

    Entry point
    ~~~~~~~~~~~
    All BBS commands arrive as **Direct Messages** addressed to the node's
    own public key.  :meth:`handle_dm` is the sole public entry point and is
    called directly from
    :class:`~meshcore_gui.ble.events.EventHandler.on_contact_msg`.
    It is completely independent of :class:`~meshcore_gui.services.bot.MeshBot`.

    Command syntax
    ~~~~~~~~~~~~~~
    Both styles are accepted:

    Short syntax::

        !p [region] <abbrev> <text>   — post a message
        !r [region] [abbrev]          — read (5 most recent)

    Full syntax::

        !bbs post [region] <category> <text>
        !bbs read [region] [category]
        !bbs help

    Category abbreviations are computed automatically as the shortest unique
    prefix per category within the configured list.  ``!r`` and ``!bbs help``
    always include the abbreviation table in the reply.

    Args:
        service:      Shared ``BbsService`` instance.
        config_store: ``BbsConfigStore`` instance for live board config.
    """

    READ_LIMIT: int = 5

    def __init__(self, service: BbsService, config_store) -> None:
        self._service = service
        self._config_store = config_store

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def handle_channel_msg(
        self,
        channel_idx: int,
        sender: str,
        sender_key: str,
        text: str,
    ) -> Optional[str]:
        """Handle a channel message on a configured BBS channel.

        Called from ``EventHandler.on_channel_msg`` **after** the message
        has been stored.  Two responsibilities:

        1. **Auto-whitelist**: every sender seen on a BBS channel gets their
           key added to ``allowed_keys`` so they can use DMs afterwards.
        2. **Bootstrap reply**: if the message starts with ``!``, reply on
           the channel so the sender knows the BBS is active and receives
           the abbreviation table.

        Args:
            channel_idx: MeshCore channel index the message arrived on.
            sender:      Display name of the sender.
            sender_key:  Public key of the sender (hex string).
            text:        Raw message text.

        Returns:
            Reply string to post on the channel, or ``None``.
        """
        board = self._config_store.get_single_board()
        if board is None:
            return None
        if channel_idx not in board.channels:
            return None

        # Auto-whitelist: register this sender so they can use DMs
        if sender_key:
            self._config_store.add_allowed_key(sender_key)

        # Bootstrap reply only for !-commands
        text = (text or "").strip()
        if not text.startswith("!"):
            return None

        first = text.split()[0].lower()
        channel_for_post = channel_idx

        if first == "!p":
            rest = text[len(first):].strip()
            return self._handle_post_short(board, channel_for_post, sender, sender_key, rest)

        if first == "!r":
            rest = text[len(first):].strip()
            return self._handle_read_short(board, rest)

        if first == "!bbs":
            parts = text.split(None, 2)
            sub = parts[1].lower() if len(parts) > 1 else ""
            rest = parts[2] if len(parts) > 2 else ""
            if sub == "post":
                return self._handle_post(board, channel_for_post, sender, sender_key, rest)
            if sub == "read":
                return self._handle_read(board, rest)
            if sub == "help" or not sub:
                return self._handle_help(board)
            return f"Unknown subcommand '{sub}'. " + self._handle_help(board)

        return None

    # ------------------------------------------------------------------

    def handle_dm(
        self,
        sender: str,
        sender_key: str,
        text: str,
    ) -> Optional[str]:
        """Parse a DM addressed to this node and return a reply (or ``None``).

        This is the **only** entry point for BBS commands.  It is called
        directly by ``EventHandler.on_contact_msg`` when a DM arrives whose
        text starts with ``!``.  The bot is never involved.

        The board is looked up from the single configured board via
        ``BbsConfigStore.get_single_board()``.

        Args:
            sender:     Display name of the DM sender.
            sender_key: Public key of the sender (hex string).
            text:       Raw DM text.

        Returns:
            Reply string to send back as DM, or ``None`` for silent drop.
        """
        text = (text or "").strip()
        first = text.split()[0].lower() if text else ""
        if not first.startswith("!"):
            return None

        board = self._config_store.get_single_board()
        if board is None:
            debug_print("BBS: no board configured, ignoring DM")
            return None

        # Whitelist check
        if board.allowed_keys and sender_key not in board.allowed_keys:
            debug_print(
                f"BBS: silently dropping DM from {sender} "
                f"(key not in whitelist for board '{board.id}')"
            )
            return None

        # Channel for storing posted messages
        channel_idx = board.channels[0] if board.channels else 0

        # Route by command prefix
        if first in ("!p",):
            rest = text[len(first):].strip()
            return self._handle_post_short(board, channel_idx, sender, sender_key, rest)

        if first in ("!r",):
            rest = text[len(first):].strip()
            return self._handle_read_short(board, rest)

        if first == "!bbs":
            parts = text.split(None, 2)
            sub = parts[1].lower() if len(parts) > 1 else ""
            rest = parts[2] if len(parts) > 2 else ""
            if sub == "post":
                return self._handle_post(board, channel_idx, sender, sender_key, rest)
            if sub == "read":
                return self._handle_read(board, rest)
            if sub == "help" or not sub:
                return self._handle_help(board)
            return f"Unknown subcommand '{sub}'. " + self._handle_help(board)

        # Unknown !-command starting with something else
        return None

    # ------------------------------------------------------------------
    # Abbreviation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_abbreviations(categories: List[str]) -> Dict[str, str]:
        """Compute shortest unique prefix for each category.

        Returns a dict mapping ``abbrev.upper()`` → ``category``.

        Examples::

            ["URGENT", "MEDICAL", "LOGISTICS", "STATUS", "GENERAL"]
            → {"U": "URGENT", "M": "MEDICAL", "L": "LOGISTICS",
               "S": "STATUS", "G": "GENERAL"}

            ["MEDICAL", "MISSING"]
            → {"ME": "MEDICAL", "MI": "MISSING"}
        """
        abbrevs: Dict[str, str] = {}
        cats_upper = [c.upper() for c in categories]
        for cat in cats_upper:
            for length in range(1, len(cat) + 1):
                prefix = cat[:length]
                # Unique if no other category starts with this prefix
                if sum(1 for c in cats_upper if c.startswith(prefix)) == 1:
                    abbrevs[prefix] = cat
                    break
        return abbrevs

    def _abbrev_table(self, categories: List[str]) -> str:
        """Return a compact abbreviation table string, e.g. ``U=URGENT M=MEDICAL``."""
        abbrevs = self.compute_abbreviations(categories)
        # abbrevs maps prefix → full name; invert for display
        inv = {v: k for k, v in abbrevs.items()}
        return " ".join(f"{inv[c]}={c}" for c in [cu.upper() for cu in categories] if cu.upper() in inv)

    def _resolve_category(self, token: str, categories: List[str]) -> Optional[str]:
        """Resolve *token* to a category via exact match or abbreviation.

        Returns the matching category string (original case from board
        config), or ``None`` if unresolvable.
        """
        token_up = token.upper()
        cats_upper = [c.upper() for c in categories]

        # Exact match first
        if token_up in cats_upper:
            return categories[cats_upper.index(token_up)]

        # Abbreviation match
        abbrevs = self.compute_abbreviations(categories)
        if token_up in abbrevs:
            matched = abbrevs[token_up]
            return categories[cats_upper.index(matched)]

        return None

    def _resolve_region(self, token: str, regions: List[str]) -> Optional[str]:
        """Resolve *token* to a region via exact (case-insensitive) match."""
        token_up = token.upper()
        regs_upper = [r.upper() for r in regions]
        if token_up in regs_upper:
            return regions[regs_upper.index(token_up)]
        return None

    # ------------------------------------------------------------------
    # Short syntax — !p and !r
    # ------------------------------------------------------------------

    def _handle_post_short(self, board, channel_idx, sender, sender_key, args):
        """Handle ``!p [region] <abbrev> <text>``."""
        regions = board.regions
        categories = board.categories

        # First token may be a region; split loosely to detect it
        first_tokens = args.split(None, 1) if args else []

        region = ""
        remainder = args  # everything after optional region

        if regions and first_tokens:
            resolved_r = self._resolve_region(first_tokens[0], regions)
            if resolved_r:
                region = resolved_r
                remainder = first_tokens[1] if len(first_tokens) > 1 else ""

        # Split remainder into exactly [category/abbrev, full_text]
        cat_and_text = remainder.split(None, 1) if remainder else []

        if len(cat_and_text) < 2:
            abbr = self._abbrev_table(categories)
            return f"Usage: !p [region] <cat> <text> | {abbr}"

        cat_token, text = cat_and_text[0], cat_and_text[1]

        category = self._resolve_category(cat_token, categories)
        if category is None:
            abbr = self._abbrev_table(categories)
            return f"Unknown category '{cat_token}'. Valid: {abbr}"

        msg = BbsMessage(
            channel=channel_idx,
            region=region, category=category,
            sender=sender, sender_key=sender_key, text=text,
        )
        self._service.post_message(msg)
        region_label = f" [{region}]" if region else ""
        return f"Posted [{category}]{region_label}: {text[:60]}"

    def _handle_read_short(self, board, args):
        """Handle ``!r [region] [abbrev]``.

        With no arguments returns 5 most recent messages across all
        categories and always includes the abbreviation table.
        """
        regions = board.regions
        categories = board.categories
        tokens = args.split() if args else []

        region = None
        category = None

        if tokens and regions:
            resolved_r = self._resolve_region(tokens[0], regions)
            if resolved_r:
                region = resolved_r
                tokens = tokens[1:]

        if tokens:
            category = self._resolve_category(tokens[0], categories)
            if category is None:
                abbr = self._abbrev_table(categories)
                return f"Unknown category '{tokens[0]}'. Valid: {abbr}"

        return self._format_messages(board, region, category, include_abbrevs=not args)

    # ------------------------------------------------------------------
    # Full syntax — !bbs post / read
    # ------------------------------------------------------------------

    def _handle_post(self, board, channel_idx, sender, sender_key, args):
        """Handle ``!bbs post [region] <category> <text>``."""
        regions = board.regions
        categories = board.categories

        # First token may be a region; split loosely to detect it
        first_tokens = args.split(None, 1) if args else []

        region = ""
        remainder = args  # everything after optional region

        if regions and first_tokens:
            resolved_r = self._resolve_region(first_tokens[0], regions)
            if resolved_r:
                region = resolved_r
                remainder = first_tokens[1] if len(first_tokens) > 1 else ""

        # Split remainder into exactly [category, full_text]
        cat_and_text = remainder.split(None, 1) if remainder else []

        if len(cat_and_text) < 2:
            abbr = self._abbrev_table(categories)
            region_hint = " [region]" if regions else ""
            return f"Usage: !bbs post{region_hint} <cat> <text> | {abbr}"

        cat_token, text = cat_and_text[0], cat_and_text[1]
        category = self._resolve_category(cat_token, categories)
        if category is None:
            abbr = self._abbrev_table(categories)
            return f"Unknown category '{cat_token}'. Valid: {abbr}"

        msg = BbsMessage(
            channel=channel_idx,
            region=region, category=category,
            sender=sender, sender_key=sender_key, text=text,
        )
        self._service.post_message(msg)
        region_label = f" [{region}]" if region else ""
        return f"Posted [{category}]{region_label}: {text[:60]}"

    def _handle_read(self, board, args):
        """Handle ``!bbs read [region] [category]``."""
        regions = board.regions
        categories = board.categories
        tokens = args.split() if args else []

        region = None
        category = None

        if tokens and regions:
            resolved_r = self._resolve_region(tokens[0], regions)
            if resolved_r:
                region = resolved_r
                tokens = tokens[1:]

        if tokens:
            category = self._resolve_category(tokens[0], categories)
            if category is None:
                abbr = self._abbrev_table(categories)
                return f"Unknown category '{tokens[0]}'. Valid: {abbr}"

        return self._format_messages(board, region, category, include_abbrevs=False)

    # ------------------------------------------------------------------
    # Shared message formatter
    # ------------------------------------------------------------------

    def _format_messages(self, board, region, category, include_abbrevs: bool) -> str:
        messages = self._service.get_messages(
            board.channels, region=region, category=category, limit=self.READ_LIMIT,
        )
        lines = []
        if include_abbrevs:
            lines.append(self._handle_help(board))
        if not messages:
            lines.append("BBS: no messages found.")
            return "\n".join(lines)
        for m in messages:
            ts = m.timestamp[:16].replace("T", " ")
            region_label = f"[{m.region}] " if m.region else ""
            lines.append(f"{ts} {m.sender} [{m.category}] {region_label}{m.text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _handle_help(self, board) -> str:
        abbr = self._abbrev_table(board.categories)
        header = f"BBS [{board.name}] | !p [cat] [text] | !r [cat]"
        if board.regions:
            regs = ", ".join(board.regions)
            return f"{header} | Regions: {regs} | {abbr}"
        return f"{header} | {abbr}"
