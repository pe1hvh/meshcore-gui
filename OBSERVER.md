# MeshCore Observer

**Read-only archive monitor dashboard for MeshCore mesh networks.**

The Observer is a standalone daemon that reads the JSON archive files produced by `meshcore_gui` and `meshcore_bridge`, aggregates them from all sources, and presents a unified live dashboard. It never connects to a device and never writes to the archive — it only watches and displays.

```
[meshcore_gui]  ──writes──►  ~/.meshcore-gui/archive/*.json  ◄──reads──  [Observer]
[meshcore_bridge] ──writes──►                                                 │
                                                                         ▼
                                                                  NiceGUI Dashboard
                                                                  http://localhost:9093
```

---

## Features

- **Multi-source aggregation** — Automatically detects and merges archives from all GUI and Bridge instances.
- **Live message feed** — Channel messages from all sources, sorted by timestamp, filterable by source and channel.
- **Live RX log** — Packet log with SNR, RSSI, type, hops, and decoded path.
- **Source overview** — Table of all detected archive files with entry counts.
- **Statistics** — Uptime, totals, per-source breakdown.
- **DOMCA theme** — Dark and light mode, consistent with meshcore_gui and meshcore_bridge.
- **Zero device access** — No serial port, no BLE, no meshcore library required.

---

## Requirements

- Python 3.10+
- `nicegui` (pip install nicegui)
- `pyyaml` (pip install pyyaml)

That's it. No `meshcore` library, no `meshcoredecoder`, no USB devices.

---

## Quick Start

### 1. Extract

```bash
unzip meshcore_observer.zip -d /path/to/meshcore-observer
cd /path/to/meshcore-observer
```

### 2. Install dependencies

```bash
pip install nicegui pyyaml
```

### 3. Run

```bash
python meshcore_observer.py
```

The dashboard opens at **http://localhost:9093**.

The Observer will immediately start scanning `~/.meshcore-gui/archive/` for JSON files. If meshcore_gui or meshcore_bridge is running and writing archives, they will appear within seconds.

### 4. (Optional) Custom configuration

```bash
python meshcore_observer.py --config=observer_config.yaml
```

---

## Command-Line Options

| Option | Description | Default |
|---|---|---|
| `--config=PATH` | Path to YAML configuration file | `./observer_config.yaml` |
| `--port=PORT` | Override dashboard port | `9093` |
| `--debug-on` | Enable verbose debug logging | Off |
| `--help` | Show usage information | — |

**Examples:**

```bash
# Default — scan ~/.meshcore-gui/archive/, dashboard on port 9093
python meshcore_observer.py

# Custom config
python meshcore_observer.py --config=/etc/meshcore/observer_config.yaml

# Different port with debug logging
python meshcore_observer.py --port=9094 --debug-on
```

---

## Configuration

All settings are optional. The Observer works with sensible defaults and no config file.

**observer_config.yaml:**

```yaml
observer:
  # Path to archive directory (where meshcore_gui/bridge write JSON files)
  archive_dir: "~/.meshcore-gui/archive"

  # How often to check for changes (seconds)
  poll_interval_s: 2.0

  # Maximum entries displayed in dashboard
  max_messages_display: 100
  max_rxlog_display: 50

gui:
  # Dashboard port (must not conflict with GUI or Bridge)
  port: 9093
  title: "MeshCore Observer"
```

### Port Allocation

| Daemon | Default Port |
|---|---|
| meshcore_gui | 8081 / 9090 |
| meshcore_bridge | 9092 |
| **meshcore_observer** | **9093** |

---

## systemd Installation

For running the Observer as a background service on Linux:

### Install

```bash
sudo bash install_observer.sh
```

This will:
1. Copy `meshcore_observer.py` and `meshcore_observer/` to `/opt/meshcore-observer/`
2. Install config template to `/etc/meshcore/observer_config.yaml` (preserves existing)
3. Create systemd service `meshcore-observer.service`

### Configure and start

```bash
# Edit configuration
sudo nano /etc/meshcore/observer_config.yaml

# Start the service
sudo systemctl start meshcore-observer

# Enable auto-start on boot
sudo systemctl enable meshcore-observer

# Check status
sudo systemctl status meshcore-observer

# Follow logs
journalctl -u meshcore-observer -f
```

### Uninstall

```bash
sudo bash install_observer.sh --uninstall
```

This removes the application and service file. Configuration at `/etc/meshcore/` is preserved.

---

## How It Works

The Observer uses a polling-based file watcher (`ArchiveWatcher`) that:

1. Scans the archive directory for `*_messages.json` and `*_rxlog.json` files
2. Checks each file's `mtime` (modification timestamp)
3. If unchanged since last poll → skip (no disk I/O)
4. If changed → read, parse, extract only new entries (delta detection)
5. Feeds new entries to the dashboard panels

This is efficient and safe:
- **No file locking conflicts** — meshcore_gui uses atomic writes (temp file + rename)
- **No race conditions** — Observer only reads completed files
- **No crash on corruption** — Malformed JSON is logged and skipped
- **No crash on missing files** — Vanished files are removed from tracking

---

## Dashboard Panels

### Sources
Table of all detected archive files with source name, message count, and RX log count.

### Messages
Aggregated message feed from all sources. Newest messages on top. Filterable by:
- **Source** — Show only messages from a specific GUI/Bridge instance
- **Channel** — Show only messages from a specific channel

### RX Log
Aggregated packet log from all sources. Columns: Time, Source, SNR, RSSI, Type, Hops, Path, Hash.

### Statistics
Observer uptime, total messages and RX log entries seen, number of active sources, and per-source breakdown.

---

## Running Alongside Other Daemons

The Observer is designed to coexist with meshcore_gui and meshcore_bridge:

```
┌──────────────────┐     ┌──────────────────┐
│  meshcore_gui    │     │ meshcore_bridge   │
│  :8081           │     │  :9092            │
│  writes archive  │     │  writes archive   │
└────────┬─────────┘     └────────┬──────────┘
         │                        │
         ▼                        ▼
    ~/.meshcore-gui/archive/
         │
         ▼
┌──────────────────┐
│ meshcore_observer │
│  :9093            │
│  reads archive    │
└──────────────────┘
```

All three can run simultaneously on the same machine. The Observer never interferes with the other daemons because it only reads files that are atomically written.

---

## Troubleshooting

**Dashboard shows "Waiting for archive files..."**
- Verify that meshcore_gui or meshcore_bridge is running and has received at least one message
- Check that the archive directory exists: `ls ~/.meshcore-gui/archive/`
- If using a custom path, verify `archive_dir` in your config

**No messages appearing despite archive files existing**
- Check file permissions — the Observer process must be able to read the archive files
- Run with `--debug-on` for verbose logging
- Verify archive files have `"version": 1` in their JSON

**Port conflict on startup**
- Another service is using port 9093
- Change with `--port=9094` or in `observer_config.yaml`

---

## Version History

| Version | Date | Description |
|---|---|---|
| 1.0.0 | 2026-02-26 | Initial release — Fase 1: read-only archive monitor |

---

*Author: PE1HVH — SPDX-License-Identifier: MIT*
