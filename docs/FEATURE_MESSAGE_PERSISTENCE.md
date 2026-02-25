# Message & Metadata Persistence

**Version:** 1.0  
**Author:** PE1HVH  
**Date:** 2026-02-07

## Overview

This feature implements persistent storage for all incoming messages, RX log entries, and contacts with configurable retention periods. The system uses a dual-layer architecture to balance real-time UI performance with comprehensive data retention.

## Architecture

```
┌─────────────────────────────────────┐
│   SharedData (in-memory buffer)    │
│   - Last 100 messages (UI)          │
│   - Last 50 rx_log (UI)             │
│   - Thread-safe via Lock            │
└──────────────┬──────────────────────┘
               │ (on every add)
               ▼
┌─────────────────────────────────────┐
│   MessageArchive (persistent)        │
│   - All messages (JSON)              │
│   - All rx_log (JSON)                │
│   - Retention filtering              │
│   - Automatic cleanup (daily)        │
│   - Separate Lock (no contention)   │
└─────────────────────────────────────┘
```

### Design Principles

1. **Separation of Concerns**: SharedData handles real-time UI updates, MessageArchive handles persistence
2. **Thread Safety**: Independent locks prevent contention between UI and archiving
3. **Batch Writes**: Buffered writes reduce disk I/O (flushes every 10 items or 60 seconds)
4. **Configurable Retention**: Automatic cleanup based on configurable periods
5. **Backward Compatibility**: SharedData API unchanged, archive is optional

## Storage Format

### Messages Archive
**Location:** `~/.meshcore-gui/archive/<ADDRESS>_messages.json`

```json
{
  "version": 1,
  "address": "literal:AA:BB:CC:DD:EE:FF",
  "last_updated": "2026-02-07T12:34:56.123456Z",
  "messages": [
    {
      "time": "12:34:56",
      "timestamp_utc": "2026-02-07T12:34:56.123456Z",
      "sender": "PE1HVH",
      "text": "Hello mesh!",
      "channel": 0,
      "direction": "in",
      "snr": 8.5,
      "path_len": 2,
      "sender_pubkey": "abc123...",
      "path_hashes": ["a1", "b2"],
      "message_hash": "def456..."
    }
  ]
}
```

### RX Log Archive
**Location:** `~/.meshcore-gui/archive/<ADDRESS>_rxlog.json`

```json
{
  "version": 1,
  "address": "literal:AA:BB:CC:DD:EE:FF",
  "last_updated": "2026-02-07T12:34:56Z",
  "entries": [
    {
      "time": "12:34:56",
      "timestamp_utc": "2026-02-07T12:34:56Z",
      "snr": 8.5,
      "rssi": -95.0,
      "payload_type": "MSG",
      "hops": 2,
      "message_hash": "def456..."
    }
  ]
}
```

**Note:** The `message_hash` field enables correlation between RX log entries and messages. It will be empty for packets that are not messages (e.g., announcements, broadcasts).

## Configuration

Add to `meshcore_gui/config.py`:

```python
# Retention period for archived messages (in days)
MESSAGE_RETENTION_DAYS: int = 30

# Retention period for RX log entries (in days)
RXLOG_RETENTION_DAYS: int = 7

# Retention period for contacts (in days)
CONTACT_RETENTION_DAYS: int = 90
```

## Usage

### Basic Usage

The archive is automatically initialized when SharedData is created with a device identifier (serial port):

```python
from meshcore_gui.core.shared_data import SharedData

# With archive (normal use)
shared = SharedData("literal:AA:BB:CC:DD:EE:FF")

# Without archive (backward compatible)
shared = SharedData()  # archive will be None
```

### Adding Data

All data added to SharedData is automatically archived:

```python
from meshcore_gui.core.models import Message, RxLogEntry

# Add message (goes to both SharedData and archive)
msg = Message(
    time="12:34:56",
    sender="PE1HVH",
    text="Hello!",
    channel=0,
    direction="in",
)
shared.add_message(msg)

# Add RX log entry (goes to both SharedData and archive)
entry = RxLogEntry(
    time="12:34:56",
    snr=8.5,
    rssi=-95.0,
    payload_type="MSG",
    hops=2,
)
shared.add_rx_log(entry)
```

### Getting Statistics

