# MeshCore Observer — Read-Only Archive Monitor
### Multi-source aggregation dashboard with optional MQTT uplink to LetsMesh.
![Status](https://img.shields.io/badge/Status-Production-green.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-orange.svg)
![Device](https://img.shields.io/badge/Device-None%20Required-blueviolet.svg)
![MQTT](https://img.shields.io/badge/MQTT-LetsMesh%20Uplink-ff6600.svg)

A standalone daemon that reads JSON archive files produced by `meshcore_gui` and `meshcore_bridge`, aggregates them from all sources, and presents a unified live dashboard. It never connects to a device and never writes to the archive — it only watches and displays.

## Table of Contents

- [1. Why This Project Exists](#1-why-this-project-exists)
- [2. Features](#2-features)
- [3. Requirements](#3-requirements)
- [4. Quick Start](#4-quick-start)
- [5. Command-Line Options](#5-command-line-options)
- [6. Configuration](#6-configuration)
  - [6.1. Observer Settings](#61-observer-settings)
  - [6.2. Port Allocation](#62-port-allocation)
- [7. MQTT Uplink to LetsMesh](#7-mqtt-uplink-to-letsmesh)
  - [7.1. What You Need](#71-what-you-need)
  - [7.2. Setup](#72-setup)
  - [7.3. Privacy Controls](#73-privacy-controls)
  - [7.4. Multiple Brokers](#74-multiple-brokers)
  - [7.5. How Authentication Works](#75-how-authentication-works)
  - [7.6. MQTT Topics](#76-mqtt-topics)
- [8. systemd Installation](#8-systemd-installation)
- [9. How It Works](#9-how-it-works)
- [10. Dashboard Panels](#10-dashboard-panels)
- [11. Running Alongside Other Daemons](#11-running-alongside-other-daemons)
- [12. Troubleshooting](#12-troubleshooting)
  - [12.1. Dashboard](#121-dashboard)
  - [12.2. MQTT](#122-mqtt)
- [13. Version History](#13-version-history)
- [14. License](#14-license)
- [15. Author](#15-author)

---

## 1. Why This Project Exists

When running multiple MeshCore devices — a GUI instance on 869 MHz, a bridge between 869 and 868 MHz, perhaps another GUI on a different frequency — each writes its own archive files. There is no single place to see all traffic at once.

The Observer solves this by watching all archive files from all sources, merging them into one live dashboard. It requires no device, no serial port and no meshcore library. Just point it at the archive directory and it works.

With MQTT uplink enabled, the Observer can also contribute your node's received packets to the global [LetsMesh analyzer](https://analyzer.letsmesh.net), helping map the mesh network's reach and signal quality.

```
[meshcore_gui]  ──writes──►  ~/.meshcore-gui/archive/*.json  ◄──reads──  [Observer]
[meshcore_bridge] ──writes──►                                                 │
                                                                         ┌────┴────┐
                                                                         ▼         ▼
                                                                   NiceGUI    MQTT Uplink
                                                                   Dashboard  (optional)
                                                                   :9093      │
                                                                              ▼
                                                                    analyzer.letsmesh.net
```

## 2. Features

- **Multi-source aggregation** — Automatically detects and merges archives from all GUI and Bridge instances
- **Live message feed** — Channel messages from all sources, sorted by timestamp, filterable by source and channel
- **Live RX log** — Packet log with SNR, RSSI, type, hops, and decoded path
- **Source overview** — Table of all detected archive files with entry counts
- **Statistics** — Uptime, totals, per-source breakdown
- **MQTT uplink to LetsMesh** — Publishes RX log packets to [analyzer.letsmesh.net](https://analyzer.letsmesh.net) via MQTT over WebSocket+TLS with Ed25519 JWT authentication. Privacy-configurable: choose which packet types to share
- **DOMCA theme** — Dark and light mode, consistent with meshcore_gui and meshcore_bridge
- **Zero device access** — No serial port, no BLE, no meshcore library required

## 3. Requirements

- Python 3.10+
- `nicegui` (pip install nicegui)
- `pyyaml` (pip install pyyaml)

**Additional for MQTT uplink (optional):**
- `paho-mqtt` >= 2.0 (pip install paho-mqtt)
- `PyNaCl` >= 1.5 (pip install PyNaCl)

Without the MQTT packages the Observer runs fine — only the LetsMesh uplink is disabled. No `meshcore` library, no `meshcoredecoder`, no USB devices.

## 4. Quick Start

The Observer is included in the meshcore-gui repository. No separate download or extraction needed.

```bash
# 1. Navigate to the project
cd ~/meshcore-gui
source venv/bin/activate

# 2. Install dependencies (if not already installed for meshcore_gui)
pip install nicegui pyyaml

# Optional: for MQTT uplink to LetsMesh
pip install paho-mqtt PyNaCl

# 3. Run
python meshcore_observer.py

# 4. (Optional) Custom configuration
python meshcore_observer.py --config=observer_config.yaml
```

The dashboard opens at **http://localhost:9093**. The Observer will immediately start scanning `~/.meshcore-gui/archive/` for JSON files. If meshcore_gui or meshcore_bridge is running and writing archives, they will appear within seconds.

## 5. Command-Line Options

| Flag | Description | Default |
|------|-------------|---------|
| `--config=PATH` | Path to YAML configuration file | `./observer_config.yaml` |
| `--port=PORT` | Override dashboard port | `9093` |
| `--debug-on` | Enable verbose debug logging | Off |
| `--mqtt-dry-run` | Log MQTT payloads without publishing (also enables MQTT) | Off |
| `--help` | Show usage information | — |

All flags are optional and can be combined in any order:

```bash
# Default — scan ~/.meshcore-gui/archive/, dashboard on port 9093
python meshcore_observer.py

# Custom config
python meshcore_observer.py --config=/etc/meshcore/observer_config.yaml

# Different port with debug logging
python meshcore_observer.py --port=9094 --debug-on

# Test MQTT payload format without connecting to a broker
python meshcore_observer.py --mqtt-dry-run --debug-on
```

---

## 6. Configuration

All settings are optional. The Observer works with sensible defaults and no config file.

### 6.1. Observer Settings

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

### 6.2. Port Allocation

| Daemon | Default Port |
|---|---|
| meshcore_gui | 8081 / 9090 |
| meshcore_bridge | 9092 |
| **meshcore_observer** | **9093** |

---

## 7. MQTT Uplink to LetsMesh

The Observer can publish RX log packet data to the LetsMesh network analyzer at [analyzer.letsmesh.net](https://analyzer.letsmesh.net). This allows your node to contribute to the global mesh network map — other operators can see your node's received packets, signal quality, and routing paths.

MQTT is **disabled by default** and requires explicit configuration.

```
[Observer]
    │
    │ RX log entries from archive
    │
    ├── filter by packet type (privacy)
    ├── transform to LetsMesh JSON format
    ├── sign JWT with Ed25519 private key
    │
    └──► mqtt-eu-v1.letsmesh.net:443 (WebSocket+TLS)
              │
              ▼
         analyzer.letsmesh.net
```

### 7.1. What You Need

1. **Your device's public key** — 64-character hex string, visible in meshcore_gui under device info
2. **Your device's private key** — 64-character hex string, needed for authentication signing
3. **An IATA airport code** — 3-letter code for your nearest airport (e.g. `AMS`, `JFK`, `LHR`) — this places your node on the map

### 7.2. Setup

**Step 1 — Install MQTT dependencies:**

```bash
cd ~/meshcore-gui
source venv/bin/activate
pip install paho-mqtt PyNaCl
```

**Step 2 — Get your device keys:**

Your device public and private keys can be found in the MeshCore firmware or companion app. The public key is the 64-character hex identifier of your device — it is shown in meshcore_gui on the device info page.

The private key is used only for signing authentication tokens. It never leaves your machine and is never sent to the broker.

**Step 3 — Store the private key securely:**

The recommended approach is a dedicated key file with restricted permissions:

```bash
# Create key file
echo "your_64_char_hex_private_key_here" > ~/.meshcore-observer-key
chmod 600 ~/.meshcore-observer-key
```

Alternatively, use an environment variable:

```bash
export MESHCORE_PRIVATE_KEY="your_64_char_hex_private_key_here"
```

**Step 4 — Configure MQTT:**

Edit `observer_config.yaml` and add the `mqtt:` section:

```yaml
mqtt:
  enabled: true
  iata: "AMS"                          # Your nearest airport code (3 letters)

  public_key: "A1B2C3D4...64chars"     # Your device public key
  device_name: "PE1HVH Observer"       # Name shown on analyzer.letsmesh.net

  # Private key — pick ONE method:
  private_key_file: "~/.meshcore-observer-key"   # Recommended
  # private_key: ""                              # Inline (not recommended)
  # Or set MESHCORE_PRIVATE_KEY env var          # Also good

  brokers:
    - name: "letsmesh-eu"
      server: "mqtt-eu-v1.letsmesh.net"
      port: 443
      transport: "websockets"
      tls: true
      enabled: true

    - name: "letsmesh-us"
      server: "mqtt-us-v1.letsmesh.net"
      port: 443
      transport: "websockets"
      tls: true
      enabled: false                    # Enable if you want US mirror too

  # Privacy: which packet types to upload (empty = ALL)
  # 0=REQ, 1=RESPONSE, 2=TXT_MSG, 3=ACK, 4=ADVERT,
  # 5=GRP_TXT, 6=GRP_DATA, 7=ANON_REQ, 8=PATH, 9=TRACE
  upload_packet_types: []               # [] = everything

  status_interval_s: 300                # Status republish every 5 min
  reconnect_delay_s: 10
```

**Step 5 — Test with dry-run:**

Before going live, verify your payload format without actually publishing:

```bash
python meshcore_observer.py --mqtt-dry-run --debug-on
```

This logs every packet that *would* be published, including the full JSON payload, so you can verify the format matches what LetsMesh expects. No data is sent to any broker.

**Step 6 — Go live:**

```bash
python meshcore_observer.py
```

The dashboard MQTT panel shows connection status, packet counters, and any errors. Within minutes your packets should appear on [analyzer.letsmesh.net](https://analyzer.letsmesh.net).

### 7.3. Privacy Controls

You control exactly which packet types are shared. Set `upload_packet_types` in your config:

```yaml
# Only share advertisements (network discovery, no message content)
upload_packet_types: [4]

# Share advertisements and group text metadata
upload_packet_types: [4, 5]

# Share everything (default)
upload_packet_types: []
```

Note that the raw packet payload (hex bytes) is always included for shared types — this is required by the LetsMesh analyzer for protocol analysis. If you do not want to share message content, limit the types to `[4]` (ADVERT only).

Entries from older archive files that do not contain `raw_payload` data are automatically skipped.

### 7.4. Multiple Brokers

You can publish to both EU and US brokers simultaneously for redundancy:

```yaml
brokers:
  - name: "letsmesh-eu"
    server: "mqtt-eu-v1.letsmesh.net"
    port: 443
    transport: "websockets"
    tls: true
    enabled: true

  - name: "letsmesh-us"
    server: "mqtt-us-v1.letsmesh.net"
    port: 443
    transport: "websockets"
    tls: true
    enabled: true
```

### 7.5. How Authentication Works

LetsMesh uses Ed25519 JWT tokens for authentication — no account registration required. Your device key pair *is* your identity:

1. The Observer generates a JWT token signed with your Ed25519 private key
2. The MQTT username is `v1_{PUBLIC_KEY}` (your 64-char hex public key)
3. The MQTT password is the signed JWT token
4. The broker verifies the signature against your public key
5. You can only publish to topics under `meshcore/{IATA}/{PUBLIC_KEY}/`
6. Tokens auto-refresh before expiry (default 1 hour lifetime)

No registration, no email, no API keys — if you have your device keys, you can publish.

### 7.6. MQTT Topics

The Observer publishes to two topics:

| Topic | Content | QoS | Retained |
|---|---|---|---|
| `meshcore/{IATA}/{KEY}/packets` | RX log entries (JSON) | 0 | No |
| `meshcore/{IATA}/{KEY}/status` | Online/offline status | 1 | Yes |

The status topic uses MQTT Last Will and Testament (LWT): if the Observer disconnects unexpectedly, the broker automatically publishes an offline status.

---

## 8. systemd Installation

For running the Observer as a background service on Linux. The installer uses the project's virtual environment and runs from the project directory — just like meshcore_gui and meshcore_bridge.

**Install:**

```bash
cd ~/meshcore-gui
source venv/bin/activate

# Ensure dependencies are installed in the venv
pip install nicegui pyyaml

# Optional: for MQTT uplink
pip install paho-mqtt PyNaCl

# Run the installer
bash install_observer.sh
```

The installer will:
1. Detect the venv and current user automatically
2. Optionally use `observer_config.yaml` from the project directory
3. Create a systemd service that runs `meshcore_observer.py` using the venv Python
4. Ask whether to enable debug logging and start the service immediately

**Configure and start:**

```bash
# Edit configuration (optional, defaults work without config)
nano ~/meshcore-gui/observer_config.yaml

# Start the service
sudo systemctl start meshcore-observer

# Enable auto-start on boot
sudo systemctl enable meshcore-observer

# Check status
sudo systemctl status meshcore-observer

# Follow logs
journalctl -u meshcore-observer -f
```

**Useful service commands:**

| Command | Description |
|---------|-------------|
| `sudo systemctl status meshcore-observer` | Check if the service is running |
| `sudo journalctl -u meshcore-observer -f` | Follow the live log output |
| `sudo systemctl restart meshcore-observer` | Restart after a configuration change |
| `sudo systemctl stop meshcore-observer` | Stop the service |

**Uninstall:**

```bash
cd ~/meshcore-gui
bash install_observer.sh --uninstall
```

This removes the systemd service. The project files and configuration remain untouched.

---

## 9. How It Works

The Observer uses a polling-based file watcher (`ArchiveWatcher`) that:

1. Scans the archive directory for `*_messages.json` and `*_rxlog.json` files
2. Checks each file's `mtime` (modification timestamp)
3. If unchanged since last poll → skip (no disk I/O)
4. If changed → read, parse, extract only new entries (delta detection)
5. Feeds new entries to the dashboard panels (and optionally to MQTT uplink)

This is efficient and safe:
- **No file locking conflicts** — meshcore_gui uses atomic writes (temp file + rename)
- **No race conditions** — Observer only reads completed files
- **No crash on corruption** — Malformed JSON is logged and skipped
- **No crash on missing files** — Vanished files are removed from tracking

---

## 10. Dashboard Panels

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

### MQTT Uplink
Connection status per broker (green/red dot), total packets published, filtered count, skipped count, last publish timestamp, and any errors. Shows "MQTT is disabled" when not configured.

---

## 11. Running Alongside Other Daemons

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
│  :9093            │──────► mqtt-eu-v1.letsmesh.net
│  reads archive    │        (optional MQTT uplink)
└──────────────────┘
```

All three can run simultaneously on the same machine. The Observer never interferes with the other daemons because it only reads files that are atomically written.

---

## 12. Troubleshooting

### 12.1. Dashboard

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

### 12.2. MQTT

**Dashboard shows "Connecting..."**
- Verify your public and private keys are correct (64 hex chars each)
- Check that `paho-mqtt` and `PyNaCl` are installed
- Run with `--debug-on` for detailed connection logs

**"Connection refused" error**
- Verify your key pair is valid — the private key must match the public key
- Check firewall allows outbound connections to port 443
- Try the US broker if the EU one is unreachable

**Packets not appearing on analyzer.letsmesh.net**
- Use `--mqtt-dry-run` first to verify payload format
- Check that `upload_packet_types` is not filtering everything
- Verify your archive files contain `raw_payload` data
- The analyzer may take a few minutes to index new nodes

---

## 13. Version History

| Version | Date | Description |
|---|---|---|
| 1.1.0 | 2026-02-26 | Fase 2: MQTT uplink to LetsMesh (WebSocket+TLS, Ed25519 JWT, privacy filter) |
| 1.0.0 | 2026-02-26 | Fase 1: Read-only archive monitor dashboard |

---

## 14. License

MIT License — see LICENSE file

## 15. Author

**PE1HVH** — [GitHub](https://github.com/pe1hvh)
