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

Tables in ``bbs_messages.db``:

1. ``bbs_messages``: the messages (unchanged since v1.14.0).
2. ``bbs_meta`` (v1.26.0): key/value pairs; ``epoch`` identifies this
   database instance for the ``!x`` sync.
3. ``bbs_deleted`` (v1.26.0): one row per message removed by the
   operator (``delete_message``), so a syncing client can remove it too.
   Rows are never purged.  Messages removed by the retention purge are
   not recorded: a client applies the same retention itself.

Sync protocol ``!x`` (v1.26.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Request (DM; same whitelist check as the other DM commands, so any
sender when ``allowed_keys`` is empty): ``!x [since_id] [since_del]``.
Both arguments are optional whole numbers from ``0`` to :data:`SYNC_MAX_ID`
written with ASCII digits (default ``0``):
``since_id`` is the highest message id the client has, ``since_del``
the highest deletion sequence number it has processed.  Reply lines, each
at most :data:`SYNC_LINE_MAX_BYTES` UTF-8 bytes:

    X1|<epoch>|<n>|<more>|<del_seq>|<n_del>|<lines>
    R|*:<days>,<abbr>:<days>,...
    <id>|<unix_ts>|<abbr>|<region>|<sender>|<text>
    +<id>|<continuation>
    -<id>,<id>,...

- ``X1``: header, protocol version 1.  ``n`` = records in this reply,
  ``more`` = ``1`` when records with a higher id remain, ``del_seq`` =
  highest deletion sequence number on the server, ``n_del`` = number of
  ids in the ``-`` lines of this reply, ``lines`` = number of lines after
  the header.  The DM sender may spread a reply over several DMs; a
  client knows the reply is complete when it has ``lines`` lines.
- ``R``: retention in days per category abbreviation (as in ``!h``),
  ``*`` = categories not listed in the ``R`` lines (no longer
  configured); ``0`` = keep forever.  More ``R``
  lines follow when one line would exceed the byte limit.
- record: ascending id (= order of arrival), at most
  ``BbsCommandHandler.SYNC_LIMIT`` per reply.  ``abbr`` is the upper-case
  full category name when the category is no longer configured.  ``|``
  in sender and region is replaced by ``/``; sender, region and text are
  split into lines (``str.splitlines``) and joined with single spaces, so
  a trailing line break disappears.  ``text`` may contain ``|``: a client
  splits a record only on its first five ``|``, after appending its ``+``
  lines.
- ``+``: continuation of the record with that id, appended without
  separator, when the record is longer than the byte limit.  Whitespace
  at a cut starts the next ``+`` line, so the DM sender's per-line strip
  does not lose it (exceptions: see ``_record_lines``).
- ``-``: ids of all messages deleted by the operator since
  ``since_del``, on any channel and without a limit per reply
  (``SYNC_LIMIT`` does not apply), so this part can take several DMs.
"""

# The service and its command handler share this module since v1.14.0;
# the v1.26.0 sync documentation pushed it past 1000 lines.  Splitting
# the module is a refactor outside the scope of the sync feature.
# pylint: disable=too-many-lines

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from meshcore_gui.config import debug_print
from meshcore_gui.services.bbs_config_store import BbsBoard

BBS_DIR = Path.home() / ".meshcore-gui" / "bbs"
BBS_DB_PATH = BBS_DIR / "bbs_messages.db"

SYNC_LINE_MAX_BYTES: int = 160
"""Maximum UTF-8 bytes of one ``!x`` reply line: the firmware DM text
limit ``MAX_TEXT_LEN`` (same value as ``CommandHandler.MAX_DM_TEXT_BYTES``).
The DM sender splits replies on line boundaries, so a line within this
limit is never cut."""

SYNC_MAX_ID: int = 2 ** 63 - 1
"""Largest ``!x`` argument accepted: the SQLite INTEGER maximum.  Larger
values would raise ``OverflowError`` in the query."""

SYNC_HEADER_TAG: str = "X1"
"""First field of the ``!x`` reply header: sync protocol version 1."""


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
        """Create the database directory and schema if not present.

        Also stores the sync ``epoch`` (Unix seconds of the first start
        with v1.26.0 or later) in ``bbs_meta`` when it is not there yet;
        an existing epoch is never changed.
        """
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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bbs_meta ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO bbs_meta (key, value) VALUES ('epoch', ?)",
                (str(int(time.time())),),
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bbs_deleted ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "msg_id INTEGER NOT NULL, deleted_at TEXT NOT NULL)"
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

    def delete_message(self, msg_id: int) -> bool:
        """Delete a single BBS message by row id.

        Only called from the GUI (``BbsPanel``).  There is deliberately
        no mesh command (``!``-DM or channel text) that reaches this
        method, so messages can only be removed by the operator of this
        meshcore-gui instance.

        A deleted message is recorded in ``bbs_deleted`` in the same
        transaction (v1.26.0), so ``!x`` can report it to clients.

        Args:
            msg_id: Database row id.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM bbs_messages WHERE id = ?", (msg_id,)
                )
                deleted = cur.rowcount > 0
                if deleted:
                    conn.execute(
                        "INSERT INTO bbs_deleted (msg_id, deleted_at) VALUES (?, ?)",
                        (msg_id, datetime.now(timezone.utc).isoformat()),
                    )
                conn.commit()
        debug_print(f"BBS: delete id={msg_id} → {'deleted' if deleted else 'not found'}")
        return deleted

    # ------------------------------------------------------------------
    # Read  (channels is a list to support multi-channel boards)
    # ------------------------------------------------------------------

    def get_messages(
        self,
        channels: List[int],
        region: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
        offset: int = 0,
    ) -> List[BbsMessage]:
        """Return messages for a set of channels, newest first.

        Args:
            channels: MeshCore channel indices to query (board's channel list).
            region:   Optional region filter (case-insensitive).
            category: Optional category filter (case-insensitive).
            limit:    Maximum number of messages to return.
            offset:   Number of messages to skip (for pagination).

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
            query += " AND region = ? COLLATE NOCASE"
            params.append(region)
        if category:
            query += " AND category = ? COLLATE NOCASE"
            params.append(category)
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def search_messages(
        self,
        channels: List[int],
        text_query: str,
        region: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[BbsMessage]:
        """Full-text search across message bodies (case-insensitive substring).

        Args:
            channels:   MeshCore channel indices to query.
            text_query: Substring to search for (case-insensitive).
            region:     Optional region filter.
            category:   Optional category filter.

        Returns:
            All matching ``BbsMessage`` objects, newest first.
        """
        if not channels or not text_query:
            return []
        placeholders = ",".join("?" * len(channels))
        query = (
            f"SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            f"FROM bbs_messages WHERE channel IN ({placeholders})"
            f" AND text LIKE ? COLLATE NOCASE"
        )
        params: list = list(channels) + [f"%{text_query}%"]
        if region:
            query += " AND region = ? COLLATE NOCASE"
            params.append(region)
        if category:
            query += " AND category = ? COLLATE NOCASE"
            params.append(category)
        query += " ORDER BY timestamp DESC"

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

    # ------------------------------------------------------------------
    # Sync (v1.26.0)
    # ------------------------------------------------------------------

    def get_epoch(self) -> str:
        """Return the sync epoch of this database.

        Returns:
            Unix seconds as decimal string, stored in ``bbs_meta`` on the
            first start with v1.26.0 or later.  A new database (file
            removed) gets a new epoch, which tells clients that ids
            start again.  The resolution is one second, so a database
            re-created within the same second gets the same epoch.
            ``"0"`` when no epoch row exists.
        """
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM bbs_meta WHERE key = 'epoch'"
                ).fetchone()
        return row[0] if row else "0"

    def get_messages_since(
        self, channels: List[int], since_id: int, limit: int,
    ) -> List[BbsMessage]:
        """Return messages with an id above *since_id*, lowest id first.

        Args:
            channels: MeshCore channel indices of the board.
            since_id: Highest id the client already has; ``0`` = all.
            limit:    Maximum number of messages returned.

        Returns:
            Up to *limit* ``BbsMessage`` objects ordered by id ascending;
            empty when *channels* is empty.
        """
        if not channels:
            return []
        placeholders = ",".join("?" * len(channels))
        query = (
            f"SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            f"FROM bbs_messages WHERE channel IN ({placeholders}) AND id > ? "
            f"ORDER BY id ASC LIMIT ?"
        )
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    query, list(channels) + [since_id, limit]
                ).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def get_deletions_since(self, since_seq: int) -> Tuple[List[int], int]:
        """Return operator deletions after *since_seq*.

        Args:
            since_seq: Highest deletion sequence number the client has
                       processed; ``0`` = all.

        Returns:
            Tuple of (message ids deleted after *since_seq*, in deletion
            order; highest sequence number in ``bbs_deleted``, ``0`` when
            nothing was ever deleted).
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT msg_id FROM bbs_deleted WHERE seq > ? ORDER BY seq",
                    (since_seq,),
                ).fetchall()
                last = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM bbs_deleted"
                ).fetchone()[0]
        return [r[0] for r in rows], int(last)

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

    def purge_board(self, board: BbsBoard) -> int:
        """Delete expired messages of *board*, per category (v1.26.0).

        Each configured category uses ``board.retention_days_for()``;
        messages in a category that is no longer configured use
        ``board.default_retention_days``.  A period of ``0`` days keeps
        the messages forever.  Category names are compared
        case-insensitively; ages are measured from the stored
        ``timestamp``.  Deletions are not recorded in ``bbs_deleted``.

        Args:
            board: ``BbsBoard`` whose channels and retention apply.

        Returns:
            Number of rows deleted.
        """
        if not board.channels:
            return 0
        now = datetime.now(timezone.utc)
        ch_marks = ",".join("?" * len(board.channels))
        configured = [c.upper() for c in board.categories]
        deleted = 0
        with self._lock:
            with self._connect() as conn:
                for cat in configured:
                    days = board.retention_days_for(cat)
                    if days == 0:
                        continue
                    cutoff = (now - timedelta(days=days)).isoformat()
                    deleted += conn.execute(
                        f"DELETE FROM bbs_messages WHERE channel IN ({ch_marks}) "
                        f"AND UPPER(category) = ? AND timestamp < ?",
                        list(board.channels) + [cat, cutoff],
                    ).rowcount
                if board.default_retention_days > 0:
                    cutoff = (
                        now - timedelta(days=board.default_retention_days)
                    ).isoformat()
                    query = (
                        f"DELETE FROM bbs_messages WHERE channel IN ({ch_marks}) "
                        f"AND timestamp < ?"
                    )
                    params = list(board.channels) + [cutoff]
                    if configured:
                        cat_marks = ",".join("?" * len(configured))
                        query += f" AND UPPER(category) NOT IN ({cat_marks})"
                        params += configured
                    deleted += conn.execute(query, params).rowcount
                conn.commit()
        if deleted:
            debug_print(
                f"BBS: purged {deleted} expired messages from ch={board.channels}"
            )
        return deleted

    def purge_all_expired(self, boards) -> None:
        """Run retention cleanup for all boards.

        Since v1.26.0 retention is per category (:meth:`purge_board`);
        :meth:`purge_expired` is kept for callers with a single period.

        Args:
            boards: Iterable of ``BbsBoard`` instances.
        """
        for board in boards:
            self.purge_board(board)


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

    Machine syntax (v1.26.0), see the module docstring::

        !x [since_id] [since_del]     — sync: messages, retention, deletions

    Category abbreviations are computed automatically as the shortest unique
    prefix per category within the configured list.  ``!r`` and ``!bbs help``
    always include the abbreviation table in the reply.

    Args:
        service:      Shared ``BbsService`` instance.
        config_store: ``BbsConfigStore`` instance for live board config.
    """

    READ_LIMIT: int = 5

    SYNC_LIMIT: int = 10
    """Maximum number of message records in one ``!x`` reply (v1.26.0)."""

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
        has been stored.

        Design rule:
        - only ``!bbs`` is handled on the linked BBS channel;
        - it whitelists the sender public key for later DM-BBS use;
        - help/read/post/search commands are DM-only.

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

        text = (text or "").strip()
        if text.lower() != "!bbs":
            return None
        if not sender_key:
            debug_print("BBS: !bbs ignored on channel because sender key is empty")
            # The sender is not in this node's contact list: a channel
            # message carries no public key, only an advert does.
            return "BBS: unknown sender. Send a flood advert first, then !bbs again."
        added = self._config_store.add_allowed_key(sender_key)
        if added:
            return "Add to BBS OK. Use !h in DM-BBS for help."
        return "Already on BBS whitelist. Use !h in DM-BBS for help."

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

        # Whitelist check (accept full-key/prefix matches in both directions)
        if board.allowed_keys:
            sender_key_up = (sender_key or "").upper()
            allowed = False
            for key in board.allowed_keys:
                key_up = (key or "").upper()
                if sender_key_up and key_up and (
                    sender_key_up == key_up
                    or sender_key_up.startswith(key_up)
                    or key_up.startswith(sender_key_up)
                ):
                    allowed = True
                    break
            if not allowed:
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

        if first in ("!s",):
            rest = text[len(first):].strip()
            return self._handle_search(board, rest)

        if first in ("!help", "!h"):
            return self._handle_help(board)

        if first == "!x":
            rest = text[len(first):].strip()
            return self._handle_sync(board, rest)

        if first == "!bbs":
            parts = text.split(None, 2)
            sub = parts[1].lower() if len(parts) > 1 else ""
            rest = parts[2] if len(parts) > 2 else ""
            if sub == "post":
                return self._handle_post(board, channel_idx, sender, sender_key, rest)
            if sub == "read":
                return self._handle_read(board, rest)
            if sub == "help":
                return self._handle_help(board)
            return "Use !bbs on the linked channel for whitelist bootstrap."

        # Unknown !-command
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
        cats_upper = [c.upper() for c in categories]
        return " ".join(f"{inv[c]}={c}" for c in cats_upper if c in inv)

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
        return f"Posted #{msg.id} [{category}]{region_label}: {text[:60]}"

    def _handle_read_short(self, board, args):
        """Handle ``!r [region] [abbrev] [from-to]``.

        Range syntax: ``!r U 6-10`` returns messages 6 to 10 (1-indexed,
        newest first).  Without a range the default is 1-5 (five most recent).
        Bare ``!r`` returns the most recent messages across all categories.
        """
        regions = board.regions
        categories = board.categories
        tokens = args.split() if args else []

        region = None
        category = None
        offset = 0
        limit = self.READ_LIMIT

        # Optional region (only if board has regions configured)
        if tokens and regions:
            resolved_r = self._resolve_region(tokens[0], regions)
            if resolved_r:
                region = resolved_r
                tokens = tokens[1:]

        # Optional category / abbreviation
        if tokens:
            # Check if token is a range (e.g. "6-10") rather than a category
            if not self._is_range(tokens[0]):
                category = self._resolve_category(tokens[0], categories)
                if category is None:
                    abbr = self._abbrev_table(categories)
                    return f"Unknown category '{tokens[0]}'. Valid: {abbr}"
                tokens = tokens[1:]

        # Optional range
        if tokens and self._is_range(tokens[0]):
            offset, limit = self._parse_range(tokens[0])
            if offset is None:
                return f"Invalid range '{tokens[0]}'. Use e.g. 6-10 or 1-20."

        return self._format_messages(
            board, region, category,
            offset=offset, limit=limit,
            include_abbrevs=False,
        )

    def _handle_search(self, board, args):
        """Handle ``!s [region] <abbrev> <query>`` — full-text search.

        Searches all messages in the given category for the query string
        (case-insensitive substring match) and returns all matches.

        Usage: ``!s U zoektekst``  or  ``!s Zwolle U zoektekst``
        """
        regions = board.regions
        categories = board.categories

        first_tokens = args.split(None, 1) if args else []

        region = None
        remainder = args

        # Optional region
        if regions and first_tokens:
            resolved_r = self._resolve_region(first_tokens[0], regions)
            if resolved_r:
                region = resolved_r
                remainder = first_tokens[1] if len(first_tokens) > 1 else ""

        # Category + query
        cat_and_query = remainder.split(None, 1) if remainder else []
        if len(cat_and_query) < 2:
            abbr = self._abbrev_table(categories)
            return f"Usage: !s [region] <cat> <query> | {abbr}"

        cat_token, query = cat_and_query[0], cat_and_query[1].strip()
        category = self._resolve_category(cat_token, categories)
        if category is None:
            abbr = self._abbrev_table(categories)
            return f"Unknown category '{cat_token}'. Valid: {abbr}"

        messages = self._service.search_messages(
            board.channels,
            text_query=query,
            region=region,
            category=category,
        )
        if not messages:
            return f"BBS: no results for '{query}' in [{category}]."
        lines = [f"Search [{category}] '{query}': {len(messages)} result(s)"]
        for m in messages:
            ts = m.timestamp[:16].replace("T", " ")
            region_label = f"[{m.region}] " if m.region else ""
            lines.append(f"{ts} {m.sender} {region_label}{m.text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Range helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_range(token: str) -> bool:
        """Return True if *token* looks like a range (e.g. ``6-10``)."""
        parts = token.split("-")
        if len(parts) != 2:
            return False
        return parts[0].isdigit() and parts[1].isdigit()

    @staticmethod
    def _parse_range(token: str):
        """Parse ``'from-to'`` into ``(offset, limit)``.

        ``'1-5'`` → offset=0, limit=5 (messages 1 to 5, 1-indexed newest first).
        ``'6-10'`` → offset=5, limit=5.

        Returns ``(None, None)`` on invalid input.
        """
        try:
            parts = token.split("-")
            start = int(parts[0])
            end = int(parts[1])
            if start < 1 or end < start:
                return None, None
            return start - 1, end - start + 1
        except (ValueError, IndexError):
            return None, None

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
        return f"Posted #{msg.id} [{category}]{region_label}: {text[:60]}"

    def _handle_read(self, board, args):
        """Handle ``!bbs read [region] [category] [from-to]``."""
        regions = board.regions
        categories = board.categories
        tokens = args.split() if args else []

        region = None
        category = None
        offset = 0
        limit = self.READ_LIMIT

        if tokens and regions:
            resolved_r = self._resolve_region(tokens[0], regions)
            if resolved_r:
                region = resolved_r
                tokens = tokens[1:]

        if tokens and not self._is_range(tokens[0]):
            category = self._resolve_category(tokens[0], categories)
            if category is None:
                abbr = self._abbrev_table(categories)
                return f"Unknown category '{tokens[0]}'. Valid: {abbr}"
            tokens = tokens[1:]

        if tokens and self._is_range(tokens[0]):
            offset, limit = self._parse_range(tokens[0])
            if offset is None:
                return f"Invalid range '{tokens[0]}'. Use e.g. 6-10."

        return self._format_messages(
            board, region, category,
            offset=offset, limit=limit,
            include_abbrevs=False,
        )

    # ------------------------------------------------------------------
    # Sync — !x (v1.26.0)
    # ------------------------------------------------------------------

    def _handle_sync(self, board: BbsBoard, args: str) -> str:
        """Handle ``!x [since_id] [since_del]`` and build the sync reply.

        The reply format is described in the module docstring.  Every
        line is at most :data:`SYNC_LINE_MAX_BYTES` UTF-8 bytes.

        Args:
            board: Active ``BbsBoard``.
            args:  Text after ``!x``: up to two whole numbers from ``0``
                   to :data:`SYNC_MAX_ID`, ASCII digits only.

        Returns:
            Multi-line sync reply, or the usage line
            ``Usage: !x <since_id> <since_del>`` when *args* is not valid.
        """
        tokens = args.split() if args else []
        if len(tokens) > 2 or not all(
            t.isascii() and t.isdigit() and int(t) <= SYNC_MAX_ID for t in tokens
        ):
            return "Usage: !x <since_id> <since_del>"
        since_id = int(tokens[0]) if tokens else 0
        since_del = int(tokens[1]) if len(tokens) > 1 else 0

        batch = self._service.get_messages_since(
            board.channels, since_id, self.SYNC_LIMIT + 1,
        )
        more = len(batch) > self.SYNC_LIMIT
        records = batch[:self.SYNC_LIMIT]
        deleted_ids, del_seq = self._service.get_deletions_since(since_del)

        abbrev_of = {
            cat: abbr
            for abbr, cat in self.compute_abbreviations(board.categories).items()
        }
        retention = [f"*:{board.default_retention_days}"] + [
            f"{abbrev_of.get(cat.upper(), cat.upper())}:{board.retention_days_for(cat)}"
            for cat in board.categories
        ]
        lines = self._pack_items("R|", retention)
        for msg in records:
            lines += self._record_lines(msg, abbrev_of)
        lines += self._pack_items("-", [str(i) for i in deleted_ids])
        return "\n".join([
            f"{SYNC_HEADER_TAG}|{self._service.get_epoch()}|{len(records)}|"
            f"{int(more)}|{del_seq}|{len(deleted_ids)}|{len(lines)}"
        ] + lines)

    @staticmethod
    def _sync_field(value: str) -> str:
        """Make *value* safe for a non-final ``|``-separated sync field.

        Args:
            value: Raw sender or region text.

        Returns:
            *value* with ``|`` replaced by ``/`` and line breaks by spaces.
        """
        return " ".join((value or "").replace("|", "/").splitlines())

    @staticmethod
    def _cut_utf8(text: str, max_bytes: int) -> Tuple[str, str]:
        """Split *text* after at most *max_bytes* UTF-8 bytes.

        Never splits a multi-byte character.

        Args:
            text:      Text to split.
            max_bytes: Byte budget for the first part, ``>= 4``.

        Returns:
            Tuple of (leading part within *max_bytes*, rest).  The
            leading part is at least one character when *text* is not
            empty.
        """
        head = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
        if not head and text:
            head = text[:1]
        return head, text[len(head):]

    def _record_lines(self, msg: BbsMessage, abbrev_of: Dict[str, str]) -> List[str]:
        """Return the sync lines for one message record.

        Args:
            msg:       Message to encode.
            abbrev_of: Mapping upper-case category name → abbreviation,
                       for the configured categories.

        Returns:
            One record line, followed by ``+<id>|`` continuation lines
            when the record exceeds :data:`SYNC_LINE_MAX_BYTES`.
            ``CommandHandler._split_reply`` strips trailing whitespace per
            line, so whitespace at a cut is moved to the start of the next
            line, unless that part would then be only whitespace.

        Warning:
            A continuation part of only whitespace keeps it and loses it to
            the DM sender: an inner run of whitespace loses
            ``160 - len("+<id>|")`` bytes (157 for ids 1-9) per full part.
            Trailing whitespace of the text is lost entirely.
        """
        cat = abbrev_of.get(msg.category.upper(), msg.category.upper())
        text = " ".join((msg.text or "").splitlines())
        line = (
            f"{msg.id}|{self._to_unix(msg.timestamp)}|{cat}|"
            f"{self._sync_field(msg.region)}|{self._sync_field(msg.sender)}|{text}"
        )
        first, rest = self._keep_whitespace(*self._cut_utf8(line, SYNC_LINE_MAX_BYTES))
        lines = [first]
        prefix = f"+{msg.id}|"
        budget = SYNC_LINE_MAX_BYTES - len(prefix.encode("utf-8"))
        while rest:
            part, rest = self._keep_whitespace(*self._cut_utf8(rest, budget))
            lines.append(prefix + part)
        return lines

    @staticmethod
    def _keep_whitespace(head: str, rest: str) -> Tuple[str, str]:
        """Move whitespace at the end of *head* to the start of *rest*.

        Args:
            head: Leading part of a cut, as returned by :meth:`_cut_utf8`.
            rest: Remainder of the cut.

        Returns:
            Tuple of (*head* without trailing whitespace, that whitespace
            followed by *rest*).  Unchanged when *rest* is empty (nothing
            follows) or when *head* is only whitespace (the cut must make
            progress).
        """
        kept = head.rstrip()
        if not rest or not kept:
            return head, rest
        return kept, head[len(kept):] + rest

    @staticmethod
    def _pack_items(prefix: str, items: List[str]) -> List[str]:
        """Pack comma-separated *items* into lines of at most the byte limit.

        Args:
            prefix: Line prefix, e.g. ``"R|"`` or ``"-"``.
            items:  Short ASCII items (each far below the limit).

        Returns:
            Lines ``<prefix><item>,<item>,...``, each at most
            :data:`SYNC_LINE_MAX_BYTES` bytes; empty when *items* is empty.
        """
        lines: List[str] = []
        current = ""
        for item in items:
            candidate = f"{current},{item}" if current else item
            if current and len((prefix + candidate).encode("utf-8")) > SYNC_LINE_MAX_BYTES:
                lines.append(prefix + current)
                candidate = item
            current = candidate
        if current:
            lines.append(prefix + current)
        return lines

    @staticmethod
    def _to_unix(timestamp: str) -> int:
        """Convert a stored ISO-8601 timestamp to Unix seconds.

        Args:
            timestamp: ISO-8601 string; without UTC offset it is taken
                       as UTC.

        Returns:
            Whole seconds since 1970-01-01T00:00:00Z; ``0`` when the
            string cannot be parsed.
        """
        try:
            moment = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            return 0
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())

    # ------------------------------------------------------------------
    # Shared message formatter
    # ------------------------------------------------------------------

    def _format_messages(
        self,
        board,
        region,
        category,
        offset: int = 0,
        limit: int = None,
        include_abbrevs: bool = False,
    ) -> str:
        if limit is None:
            limit = self.READ_LIMIT
        messages = self._service.get_messages(
            board.channels,
            region=region,
            category=category,
            limit=limit,
            offset=offset,
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
        """Return the help text for *board*, one part per line.

        The parts are separated by newlines so the DM sender can split a
        help text longer than one DM (160 UTF-8 bytes, firmware
        ``MAX_TEXT_LEN``) on line boundaries into several DMs, just like
        a ``!r`` reply.  As one line the text was refused by the device
        once regions and categories made it longer than that limit.

        The board name (the linked whitelist channels) is not shown: the
        BBS is used by DM, so a channel name in the help was confusing.

        Args:
            board: Board whose regions and categories are shown.

        Returns:
            Multi-line help text.
        """
        abbr = self._abbrev_table(board.categories)
        lines = [
            "BBS",
            "!p [cat] [text] | !r [cat] [1-5] | !s [cat] [query]",
        ]
        if board.regions:
            lines.append(f"Regions: {', '.join(board.regions)}")
        if abbr:
            lines.append(abbr)
        return "\n".join(lines)