```python
# Get archive statistics
stats = shared.get_archive_stats()
if stats:
    print(f"Total messages: {stats['total_messages']}")
    print(f"Total RX log: {stats['total_rxlog']}")
    print(f"Pending writes: {stats['pending_messages']}")
```

### Manual Flush

Archive writes are normally batched. To force immediate write:

```python
if shared.archive:
    shared.archive.flush()
```

### Manual Cleanup

Cleanup runs automatically daily, but can be triggered manually:

```python
if shared.archive:
    shared.archive.cleanup_old_data()
```

## Performance Characteristics

### Write Performance
- Batch writes: 10 messages or 60 seconds (whichever comes first)
- Write time: ~10ms for 1000 messages
- Memory overhead: Minimal (only buffer in memory, ~10 messages)

### Startup Performance
- Archive loading: <500ms for 10,000 messages
- Archive is counted, not loaded into memory
- No impact on UI responsiveness

### Storage Size
With default retention (30 days messages, 7 days rxlog):
- Typical message: ~200 bytes JSON
- 100 messages/day → ~6KB/day → ~180KB/month
- Expected archive size: <10MB

## Automatic Cleanup

The worker runs cleanup daily (every 86400 seconds):

1. **Message Cleanup**: Removes messages older than `MESSAGE_RETENTION_DAYS`
2. **RxLog Cleanup**: Removes entries older than `RXLOG_RETENTION_DAYS`
3. **Contact Cleanup**: Removes contacts not seen for `CONTACT_RETENTION_DAYS`

Cleanup is non-blocking and runs in the background worker thread.

## Thread Safety

### Lock Ordering
1. SharedData acquires its lock
2. SharedData calls MessageArchive methods
3. MessageArchive acquires its own lock

This ordering prevents deadlocks.

### Concurrent Access
- SharedData lock: Protects in-memory buffers
- MessageArchive lock: Protects file writes and batch buffers
- Independent locks prevent contention

## Error Handling

### Disk Write Failures
- Atomic writes using temp file + rename
- If write fails: buffer retained for retry
- Logged to debug output
- Application continues normally

### Corrupt Archives
- Version checking on load
- Invalid JSON → skip and start fresh
- Corrupted data → logged, not loaded

### Missing Directory
- Archive directory created automatically
- Parent directories created if needed

## Testing

### Unit Tests
```bash
python -m unittest tests.test_message_archive
```

Tests cover:
- Message and RxLog archiving
- Batch write behavior
- Retention cleanup
- Thread safety
- JSON serialization

### Integration Tests
```bash
python -m unittest tests.test_integration_archive
```

Tests cover:
- SharedData + Archive flow
- Buffer limits with archiving
- Persistence across restarts
- Backward compatibility

### Running All Tests
```bash
python -m unittest discover tests
```

## Migration Guide

### From v5.1 to v5.2

No migration needed! The feature is fully backward compatible:

1. Existing SharedData code works unchanged
2. Archive is optional (requires device identifier)
3. First run creates archive files automatically
4. No data loss from existing cache

### Upgrading Existing Installation

```bash
# No special steps needed
python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
```

Archive files will be created automatically on first message/rxlog.

## Future Enhancements (Out of Scope for v1.0)

- Full-text search in archive
- Export to CSV/JSON
- Compression of old messages
- Cloud sync / multi-device sync
- Web interface for archive browsing
- Advanced filtering and queries

## Troubleshooting

### Archive Not Created
**Problem:** No `~/.meshcore-gui/archive/` directory

**Solution:**
- Check that SharedData was initialized with device identifier
- Check disk permissions
- Enable debug mode: `--debug-on`

### Cleanup Not Running
**Problem:** Old messages not removed

**Solution:**
- Cleanup runs every 24 hours
- Manually trigger: `shared.archive.cleanup_old_data()`
- Check retention config values

### High Disk Usage
**Problem:** Archive files growing too large

**Solution:**
- Reduce `MESSAGE_RETENTION_DAYS` in config
- Run manual cleanup
- Check for misconfigured retention values

## Support

For issues or questions:
- GitHub: [PE1HVH/meshcore-gui](https://github.com/PE1HVH/meshcore-gui)
- Email: pe1hvh@example.com

## License

MIT License - Copyright (c) 2026 PE1HVH
