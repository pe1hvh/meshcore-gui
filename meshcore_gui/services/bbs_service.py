"""
Offline Bulletin Board System (BBS) service for MeshCore GUI.

Stores BBS messages in a local SQLite database, one table per channel.
Channel configuration is managed by
:class:`~meshcore_gui.services.bbs_config_store.BbsConfigStore` and
persisted to ``~/.meshcore-gui/bbs/bbs_config.json``.

Architecture
~~~~~~~~~~~~
- ``BbsService``        — persistence layer (SQLite, retention, queries).
- ``BbsCommandHandler`` — parses incoming ``!bbs`` text commands and
                          delegates to ``BbsService``.  Returns reply text.

Thread safety
~~~~~~~~~~~~~
SQLite connections are created in the calling thread.  The service uses
``check_same_thread=False`` combined with an internal ``threading.Lock``
so it is safe to call from both the GUI thread and the worker thread.

Storage location
~~~~~~~~~~~~~~~~
``~/.meshcore-gui/bbs/bbs_messages.db`` (SQLite, stdlib).
``~/.meshcore-gui/bbs/bbs_config.json`` (via BbsConfigStore).
"""

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import debug_print

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

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
        channel:      MeshCore channel index.
        region:       Region tag (empty string when channel has no regions).
        category:     Category tag (e.g. ``'MEDISCH'``).
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
                 Defaults to ``~/.meshcore-gui/bbs/bbs_messages.db``.
    """

    def __init__(self, db_path: Path = BBS_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

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
        """Return a new SQLite connection (check_same_thread=False)."""
        return sqlite3.connect(
            str(self._db_path), check_same_thread=False
        )

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
                    """
                    INSERT INTO bbs_messages
                        (channel, region, category, sender, sender_key, text, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg.channel,
                        msg.region,
                        msg.category,
                        msg.sender,
                        msg.sender_key,
                        msg.text,
                        msg.timestamp,
                    ),
                )
                conn.commit()
                msg.id = cur.lastrowid
                debug_print(
                    f"BBS: posted msg id={msg.id} ch={msg.channel} "
                    f"cat={msg.category} sender={msg.sender}"
                )
                return msg.id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_messages(
        self,
        channel: int,
        region: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[BbsMessage]:
        """Return the *limit* most recent messages for a channel.

        Args:
            channel:  MeshCore channel index.
            region:   Optional region filter (exact match; ``None`` = all).
            category: Optional category filter (exact match; ``None`` = all).
            limit:    Maximum number of messages to return.

        Returns:
            List of ``BbsMessage`` objects, newest first.
        """
        query = (
            "SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            "FROM bbs_messages WHERE channel = ?"
        )
        params: list = [channel]

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

        return [self._row_to_msg(row) for row in rows]

    def get_all_messages(
        self,
        channel: int,
        region: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[BbsMessage]:
        """Return all messages for a channel (oldest first) for the GUI panel.

        Args:
            channel:  MeshCore channel index.
            region:   Optional region filter.
            category: Optional category filter.

        Returns:
            List of ``BbsMessage`` objects, oldest first.
        """
        query = (
            "SELECT id, channel, region, category, sender, sender_key, text, timestamp "
            "FROM bbs_messages WHERE channel = ?"
        )
        params: list = [channel]

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

        return [self._row_to_msg(row) for row in rows]

    @staticmethod
    def _row_to_msg(row: tuple) -> BbsMessage:
        return BbsMessage(
            id=row[0],
            channel=row[1],
            region=row[2],
            category=row[3],
            sender=row[4],
            sender_key=row[5],
            text=row[6],
            timestamp=row[7],
        )

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def purge_expired(self, channel: int, retention_hours: int) -> int:
        """Delete messages older than *retention_hours* for a channel.

        Args:
            channel:         MeshCore channel index.
            retention_hours: Messages older than this are deleted.

        Returns:
            Number of rows deleted.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        ).isoformat()

        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM bbs_messages WHERE channel = ? AND timestamp < ?",
                    (channel, cutoff),
                )
                conn.commit()
                deleted = cur.rowcount
                if deleted:
                    debug_print(
                        f"BBS: purged {deleted} expired messages from ch={channel}"
                    )
                return deleted

    def purge_all_expired(self, channels_config: List[Dict]) -> None:
        """Run retention cleanup for all configured channels.

        Args:
            channels_config: List of channel config dicts.
        """
        for cfg in channels_config:
            self.purge_expired(cfg["channel"], cfg["retention_hours"])


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------

class BbsCommandHandler:
    """Parses ``!bbs`` mesh commands and delegates to :class:`BbsService`.

    Channel configuration is read live from the supplied
    :class:`~meshcore_gui.services.bbs_config_store.BbsConfigStore`
    so that changes made in the GUI take effect immediately without
    restarting the application.

    Args:
        service:      Shared ``BbsService`` instance.
        config_store: ``BbsConfigStore`` instance for live channel config.
    """

    READ_LIMIT: int = 5

    def __init__(self, service: BbsService, config_store) -> None:
        self._service = service
        self._config_store = config_store

    def _get_cfg(self, channel_idx: int) -> Optional[Dict]:
        """Return enabled channel config, or ``None``."""
        cfg = self._config_store.get_channel(channel_idx)
        if cfg and cfg.get("enabled", False):
            return cfg
        return None

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

        cfg = self._get_cfg(channel_idx)
        if cfg is None:
            return None

        # Whitelist check
        allowed = cfg.get("allowed_keys", [])
        if allowed and sender_key not in allowed:
            debug_print(
                f"BBS: silently dropping msg from {sender} "
                f"(key not in whitelist for ch={channel_idx})"
            )
            return None

        parts = text.split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""
        return self._dispatch(cfg, sender, sender_key, args)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, cfg: Dict, sender: str, sender_key: str, args: str) -> str:
        sub = args.split(None, 1)[0].lower() if args else ""
        rest = args.split(None, 1)[1] if len(args.split(None, 1)) > 1 else ""

        if sub == "post":
            return self._handle_post(cfg, sender, sender_key, rest)
        if sub == "read":
            return self._handle_read(cfg, rest)
        if sub == "help" or not sub:
            return self._handle_help(cfg)
        return f"Unknown command '{sub}'. {self._handle_help(cfg)}"

    # ------------------------------------------------------------------
    # Sub-command: post
    # ------------------------------------------------------------------

    def _handle_post(self, cfg: Dict, sender: str, sender_key: str, args: str) -> str:
        regions: List[str] = cfg.get("regions", [])
        categories: List[str] = cfg["categories"]
        tokens = args.split(None, 2) if args else []

        if regions:
            if len(tokens) < 3:
                return (
                    f"Usage: !bbs post [region] [category] [text] | "
                    f"Regions: {', '.join(regions)} | "
                    f"Categories: {', '.join(categories)}"
                )
            region, category, text = tokens[0], tokens[1], tokens[2]
            region_upper = region.upper()
            valid_regions = [r.upper() for r in regions]
            if region_upper not in valid_regions:
                return f"Invalid region '{region}'. Valid: {', '.join(regions)}"
            region = regions[valid_regions.index(region_upper)]
            category_upper = category.upper()
            valid_cats = [c.upper() for c in categories]
            if category_upper not in valid_cats:
                return f"Invalid category '{category}'. Valid: {', '.join(categories)}"
            category = categories[valid_cats.index(category_upper)]
        else:
            if len(tokens) < 2:
                return (
                    f"Usage: !bbs post [category] [text] | "
                    f"Categories: {', '.join(categories)}"
                )
            region = ""
            category, text = tokens[0], tokens[1]
            category_upper = category.upper()
            valid_cats = [c.upper() for c in categories]
            if category_upper not in valid_cats:
                return f"Invalid category '{category}'. Valid: {', '.join(categories)}"
            category = categories[valid_cats.index(category_upper)]

        msg = BbsMessage(
            channel=cfg["channel"],
            region=region,
            category=category,
            sender=sender,
            sender_key=sender_key,
            text=text,
        )
        self._service.post_message(msg)
        region_label = f" [{region}]" if region else ""
        return f"Posted [{category}]{region_label}: {text[:60]}"

    # ------------------------------------------------------------------
    # Sub-command: read
    # ------------------------------------------------------------------

    def _handle_read(self, cfg: Dict, args: str) -> str:
        regions: List[str] = cfg.get("regions", [])
        categories: List[str] = cfg["categories"]
        tokens = args.split() if args else []

        region: Optional[str] = None
        category: Optional[str] = None

        if regions:
            valid_regions_upper = [r.upper() for r in regions]
            valid_cats_upper = [c.upper() for c in categories]
            if len(tokens) >= 1:
                tok0 = tokens[0].upper()
                if tok0 in valid_regions_upper:
                    region = regions[valid_regions_upper.index(tok0)]
                    if len(tokens) >= 2:
                        tok1 = tokens[1].upper()
                        if tok1 in valid_cats_upper:
                            category = categories[valid_cats_upper.index(tok1)]
                        else:
                            return f"Invalid category '{tokens[1]}'. Valid: {', '.join(categories)}"
                else:
                    return f"Invalid region '{tokens[0]}'. Valid: {', '.join(regions)}"
        else:
            valid_cats_upper = [c.upper() for c in categories]
            if len(tokens) >= 1:
                tok0 = tokens[0].upper()
                if tok0 in valid_cats_upper:
                    category = categories[valid_cats_upper.index(tok0)]
                else:
                    return f"Invalid category '{tokens[0]}'. Valid: {', '.join(categories)}"

        messages = self._service.get_messages(
            cfg["channel"], region=region, category=category, limit=self.READ_LIMIT,
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
    # Sub-command: help
    # ------------------------------------------------------------------

    def _handle_help(self, cfg: Dict) -> str:
        regions: List[str] = cfg.get("regions", [])
        categories: List[str] = cfg["categories"]
        name = cfg.get("name", f"ch{cfg['channel']}")
        if regions:
            return (
                f"BBS [{name}] | "
                f"!bbs post [region] [cat] [text] | "
                f"!bbs read [region] [cat] | "
                f"Regions: {', '.join(regions)} | "
                f"Categories: {', '.join(categories)}"
            )
        return (
            f"BBS [{name}] | "
            f"!bbs post [cat] [text] | "
            f"!bbs read [cat] | "
            f"Categories: {', '.join(categories)}"
        )

