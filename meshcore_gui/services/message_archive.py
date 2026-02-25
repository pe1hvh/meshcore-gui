"""
Persistent message and RxLog archive for MeshCore GUI.

Stores all incoming messages and RX log entries with configurable retention.
Works alongside SharedData: SharedData holds the latest N items for UI display,
while MessageArchive persists everything to disk with automatic cleanup.

Storage location
~~~~~~~~~~~~~~~~
~/.meshcore-gui/archive/<ADDRESS>_messages.json
~/.meshcore-gui/archive/<ADDRESS>_rxlog.json

Retention strategy
~~~~~~~~~~~~~~~~~~
- Messages older than MESSAGE_RETENTION_DAYS are purged daily
- RxLog entries older than RXLOG_RETENTION_DAYS are purged daily
- Cleanup runs in background (non-blocking)

Thread safety
~~~~~~~~~~~~~~
All methods use an internal lock for thread-safe operation.
The lock is separate from SharedData's lock to avoid contention.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import (
    MESSAGE_RETENTION_DAYS,
    RXLOG_RETENTION_DAYS,
    debug_print,
)
from meshcore_gui.core.models import Message, RxLogEntry

ARCHIVE_VERSION = 1
ARCHIVE_DIR = Path.home() / ".meshcore-gui" / "archive"


class MessageArchive:
    """Persistent storage for messages and RX log entries.
    
    Args:
        device_id: Device identifier string (used to derive filenames).
    """

    def __init__(self, device_id: str) -> None:
        self._address = device_id
        self._lock = threading.Lock()
        
        # Sanitize address for filename
        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        )
        
        self._messages_path = ARCHIVE_DIR / f"{safe_name}_messages.json"
        self._rxlog_path = ARCHIVE_DIR / f"{safe_name}_rxlog.json"
        
        # In-memory batch buffers (flushed periodically)
        self._message_buffer: List[Dict] = []
        self._rxlog_buffer: List[Dict] = []
        
        # Batch write thresholds
        self._batch_size = 10
        self._last_flush = datetime.now(timezone.utc)
        self._flush_interval_seconds = 60
        
        # Stats
        self._total_messages = 0
        self._total_rxlog = 0
        
        # Load existing archives
        self._load_archives()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _load_archives(self) -> None:
        """Load existing archive files and count entries."""
        with self._lock:
            # Load messages
            if self._messages_path.exists():
                try:
                    data = json.loads(self._messages_path.read_text(encoding="utf-8"))
                    if data.get("version") == ARCHIVE_VERSION:
                        self._total_messages = len(data.get("messages", []))
                        debug_print(
                            f"Archive: loaded {self._total_messages} messages "
                            f"from {self._messages_path}"
                        )
                except (json.JSONDecodeError, OSError) as exc:
                    debug_print(f"Archive: error loading messages: {exc}")
            
            # Load rxlog
            if self._rxlog_path.exists():
                try:
                    data = json.loads(self._rxlog_path.read_text(encoding="utf-8"))
                    if data.get("version") == ARCHIVE_VERSION:
                        self._total_rxlog = len(data.get("entries", []))
                        debug_print(
                            f"Archive: loaded {self._total_rxlog} rxlog entries "
                            f"from {self._rxlog_path}"
                        )
                except (json.JSONDecodeError, OSError) as exc:
                    debug_print(f"Archive: error loading rxlog: {exc}")

    # ------------------------------------------------------------------
    # Add operations (buffered)
    # ------------------------------------------------------------------

    def add_message(self, msg: Message) -> None:
        """Add a message to the archive (buffered write).
        
        Args:
            msg: Message dataclass instance.
        """
        with self._lock:
            # Convert to dict and add UTC timestamp
            msg_dict = {
                "time": msg.time,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "sender": msg.sender,
                "text": msg.text,
                "channel": msg.channel,
                "channel_name": msg.channel_name,
                "direction": msg.direction,
                "snr": msg.snr,
                "path_len": msg.path_len,
                "sender_pubkey": msg.sender_pubkey,
                "path_hashes": msg.path_hashes,
                "path_names": msg.path_names,
                "message_hash": msg.message_hash,
            }
            
            self._message_buffer.append(msg_dict)
            
            # Flush if batch size reached
            if len(self._message_buffer) >= self._batch_size:
                self._flush_messages()
            
            # Also flush if interval exceeded
            elif self._should_flush():
                self._flush_all()

    def add_rx_log(self, entry: RxLogEntry) -> None:
        """Add an RX log entry to the archive (buffered write).
        
        Args:
            entry: RxLogEntry dataclass instance.
        """
        with self._lock:
            # Convert to dict and add UTC timestamp
            entry_dict = {
                "time": entry.time,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "snr": entry.snr,
                "rssi": entry.rssi,
                "payload_type": entry.payload_type,
                "hops": entry.hops,
                "message_hash": entry.message_hash,
                "path_hashes": entry.path_hashes,
                "path_names": entry.path_names,
                "sender": entry.sender,
                "receiver": entry.receiver,
            }
            
            self._rxlog_buffer.append(entry_dict)
            
            # Flush if batch size reached
            if len(self._rxlog_buffer) >= self._batch_size:
                self._flush_rxlog()
            
            # Also flush if interval exceeded
            elif self._should_flush():
                self._flush_all()

    # ------------------------------------------------------------------
    # Flushing (write to disk)
    # ------------------------------------------------------------------

    def _should_flush(self) -> bool:
        """Check if flush interval has been exceeded."""
        elapsed = (datetime.now(timezone.utc) - self._last_flush).total_seconds()
        return elapsed >= self._flush_interval_seconds

    def _flush_messages(self) -> None:
        """Flush message buffer to disk (MUST be called with lock held)."""
        if not self._message_buffer:
            return
        
        # Read existing archive
        existing_messages = []
        if self._messages_path.exists():
            try:
                data = json.loads(self._messages_path.read_text(encoding="utf-8"))
                if data.get("version") == ARCHIVE_VERSION:
                    existing_messages = data.get("messages", [])
                else:
                    debug_print(
                        f"Archive: version mismatch in {self._messages_path}, "
                        f"expected {ARCHIVE_VERSION}, got {data.get('version')}"
                    )
                    # Don't overwrite if version mismatch - keep buffer for retry
                    return
            except (json.JSONDecodeError, OSError) as exc:
                debug_print(
                    f"Archive: error reading existing messages from {self._messages_path}: {exc}"
                )
                # Don't overwrite corrupted file - keep buffer for retry
                return
        
        # Append new messages
        existing_messages.extend(self._message_buffer)
        
        try:
            # Write atomically (temp file + rename)
            self._write_atomic(
                self._messages_path,
                {
                    "version": ARCHIVE_VERSION,
                    "address": self._address,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "messages": existing_messages,
                }
            )
            
            self._total_messages = len(existing_messages)
            debug_print(
                f"Archive: flushed {len(self._message_buffer)} messages "
                f"(total: {self._total_messages})"
            )
            
            # Clear buffer only after successful write
            self._message_buffer.clear()
            self._last_flush = datetime.now(timezone.utc)
            
        except (OSError) as exc:
            debug_print(f"Archive: error writing messages: {exc}")
            # Keep buffer for retry

    def _flush_rxlog(self) -> None:
        """Flush rxlog buffer to disk (MUST be called with lock held)."""
        if not self._rxlog_buffer:
            return
        
        # Read existing archive
        existing_entries = []
        if self._rxlog_path.exists():
            try:
                data = json.loads(self._rxlog_path.read_text(encoding="utf-8"))
                if data.get("version") == ARCHIVE_VERSION:
                    existing_entries = data.get("entries", [])
                else:
                    debug_print(
                        f"Archive: version mismatch in {self._rxlog_path}, "
                        f"expected {ARCHIVE_VERSION}, got {data.get('version')}"
                    )
                    # Don't overwrite if version mismatch - keep buffer for retry
                    return
            except (json.JSONDecodeError, OSError) as exc:
                debug_print(
                    f"Archive: error reading existing rxlog from {self._rxlog_path}: {exc}"
                )
                # Don't overwrite corrupted file - keep buffer for retry
                return
        
        # Append new entries
        existing_entries.extend(self._rxlog_buffer)
        
        try:
            # Write atomically (temp file + rename)
            self._write_atomic(
                self._rxlog_path,
                {
                    "version": ARCHIVE_VERSION,
                    "address": self._address,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "entries": existing_entries,
                }
            )
            
            self._total_rxlog = len(existing_entries)
            debug_print(
                f"Archive: flushed {len(self._rxlog_buffer)} rxlog entries "
                f"(total: {self._total_rxlog})"
            )
            
            # Clear buffer only after successful write
            self._rxlog_buffer.clear()
            self._last_flush = datetime.now(timezone.utc)
            
        except (OSError) as exc:
            debug_print(f"Archive: error writing rxlog: {exc}")
            # Keep buffer for retry

    def _flush_all(self) -> None:
        """Flush all buffers to disk (MUST be called with lock held)."""
        self._flush_messages()
        self._flush_rxlog()

    def flush(self) -> None:
        """Manually flush all pending writes to disk."""
        with self._lock:
            self._flush_all()

    # ------------------------------------------------------------------
    # Cleanup (retention)
    # ------------------------------------------------------------------

    def cleanup_old_data(self) -> None:
        """Remove messages and rxlog entries older than retention period.
        
        This is intended to be called periodically (e.g., daily) as a
        background task.
        """
        with self._lock:
            # Flush pending writes first
            self._flush_all()
            
            # Cleanup messages
            self._cleanup_messages()
            
            # Cleanup rxlog
            self._cleanup_rxlog()

    def _cleanup_messages(self) -> None:
        """Remove messages older than MESSAGE_RETENTION_DAYS."""
        if not self._messages_path.exists():
            return
        
        try:
            data = json.loads(self._messages_path.read_text(encoding="utf-8"))
            if data.get("version") != ARCHIVE_VERSION:
                return
            
            messages = data.get("messages", [])
            original_count = len(messages)
            
            # Calculate cutoff date
            cutoff = datetime.now(timezone.utc) - timedelta(days=MESSAGE_RETENTION_DAYS)
            
            # Filter messages
            filtered = [
                msg for msg in messages
                if self._is_newer_than(msg.get("timestamp_utc"), cutoff)
            ]
            
            # Write back if anything was removed
            if len(filtered) < original_count:
                data["messages"] = filtered
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._write_atomic(self._messages_path, data)
                
                removed = original_count - len(filtered)
                self._total_messages = len(filtered)
                debug_print(
                    f"Archive: cleanup removed {removed} old messages "
                    f"(retained: {len(filtered)})"
                )
        
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"Archive: error cleaning up messages: {exc}")

    def _cleanup_rxlog(self) -> None:
        """Remove rxlog entries older than RXLOG_RETENTION_DAYS."""
        if not self._rxlog_path.exists():
            return
        
        try:
            data = json.loads(self._rxlog_path.read_text(encoding="utf-8"))
            if data.get("version") != ARCHIVE_VERSION:
                return
            
            entries = data.get("entries", [])
            original_count = len(entries)
            
            # Calculate cutoff date
            cutoff = datetime.now(timezone.utc) - timedelta(days=RXLOG_RETENTION_DAYS)
            
            # Filter entries
            filtered = [
                entry for entry in entries
                if self._is_newer_than(entry.get("timestamp_utc"), cutoff)
            ]
            
            # Write back if anything was removed
            if len(filtered) < original_count:
                data["entries"] = filtered
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._write_atomic(self._rxlog_path, data)
                
                removed = original_count - len(filtered)
                self._total_rxlog = len(filtered)
                debug_print(
                    f"Archive: cleanup removed {removed} old rxlog entries "
                    f"(retained: {len(filtered)})"
                )
        
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"Archive: error cleaning up rxlog: {exc}")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _is_newer_than(self, timestamp_str: Optional[str], cutoff: datetime) -> bool:
        """Check if ISO timestamp is newer than cutoff date."""
        if not timestamp_str:
            return False
        
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            return timestamp > cutoff
        except (ValueError, TypeError):
            return False

    def _write_atomic(self, path: Path, data: Dict) -> None:
        """Write JSON data atomically using temp file + rename."""
        # Ensure directory exists
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Write to temp file
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        
        # Atomic rename
        temp_path.replace(path)

    # ------------------------------------------------------------------
    # Channel name discovery
    # ------------------------------------------------------------------

    def get_distinct_channel_names(self) -> list:
        """Return a sorted list of distinct channel names from archived messages.

        Scans all stored messages and collects unique ``channel_name``
        values.  Empty or missing names are excluded.

        Returns:
            Sorted list of unique channel name strings.
        """
        with self._lock:
            # Flush pending writes so we don't miss recent messages
            self._flush_messages()

            if not self._messages_path.exists():
                return []

            try:
                data = json.loads(
                    self._messages_path.read_text(encoding="utf-8")
                )
                if data.get("version") != ARCHIVE_VERSION:
                    return []

                messages = data.get("messages", [])
                names: set = set()
                for msg in messages:
                    name = msg.get("channel_name", "")
                    if name:
                        names.add(name)

                return sorted(names)

            except (json.JSONDecodeError, OSError) as exc:
                debug_print(
                    f"Archive: error reading distinct channel names: {exc}"
                )
                return []

    # ------------------------------------------------------------------
    # Single message lookup
    # ------------------------------------------------------------------

    def get_message_by_hash(self, message_hash: str) -> Optional[Dict]:
        """Return a single archived message by its message_hash.

        Args:
            message_hash: Hex string packet identifier.

        Returns:
            Message dict, or ``None`` if not found.
        """
        if not message_hash:
            return None

        with self._lock:
            # Flush pending writes so recent messages are searchable
            self._flush_messages()

            if not self._messages_path.exists():
                return None

            try:
                data = json.loads(
                    self._messages_path.read_text(encoding="utf-8")
                )
                if data.get("version") != ARCHIVE_VERSION:
                    return None

                for msg in data.get("messages", []):
                    if msg.get("message_hash") == message_hash:
                        return msg

            except (json.JSONDecodeError, OSError) as exc:
                debug_print(
                    f"Archive: error looking up hash {message_hash[:16]}: "
                    f"{exc}"
                )

        return None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Get archive statistics.
        
        Returns:
            Dict with 'total_messages' and 'total_rxlog' counts.
        """
        with self._lock:
            return {
                "total_messages": self._total_messages,
                "total_rxlog": self._total_rxlog,
                "pending_messages": len(self._message_buffer),
                "pending_rxlog": len(self._rxlog_buffer),
            }

    def get_messages_by_sender_pubkey(
        self, pubkey_prefix: str, limit: int = 50,
    ) -> List[Dict]:
        """Return archived messages whose *sender_pubkey* starts with *pubkey_prefix*.

        Useful for loading Room Server history: room messages are stored
        with ``sender_pubkey`` equal to the room's public-key prefix.

        Args:
            pubkey_prefix: First N hex chars of the sender pubkey to match.
            limit:         Maximum number of messages to return (newest).

        Returns:
            List of message dicts (oldest-first), at most *limit* entries.
        """
        with self._lock:
            # Flush pending writes so we don't miss recent messages
            self._flush_messages()

            if not self._messages_path.exists():
                return []

            try:
                data = json.loads(
                    self._messages_path.read_text(encoding="utf-8")
                )
                if data.get("version") != ARCHIVE_VERSION:
                    return []

                messages = data.get("messages", [])
                norm = pubkey_prefix[:12]

                matched = [
                    msg for msg in messages
                    if (msg.get("sender_pubkey") or "").startswith(norm)
                ]

                # Oldest-first, keep last *limit*
                matched.sort(key=lambda m: m.get("timestamp_utc", ""))
                return matched[-limit:]

            except (json.JSONDecodeError, OSError) as exc:
                debug_print(
                    f"Archive: error querying by pubkey {pubkey_prefix[:12]}: "
                    f"{exc}"
                )
                return []

    def query_messages(
        self,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        channel_name: Optional[str] = None,
        sender: Optional[str] = None,
        text_search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple:
        """Query archived messages with filters.
        
        Args:
            after: Only messages after this timestamp (UTC).
            before: Only messages before this timestamp (UTC).
            channel_name: Filter by channel name (exact match).
            sender: Filter by sender name (case-insensitive substring match).
            text_search: Search in message text (case-insensitive substring match).
            limit: Maximum number of results to return.
            offset: Skip this many results (for pagination).
            
        Returns:
            Tuple of (messages, total_count):
            - messages: List of message dicts matching the filters, newest first
            - total_count: Total number of messages matching filters (for pagination)
        """
        with self._lock:
            # Flush pending writes first
            self._flush_messages()
            
            if not self._messages_path.exists():
                return [], 0
            
            try:
                data = json.loads(self._messages_path.read_text(encoding="utf-8"))
                if data.get("version") != ARCHIVE_VERSION:
                    return [], 0
                
                messages = data.get("messages", [])
                
                # Apply filters
                filtered = []
                for msg in messages:
                    # Time filters
                    if after or before:
                        try:
                            msg_time = datetime.fromisoformat(msg.get("timestamp_utc", ""))
                            if after and msg_time < after:
                                continue
                            if before and msg_time > before:
                                continue
                        except (ValueError, TypeError):
                            continue
                    
                    # Channel name filter (exact match)
                    if channel_name is not None:
                        if msg.get("channel_name", "") != channel_name:
                            continue
                    
                    # Sender filter (case-insensitive substring)
                    if sender:
                        msg_sender = msg.get("sender", "")
                        if sender.lower() not in msg_sender.lower():
                            continue
                    
                    # Text search (case-insensitive substring)
                    if text_search:
                        msg_text = msg.get("text", "")
                        if text_search.lower() not in msg_text.lower():
                            continue
                    
                    filtered.append(msg)
                
                # Sort newest first
                filtered.sort(
                    key=lambda m: m.get("timestamp_utc", ""),
                    reverse=True
                )
                
                total_count = len(filtered)
                
                # Apply pagination
                paginated = filtered[offset:offset + limit]
                
                return paginated, total_count
                
            except (json.JSONDecodeError, OSError) as exc:
                debug_print(f"Archive: error querying messages: {exc}")
                return [], 0
