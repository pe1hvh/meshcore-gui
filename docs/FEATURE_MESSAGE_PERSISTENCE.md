# Message & Metadata Persistence

**Version:** 1.0  
**Author:** PE1HVH  
**Date:** 2026-02-07

## Overview

This feature implements persistent storage for all incoming messages, RX log entries, and contacts with configurable retention periods. The system uses a dual-layer architecture to balance real-time UI performance with comprehensive data retention.

The architectural decision (why two layers, why independent locks, lock-ordering rules, schema-evolution policy) is recorded in **`docs/adr/ADR-005-dual-layer-persistence.md`**. This document is the feature reference: storage format, API, performance, testing.

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
│   - rx_log stream (JSONL, unbuffered)│
│   - Retention filtering              │
│   - Automatic cleanup (daily)        │
│   - Separate Lock (no contention)   │
└─────────────────────────────────────┘
```

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
      "date": "2026-02-07",
      "timestamp_utc": "2026-02-07T12:34:56.123456Z",
      "sender": "PE1HVH",
      "text": "Hello mesh!",
      "channel": 0,
      "channel_name": "Public",
      "direction": "in",
      "snr": 8.5,
      "path_len": 2,
      "sender_pubkey": "abc123...",
      "path_hashes": ["a1", "b2"],
      "path_names": ["Repeater A", "Repeater B"],
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
      "message_hash": "def456...",
      "path_hashes": ["a1", "b2"],
      "path_names": ["Repeater A", "Repeater B"],
      "sender": "PE1HVH",
      "receiver": "",
      "raw_payload": "15023a...",
      "packet_len": 64,
      "payload_len": 48,
      "route_type": "F",
      "packet_type_num": 5
    }
  ]
}
```

**Note:** The `message_hash` field enables correlation between RX log entries and messages. It will be empty for packets that are not messages (e.g., announcements, broadcasts).

### RX Log Stream (JSONL)
**Location:** `~/.meshcore-gui/archive/<ADDRESS>_rxlog.jsonl`

Every RX log entry is also appended to this file immediately, one JSON object per line, with the same fields as an entry in `<ADDRESS>_rxlog.json`. The write is direct — no batch buffer — so the line appears within a second of reception. It is a real-time source for separate local services that want the raw RX feed without depending on the batched JSON file.

- The batched `<ADDRESS>_rxlog.json` archive is unchanged and remains the source for the GUI, the REST API and the archive viewer.
- A failed append is logged via `debug_print` and does not affect the batched archive; the two paths are independent.
- Daily cleanup rewrites the stream file with the same `RXLOG_RETENTION_DAYS` cutoff. Corrupt lines (for example a partial last line after a crash) are skipped during cleanup.

## Configuration

Add to `meshcore_gui/config.py`:

```python
# Retention period for archived messages (in days)
MESSAGE_RETENTION_DAYS: int = 30

# Retention period for RX log entries (in days)
RXLOG_RETENTION_DAYS: int = 14

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
With default retention (30 days messages, 14 days rxlog):
- Typical message: ~200 bytes JSON
- 100 messages/day → ~6KB/day → ~180KB/month
- Expected archive size: <10MB

## Automatic Cleanup

The worker runs cleanup daily (every 86400 seconds):

1. **Message Cleanup**: Removes messages older than `MESSAGE_RETENTION_DAYS`
2. **RxLog Cleanup**: Removes entries older than `RXLOG_RETENTION_DAYS` from both `<ADDRESS>_rxlog.json` and the `<ADDRESS>_rxlog.jsonl` stream
3. **Contact Cleanup**: Removes contacts not seen for `CONTACT_RETENTION_DAYS`

Cleanup is non-blocking and runs in the background worker thread.

## Thread Safety

Lock-ordering rules (SharedData → MessageArchive) and the rationale for
two independent locks are documented in
**`docs/adr/ADR-005-dual-layer-persistence.md`**.

In short:
- SharedData lock protects in-memory buffers
- MessageArchive lock protects file writes and batch buffers
- Locks are independent — no contention between UI and archiving

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
