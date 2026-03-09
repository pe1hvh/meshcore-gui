"""
Archive file watcher for MeshCore Observer.

Scans the archive directory for ``*_messages.json`` and ``*_rxlog.json``
files, tracks their modification times, and returns only NEW entries
since the previous poll.  100% read-only — never writes to archive files.

Thread safety: all public methods acquire ``_lock`` before touching state.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ARCHIVE_VERSION = 1


@dataclass
class _FileState:
    """Tracking state for a single archive JSON file."""

    path: Path
    last_mtime: float = 0.0
    last_entry_count: int = 0
    address: str = ""


@dataclass
class PollResult:
    """New entries discovered during a single poll cycle.

    Attributes:
        new_messages: List of (source_address, message_dict) tuples.
        new_rxlog:    List of (source_address, entry_dict) tuples.
    """

    new_messages: List[Tuple[str, dict]] = field(default_factory=list)
    new_rxlog: List[Tuple[str, dict]] = field(default_factory=list)


class ArchiveWatcher:
    """Polls archive directory for new messages and RX log entries.

    Designed for timer-based polling from the NiceGUI main thread.
    Each call to :meth:`poll` scans the archive directory, detects
    changed files via ``stat().st_mtime``, reads only changed files,
    and returns new entries as a :class:`PollResult`.

    Args:
        archive_dir: Path to the archive directory.
        debug:       Enable verbose debug logging.
    """

    def __init__(self, archive_dir: str, debug: bool = False) -> None:
        self._archive_dir = Path(archive_dir).expanduser().resolve()
        self._debug = debug
        self._lock = threading.Lock()

        # Tracking state: filepath_str → _FileState
        self._msg_files: Dict[str, _FileState] = {}
        self._rxlog_files: Dict[str, _FileState] = {}

        # Aggregated totals
        self._total_messages_seen: int = 0
        self._total_rxlog_seen: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> PollResult:
        """Scan archive directory and return new entries since last poll.

        Returns:
            PollResult with new messages and RX log entries.
            Empty lists when nothing has changed (no disk I/O).
        """
        with self._lock:
            result = PollResult()

            if not self._archive_dir.exists():
                return result

            # Discover current files on disk
            current_msg_paths = set()
            current_rxlog_paths = set()

            try:
                for f in self._archive_dir.iterdir():
                    name = f.name
                    if name.endswith("_messages.json"):
                        current_msg_paths.add(str(f))
                    elif name.endswith("_rxlog.json"):
                        current_rxlog_paths.add(str(f))
            except OSError as exc:
                logger.error("Error scanning archive dir: %s", exc)
                return result

            # Prune vanished files
            vanished_msg = set(self._msg_files.keys()) - current_msg_paths
            for vp in vanished_msg:
                del self._msg_files[vp]

            vanished_rxlog = set(self._rxlog_files.keys()) - current_rxlog_paths
            for vp in vanished_rxlog:
                del self._rxlog_files[vp]

            # Check message files
            for fpath_str in current_msg_paths:
                new_entries = self._check_file(
                    fpath_str, self._msg_files, "messages",
                )
                if new_entries:
                    result.new_messages.extend(new_entries)
                    self._total_messages_seen += len(new_entries)

            # Check rxlog files
            for fpath_str in current_rxlog_paths:
                new_entries = self._check_file(
                    fpath_str, self._rxlog_files, "entries",
                )
                if new_entries:
                    result.new_rxlog.extend(new_entries)
                    self._total_rxlog_seen += len(new_entries)

            return result

    def get_sources(self) -> List[Dict]:
        """Return metadata about all tracked archive sources.

        Returns:
            List of dicts with keys: address, path, last_updated, message_count,
            rxlog_count.
        """
        with self._lock:
            # Collect per-address info
            sources: Dict[str, Dict] = {}

            for fpath_str, state in self._msg_files.items():
                addr = state.address or Path(fpath_str).stem
                if addr not in sources:
                    sources[addr] = {
                        "address": addr,
                        "path": str(Path(fpath_str).parent),
                        "last_updated": "",
                        "message_count": 0,
                        "rxlog_count": 0,
                    }
                sources[addr]["message_count"] = state.last_entry_count
                sources[addr]["path"] = fpath_str

            for fpath_str, state in self._rxlog_files.items():
                addr = state.address or Path(fpath_str).stem
                if addr not in sources:
                    sources[addr] = {
                        "address": addr,
                        "path": fpath_str,
                        "last_updated": "",
                        "message_count": 0,
                        "rxlog_count": 0,
                    }
                sources[addr]["rxlog_count"] = state.last_entry_count

            return list(sources.values())

    def get_stats(self) -> Dict:
        """Return aggregate statistics.

        Returns:
            Dict with total_messages_seen, total_rxlog_seen, active_sources.
        """
        with self._lock:
            addresses = set()
            for state in self._msg_files.values():
                if state.address:
                    addresses.add(state.address)
            for state in self._rxlog_files.values():
                if state.address:
                    addresses.add(state.address)

            return {
                "total_messages_seen": self._total_messages_seen,
                "total_rxlog_seen": self._total_rxlog_seen,
                "active_sources": len(addresses),
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_file(
        self,
        fpath_str: str,
        tracking: Dict[str, _FileState],
        entries_key: str,
    ) -> List[Tuple[str, dict]]:
        """Check a single file for new entries.

        Args:
            fpath_str:   Absolute path string.
            tracking:    Dict of _FileState for this file category.
            entries_key: JSON key containing the entry list ("messages" or "entries").

        Returns:
            List of (source_address, entry_dict) for new entries, or empty list.
        """
        fpath = Path(fpath_str)

        try:
            current_mtime = fpath.stat().st_mtime
        except OSError:
            # File vanished between iterdir and stat
            tracking.pop(fpath_str, None)
            return []

        # New file — start tracking
        if fpath_str not in tracking:
            tracking[fpath_str] = _FileState(path=fpath)

        state = tracking[fpath_str]

        # Unchanged file — no I/O needed
        if current_mtime == state.last_mtime:
            return []

        # File changed — read and parse
        state.last_mtime = current_mtime

        try:
            raw_text = fpath.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Error reading %s: %s", fpath, exc)
            return []

        # Version check
        if data.get("version") != ARCHIVE_VERSION:
            if self._debug:
                logger.debug(
                    "Skipping %s: version %s (expected %d)",
                    fpath.name, data.get("version"), ARCHIVE_VERSION,
                )
            return []

        # Extract source address
        address = data.get("address", fpath.stem)
        state.address = address

        entries = data.get(entries_key, [])
        total_count = len(entries)
        prev_count = state.last_entry_count

        # Detect new entries (append-only assumption)
        new_entries: List[Tuple[str, dict]] = []
        if total_count > prev_count:
            for entry in entries[prev_count:]:
                # Tag each entry with source address
                entry["_source"] = address
                new_entries.append((address, entry))

        state.last_entry_count = total_count

        if new_entries and self._debug:
            logger.debug(
                "%s: %d new %s (total: %d)",
                fpath.name, len(new_entries), entries_key, total_count,
            )

        return new_entries
