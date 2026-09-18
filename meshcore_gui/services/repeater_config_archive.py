"""
Persistent repeater configuration archive for MeshCore GUI.

Every nightly configuration read is written as one JSON object on its own
line to ``~/.meshcore-gui/archive/<safe_dev_id>_repeater_config.jsonl``.

Separate from
:class:`~meshcore_gui.services.repeater_stats_archive.RepeaterStatsArchive`
on purpose.  The statistics archive holds telemetry that changes on every
poll; this one holds settings that change only when somebody edits them.
Mixing both in one file would inflate the statistics stream with
identical values and force every consumer of that stream to filter them
out again.  Keeping them apart also leaves the statistics record schema
untouched.

Record schema
~~~~~~~~~~~~~
::

    {
      "polled_at": "2026-09-19T03:00:11+00:00",  # UTC, always present
      "pubkey":    "<64 hex characters>",
      "name":      "Repeater display name",
      "ok":        true,
      "error":     null,
      "config":    { "flood.max": "3", ... },    # answered keys
      "missing":   [ "txdelay" ]                 # keys without a reply
    }

The timestamp field is called ``polled_at`` so a record from this archive
can be handed to the same helpers in the GUI panel as a statistics
record.

Values are stored exactly as the repeater reported them, as text.  No
conversion to numbers happens here: a CLI reply is free-form and a
setting such as the region is not numeric at all.  Interpretation
happens elsewhere.

A failed read is recorded too, with ``ok`` false and an ``error`` string,
so an unreachable repeater is visible in the panel rather than showing
stale values without explanation.

Passwords never enter a record.

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
    REPEATER_CONFIG_RETENTION_DAYS,
    debug_print,
)

ARCHIVE_DIR = Path.home() / ".meshcore-gui" / "archive"

#: Number of most recent records kept in memory for the GUI panel.
RECENT_CACHE_SIZE = 200


class RepeaterConfigArchive:
    """Append-only archive of repeater configuration readings.

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

        self._path: Path = ARCHIVE_DIR / f"{safe_name}_repeater_config.jsonl"

        # Most recent record per repeater, and a bounded recent list, so
        # the GUI panel can render without reading the file on every
        # update tick.
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

    def add_reading(
        self,
        pubkey: str,
        name: str,
        config: Optional[Dict[str, str]] = None,
        error: Optional[str] = None,
        missing: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Append one configuration read to the archive.

        Args:
            pubkey:  Full public key of the repeater.
            name:    Display name of the repeater.
            config:  Answered settings, keyed by setting name, or ``None``
                     when the session failed before any reply came in.
            error:   Short failure reason, or ``None`` on success.
            missing: Settings that were asked for but never answered.

        Returns:
            The record that was written.
        """
        record: Dict[str, Any] = {
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "pubkey": pubkey,
            "name": name,
            "ok": error is None and bool(config),
            "error": error,
            "config": config or {},
            "missing": list(missing or []),
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
                debug_print(f"RepeaterConfigArchive: append error: {exc}")

        debug_print(
            f"RepeaterConfigArchive: recorded {name or pubkey[:16]} — "
            f"ok={record['ok']}, settings={len(record['config'])}"
            + (f", missing={len(record['missing'])}" if record["missing"] else "")
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
            The record, or ``None`` when the repeater was never read.
        """
        with self._lock:
            return self._latest.get(pubkey)

    def get_latest_success(self, pubkey: str) -> Optional[Dict[str, Any]]:
        """Return the most recent successful record for a repeater.

        Args:
            pubkey: Full public key of the repeater.

        Returns:
            The record, or ``None`` when no read has ever succeeded.
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
            days=REPEATER_CONFIG_RETENTION_DAYS
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
                        f"RepeaterConfigArchive: cleanup removed "
                        f"{original - len(kept)} old records "
                        f"(retained: {len(kept)})"
                    )
            except OSError as exc:
                debug_print(f"RepeaterConfigArchive: cleanup error: {exc}")

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _load_latest(self) -> None:
        """Populate the in-memory caches from the existing archive.

        Keeps the GUI panel populated across a restart, and lets the
        poller see when each repeater was last read so a restart does not
        trigger a fresh round of queries.
        """
        if not self._path.exists():
            debug_print(f"RepeaterConfigArchive: no file at {self._path}")
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
                f"RepeaterConfigArchive: loaded {self._total_records} records "
                f"for {len(self._latest)} repeaters"
            )
        except OSError as exc:
            debug_print(f"RepeaterConfigArchive: load error: {exc}")


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
