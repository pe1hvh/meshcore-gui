"""
Persistent repeater statistics archive for MeshCore GUI.

Every poll attempt is written as one JSON object on its own line to
``~/.meshcore-gui/archive/<safe_dev_id>_repeater_stats.jsonl``.

The append-only JSONL form mirrors the RX-log stream that
:class:`~meshcore_gui.services.message_archive.MessageArchive` already
writes: one record per line, written immediately, cheap for an external
consumer to tail.

Record schema
~~~~~~~~~~~~~
::

    {
      "polled_at": "2026-09-01T10:15:00+00:00",   # UTC, always present
      "pubkey":    "<64 hex characters>",
      "name":      "Repeater display name",
      "ok":        true,
      "error":     null,
      "attempts":  1,                             # sessions used, since 1.24.2
      "status":    { ... raw fields as reported ... }
    }

Failed polls are recorded too, with ``ok`` false, an ``error`` string and
an empty ``status``.  That is deliberate: a gap in the message archive
can then be matched against the poll moments to see whether it coincided
with a session.

``attempts`` counts how many complete sessions the poller needed before
it gave up or succeeded, so a repeater that only ever answers on the
third try is distinguishable from one that answers immediately.  It is
zero when no session was started at all, such as when no password is
configured.  Records written before 1.24.2 do not carry the field;
consumers should treat a missing value as unknown rather than as one.

Values in ``status`` are stored exactly as the repeater reports them —
no scaling, no rounding, no smoothing.  Interpretation happens elsewhere.

Passwords never enter a record.  The archive is only ever handed values
from the status response.

Thread safety
~~~~~~~~~~~~~
All public methods acquire an internal lock, separate from both the
SharedData lock and the MessageArchive lock.

                   Author: PE1HVH
  SPDX-License-Identifier: MIT
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from meshcore_gui.config import (
    REPEATER_STATS_RETENTION_DAYS,
    debug_print,
)

ARCHIVE_DIR = Path.home() / ".meshcore-gui" / "archive"

#: Number of most recent records kept in memory for the GUI panel.
RECENT_CACHE_SIZE = 200


class RepeaterStatsArchive:
    """Append-only archive of repeater poll results.

    Args:
        device_id: Device identifier string used to derive the filename.
    """

    def __init__(self, device_id: str = "") -> None:
        self._lock = threading.Lock()

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        ) if device_id else "default"

        self._path: Path = ARCHIVE_DIR / f"{safe_name}_repeater_stats.jsonl"

        # Most recent record per repeater, and a bounded recent list.
        # Both exist so the GUI panel can render without reading the
        # file on every 0.5 s update tick.
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._latest_ok: Dict[str, Dict[str, Any]] = {}
        self._recent: List[Dict[str, Any]] = []
        self._total_records = 0

        self._load_latest()

    # ------------------------------------------------------------------
    # Public API — writing
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Return the JSONL archive path."""
        return self._path

    def add_measurement(
        self,
        pubkey: str,
        name: str,
        status: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        attempts: int = 1,
    ) -> Dict[str, Any]:
        """Append one poll result to the archive.

        Args:
            pubkey:   Full public key of the polled repeater.
            name:     Display name of the repeater.
            status:   Raw status fields as reported, or ``None`` on failure.
            error:    Short failure reason, or ``None`` on success.
            attempts: Number of complete sessions the poller used for this
                      result.  Zero when no session was started at all.

        Returns:
            The record that was written.
        """
        record: Dict[str, Any] = {
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "pubkey": pubkey,
            "name": name,
            "ok": error is None and status is not None,
            "error": error,
            "attempts": attempts,
            "status": status or {},
        }

        with self._lock:
            self._latest[pubkey] = record
            if record["ok"]:
                self._latest_ok[pubkey] = record

            self._recent.append(record)
            if len(self._recent) > RECENT_CACHE_SIZE:
                del self._recent[:-RECENT_CACHE_SIZE]

            self._total_records += 1

            try:
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                debug_print(f"RepeaterStatsArchive: append error: {exc}")

        debug_print(
            f"RepeaterStatsArchive: recorded {name or pubkey[:16]} — "
            f"ok={record['ok']}, attempts={attempts}"
            + (f", error={error}" if error else "")
        )
        return record

    # ------------------------------------------------------------------
    # Public API — reading
    # ------------------------------------------------------------------

    def get_latest(self, pubkey: str) -> Optional[Dict[str, Any]]:
        """Return the most recent record for a repeater, success or not.

        Args:
            pubkey: Full public key of the repeater.

        Returns:
            The record, or ``None`` when the repeater was never polled.
        """
        with self._lock:
            return self._latest.get(pubkey)

    def get_latest_success(self, pubkey: str) -> Optional[Dict[str, Any]]:
        """Return the most recent successful record for a repeater.

        Args:
            pubkey: Full public key of the repeater.

        Returns:
            The record, or ``None`` when no poll has ever succeeded.
        """
        with self._lock:
            return self._latest_ok.get(pubkey)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent records across all repeaters.

        Args:
            limit: Maximum number of records to return.

        Returns:
            Newest-first list of records.
        """
        with self._lock:
            return list(reversed(self._recent[-limit:]))

    def get_stats(self) -> Dict[str, Any]:
        """Return archive counters for diagnostics.

        Returns:
            Dict with the record count and the archive path.
        """
        with self._lock:
            return {
                "total_records": self._total_records,
                "repeaters_seen": len(self._latest),
                "path": str(self._path),
            }

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def cleanup_old_data(self) -> None:
        """Drop records older than the configured retention period.

        Reads every line, filters on ``polled_at`` and rewrites the file
        atomically via a temp file plus rename.  Corrupt lines are
        dropped rather than retained.
        """
        if not self._path.exists():
            return

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=REPEATER_STATS_RETENTION_DAYS
        )

        with self._lock:
            try:
                kept: List[str] = []
                original = 0
                with self._path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        original += 1
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if _is_newer_than(record.get("polled_at"), cutoff):
                            kept.append(line)

                if len(kept) < original:
                    temp_path = self._path.with_suffix(".jsonl.tmp")
                    temp_path.write_text(
                        "\n".join(kept) + ("\n" if kept else ""),
                        encoding="utf-8",
                    )
                    temp_path.replace(self._path)
                    debug_print(
                        f"RepeaterStatsArchive: cleanup removed "
                        f"{original - len(kept)} old records "
                        f"(retained: {len(kept)})"
                    )
            except OSError as exc:
                debug_print(f"RepeaterStatsArchive: cleanup error: {exc}")

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _load_latest(self) -> None:
        """Populate the in-memory caches from the existing archive.

        Keeps the GUI panel populated across a restart without having to
        wait for the first poll.
        """
        if not self._path.exists():
            debug_print(f"RepeaterStatsArchive: no file at {self._path}")
            return

        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    self._total_records += 1
                    pubkey = record.get("pubkey", "")
                    if pubkey:
                        self._latest[pubkey] = record
                        if record.get("ok"):
                            self._latest_ok[pubkey] = record

                    self._recent.append(record)
                    if len(self._recent) > RECENT_CACHE_SIZE:
                        del self._recent[:-RECENT_CACHE_SIZE]

            debug_print(
                f"RepeaterStatsArchive: loaded {self._total_records} records "
                f"for {len(self._latest)} repeaters"
            )
        except OSError as exc:
            debug_print(f"RepeaterStatsArchive: load error: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_newer_than(timestamp_str: Optional[str], cutoff: datetime) -> bool:
    """Check whether an ISO timestamp is newer than *cutoff*.

    Args:
        timestamp_str: ISO-8601 timestamp, or None.
        cutoff:        Threshold datetime (timezone-aware).

    Returns:
        True when the timestamp parses and lies after the cutoff.
    """
    if not timestamp_str:
        return False
    try:
        return datetime.fromisoformat(timestamp_str) > cutoff
    except (ValueError, TypeError):
        return False
