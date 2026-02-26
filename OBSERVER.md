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
- [4. Installation](#4-installation)
  - [4.1. Base Installation (dashboard only)](#41-base-installation-dashboard-only)
  - [4.2. MQTT Uplink Dependencies](#42-mqtt-uplink-dependencies)
  - [4.3. Verify Installation](#43-verify-installation)
- [5. Quick Start](#5-quick-start)
- [6. Command-Line Options](#6-command-line-options)
- [7. Configuration](#7-configuration)
  - [7.1. Observer Settings](#71-observer-settings)
  - [7.2. Port Allocation](#72-port-allocation)
- [8. MQTT Uplink to LetsMesh](#8-mqtt-uplink-to-letsmesh)
  - [8.1. Prerequisites](#81-prerequisites)
  - [8.2. Automatic Key Setup (same machine)](#82-automatic-key-setup-same-machine)
  - [8.3. Manual Key Setup (remote GUI)](#83-manual-key-setup-remote-gui)
  - [8.4. MQTT Configuration](#84-mqtt-configuration)
  - [8.5. Test and Go Live](#85-test-and-go-live)
  - [8.6. Privacy Controls](#86-privacy-controls)
  - [8.7. Multiple Brokers](#87-multiple-brokers)
  - [8.8. How Authentication Works](#88-how-authentication-works)
  - [8.9. MQTT Topics](#89-mqtt-topics)
- [9. systemd Installation](#9-systemd-installation)
- [10. How It Works](#10-how-it-works)
- [11. Dashboard Panels](#11-dashboard-panels)
- [12. Running Alongside Other Daemons](#12-running-alongside-other-daemons)
- [13. Troubleshooting](#13-troubleshooting)
  - [13.1. Dashboard](#131-dashboard)
  - [13.2. MQTT](#132-mqtt)
- [14. Version History](#14-version-history)
- [15. License](#15-license)
- [16. Author](#16-author)

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

**Dashboard (always required):**
- Python 3.10+
- `nicegui`
- `pyyaml`

**MQTT uplink (optional):**
- `paho-mqtt` >= 2.0
- Node.js 18+ with `@michaelhart/meshcore-decoder` — **required** for signing JWT tokens with the orlp/ed25519 algorithm used by LetsMesh

**Note on PyNaCl:** PyNaCl can be used as a fallback for token signing, but **only** with legacy 64-char seed keys. The current `device_identity.json` format uses 128-char orlp/ed25519 expanded keys which are **not compatible** with PyNaCl. For new installations, use Node.js + meshcore-decoder.

Without the MQTT packages the Observer runs fine — only the LetsMesh uplink is disabled.

---

## 4. Installation

### 4.1. Base Installation (dashboard only)

```bash
cd ~/meshcore-gui
source venv/bin/activate

pip install nicegui pyyaml
```

Verify:

```bash
python meshcore_observer.py --help
```

### 4.2. MQTT Uplink Dependencies

**Step 1 — paho-mqtt:**

```bash
pip install paho-mqtt
```

**Step 2 — Node.js (if not already installed):**

```bash
# Check if Node.js is available
node --version

# If not installed (Debian/Ubuntu/Raspberry Pi OS):
sudo apt update && sudo apt install -y nodejs npm
```

**Step 3 — meshcore-decoder:**

```bash
sudo npm install -g @michaelhart/meshcore-decoder
```

**Step 4 — Verify Node.js can find meshcore-decoder:**

```bash
node -e "require('@michaelhart/meshcore-decoder').createAuthToken; console.log('OK')"
```

If this prints `OK`, you're good. If it says `Cannot find module`, Node.js can't find the global install. Fix with:

```bash
# Check where npm installs global packages:
npm root -g

# If it's /usr/local/lib/node_modules, set NODE_PATH:
export NODE_PATH=/usr/local/lib/node_modules
node -e "require('@michaelhart/meshcore-decoder').createAuthToken; console.log('OK')"
```

If you need `NODE_PATH`, add it to your shell profile or systemd service (see [section 9](#9-systemd-installation)).

> **Note:** The Observer auto-detects `NODE_PATH` from `/usr/lib/node_modules`, `/usr/local/lib/node_modules`, and `~/.npm-global/lib/node_modules`. You only need to set it manually if npm uses a non-standard location.

### 4.3. Verify Installation

```bash
cd ~/meshcore-gui
source venv/bin/activate

# Dashboard only:
python -c "import nicegui, yaml; print('Dashboard deps OK')"

# MQTT uplink:
python -c "import paho.mqtt; print('paho-mqtt OK')"
node -e "require('@michaelhart/meshcore-decoder'); console.log('meshcore-decoder OK')"
```

---

## 5. Quick Start

```bash
cd ~/meshcore-gui
source venv/bin/activate

# Run with defaults (dashboard on port 9093, reads ~/.meshcore-gui/archive/)
python meshcore_observer.py
```

The dashboard opens at **http://localhost:9093**. The Observer immediately starts scanning for archive JSON files. If meshcore_gui or meshcore_bridge is running and writing archives, they will appear within seconds.

---

## 6. Command-Line Options

| Flag | Description | Default |
|------|-------------|---------|
| `--config=PATH` | Path to YAML configuration file | `./observer_config.yaml` |
| `--port=PORT` | Override dashboard port | `9093` |
| `--debug-on` | Enable verbose debug logging | Off |
| `--mqtt-dry-run` | Log MQTT payloads without publishing (also enables MQTT) | Off |
| `--help` | Show usage information | — |

Examples:

```bash
python meshcore_observer.py
python meshcore_observer.py --config=/etc/meshcore/observer_config.yaml
python meshcore_observer.py --port=9094 --debug-on
python meshcore_observer.py --mqtt-dry-run --debug-on
```

---

## 7. Configuration

All settings are optional. The Observer works with sensible defaults and no config file.

### 7.1. Observer Settings

**observer_config.yaml:**

```yaml
observer:
  archive_dir: "~/.meshcore-gui/archive"
  poll_interval_s: 2.0
  max_messages_display: 100
  max_rxlog_display: 50

gui:
  port: 9093
  title: "MeshCore Observer"
```

### 7.2. Port Allocation

| Daemon | Default Port |
|---|---|
| meshcore_gui | 8081 / 9090 |
| meshcore_bridge | 9092 |
| **meshcore_observer** | **9093** |

---

## 8. MQTT Uplink to LetsMesh

The Observer can publish RX log packets to the LetsMesh network analyzer at [analyzer.letsmesh.net](https://analyzer.letsmesh.net). MQTT is **disabled by default**.

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

### 8.1. Prerequisites

Before enabling MQTT, ensure:

1. **MQTT dependencies are installed** (see [section 4.2](#42-mqtt-uplink-dependencies))
2. **meshcore_gui has the fixed `device_identity.py`** — version ≥ 1.2.0 that writes the full 128-char orlp/ed25519 private key. Without this fix, `device_identity.json` contains only a 64-char key that is **not the Ed25519 seed** but a clamped scalar, which causes "Not authorized" errors.

   Verify your identity file:
   ```bash
   cat ~/.meshcore-gui/device_identity.json | python -c "
   import json, sys
   d = json.load(sys.stdin)
   pub = d.get('public_key', '')
   priv = d.get('private_key', '')
   print(f'Public key:  {len(pub)} chars — {pub[:16]}...')
   print(f'Private key: {len(priv)} chars')
   if len(priv) == 128:
       print('✅ Correct format (128-char orlp expanded key)')
   elif len(priv) == 64:
       print('❌ Legacy format (64 chars) — update device_identity.py and restart meshcore_gui')
   else:
       print(f'❌ Unexpected length: {len(priv)}')
   "
   ```

3. **Your IATA airport code** — 3-letter code for your nearest airport (e.g. `AMS`, `JFK`, `LHR`)

### 8.2. Automatic Key Setup (same machine)

When meshcore_gui and the Observer run on the **same machine**, keys are shared automatically via `~/.meshcore-gui/device_identity.json`. No manual key configuration needed — just add the MQTT section to your config and the Observer reads the keys at startup.

### 8.3. Manual Key Setup (remote GUI)

When meshcore_gui runs on a **different machine**, you need to transfer the keys.

**Option A — Copy the identity file (recommended):**

Copy `~/.meshcore-gui/device_identity.json` from the GUI machine to the Observer machine, then:

```bash
cd ~/meshcore-gui
source venv/bin/activate
python -m meshcore_observer.setup_mqtt_keys --identity /path/to/device_identity.json
```

This saves the private key to `~/.meshcore-observer-key` (chmod 600) and writes the public key to `observer_config.yaml`.

**Option B — Interactive setup:**

```bash
cd ~/meshcore-gui
source venv/bin/activate
python -m meshcore_observer.setup_mqtt_keys
```

You will need:
- The **public key** (64 hex chars) — visible in meshcore_gui device info
- The **private key** (128 hex chars) — from `device_identity.json` on the GUI machine

**Option C — Environment variable:**

```bash
export MESHCORE_PRIVATE_KEY="<128-char hex private key>"
export MESHCORE_PUBLIC_KEY="<64-char hex public key>"
```

### 8.4. MQTT Configuration

Edit `observer_config.yaml`:

```yaml
mqtt:
  enabled: true
  iata: "AMS"                          # Your nearest airport code
  device_name: "PE1HVH Observer"       # Name shown on analyzer.letsmesh.net

  # Keys — only needed if meshcore_gui runs on a different machine.
  # On the same machine, keys are read from device_identity.json automatically.
  # public_key: "D955E72C..."
  # private_key_file: "~/.meshcore-observer-key"

  brokers:
    - name: "letsmesh-eu"
      server: "mqtt-eu-v1.letsmesh.net"
      port: 443
      transport: "websockets"
      tls: true
      enabled: true

  upload_packet_types: []               # [] = all types
  status_interval_s: 300
  reconnect_delay_s: 10
```

### 8.5. Test and Go Live

**Step 1 — Dry run** (log payloads without publishing):

```bash
python meshcore_observer.py --mqtt-dry-run --debug-on
```

Check the output for:
- `"Loaded device identity from ..."` — keys found
- `"Using Node.js meshcore-decoder for MQTT auth tokens"` — signing works
- `"[DRY RUN] Would connect to ..."` — broker config OK

**Step 2 — Live:**

```bash
python meshcore_observer.py
```

The dashboard MQTT panel shows connection status, packet counters, and any errors. Within minutes your packets should appear on [analyzer.letsmesh.net](https://analyzer.letsmesh.net).

### 8.6. Privacy Controls

Control which packet types are shared:

```yaml
# Only advertisements (network discovery, no message content)
upload_packet_types: [4]

# Advertisements and group text metadata
upload_packet_types: [4, 5]

# Everything (default)
upload_packet_types: []
```

Packet types: 0=REQ, 1=RESPONSE, 2=TXT_MSG, 3=ACK, 4=ADVERT, 5=GRP_TXT, 6=GRP_DATA, 7=ANON_REQ, 8=PATH, 9=TRACE.

The raw packet payload (hex bytes) is always included for shared types. If you do not want to share message content, use `[4]` (ADVERT only).

### 8.7. Multiple Brokers

Publish to EU and US brokers simultaneously for redundancy:

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

### 8.8. How Authentication Works

LetsMesh uses Ed25519 JWT tokens — no registration required. Your device key pair *is* your identity:

1. meshcore_gui exports the device's Ed25519 keypair to `device_identity.json`
2. The Observer generates a JWT signed with the 128-char orlp/ed25519 private key via Node.js meshcore-decoder
3. MQTT username: `v1_{PUBLIC_KEY}` (uppercase, 64 hex chars)
4. MQTT password: the signed JWT token
5. The broker verifies the signature against the public key from the username
6. Topics are scoped to `meshcore/{IATA}/{PUBLIC_KEY}/`
7. Tokens auto-refresh before expiry (default 1 hour)

**Key format:** The private key in `device_identity.json` is 128 hex chars (64 bytes) in orlp/ed25519 expanded format: `[clamped_scalar(32)][nonce_prefix(32)]`. This is **not** a seed+pubkey concatenation — it is the output of `SHA-512(seed)` with clamping. The public key comes from `send_appstart()` and is stored separately.

### 8.9. MQTT Topics

| Topic | Content | QoS | Retained |
|---|---|---|---|
| `meshcore/{IATA}/{KEY}/packets` | RX log entries (JSON) | 0 | No |
| `meshcore/{IATA}/{KEY}/status` | Online/offline status | 1 | Yes |

The status topic uses MQTT Last Will and Testament (LWT): if the Observer disconnects unexpectedly, the broker automatically publishes an offline status.

---

## 9. systemd Installation

For running the Observer as a background service on Linux.

**Install:**

```bash
cd ~/meshcore-gui
source venv/bin/activate

bash install_scripts/install_observer.sh
```

The installer detects the venv and current user automatically, creates a systemd service, and offers to start it immediately.

**If you need a custom NODE_PATH** (see [section 4.2](#42-mqtt-uplink-dependencies)), edit the service file after installation:

```bash
sudo systemctl edit meshcore-observer
```

Add:

```ini
[Service]
Environment="NODE_PATH=/usr/local/lib/node_modules"
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart meshcore-observer
```

**Service commands:**

| Command | Description |
|---------|-------------|
| `sudo systemctl start meshcore-observer` | Start the service |
| `sudo systemctl stop meshcore-observer` | Stop the service |
| `sudo systemctl restart meshcore-observer` | Restart after config change |
| `sudo systemctl status meshcore-observer` | Check status |
| `sudo journalctl -u meshcore-observer -f` | Follow live logs |

**Uninstall:**

```bash
cd ~/meshcore-gui
bash install_scripts/install_observer.sh --uninstall
```

---

## 10. How It Works

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

## 11. Dashboard Panels

### Sources
Table of all detected archive files with source name, message count, and RX log count.

### Messages
Aggregated message feed from all sources. Newest messages on top. Filterable by source and channel.

### RX Log
Aggregated packet log from all sources. Columns: Time, Source, SNR, RSSI, Type, Hops, Path, Hash.

### Statistics
Observer uptime, total messages and RX log entries seen, number of active sources, per-source breakdown.

### MQTT Uplink
Connection status per broker (green/red dot), total packets published, filtered count, skipped count, last publish timestamp, and any errors.

---

## 12. Running Alongside Other Daemons

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

All three can run simultaneously. The Observer only reads atomically-written files and never interferes with the other daemons.

---

## 13. Troubleshooting

### 13.1. Dashboard

**"Waiting for archive files..."**
- Verify meshcore_gui or meshcore_bridge is running and has received at least one message
- Check: `ls ~/.meshcore-gui/archive/`
- If using a custom path, verify `archive_dir` in your config

**No messages despite archive files existing**
- Check file permissions
- Run with `--debug-on`
- Verify archive files have `"version": 1` in their JSON

**Port conflict**
- Change with `--port=9094` or in `observer_config.yaml`

### 13.2. MQTT

**"Not authorized" (rc=5)**

This is almost always a key format issue. Check in order:

1. **Is the private key 128 chars?**
   ```bash
   python -c "
   import json
   d = json.load(open('$HOME/.meshcore-gui/device_identity.json'))
   print(f\"private_key length: {len(d.get('private_key',''))}\")" 
   ```
   If 64: you need the fixed `device_identity.py` in meshcore_gui. Deploy it and restart meshcore_gui.

2. **Does the public key match the GUI?**
   The `public_key` in `device_identity.json` must match what meshcore_gui shows under device info (uppercase hex). If it doesn't, the identity file was written by a buggy version — deploy the fix and restart.

3. **Is meshcore-decoder available?**
   ```bash
   node -e "require('@michaelhart/meshcore-decoder').createAuthToken; console.log('OK')"
   ```
   If this fails, see [section 4.2](#42-mqtt-uplink-dependencies).

4. **Run with debug:**
   ```bash
   python meshcore_observer.py --mqtt-dry-run --debug-on
   ```
   Look for `"Node.js token generation failed"` or `"PyNaCl"` fallback messages.

**"Connecting..." but never connects**
- Check firewall allows outbound connections to port 443
- Try the US broker: change `server` to `mqtt-us-v1.letsmesh.net`
- Check DNS resolution: `nslookup mqtt-eu-v1.letsmesh.net`

**Packets not appearing on analyzer.letsmesh.net**
- Use `--mqtt-dry-run` to verify payload format
- Check `upload_packet_types` is not filtering everything
- Verify archive files contain `raw_payload` data
- The analyzer may take a few minutes to index new nodes

**"PyNaCl fallback requires a 64-char Ed25519 seed"**
- Node.js meshcore-decoder is not available, and the private key is 128 chars
- Solution: install meshcore-decoder (see [section 4.2](#42-mqtt-uplink-dependencies))

---

## 14. Version History

| Version | Date | Description |
|---|---|---|
| 1.2.0 | 2026-02-26 | Fix: 128-char orlp/ed25519 private key support, NODE_PATH auto-detection, improved key validation |
| 1.1.0 | 2026-02-26 | Fase 2: MQTT uplink to LetsMesh (WebSocket+TLS, Ed25519 JWT, privacy filter) |
| 1.0.0 | 2026-02-26 | Fase 1: Read-only archive monitor dashboard |

---

## 15. License

MIT License — see LICENSE file

## 16. Author

**PE1HVH** — [GitHub](https://github.com/pe1hvh)
