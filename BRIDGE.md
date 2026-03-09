# MeshCore Bridge — Cross-Frequency Message Bridge
### No MQTT, no broker, no cloud. Just LoRa ↔ LoRa.
![Status](https://img.shields.io/badge/Status-Production-green.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-orange.svg)
![Transport](https://img.shields.io/badge/Transport-Dual%20USB%20Serial-blueviolet.svg)
![Bridge](https://img.shields.io/badge/Bridge-Cross--Frequency%20LoRa%20↔%20LoRa-ff6600.svg)

A standalone daemon that connects two MeshCore devices operating on different radio frequencies. It forwards messages on a configurable bridge channel from one device to the other, effectively extending your mesh network across frequency boundaries.

## Table of Contents

- [1. Overview](#1-overview)
- [2. Features](#2-features)
- [3. Requirements](#3-requirements)
  - [3.1. Requirement Status](#31-requirement-status)
- [4. Installation](#4-installation)
  - [4.1. Quick Start](#41-quick-start)
  - [4.2. systemd Service](#42-systemd-service)
- [5. Configuration](#5-configuration)
  - [5.1. Bridge Settings](#51-bridge-settings)
  - [5.2. Command-Line Options](#52-command-line-options)
- [6. How It Works](#6-how-it-works)
  - [6.1. Message Flow](#61-message-flow)
  - [6.2. Loop Prevention](#62-loop-prevention)
  - [6.3. Private (Encrypted) Channels](#63-private-encrypted-channels)
- [7. Dashboard](#7-dashboard)
- [8. File Structure](#8-file-structure)
- [9. Assumptions](#9-assumptions)
- [10. Troubleshooting](#10-troubleshooting)
  - [10.1. Bridge Won't Start](#101-bridge-wont-start)
  - [10.2. Messages Not Forwarding](#102-messages-not-forwarding)
  - [10.3. Port Conflicts](#103-port-conflicts)
  - [10.4. Service Issues](#104-service-issues)
- [11. License](#11-license)
- [12. Author](#12-author)

---

## 1. Overview

The bridge runs as an independent process alongside (or instead of) the regular meshcore_gui instances. It imports the existing meshcore_gui modules (SharedData, Worker, models, config) as a library and requires **zero modifications** to the meshcore_gui codebase.

```
┌───────────────────────────────────────────┐
│           meshcore_bridge daemon           │
│                                           │
│  ┌──────────────┐    ┌────────────────┐   │
│  │ SharedData A │    │  BridgeEngine  │   │
│  │ + Worker A   │◄──►│  (forward &    │   │
│  │ (ttyUSB1)    │    │   dedup)       │   │
│  └──────────────┘    └────────────────┘   │
│  ┌──────────────┐         │               │
│  │ SharedData B │◄────────┘               │
│  │ + Worker B   │                         │
│  │ (ttyUSB2)    │                         │
│  └──────────────┘                         │
│                                           │
│  ┌───────────────────────────────────┐    │
│  │  Bridge Dashboard (NiceGUI :9092) │    │
│  │  - Device A & B status            │    │
│  │  - Forwarded message log          │    │
│  │  - Bridge config view             │    │
│  └───────────────────────────────────┘    │
└───────────────────────────────────────────┘
```

Key properties:

- **Separate process** — the bridge runs independently from meshcore_gui; both can run simultaneously on the same host
- **Loop prevention** — three mechanisms prevent message loops: direction filter, message hash tracking, and echo suppression
- **Private channels** — encrypted channels work transparently because the bridge operates at the plaintext level between firmware decryption and encryption
- **DOMCA dashboard** — status page on its own port showing both device connections, bridge statistics and a forwarded message log
- **YAML configuration** — all settings in a single `bridge_config.yaml` file

## 2. Features

- **Bidirectional forwarding** — Messages on the bridge channel are forwarded A→B and B→A automatically
- **Loop prevention** — Direction filter, message hash tracking, and echo suppression prevent infinite loops
- **Private channel support** — Encrypted channels work transparently; bridge operates at the plaintext level
- **DOMCA dashboard** — Live status page with device connections, bridge statistics and forwarded message log
- **YAML configuration** — All settings in a single `bridge_config.yaml` file
- **systemd integration** — Install as a background daemon with automatic restart
- **Zero meshcore_gui changes** — Imports existing modules as a library, 0 changed files

## 3. Requirements

- Python 3.10+
- meshcore_gui (installed or on PYTHONPATH)
- meshcore Python library (`pip install meshcore`)
- pyyaml (`pip install pyyaml`)
- Two MeshCore devices connected via USB serial

### 3.1. Requirement Status

| ID | Requirement | Status |
|----|-------------|--------|
| M1 | Bridge as separate process, meshcore_gui unchanged | ✅ |
| M2 | Forward messages on #bridge channel A↔B within <2s | ✅ |
| M3 | YAML config for channel, ports, polling interval | ✅ |
| M4 | 0 changed files in meshcore_gui/ | ✅ |
| M5 | GUI identical to meshcore_gui (DOMCA theme) | ✅ |
| M6 | Configurable port (--port=9092) | ✅ |
| M7 | Loop prevention via forwarded-hash set | ✅ |
| M8 | Two devices on different frequencies | ✅ |
| M9 | Private (encrypted) channels fully supported | ✅ |

---

## 4. Installation

### 4.1. Quick Start

```bash
# 1. Install the dependency
pip install pyyaml

# 2. Copy the config template and edit it
cp bridge_config.yaml /etc/meshcore/bridge_config.yaml
nano /etc/meshcore/bridge_config.yaml

# 3. Run the bridge
python meshcore_bridge.py --config=/etc/meshcore/bridge_config.yaml

# 4. Open the dashboard at http://your-host:9092
```

**Prerequisites:** Two MeshCore devices connected via USB serial to the same host, with the bridge channel configured on both devices using the same channel secret/password.

### 4.2. systemd Service

Install the bridge as a systemd daemon for production use:

```bash
# Run the installer script
sudo bash install_bridge.sh

# Edit the configuration
sudo nano /etc/meshcore/bridge_config.yaml

# Start the service
sudo systemctl start meshcore-bridge
sudo systemctl enable meshcore-bridge
```

**Useful service commands:**

| Command | Description |
|---------|-------------|
| `sudo systemctl status meshcore-bridge` | Check if the service is running |
| `sudo journalctl -u meshcore-bridge -f` | Follow the live log output |
| `sudo systemctl restart meshcore-bridge` | Restart after a configuration change |
| `sudo systemctl stop meshcore-bridge` | Stop the service |

**Uninstall:**

```bash
sudo bash install_bridge.sh --uninstall
```

---

## 5. Configuration

### 5.1. Bridge Settings

All settings are defined in `bridge_config.yaml`:

```yaml
bridge:
  channel_name: "bridge"        # Channel name (for display)
  channel_idx_a: 3              # Channel index on device A
  channel_idx_b: 3              # Channel index on device B
  poll_interval_ms: 200         # Polling interval (ms)
  forward_prefix: true          # Add [sender] prefix
  max_forwarded_cache: 500      # Loop prevention cache size

device_a:
  port: /dev/ttyUSB1            # Serial port device A
  baud: 115200                  # Baud rate
  label: "869.525 MHz"          # Dashboard label

device_b:
  port: /dev/ttyUSB2            # Serial port device B
  baud: 115200                  # Baud rate
  label: "868.000 MHz"          # Dashboard label

gui:
  port: 9092                    # Dashboard port
  title: "MeshCore Bridge"      # Browser tab title
```

### 5.2. Command-Line Options

| Flag | Description | Default |
|------|-------------|---------|
| `--config=PATH` | Path to YAML config file | `./bridge_config.yaml` |
| `--port=PORT` | Override GUI port | From config (9092) |
| `--debug-on` | Enable debug logging | Off |
| `--help` | Show usage info | — |

---

## 6. How It Works

### 6.1. Message Flow

1. **Device A** receives a channel message on the bridge channel via LoRa
2. MeshCore firmware decrypts the message (if private channel) and passes plaintext to the Worker
3. The Worker's EventHandler stores the message in **SharedData A**
4. **BridgeEngine** polls SharedData A, detects the new message, checks dedup hash set
5. BridgeEngine injects a `send_message` command into **SharedData B**'s command queue
6. Worker B picks up the command and transmits the message on Device B's bridge channel
7. MeshCore firmware on Device B encrypts (if private channel) and transmits via LoRa

The reverse direction (B→A) works identically.

### 6.2. Loop Prevention

The bridge uses three mechanisms to prevent message loops:

1. **Direction filter** — Only incoming messages (`direction='in'`) are forwarded. Messages we transmitted (`direction='out'`) are never forwarded.

2. **Message hash tracking** — Each forwarded message's hash is stored in a bounded set (configurable via `max_forwarded_cache`). If the same hash appears again, it is blocked.

3. **Echo suppression** — When a message is forwarded, the hash of the forwarded text (including `[sender]` prefix) is also registered, preventing the forwarded message from being re-forwarded when it appears on the target device.

### 6.3. Private (Encrypted) Channels

The bridge works transparently with both public and private channels. No extra configuration is needed beyond ensuring that both devices have the same channel secret/password:

- **Inbound**: MeshCore firmware decrypts → Worker receives plaintext → BridgeEngine reads plaintext
- **Outbound**: BridgeEngine injects command → Worker sends via meshcore lib → Firmware encrypts → LoRa TX

> **Prerequisite:** The bridge channel MUST be configured on both devices with **identical channel secret/password**. Only the frequency and channel index may differ.

---

## 7. Dashboard

The bridge dashboard is accessible at `http://your-host:9092` (or your configured port) and shows:

- **Configuration summary** — active channel, indices, poll interval
- **Device A status** — connection state, device name, radio frequency
- **Device B status** — connection state, device name, radio frequency
- **Bridge statistics** — messages forwarded (total, A→B, B→A), duplicates blocked, uptime
- **Forwarded message log** — last 200 forwarded messages with timestamps and direction

The dashboard uses the same DOMCA theme as meshcore_gui with dark/light mode toggle.

---

## 8. File Structure

```
meshcore_bridge.py                          # Entry point (~25 lines)
meshcore_bridge/
├── __init__.py                             # Package init
├── __main__.py                             # CLI, dual-worker setup, NiceGUI server (~180 lines)
├── config.py                               # YAML config loading (~130 lines)
├── bridge_engine.py                        # Core bridge logic (~250 lines)
└── gui/
    ├── __init__.py                         # GUI package init
    ├── dashboard.py                        # Bridge dashboard page (~180 lines)
    └── panels/
        ├── __init__.py                     # Panels package init
        ├── status_panel.py                 # Device connection status (~180 lines)
        └── log_panel.py                    # Forwarded message log (~100 lines)

bridge_config.yaml                          # Configuration template
install_bridge.sh                           # systemd service installer
BRIDGE.md                                   # This documentation
```

**Total new code:** ~1,050 lines
**Changed files in meshcore_gui/:** 0 (zero)

---

## 9. Assumptions

- Both MeshCore devices are connected via USB serial to the same host (Raspberry Pi / Linux server)
- The bridge channel exists on both devices with the same name (but possibly different index)
- The bridge channel has identical channel secret/password on both devices
- The meshcore_gui package is importable (installed via `pip install -e .` or on PYTHONPATH)
- Sufficient CPU/RAM for two simultaneous MeshCore connections (~100MB)
- Messages are forwarded with a sender prefix `[original_sender]` for identification

---

## 10. Troubleshooting

### 10.1. Bridge Won't Start

- Check that both serial ports exist: `ls -l /dev/ttyUSB*`
- Verify meshcore_gui is importable: `python -c "from meshcore_gui.core.shared_data import SharedData"`
- Check pyyaml is installed: `pip install pyyaml`

### 10.2. Messages Not Forwarding

- Verify the bridge channel index matches on both devices
- Check that the channel secret is identical on both devices
- Look at the dashboard: are both devices showing "Connected"?
- Enable debug mode: `python meshcore_bridge.py --debug-on`

### 10.3. Port Conflicts

| Daemon | Default Port |
|---|---|
| meshcore_gui | 8081 |
| **meshcore_bridge** | **9092** |
| meshcore_observer | 9093 |

Change via `--port=XXXX` or in `bridge_config.yaml`.

### 10.4. Service Issues

```bash
sudo systemctl status meshcore-bridge
journalctl -u meshcore-bridge -f
sudo systemctl restart meshcore-bridge
```

---

## 11. License

MIT License — Copyright (c) 2026 PE1HVH

## 12. Author

**PE1HVH** — [GitHub](https://github.com/pe1hvh) — DOMCA MeshCore Project
