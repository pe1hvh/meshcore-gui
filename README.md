# MeshCore GUI — All-in-One MeshCore Platform
### Monitor, message, bridge, automate and publish — no cloud, no broker, just LoRa.
![Status](https://img.shields.io/badge/Status-Production-green.svg)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-orange.svg)
![Transport](https://img.shields.io/badge/Transport-USB%20Serial%20%7C%20BLE-blueviolet.svg)
![Bridge](https://img.shields.io/badge/Bridge-Cross--Frequency%20LoRa%20↔%20LoRa-ff6600.svg)
<img width="920" height="769" alt="image" src="https://github.com/user-attachments/assets/ff38b97f-557b-4217-abce-aaec68a90c35" />


A full-featured desktop platform for MeshCore mesh radio devices. Connects via USB serial or Bluetooth LE, runs headless on a Raspberry Pi, and brings together a real-time dashboard, message archive, channel manager, BBS, bot, cross-frequency bridge and public REST API — all in a single self-contained Python application.

## Table of Contents

- [1. Why This Project Exists](#1-why-this-project-exists)
- [2. Features](#2-features)
- [3. Screenshots](#3-screenshots)
- [4. Requirements](#4-requirements)
  - [4.1. Platform Support](#41-platform-support)
- [5. Installation](#5-installation)
  - [5.1. System Dependencies](#51-system-dependencies)
    - [5.1.1. D-Bus Policy for BLE (Linux only)](#511-d-bus-policy-for-ble-linux-only)
  - [5.2. Clone the Repository](#52-clone-the-repository)
  - [5.3. Create Virtual Environment](#53-create-virtual-environment)
  - [5.4. Install Python Packages](#54-install-python-packages)
- [6. Usage](#6-usage)
  - [6.1. Activate the Virtual Environment](#61-activate-the-virtual-environment)
  - [6.2. Find Your Device](#62-find-your-device)
  - [6.3. Configure Channels](#63-configure-channels-optional)
  - [6.4. Start the GUI](#64-start-the-gui)
- [7. Starting the Application](#7-starting-the-application)
  - [7.1. Command-Line Options](#71-command-line-options)
  - [7.2. Method 1: Interactive (foreground)](#72-method-1-interactive-foreground)
  - [7.3. Method 2: Background with Visible Output](#73-method-2-background-with-visible-output-nohup--tail)
  - [7.4. Method 3: Background with Terminal Free](#74-method-3-background-with-terminal-free-nohup)
  - [7.5. Method 4: systemd Service](#75-method-4-systemd-service-recommended-for-production)
    - [7.5.1. Automated Setup](#751-automated-setup)
    - [7.5.2. Manual Setup](#752-manual-setup)
  - [7.6. Accessing the Interface](#76-accessing-the-interface)
  - [7.7. Running Multiple Instances](#77-running-multiple-instances)
  - [7.8. Migrating Existing Data](#78-migrating-existing-data)
  - [7.9. Raspberry Pi 5 Notes](#79-raspberry-pi-5-notes)
- [8. Configuration](#8-configuration)
  - [8.1. Data Directory (`~/.meshcore-gui/`)](#81-data-directory-meshcore-gui)
- [9. Functionality](#9-functionality)
  - [9.1. Device Info](#91-device-info)
  - [9.2. Contacts](#92-contacts)
  - [9.3. Map](#93-map)
  - [9.4. Channel Messages](#94-channel-messages)
  - [9.5. Direct Messages (DM)](#95-direct-messages-dm)
  - [9.6. Message Route Visualization](#96-message-route-visualization)
  - [9.7. Room Server](#97-room-server)
  - [9.8. Message Archive](#98-message-archive)
  - [9.9. Local Cache](#99-local-cache)
  - [9.10. Keyword Bot](#910-keyword-bot)
  - [9.11. RX Log](#911-rx-log)
  - [9.12. Actions](#912-actions)
  - [9.13. Public REST API](#913-public-rest-api)
  - [9.14. BBS — Bulletin Board System](#914-bbs--bulletin-board-system)
- [10. Architecture](#10-architecture)
- [11. Cross-Frequency Bridge](#11-cross-frequency-bridge)
  - [11.1. Bridge Overview](#111-bridge-overview)
  - [11.2. Quick Start](#112-quick-start)
  - [11.3. Bridge Configuration](#113-bridge-configuration)
  - [11.4. systemd Service](#114-systemd-service)
- [12. Known Limitations](#12-known-limitations)
- [13. Troubleshooting](#13-troubleshooting)
  - [13.1. Linux](#131-linux)
    - [13.1.1. Serial Quick Fixes](#1311-serial-quick-fixes)
    - [13.1.2. BLE Quick Fixes](#1312-ble-quick-fixes)
  - [13.2. macOS](#132-macos)
  - [13.3. Windows](#133-windows)
  - [13.4. All Platforms](#134-all-platforms)
- [14. Development](#14-development)
  - [14.1. Debug Mode](#141-debug-mode)
  - [14.2. Project Structure](#142-project-structure)
- [15. Roadmap](#15-roadmap)
- [16. Disclaimer](#16-disclaimer)
- [17. License](#17-license)
- [18. Author](#18-author)
- [19. Acknowledgments](#19-acknowledgments)
---

## 1. Why This Project Exists

MeshCore devices like the SenseCAP T1000-E can be managed through two interfaces: USB serial and BLE (Bluetooth Low Energy). The official companion apps communicate over BLE but are mobile-only. For desktop or headless operation there was nothing — this project fills that gap.

What started as a basic serial GUI has grown into a comprehensive platform. Today it covers the full operator workflow:

- **Connect** — dual transport, auto-detected: USB serial or Bluetooth LE with automatic PIN pairing
- **Monitor** — real-time dashboard with device info, contacts, map, channel messages, DMs and raw RX log
- **Manage nodes** — pin contacts, bulk-clean stale nodes, control auto-add behaviour
- **Manage channels** — add hashtag or private channels from the GUI, generate and share QR codes, delete and re-index slots
- **Archive** — all messages and RX log entries persisted to disk with configurable retention; searchable via the archive viewer
- **Automate** — keyword bot with configurable replies, cooldown and private-contact mode
- **Bulletin Board** — offline BBS with DM-based commands, category and region filtering, and automatic abbreviations
- **Bridge** — standalone cross-frequency bridge daemon connecting two devices on different frequencies, with loop prevention and its own dashboard
- **Publish** — read-only REST API exposing stats, nodes, messages and channels for external dashboards; private channel messages are unconditionally excluded
- **Headless** — the web-based interface (NiceGUI) runs on any platform, accessible from any browser on your local network; ideal for a Raspberry Pi as a permanent mesh node

Under the hood it uses `meshcore` as the protocol layer, `meshcoredecoder` for raw LoRa packet decryption and route extraction, and `NiceGUI` for the web-based interface.

> **Note:** Tested on Linux (Ubuntu 24.04) and Raspberry Pi 5 (Debian Bookworm, headless) with both serial and BLE transports. macOS and Windows should work for serial mode — all core dependencies are cross-platform — but this has not been verified. BLE mode requires Linux with BlueZ. Feedback and contributions for other platforms are welcome.


## 2. Features

- **Real-time Dashboard** — Device info, contacts, messages and RX log
- **Interactive Map** — Leaflet map with markers for own position and contacts
- **Channel Messages** — Send and receive messages on channels
- **Direct Messages** — Click on a contact to send a DM
- **Channel Management** — Channels are automatically discovered at startup. Add hashtag or private channels directly from the GUI; new private channels generate a shareable QR code and hex key. Each channel has an inline 🗑 delete button that automatically re-indexes remaining slots
- **Contact Management** — Pin/unpin contacts to protect them from deletion, individual and bulk-delete unpinned contacts, and toggle automatic contact addition from mesh adverts
- **Message Filtering** — Filter messages per channel via checkboxes
- **Message Route Visualization** — Click any message to open a detailed route page showing the path (hops) through the mesh network on an interactive map, with a hop summary, route table and reply panel
- **Message Archive** — All messages and RX log entries are persisted to disk with configurable retention. Browse archived messages via the archive viewer with filters (channel, time range, text search), pagination and inline route tables
- **Room Server Support** — Login to Room Servers directly from the GUI. Each Room Server gets a dedicated panel with message display, send functionality and login/logout controls. Passwords are stored securely outside the repository
- **BBS — Bulletin Board System** — Offline message board with DM-based commands (`!p`, `!r`, `!s`), category and region filtering, automatic abbreviations and a channel-based whitelist. See [9.14. BBS](#914-bbs--bulletin-board-system) for full documentation
- **Keyword Bot** — Built-in auto-reply bot that responds to configurable keywords on selected channels, with cooldown, private-contact mode and loop prevention
- **Cross-Frequency Bridge** — Standalone bridge daemon (`meshcore_bridge`) connects two devices on different frequencies by forwarding messages bidirectionally on a configurable channel. Runs as a separate process with its own dashboard, YAML configuration and systemd service installer. See [11. Cross-Frequency Bridge](#11-cross-frequency-bridge) for details
- **Public REST API** — Read-only JSON endpoints (`/api/v1/stats`, `/api/v1/nodes`, `/api/v1/messages`, `/api/v1/channels`) for external consumers such as statistics dashboards. Private channel messages are unconditionally excluded; no authentication required
- **Packet Decoding** — Raw LoRa packets from RX log are decoded and decrypted using channel keys, providing message hashes, path hashes and hop data
- **Message Deduplication** — Dual-strategy dedup (hash-based and content-based) prevents duplicate messages from appearing
- **Local Cache** — Device info, contacts and channel keys are cached to disk so the GUI is instantly populated on startup from the last known state, even before the device connects. Offline nodes are preserved; missing channel keys are retried in the background
- **Periodic Contact Refresh** — Contacts are automatically refreshed from the device at a configurable interval (default: 5 minutes) and merged with the cache
- **Dual Transport** — Auto-detects USB serial or Bluetooth LE from the device argument; BLE includes automatic PIN pairing and bond management
- **Headless / Multi-instance** — Web-based interface accessible from any browser; run multiple instances simultaneously on different ports for multiple devices

## 3. Screenshots

<img width="1000" height="873" alt="a_Screenshots" src="https://github.com/user-attachments/assets/bd19de9a-05f7-43fd-8acd-3b92cdf6c7fa" />
<img width="944" height="877" alt="Screenshot from 2026-02-18 09-27-59" src="https://github.com/user-attachments/assets/6b0b19f4-9886-4cca-bd36-50b4c3797e02" />
<img width="944" height="877" alt="Screenshot from 2026-02-18 09-28-27" src="https://github.com/user-attachments/assets/374694fa-ab2d-4b96-b81f-6a351af7710a" />
<img width="920" height="769" alt="image" src="https://github.com/user-attachments/assets/78b8112a-1ad8-460c-99ae-a16d15b14b77" />


## 4. Requirements

- Python 3.10+
- **Serial mode:** USB serial connection + Serial Companion firmware on the device
- **BLE mode:** Bluetooth adapter + Linux with BlueZ (D-Bus); additional Python packages: `bleak`, `dbus_fast`

### 4.1. Platform Support

| Platform | Serial | BLE | Status |
|---|---|---|---|
| Linux (Ubuntu/Debian) | ✅ pySerial | ✅ bleak + dbus_fast | ✅ Tested |
| Raspberry Pi 5 (Debian Bookworm) | ✅ pySerial | ✅ bleak + dbus_fast | ✅ Tested (headless) |
| macOS | ✅ pySerial | ❌ No D-Bus | ⬜ Serial untested |
| Windows 10/11 | ✅ pySerial | ❌ No D-Bus | ⬜ Serial untested |

## 5. Installation

### 5.1. System Dependencies

**Linux (Ubuntu/Debian) — Serial:**
```bash
sudo apt update
sudo apt install python3-pip python3-venv
```

**Linux (Ubuntu/Debian) — BLE (additionally):**
```bash
sudo apt install bluetooth bluez
```

Verify that the Bluetooth service is running:
```bash
sudo systemctl status bluetooth
```

> ⚠️ **BlueZ driver warning:** Recent versions of BlueZ (5.66+, shipped with Ubuntu 24.04 and Debian Bookworm) introduced changes to the BLE connection handling and D-Bus agent API that can cause **connection instability, pairing failures and unexpected disconnects** in BLE mode. Known symptoms include:
> - Pairing succeeds but the connection drops within seconds
> - `org.bluez.Error.AuthenticationFailed` or `org.bluez.Error.ConnectionAttemptFailed` in the logs
> - Repeated bond/unbond cycles without a stable connection
>
> **Workaround:** If you experience BLE instability, try downgrading BlueZ to 5.65 or pinning the package version. Alternatively, use **USB serial mode** which is not affected by BlueZ and provides the most reliable connection on all platforms. See [14.1.2. BLE Quick Fixes](#1412-ble-quick-fixes) for troubleshooting steps.

**Raspberry Pi (Raspberry Pi OS Lite) — Serial:**
```bash
sudo apt update
sudo apt install python3-pip python3-venv git
```

**Raspberry Pi — BLE (additionally):**
```bash
sudo apt install bluetooth bluez
```
The Raspberry Pi 5 has a built-in Bluetooth adapter. Verify with `hciconfig` or `bluetoothctl show`.

> ⚠️ **Raspberry Pi OS Bookworm ships with BlueZ 5.66+** which is affected by the BLE stability issues described above. If BLE connections are unreliable, consider USB serial as the primary transport.

**macOS:**
```bash
# Python 3.10+ via Homebrew (if not already installed)
brew install python
```
No additional system packages needed. BLE mode is not supported on macOS (requires Linux D-Bus).

**Windows:**
- Install [Python 3.10+](https://www.python.org/downloads/) (check "Add to PATH" during installation)
- No additional system packages needed. BLE mode is not supported on Windows (requires Linux D-Bus).

#### 5.1.1. D-Bus Policy for BLE (Linux only)

BLE mode uses a D-Bus PIN agent to handle automatic pairing. Your user needs permission to interact with BlueZ over the system bus. Create a policy file:

```bash
sudo tee /etc/dbus-1/system.d/meshcore-ble.conf > /dev/null << 'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="YOUR_USERNAME">
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.Agent1"/>
    <allow send_interface="org.bluez.AgentManager1"/>
  </policy>
</busconfig>
EOF
```

Replace `YOUR_USERNAME` with your actual username. This step is handled automatically if you use the `install_ble_stable.sh` installer (see [7.5.1](#751-automated-setup)).

> **Note:** Without this policy, the BLE PIN agent cannot register with BlueZ and pairing will fail with a D-Bus permission error.

### 5.2. Clone the Repository

```bash
git clone https://github.com/pe1hvh/meshcore-gui.git
cd meshcore-gui
```

### 5.3. Create Virtual Environment

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

### 5.4. Install Python Packages

**Core (Serial mode):**
```bash
pip install nicegui meshcore meshcoredecoder
```

**BLE mode (additionally):**
```bash
pip install bleak dbus_fast
```

> **Note:** BLE dependencies (`bleak`, `dbus_fast`) are only needed when connecting via Bluetooth LE. Serial-only installs do not require them — they are imported lazily at runtime.

## 6. Usage

### 6.1. Activate the Virtual Environment

**Linux / macOS:**
```bash
cd meshcore-gui
source venv/bin/activate
```

**Windows:**
```cmd
cd meshcore-gui
venv\Scripts\activate
```

### 6.2. Find Your Device

**Serial — Linux:**
```bash
ls -l /dev/serial/by-id
```
Look for your MeshCore device and note the device path (e.g., `/dev/ttyUSB0`).

**Serial — macOS:**
```bash
ls /dev/tty.usb* /dev/tty.usbserial* /dev/tty.usbmodem*
```

**Serial — Windows:**
Open Device Manager → Ports (COM & LPT) and note the COM port (e.g., `COM3`).

**BLE — Linux:**
```bash
bluetoothctl scan on
```
Look for your MeshCore device and note the MAC address (e.g., `AA:BB:CC:DD:EE:FF`).

### 6.3. Configure Channels (optional)

Channels are automatically discovered from the device at startup via the serial link. No manual configuration is required.

If you want to cache the discovered channel list to disk (for faster startup), set `CHANNEL_CACHE_ENABLED = True` in `meshcore_gui/config.py`. By default, channels are always fetched fresh from the device.

> **Note:** The maximum number of channel slots probed can be adjusted via `MAX_CHANNELS` in `config.py` (default: 100).

#### Adding channels from the GUI

Open the **Messages** section in the left drawer and click **＋ Add Channel** at the bottom of the channel list. A dialog appears with three modes:

| Mode | When to use | Key input |
|---|---|---|
| **# Hashtag** | Join a public topic channel (e.g. `#localmesh`) | None — key is derived from the name |
| **🔒 Private – New** | Create a new private group channel | Click *Generate key*, then share the QR or hex key |
| **🔒 Private – Existing** | Join a private channel someone shared with you | Paste the 32-char hex key |

After clicking **Add Channel**, the device is updated and channel discovery re-runs automatically. A new private channel shows a scannable QR code (`meshcore://channel/add?name=…&secret=…`) that the official MeshCore app can read directly.

#### Deleting channels from the GUI

Each channel row in the **Messages** and **Archive** submenus has an inline 🗑 delete button. Clicking it removes the channel slot from the device and automatically re-indexes any higher-numbered channels downward by one position, keeping the list gapless. Private channel keys for renumbered slots are read from the local cache, so no key material is lost.

### 6.4. Start the GUI

See [7. Starting the Application](#7-starting-the-application) below for all startup methods.

## 7. Starting the Application

MeshCore GUI is a web-based application powered by NiceGUI. Once started, it serves a dashboard that you can access from any browser — locally or over your network. There are several ways to run it, depending on your use case.

All examples below assume you have activated the virtual environment and are in the project directory:

```bash
cd ~/meshcore-gui
source venv/bin/activate       # Linux / macOS
```

### 7.1. Command-Line Options

The transport mode is **auto-detected** from the device argument:
- Path like `/dev/ttyUSB0` or `COM3` → Serial mode
- MAC address like `literal:AA:BB:CC:DD:EE:FF` → BLE mode

| Flag | Description | Default | Mode |
|------|-------------|---------|------|
| `--debug-on` | Enable verbose debug logging (stdout + log file) | Off | Both |
| `--port=PORT` | Web server port | `8081` | Both |
| `--ssl` | Enable HTTPS with auto-generated certificate | Off | Both |
| `--baud=BAUD` | Serial baudrate | `115200` | Serial |
| `--serial-cx-dly=SECONDS` | Serial connection delay | `0.1` | Serial |
| `--ble-pin PIN` | BLE pairing PIN | `123456` | BLE |

All flags are optional and can be combined in any order:

```bash
# Serial
python meshcore_gui.py /dev/ttyUSB0 --debug-on --port=8082 --baud=115200

# BLE
python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on --ble-pin 654321
```

### 7.2. Method 1: Interactive (foreground)

The simplest way to start — runs in your current terminal. Output is visible directly. Press `Ctrl+C` to stop.

**Serial:**
```bash
python meshcore_gui.py /dev/ttyUSB0
```

**BLE:**
```bash
python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
```

Open your browser at `http://localhost:8081` (or the port you specified with `--port`).

This is the recommended method during development or when debugging, because you see all output immediately in your terminal.

### 7.3. Method 2: Background with Visible Output (nohup + tail)

Runs in the background but keeps the output visible in your terminal. Useful for SSH sessions where you want to monitor the application while keeping the terminal usable.

**Serial:**
```bash
nohup python meshcore_gui.py /dev/ttyUSB0 --debug-on > ~/meshcore.log 2>&1 &
tail -f ~/meshcore.log
```

**BLE:**
```bash
nohup python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
tail -f ~/meshcore.log
```

The first command starts the application in the background and writes all output to `~/meshcore.log`. The `&` at the end returns control to your terminal. The second command follows the log file in real-time — press `Ctrl+C` to stop following (the application keeps running).

### 7.4. Method 3: Background with Terminal Free (nohup)

Runs entirely in the background. Your terminal is free and the application survives closing your SSH session. Ideal for headless devices where you start the application once and leave it running.

**Serial:**
```bash
nohup python meshcore_gui.py /dev/ttyUSB0 --debug-on > ~/meshcore.log 2>&1 &
```

**BLE:**
```bash
nohup python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
```

To check if it is running:

```bash
ps aux | grep meshcore_gui
```

To view recent output:

```bash
tail -50 ~/meshcore.log
```

To stop it:

```bash
pkill -f meshcore_gui
```

> **Tip:** Avoid redirecting to `/dev/null` — keeping the output in a log file preserves connection errors and other diagnostics. When `--debug-on` is enabled, detailed debug output is also written to a per-device rotating log file at `~/.meshcore-gui/logs/<ADDRESS>_meshcore_gui.log` (e.g. `F0_9E_9E_75_A3_01_meshcore_gui.log`, max 20 MB, rotates automatically).

### 7.5. Method 4: systemd Service (recommended for production)

A systemd service starts automatically on boot, restarts on crashes, and integrates with system logging. This is the recommended method for permanent headless deployments (e.g. Raspberry Pi).

#### 7.5.1. Automated Setup

If you have not yet created a virtual environment, use the venv setup script first:

```bash
bash install_scripts/install_venv.sh
```

This creates `venv/` and installs all core dependencies (`nicegui`, `meshcore`, `bleak`, `meshcoredecoder`) in one step.

Use the appropriate installer for your transport:

```bash
# Serial connection
bash install_scripts/install_serial.sh

# BLE connection
bash install_scripts/install_ble_stable.sh
```

**Serial environment variables** (optional):

```bash
SERIAL_PORT=/dev/ttyACM0
BAUD=115200
SERIAL_CX_DLY=0.1
WEB_PORT=8081
DEBUG_ON=yes
```

**BLE environment variables** (optional):

```bash
BLE_ADDRESS=AA:BB:CC:DD:EE:FF
WEB_PORT=8081
DEBUG_ON=yes
```

The BLE installer also installs the D-Bus policy file and configures the systemd service with the correct `DBUS_SYSTEM_BUS_ADDRESS` environment variable.

#### 7.5.2. Manual Setup

##### Serial

**Step 1 — Create the service file:**

```bash
sudo nano /etc/systemd/system/meshcore-gui.service
```

```ini
[Unit]
Description=MeshCore GUI (Serial)

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/meshcore-gui
ExecStart=/home/your-username/meshcore-gui/venv/bin/python meshcore_gui.py /dev/ttyUSB0 --debug-on --port=8081 --baud=115200
Restart=on-failure
RestartSec=30
[Install]
WantedBy=multi-user.target
```

Replace `your-username`, `/dev/ttyUSB0` and port with your actual values.

##### BLE

**Step 1 — Ensure the D-Bus policy is installed** (see [5.1.1](#511-d-bus-policy-for-ble-linux-only)).

**Step 2 — Create the service file:**

```bash
sudo nano /etc/systemd/system/meshcore-gui.service
```

```ini
[Unit]
Description=MeshCore GUI (BLE)
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/meshcore-gui
ExecStart=/home/your-username/meshcore-gui/venv/bin/python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on --port=8081 --ble-pin 123456
Restart=on-failure
RestartSec=30
Environment=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket
[Install]
WantedBy=multi-user.target
```

Replace `your-username`, `AA:BB:CC:DD:EE:FF` and PIN with your actual values. The `DBUS_SYSTEM_BUS_ADDRESS` environment variable is required for the BLE PIN agent to communicate with BlueZ.

##### Enable and start

**For both serial and BLE:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable meshcore-gui
sudo systemctl start meshcore-gui
```

**Useful service commands:**

| Command | Description |
|---------|-------------|
| `sudo systemctl status meshcore-gui` | Check if the service is running |
| `sudo journalctl -u meshcore-gui -f` | Follow the live log output |
| `sudo journalctl -u meshcore-gui --since "1 hour ago"` | View recent logs |
| `sudo systemctl restart meshcore-gui` | Restart after a configuration change |
| `sudo systemctl stop meshcore-gui` | Stop the service |
| `sudo systemctl disable meshcore-gui` | Prevent starting on boot |

### 7.6. Accessing the Interface

Once the application is running (via any method), open a browser and navigate to:

```
http://localhost:8081
```

From another device on the same network, use the hostname or IP address:

```
http://<hostname-or-ip>:8081
```

For example: `http://raspberrypi5nas:8081` or `http://192.168.2.234:8081`. This works from any device on the same network — desktop, laptop, tablet or phone.

### 7.7. Running Multiple Instances

You can run multiple instances simultaneously (e.g. for different MeshCore devices) by assigning each a different port:

```bash
# Two serial devices
python meshcore_gui.py /dev/ttyUSB0 --port=8081 --baud=115200 &
python meshcore_gui.py /dev/ttyUSB1 --port=8082 --baud=115200 &

# Mixed: serial + BLE
python meshcore_gui.py /dev/ttyACM0 --port=8081 &
python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --port=8082 &
```

Each instance gets its own log file, cache and archive, all keyed by the device identifier (serial port or BLE address).

### 7.8. Migrating Existing Data

If you are moving from an existing installation, copy the data directory to preserve your cache, pinned contacts, room server passwords and message archive:

```bash
scp -r ~/.meshcore-gui user@headless-device:~/
```

### 7.9. Raspberry Pi 5 Notes

The Raspberry Pi 5 is a good fit for running MeshCore GUI headless:

- **Serial**: USB serial adapter or direct USB connection to the device
- **BLE**: Built-in Bluetooth adapter; works out of the box with BlueZ on Raspberry Pi OS
- **RAM**: 2 GB is sufficient; 4 GB or more provides extra headroom for long-running operation
- **OS**: Raspberry Pi OS Lite (64-bit, Bookworm) — no desktop environment needed
- **Storage**: 16 GB+ SD card or NVMe; the application stores cache and archive data in `~/.meshcore-gui/`
- **Power**: Low idle power consumption (~5W), suitable for 24/7 operation

Ensure your user has permission to access the serial device (e.g. member of `dialout` on many Linux distros).

## 8. Configuration

| Setting | Location | Description |
|---------|----------|-------------|
| `OPERATOR_CALLSIGN` | `meshcore_gui/config.py` | Operator callsign shown on landing page and drawer footer (default: `"PE1HVH"`) |
| `LANDING_SVG_PATH` | `meshcore_gui/config.py` | Path to the landing page SVG file; supports `{callsign}` placeholder (default: `static/landing_default.svg`) |
| `DEBUG` | `meshcore_gui/config.py` | Set to `True` for verbose logging (or use `--debug-on`) |
| `MAX_CHANNELS` | `meshcore_gui/config.py` | Maximum channel slots to probe on device (default: 8) |
| `CHANNEL_CACHE_ENABLED` | `meshcore_gui/config.py` | Cache discovered channels to disk for faster startup (default: `False` — always fresh from device) |
| `DEFAULT_TIMEOUT` | `meshcore_gui/config.py` | Default command timeout in seconds (default: `10.0`) |
| `MESHCORE_LIB_DEBUG` | `meshcore_gui/config.py` | Enable meshcore library debug logging (default: `True`) |
| `SERIAL_BAUDRATE` | `meshcore_gui/config.py` | Serial baudrate (default: `115200`) |
| `SERIAL_CX_DELAY` | `meshcore_gui/config.py` | Serial connection delay (default: `0.1`) |
| `TRANSPORT` | `meshcore_gui/config.py` | Auto-detected transport mode: `"serial"` or `"ble"` (set at startup) |
| `BLE_PIN` | `meshcore_gui/config.py` | BLE pairing PIN for T1000e devices (default: `"123456"`) |
| `RECONNECT_MAX_RETRIES` | `meshcore_gui/config.py` | Maximum reconnect attempts after a disconnect (default: 5) |
| `RECONNECT_BASE_DELAY` | `meshcore_gui/config.py` | Base delay in seconds between reconnect attempts, multiplied by attempt number (default: 5.0) |
| `CONTACT_REFRESH_SECONDS` | `meshcore_gui/config.py` | Interval between periodic contact refreshes (default: 300s / 5 minutes) |
| `MESSAGE_RETENTION_DAYS` | `meshcore_gui/config.py` | Retention period for archived messages (default: 30 days) |
| `RXLOG_RETENTION_DAYS` | `meshcore_gui/config.py` | Retention period for archived RX log entries (default: 7 days) |
| `CONTACT_RETENTION_DAYS` | `meshcore_gui/config.py` | Retention period for cached contacts (default: 90 days) |
| `KEY_RETRY_INTERVAL` | `meshcore_gui/ble/worker.py` | Interval between background retry attempts for missing channel keys (default: 30s) |
| `BOT_DEVICE_NAME` | `meshcore_gui/config.py` | Device name set when bot mode is active (default: `;NL-OV-ZWL-STDSHGN-WKC Bot`) |
| `BOT_CHANNELS` | `meshcore_gui/services/bot.py` | Channel indices the bot listens on |
| `BOT_COOLDOWN_SECONDS` | `meshcore_gui/services/bot.py` | Minimum seconds between bot replies |
| `BOT_KEYWORDS` | `meshcore_gui/services/bot.py` | Keyword → reply template mapping |
| Room passwords | `~/.meshcore-gui/room_passwords/<ADDRESS>.json` | Per-device Room Server passwords (managed via GUI, stored outside repository) |
| Serial Port | CLI argument | Device serial port (e.g. `/dev/ttyUSB0` or `COM3`) |
| BLE Address | CLI argument | BLE MAC address (e.g. `literal:AA:BB:CC:DD:EE:FF`) |
| `--port=PORT` | CLI flag | Web server port (default: `8081`) |
| `--baud=BAUD` | CLI flag | Serial baudrate (default: `115200`) |
| `--serial-cx-dly=SECONDS` | CLI flag | Serial connection delay (default: `0.1`) |
| `--ble-pin PIN` | CLI flag | BLE pairing PIN (default: `123456`) |
| `--ssl` | CLI flag | Enable HTTPS with auto-generated self-signed certificate |
| `--debug-on` | CLI flag | Enable verbose debug logging |

## 8.1. Data Directory (`~/.meshcore-gui/`)

All persistent data is stored under `~/.meshcore-gui/` in your home directory. Each file is plain JSON (or SQLite for the BBS), human-readable and safe to inspect. The directory is created automatically on first run.

```
~/.meshcore-gui/
├── cache/
│   └── <ADDRESS>.json          # Device cache: contacts, channel keys, device info
│                               # Populated at startup; read back instantly if offline
├── pins/
│   └── <ADDRESS>_pins.json     # Pinned contact public keys per device
│                               # Pinned contacts are protected from bulk delete
├── archive/
│   ├── <ADDRESS>_messages.json # All received channel and DM messages (retained per MESSAGE_RETENTION_DAYS)
│   └── <ADDRESS>_rxlog.json    # Raw RX log entries (retained per RXLOG_RETENTION_DAYS)
├── room_passwords/
│   └── <ADDRESS>.json          # Room Server passwords per device (managed via GUI)
├── bot/
│   └── _<dev_id>_bot.json      # Bot channel selection and settings per device
├── bbs/
│   ├── bbs_config.json         # BBS settings: channels, categories, regions, whitelist
│   └── bbs_messages.db         # BBS message store (SQLite, WAL mode)
└── logs/
    └── <ADDRESS>_meshcore_gui.log  # Rotating debug log (max 20 MB, only with --debug-on)
```

`<ADDRESS>` is derived from the device argument: a serial port like `/dev/ttyUSB0` becomes `_dev_ttyUSB0`, a BLE address like `AA:BB:CC:DD:EE:FF` becomes `AA_BB_CC_DD_EE_FF`. This means each device gets its own set of files.

**Useful maintenance commands:**

```bash
# Clear the device cache (forces a fresh read from the device on next startup)
rm ~/.meshcore-gui/cache/*.json

# Remove a specific device's archive to free disk space
rm ~/.meshcore-gui/archive/AA_BB_CC_DD_EE_FF_*.json

# View the BBS config
cat ~/.meshcore-gui/bbs/bbs_config.json
```

> **Tip:** When moving to a new machine or a different Raspberry Pi, copy the entire `~/.meshcore-gui/` directory to preserve your pinned contacts, room passwords, bot configuration and message history.

## 9. Functionality

### 9.1. Device Info
- Name, frequency, SF/BW, TX power, location, firmware version

### 9.2. Contacts

> **Note:** In MeshCore firmware and protocol documentation, network participants are called *nodes*. The GUI uses the term *contacts* for the same concept — every node that your device has seen or exchanged adverts with appears here as a contact.

- List of known nodes with type and location
- Click on a contact to send a DM (or add a Room Server panel for type=3 contacts)
<!-- CHANGED: Contact click now dispatches by type (v5.7.0) -->
- **Pin/Unpin**: Checkbox per contact to pin it — pinned contacts are sorted to the top and visually marked with a yellow background. Pin state is persisted locally and survives app restart.
- **Individual delete**: 🗑️ button per unpinned contact to remove a single contact from the device with confirmation dialog. Pinned contacts are protected.
<!-- ADDED: Individual contact deletion (v5.7.0) -->
- **Bulk delete**: "🧹 Clean up" button removes all unpinned contacts from the device in one action, with a confirmation dialog showing how many will be removed vs. kept. Optional "Also delete from history" checkbox to clear locally cached data.
<!-- CHANGED: Added "Also delete from history" option (v5.7.0) -->
- **Auto-add toggle**: "📥 Auto-add" checkbox controls whether the device automatically adds new contacts when it receives adverts from other mesh nodes. Disabled by default to prevent the contact list from filling up.

### 9.3. Map
- OpenStreetMap with markers for own position and contacts
- Shows your own position (blue marker)
- Automatically centers on your own position

### 9.4. Channel Messages
- Select a channel in the dropdown
- Type your message and click "Send"
- Received messages appear in the messages list
- Filter messages via the checkboxes

### 9.5. Direct Messages (DM)
- Click on a contact in the contacts list
- A dialog opens where you can type your message
- Click "Send" to send the DM

### 9.6. Message Route Visualization

Click on any message in the messages list to open a route page in a new tab. The route page shows:

- **Hop summary** — Number of hops and SNR
- **Interactive map** — Leaflet map with markers for sender, repeaters and receiver, connected by a polyline showing the message path
- **Route table** — Detailed table with each hop: name, ID (first byte of public key), node type and GPS coordinates
- **Reply panel** — Pre-filled reply message with route acknowledgement (sender, path length, repeater IDs)

Route data is resolved from two sources (in priority order):
1. **RX log packet decode** — Path hashes extracted from the raw LoRa packet via `meshcoredecoder`
2. **Contact out_path** — Stored route from the sender's contact record (fallback)

<!-- CHANGED: Self-contained route table data (v1.7.1) -->
Route table data (path hashes, resolved repeater names and channel names) is captured at receive time and stored in the archive. This means route tables (names and IDs) remain correct even when contacts are renamed, removed or offline. Sender identity is resolved via pubkey lookup with an automatic name-based fallback when the pubkey lookup fails. Map visualization still depends on live contact GPS data — see [13. Known Limitations](#13-known-limitations).

<!-- ADDED: Room Server section (v5.7.0) -->
### 9.7. Room Server

Room Servers (type=3 contacts) allow group-style messaging via a shared server node in the mesh network.

**Adding a Room Server:** Click on any Room Server contact (🏠 icon) in the contacts list. A dialog opens where you enter the room password. Click "Add & Login" to create a dedicated room panel and log in.

**Room panel features:**
- Each Room Server gets its own card in the centre column below the Messages panel
- After login: the password field is replaced by a Logout button
- Messages from the room are displayed in the card with correct author attribution (the real sender, not the room server)
- Send messages to the room via the input field and Send button
- Room panels are restored from stored passwords on app restart

**How it works under the hood:**
- Login via `send_login(pubkey, password)` — the Room Server authenticates and starts pushing messages over LoRa RF
- Messages arrive asynchronously via `MESSAGES_WAITING` events (event-driven, no polling)
- Room messages use `txt_type=2` (signed), where the `signature` field contains the 4-byte pubkey prefix of the real author
- The first message may take 10–75 seconds to arrive after login (inherent LoRa RF latency)
- Passwords are stored in `~/.meshcore-gui/room_passwords/` outside the repository

**Note:** The Room Server pushes messages round-robin to all logged-in clients. With many clients or large message buffers, it can take several minutes to receive all historical messages.

### 9.8. Message Archive

All incoming messages and RX log entries are automatically persisted to disk in `~/.meshcore-gui/archive/`. One JSON file per data type per device identifier.

Click the **📚 Archive** button in the Messages panel header to open the archive viewer in a new tab. The archive viewer provides:

- **Pagination** — 50 messages per page, with Previous/Next navigation
- **Channel filter** — Filter by specific channel or view all
- **Time range filter** — Last 24 hours, 7 days, 30 days, 90 days, or all time
- **Text search** — Case-insensitive search in message text
- **Inline route tables** — Expandable route display per message (sender, repeaters, receiver with names and IDs)
- **Reply from archive** — Expandable reply panel per message with pre-filled @sender mention

Old data is automatically cleaned up based on configurable retention periods (`MESSAGE_RETENTION_DAYS`, `RXLOG_RETENTION_DAYS` in `config.py`).

### 9.9. Local Cache

Device info, contacts and channel keys are automatically cached to disk in `~/.meshcore-gui/cache/`. One JSON file is created per device identifier.

**Startup behaviour:**
1. Cache is loaded first — GUI is immediately populated with the last known state
2. Connection is established in the background (serial or BLE)
3. Fresh data from the device updates both the GUI and the cache

**Channel key loading:**

Channel key loading uses a cache-first strategy with device fallback:

1. Cached keys are loaded first and never overwritten by name-derived fallbacks
2. Each channel is queried from the device at startup
3. Channels that fail are retried in the background every 30 seconds
4. Successfully loaded keys are immediately written to the cache for next startup

**Contact merge strategy:**
- New contacts from the device are added to the cache with a `last_seen` timestamp
- Existing contacts are updated (fresh data wins)
- Contacts only in cache (node offline) are preserved

If the connection fails (serial or BLE), the GUI remains usable with cached data and shows an offline status.

### 9.10. Keyword Bot

The built-in bot automatically replies to messages containing recognised keywords. Configure it via the dedicated **🤖 BOT** menu item.

<!-- CHANGED: v1.15.0 — bot moved from Actions panel to dedicated BOT panel -->
**BOT panel features:**
- **Enable / disable toggle** — activating the bot changes the device name to the configured `BOT_DEVICE_NAME`; disabling restores the original name.
- **Interactive channel assignment** — checkboxes for each discovered channel; selection is saved per device to `~/.meshcore-gui/bot/_<dev_id>_bot.json`.
- **Private mode** — when enabled the bot only responds to pinned contacts.  The toggle is disabled until at least one contact is pinned; auto-disables if all pins are removed.

**Device name switching:** When the bot is enabled, the device name is automatically changed to the configured `BOT_DEVICE_NAME` (default: `ZwolsBotje`). The original device name is saved and restored when bot mode is disabled. This allows the mesh network to identify the node as a bot by its name.

**Default keywords:**

| Keyword | Reply |
|---------|-------|
| `test` | `<sender>, rcvd \| SNR <snr> \| path(<hops>)` |
| `ping` | `Pong!` |
| `help` | `test, ping, help` |

**Safety guards:**
- Only replies on configured channels (interactive selection in BOT panel)
- Private mode: optionally restricts replies to pinned contacts only
- Ignores own messages and messages from other bots (names ending in "Bot")
- Cooldown period between replies (default: 5 seconds)

**Customisation:** Edit `BOT_KEYWORDS` in `meshcore_gui/services/bot.py`. Templates support `{sender}`, `{snr}` and `{path}` variables.

### 9.11. RX Log
- Received packets with SNR and type

### 9.12. Actions
- Refresh data
- Send advertisement
- Set device name

### 9.13. Public REST API

MeshCore GUI exposes a lightweight read-only REST API under `/api/v1/`.
It is designed for consumption by the [domca.nl](https://www.domca.nl)
statistics pages but can be used by any HTTP client on the same network.

Enable or disable the API in `meshcore_gui/config.py`:

```python
API_ENABLED: bool = True          # set False to disable all endpoints
API_CORS_ORIGINS: list[str] = ["*"]   # restrict to your RPi IP in production
```

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/stats` | Network statistics for the last 72 hours |
| GET | `/api/v1/nodes` | All known mesh nodes with GPS and type |
| GET | `/api/v1/messages?limit=100&offset=0` | Paginated public channel messages |
| GET | `/api/v1/channels` | Channel list with `is_private` flag |

**Privacy guarantee:** the `/api/v1/messages` endpoint returns messages from
`Public` (index 0) and `#hashtag` channels **only**. Private channel messages
are unconditionally excluded — no authentication is needed because there is
nothing private in the response.

#### Quick test

```bash
curl http://<meshcore-ip>:8081/api/v1/stats | python3 -m json.tool
curl "http://<meshcore-ip>:8081/api/v1/messages?limit=5"
```

#### Example responses

`GET /api/v1/stats`
```json
{
  "generated_at": "2026-04-04T10:00:00+00:00",
  "period_hours": 72,
  "total_messages": 1240,
  "unique_senders": 38,
  "active_clients": 89,
  "active_repeaters": 12,
  "active_room_servers": 3,
  "avg_hops": 1.8,
  "peak_hour": 14
}
```

`GET /api/v1/channels`
```json
[
  {"idx": 0, "name": "Public",     "is_private": false},
  {"idx": 1, "name": "#localmesh", "is_private": false},
  {"idx": 2, "name": "TeamNL",     "is_private": true}
]
```

### 9.14. BBS — Bulletin Board System

MeshCore GUI includes an offline BBS that lets mesh nodes exchange structured messages by category, with optional region tagging.

#### Access model

The operator links one or more channels to the BBS. Anyone who sends a message on a configured BBS channel is automatically added to the whitelist. After that, they can send commands via **Direct Message** to the BBS node — the channel itself stays clean.

```
First contact:  !bbs help  on the configured channel
                → node sees the public key → whitelists it
After that:     !p U need assistance  as DM to the node
                → processed, reply sent back via DM
```

Anyone who has never sent a message on a configured channel is not on the whitelist and is silently ignored.

#### Settings

Open via the gear icon (⚙) in the BBS panel, or navigate to `/bbs-settings`.

```
BBS Settings
──────────────────────────────────────────
Channels:    ☑ [1] NoodNet Zwolle
             ☑ [2] NoodNet Dalfsen
             ☐ [3] NoodNet OV
Categories:  URGENT, MEDICAL, LOGISTICS, STATUS, GENERAL
Retain:      48 hours
[Save]

▶ Advanced
  Regions (comma-separated)
  Allowed keys (DM-BBS whitelist)
```

- **Channels** — check all channels whose participants should have access to the BBS. Multiple channels can be selected.
- **Categories** — comma-separated list of valid category tags.
- **Retain** — message retention in hours (default 48).
- **Advanced → Regions** — optional region tags for geographic filtering.
- **Advanced → Allowed keys** — manual whitelist override; leave empty to rely on auto-learned keys only.

#### Command syntax

##### Short syntax

| Command | Description |
|---|---|
| `!p <cat> <text>` | Post a message |
| `!p <region> <cat> <text>` | Post with region |
| `!r` | Read 5 most recent messages (all categories) |
| `!r <cat>` | Read filtered by category |
| `!r <cat> <from-to>` | Read with range, e.g. `!r U 6-10` |
| `!r <region> <cat> <from-to>` | Read filtered by region, category and range |
| `!s <cat> <query>` | Search messages in a category |
| `!s <region> <cat> <query>` | Search with region filter |
| `!h` | Show help and abbreviation table |

Category abbreviations are computed automatically as the shortest unique prefix within the configured list. Example with `URGENT, MEDICAL, LOGISTICS, STATUS, GENERAL`:

```
U=URGENT  M=MEDICAL  L=LOGISTICS  S=STATUS  G=GENERAL
```

If two categories share the same leading letters (e.g. `MEDICAL` and `MISSING`), longer prefixes are calculated automatically: `ME` and `MI`. The `!r` (without arguments) and `!h` / `!bbs help` replies always include the current abbreviation table.

**Range pagination** — messages are returned newest first, 1-indexed:

| Range | Returns |
|---|---|
| `!r U 1-5` | Messages 1–5 (same as `!r U`) |
| `!r U 6-10` | Messages 6–10 |
| `!r U 15-40` | Messages 15–40 |

**Search** — case-insensitive substring match across message bodies, all results returned:

```
!s U assistance         → all URGENT messages containing "assistance"
!s Zwolle U water       → all URGENT messages in region Zwolle containing "water"
```

##### Full syntax

| Command | Description |
|---|---|
| `!bbs help` | Show commands and abbreviation table |
| `!bbs post <category> <text>` | Post a message |
| `!bbs post <region> <category> <text>` | Post with region |
| `!bbs read` | Read 5 most recent messages |
| `!bbs read <category>` | Read filtered by category |
| `!bbs read <category> <from-to>` | Read with range |
| `!bbs read <region> <category> <from-to>` | Read filtered by region, category and range |

##### Example help reply

```
BBS [NoodNet Zwolle, NoodNet Dalfsen] | !p [cat] [text] | !r [cat] [1-5] | !s [cat] [query] | U=URGENT M=MEDICAL L=LOGISTICS S=STATUS G=GENERAL
```

#### Error handling

| Situation | Reply |
|---|---|
| Unknown category | Lists valid categories and abbreviations |
| Ambiguous abbreviation | Lists all matching categories |
| Sender not on whitelist | Silent drop — no reply |

#### Storage

```
~/.meshcore-gui/bbs/bbs_messages.db    — SQLite message store (WAL mode)
~/.meshcore-gui/bbs/bbs_config.json    — Board configuration
```

## 10. Architecture

<!-- CHANGED: Architecture diagram updated — added BBS, ChannelService, PublicAPIService, MapSnapshotService -->

```
┌─────────────────┐     ┌─────────────────┐
│   Main Thread   │     │  Worker Thread  │
│   (NiceGUI)     │     │   (asyncio)     │
│                 │     │                 │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ Dashboard │◄─┼──┬──┼─►│  Worker   │  │
│  └───────────┘  │  │  │  │ (Serial   │  │
│        │        │  │  │  │  or BLE)  │  │
│        ▼        │  │  │  └─────┬─────┘  │
│  ┌───────────┐  │  │  │   │Commands │   │
│  │  Timer    │  │  │  │   │Events   │   │
│  │  (500ms)  │  │  │  │   │Decoder  │   │
│  └───────────┘  │  │  │   └────┬────┘   │
│        │        │  │  │        │        │
│  ┌─────┴─────┐  │  │  │   ┌────┴────┐   │
│  │  Panels   │  │  │  │   │   Bot   │   │
│  │  RoutePage│  │  │  │   │  Dedup  │   │
│  │ ArchivePg │  │  │  │   │  Cache  │   │
│  │ RoomSrvPnl│  │  │  │   │  BBS   │   │
│  │  BBSPanel │  │  │  │   └─────────┘   │
│  │  BotPanel │  │  │  │   ┌─────────┐   │
│  └───────────┘  │  │  │   │Reconnect│   │
│                 │  │  │   │  Loop   │   │
│  ┌───────────┐  │  │  │   └─────────┘   │
│  │  REST API │  │  │  │                 │
│  │ /api/v1/  │  │  │  │                 │
│  └───────────┘  │  │  │                 │
└─────────────────┘  │  └─────────────────┘
              ┌──────┴──────┐
              │ SharedData  │     ┌───────────────┐
              │ (thread-    │     │ DeviceCache   │
              │  safe)      │     │ (~/.meshcore- │
              └──────┬──────┘     │  gui/cache/)  │
                     │            └───────────────┘
              ┌──────┴──────┐     ┌───────────────┐
              │ Message     │     │ PinStore      │
              │ Archive     │     │ Contact       │
              │ (~/.meshcore│     │  Cleaner      │
              │ -gui/       │     │ RoomPassword  │
              │  archive/)  │     │  Store        │
              └─────────────┘     │ ChannelService│
                                  │ MapSnapshot   │
                                  └───────────────┘
```

- **Worker (Serial/BLE)**: Runs in separate thread with its own asyncio loop. Auto-detected transport: `SerialWorker` for USB serial, `BLEWorker` for Bluetooth LE (with PIN agent and bond management). Both share a common base class with disconnect detection, auto-reconnect and background key retry
- **CommandHandler**: Executes commands (send message, advert, refresh, purge unpinned, set auto-add, set bot name, restore name, login room, send room msg, remove single contact)
- **EventHandler**: Processes incoming device events (messages, RX log) with path hash caching between RX_LOG and fallback handlers, and resolves repeater names at receive time for self-contained archive data
- **PacketDecoder**: Decodes raw LoRa packets and extracts route data
- **MeshBot**: Keyword-triggered auto-reply on configured channels with automatic device name switching
- **DualDeduplicator**: Prevents duplicate messages (hash-based + content-based)
- **DeviceCache**: Local JSON cache per device for instant startup and offline resilience
- **MessageArchive**: Persistent storage for messages and RX log with configurable retention and automatic cleanup
- **PinStore**: Persistent pin state storage per device (JSON-backed)
- **ContactCleanerService**: Bulk-delete logic for unpinned contacts with statistics
- **ChannelService**: Manages channel discovery, add, delete and re-indexing; persists channel keys to the device cache
- **BbsService**: Bulletin Board System — processes DM commands, manages the SQLite message store and whitelist
- **PublicApiService**: Aggregates data from SharedData and MessageArchive for the REST API; enforces privacy filtering (no private channel messages)
- **MapSnapshotService**: Builds a point-in-time snapshot of node positions and device state for use by the REST API `/api/v1/nodes` endpoint
- **RoomServerPanel**: Per-room-server card management with login/logout, message display and send functionality
- **RoomPasswordStore**: Persistent Room Server password storage per device in `~/.meshcore-gui/room_passwords/` (JSON-backed, analogous to PinStore)
- **SharedData**: Thread-safe data sharing between serial worker and GUI via Protocol interfaces
- **DashboardPage**: Main GUI with modular panels (device, contacts, map, messages, etc.)
- **RoutePage**: Standalone route visualization page opened per message
- **ArchivePage**: Archive viewer with filters, pagination and inline route tables
- **REST API** (`/api/v1/`): Read-only NiceGUI/FastAPI endpoints served alongside the dashboard; see [9.13. Public REST API](#913-public-rest-api)
- **Communication**: Via command queue (GUI→worker) and shared state with flags (worker→GUI)

## 11. Cross-Frequency Bridge

### 11.1. Bridge Overview

**meshcore_bridge** is a standalone daemon that connects two MeshCore devices operating on different radio frequencies. It forwards messages on a configurable bridge channel from one device to the other, effectively extending your mesh network across frequency boundaries.

The bridge runs as an independent process, imports the existing meshcore_gui modules (SharedData, Worker, models, config) as a library, and requires **zero modifications** to the meshcore_gui codebase.

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
│  └───────────────────────────────────┘    │
└───────────────────────────────────────────┘
```

Key properties:

- **Separate process** — the bridge runs independently from meshcore_gui; both can run simultaneously on the same host
- **Loop prevention** — three mechanisms prevent message loops: direction filter, message hash tracking, and echo suppression
- **Private channels** — encrypted channels work transparently because the bridge operates at the plaintext level between firmware decryption and encryption
- **DOMCA dashboard** — status page on its own port showing both device connections, bridge statistics and a forwarded message log
- **YAML configuration** — all settings in a single `bridge_config.yaml` file

### 11.2. Quick Start

```bash
# 1. Install the additional dependency
pip install pyyaml

# 2. Edit the configuration
cp bridge_config.yaml bridge_config.yaml.local
nano bridge_config.yaml.local

# 3. Start the bridge
python meshcore_bridge.py --config=bridge_config.yaml.local

# 4. Open the dashboard at http://localhost:9092
```

**Prerequisites**: two MeshCore devices connected via USB serial to the same host, with the bridge channel configured on both devices using the same channel secret/password.

### 11.3. Bridge Configuration

All settings are defined in `bridge_config.yaml`:

```yaml
bridge:
  channel_name: "bridge"        # Channel name (for display)
  channel_idx_a: 3              # Channel index on device A
  channel_idx_b: 3              # Channel index on device B
  poll_interval_ms: 200         # Polling interval (ms)
  forward_prefix: true          # Add [sender] prefix to forwarded messages
  max_forwarded_cache: 500      # Loop prevention cache size

device_a:
  port: /dev/ttyUSB1
  baud: 115200
  label: "869.525 MHz"

device_b:
  port: /dev/ttyUSB2
  baud: 115200
  label: "868.000 MHz"

gui:
  port: 9092
  title: "MeshCore Bridge"
```

CLI options: `--config=PATH`, `--port=PORT`, `--debug-on`, `--help`.

### 11.4. systemd Service

Install the bridge as a systemd daemon for production use:

```bash
sudo bash install_scripts/install_bridge.sh
sudo nano /etc/meshcore/bridge_config.yaml
sudo systemctl start meshcore-bridge
sudo systemctl enable meshcore-bridge
```

To uninstall: `sudo bash install_scripts/install_bridge.sh --uninstall`

For full documentation including architecture details, troubleshooting and assumptions, see [BRIDGE.md](BRIDGE.md).

## 12. Known Limitations

1. **Channel discovery timing** — Dynamic channel discovery probes the device at startup; on very slow links (especially BLE), some channels may be missed on first attempt. Channels are retried in the background and cached for subsequent startups when `CHANNEL_CACHE_ENABLED = True`
2. **Initial load time** — GUI waits for device data before the first render is complete (mitigated by cache: if cached data exists, the GUI populates instantly)
3. **Archive route map visualization** — Route table names and IDs are now stored at receive time and display correctly regardless of current contacts. However, the route *map* still depends on GPS coordinates from contacts currently in memory; archived messages without recent contact data may show incomplete map markers
<!-- CHANGED: Partially resolved in v1.7.1 — route table self-contained, map still depends on live GPS -->
4. **Room Server message latency** — Room Server messages travel over LoRa RF and arrive asynchronously (10–75 seconds per message). With many logged-in clients, receiving all historical messages can take 10+ minutes due to the round-robin push protocol
5. **BLE Linux only** — BLE mode requires Linux with BlueZ and D-Bus. macOS and Windows are not supported for BLE connections because the PIN agent relies on the D-Bus system bus
6. **BlueZ 5.66+ instability** — Recent BlueZ versions (shipped with Ubuntu 24.04, Debian Bookworm, Raspberry Pi OS Bookworm) can cause BLE connection instability, pairing failures and unexpected disconnects. USB serial is not affected and is recommended as the most reliable transport

## 13. Troubleshooting

### 13.1. Linux

For Linux troubleshooting, start by checking device permissions and that the correct device argument is used.

#### 13.1.1. Serial Quick Fixes

##### GUI remains empty / serial connection fails

1. Check the service logs:
   ```bash
   journalctl -u meshcore-gui -n 50 --no-pager
   ```
2. Confirm the serial device exists and is readable:
   ```bash
   ls -l /dev/serial/by-id
   ```
3. Ensure your user has serial permissions (commonly `dialout` on Linux):
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```
4. Kill any existing GUI instance and free the port:
   ```bash
   pkill -9 -f meshcore_gui
   sleep 3
   ```
5. Restart the GUI:
   ```bash
   python meshcore_gui.py /dev/ttyUSB0
   ```

#### 13.1.2. BLE Quick Fixes

##### GUI remains empty / BLE connection fails

1. Verify Bluetooth is running:
   ```bash
   sudo systemctl status bluetooth
   ```
   If not running: `sudo systemctl start bluetooth`

2. Check that the device is visible:
   ```bash
   bluetoothctl scan on
   ```
   Look for your device's MAC address. Press `Ctrl+C` to stop scanning.

3. Verify the D-Bus policy is installed:
   ```bash
   ls -l /etc/dbus-1/system.d/meshcore-ble.conf
   ```
   If missing, see [5.1.1. D-Bus Policy for BLE](#511-d-bus-policy-for-ble-linux-only).

4. Remove stale BLE bond (if the device was previously paired):
   ```bash
   bluetoothctl remove AA:BB:CC:DD:EE:FF
   ```

5. Kill any existing GUI instance:
   ```bash
   pkill -9 -f meshcore_gui
   sleep 3
   ```

6. Restart the GUI:
   ```bash
   python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on
   ```
   Check the debug output for D-Bus or pairing errors.

##### BLE PIN agent errors

If you see `org.freedesktop.DBus.Error.AccessDenied` in the logs, the D-Bus policy is missing or incorrect. Reinstall it per [5.1.1](#511-d-bus-policy-for-ble-linux-only) and reload D-Bus:

```bash
sudo systemctl reload dbus
```

##### BLE reconnect issues

If the connection drops and does not recover, the BLE bond may be stale. The application includes automatic bond cleanup and reconnect logic, but in some cases a manual bond removal is needed:

```bash
bluetoothctl remove AA:BB:CC:DD:EE:FF
sudo systemctl restart meshcore-gui
```

##### BlueZ 5.66+ driver instability

If BLE connections are consistently unreliable (frequent disconnects, pairing loops, authentication errors), the issue is likely caused by changes in BlueZ 5.66+. Check your BlueZ version:

```bash
bluetoothctl --version
```

If the version is 5.66 or higher, you have several options:

1. **Switch to USB serial** (recommended) — the most reliable workaround. Connect your device via USB and use serial mode instead:
   ```bash
   python meshcore_gui.py /dev/ttyACM0
   ```

2. **Downgrade BlueZ** — on Debian/Ubuntu, you can pin an older version:
   ```bash
   sudo apt install bluez=5.65-0ubuntu1
   sudo apt-mark hold bluez
   ```
   Note: exact package versions vary by distribution.

3. **Disable LE Privacy and Secure Connections** — in some cases, adding these options to `/etc/bluetooth/main.conf` can help:
   ```ini
   [General]
   Privacy = off

   [LE]
   MinConnectionInterval=6
   MaxConnectionInterval=9
   ConnectionLatency=0
   ```
   Restart Bluetooth after editing: `sudo systemctl restart bluetooth`

### 13.2. macOS

- Ensure the device shows up under `/dev/tty.usb*`, `/dev/tty.usbserial*`, or `/dev/tty.usbmodem*`
- Close any other app that might be using the serial port

### 13.3. Windows

- Confirm the COM port in Device Manager → Ports (COM & LPT)
- Close any other app that might be using the COM port

### 13.4. All Platforms

#### 13.4.1. Device Not Found

**Serial:** Make sure the MeshCore device is powered on, running Serial Companion firmware, and the correct serial port is selected.

**BLE:** Ensure the device is powered on and discoverable (`bluetoothctl scan on`). Check that the MAC address is correct and that the BLE PIN matches (default: `123456`). On Linux, verify D-Bus permissions — see `docs/ble/BLE_ARCHITECTURE.md` for details.

#### 13.4.2. Messages Not Arriving

- Check if your channels are correctly configured
- Use `meshcli` to verify that messages are arriving

#### 13.4.3. Clearing the Cache

If cached data causes issues (e.g. stale contacts), delete the cache file:

```bash
rm ~/.meshcore-gui/cache/*.json
```

The cache will be recreated on the next successful serial connection.

## 14. Development

### 14.1. Debug Mode

Enable via command line flag:

```bash
python meshcore_gui.py /dev/ttyUSB0 --debug-on
```

Or set `DEBUG = True` in `meshcore_gui/config.py`.

Debug output is written to both stdout and a per-device rotating log file at `~/.meshcore-gui/logs/<ADDRESS>_meshcore_gui.log` (e.g. `F0_9E_9E_75_A3_01_meshcore_gui.log`).

### 14.2. Project Structure

<!-- CHANGED: Project structure updated — added api/, bbs_panel, bot_panel, channel_service, bbs_config_store, bot_config_store, map_snapshot_service, public_api_service, install_scripts/ -->

```
meshcore-gui/
├── meshcore_gui.py                  # Entry point (auto-detects Serial or BLE)
├── meshcore_gui/                    # Application package
│   ├── __init__.py
│   ├── __main__.py                  # Alternative entry: python -m meshcore_gui
│   ├── config.py                    # All settings: callsign, transport, channels, bot, API, retention, paths
│   ├── api/                         # REST API layer
│   │   ├── __init__.py
│   │   └── routes.py                # Read-only /api/v1/ endpoints registered on the NiceGUI app
│   ├── ble/                         # Connection layer (serial + BLE transport)
│   │   ├── __init__.py
│   │   ├── worker.py                # _BaseWorker + SerialWorker + BLEWorker + create_worker() factory; thread lifecycle, cache-first startup, disconnect detection, auto-reconnect, background key retry
│   │   ├── ble_agent.py             # BlueZ D-Bus PIN agent for BLE pairing (Linux only, lazy-loaded)
│   │   ├── ble_reconnect.py         # BLE bond cleanup and reconnect loop via D-Bus (lazy-loaded)
│   │   ├── commands.py              # Command execution (send, refresh, advert)
│   │   ├── events.py                # Event callbacks (messages, RX log) with path hash caching and name resolution at receive time
│   │   └── packet_decoder.py        # Raw LoRa packet decoding via meshcoredecoder
│   ├── core/                        # Domain models and shared state
│   │   ├── __init__.py
│   │   ├── models.py                # Dataclasses: Message, Contact, DeviceInfo, RxLogEntry, RouteNode
│   │   ├── shared_data.py           # Thread-safe shared data store
│   │   └── protocols.py             # Protocol interfaces (ISP/DIP)
│   ├── gui/                         # NiceGUI web interface
│   │   ├── __init__.py
│   │   ├── constants.py             # UI display constants
│   │   ├── dashboard.py             # Main dashboard page orchestrator, loads landing SVG from config.LANDING_SVG_PATH
│   │   ├── route_page.py            # Message route visualization page
│   │   ├── archive_page.py          # Message archive viewer with filters and pagination
│   │   └── panels/                  # Modular UI panels
│   │       ├── __init__.py
│   │       ├── device_panel.py      # Device info display
│   │       ├── contacts_panel.py    # Contacts list with DM, pin/unpin, bulk delete, auto-add toggle
│   │       ├── map_panel.py         # Leaflet map
│   │       ├── input_panel.py       # Message input and channel select
│   │       ├── filter_panel.py      # Channel filters and bot toggle
│   │       ├── messages_panel.py    # Filtered message display with archive button
│   │       ├── actions_panel.py     # Refresh and advert buttons
│   │       ├── bbs_panel.py         # BBS enable/configure panel (channel selection, settings link)
│   │       ├── bot_panel.py         # Bot enable/configure panel (channel selection, private mode)
│   │       ├── channel_panel.py     # Add Channel dialog (Hashtag / Private New / Private Existing)
│   │       ├── room_server_panel.py # Per-room-server card with login/logout and messages
│   │       └── rxlog_panel.py       # RX log table
│   └── services/                    # Business logic
│       ├── __init__.py
│       ├── bbs_config_store.py      # BBS configuration persistence (~/.meshcore-gui/bbs/bbs_config.json)
│       ├── bbs_service.py           # BBS engine: command parsing, whitelist, SQLite store, category abbreviations
│       ├── bot.py                   # Keyword-triggered auto-reply bot
│       ├── bot_config_store.py      # Bot channel/mode persistence per device (~/.meshcore-gui/bot/)
│       ├── cache.py                 # Local JSON cache per device (~/.meshcore-gui/cache/)
│       ├── channel_service.py       # Channel discovery, add, delete, re-indexing and key caching
│       ├── contact_cleaner.py       # Bulk-delete logic for unpinned contacts
│       ├── dedup.py                 # Message deduplication
│       ├── device_identity.py       # Device address normalisation helpers
│       ├── map_snapshot_service.py  # Builds node-position snapshots for the REST API
│       ├── message_archive.py       # Persistent message and RX log archive with retention and cleanup
│       ├── pin_store.py             # Persistent pin state storage per device (~/.meshcore-gui/pins/)
│       ├── public_api_service.py    # Data aggregation layer for /api/v1/ (enforces privacy filtering)
│       ├── room_password_store.py   # Persistent Room Server password storage per device
│       └── route_builder.py         # Route data construction
├── install_scripts/                 # Installer shell scripts
│   ├── install_venv.sh              # Create venv and install core Python dependencies
│   ├── install_serial.sh            # systemd service installer for serial connections
│   ├── install_ble_stable.sh        # systemd service installer for BLE connections (includes D-Bus policy)
│   ├── install_bridge.sh            # systemd service installer for the cross-frequency bridge
│   └── install_observer.sh          # systemd service installer for the observer daemon (in development)
├── meshcore_gui/static/             # Static assets served by NiceGUI
│   ├── icon.svg
│   ├── icon-192.png
│   ├── icon-512.png
│   ├── landing_default.svg          # Default landing page graphic (operator-replaceable)
│   ├── manifest.json                # PWA manifest
│   ├── leaflet_map_panel.js         # Leaflet map integration
│   └── leaflet_map_panel.css
├── docs/
│   ├── TROUBLESHOOTING.md           # BLE troubleshooting guide (detailed)
│   ├── MeshCore_GUI_Design.docx     # Design document
│   ├── ble_capture_workflow_t_1000_e_explanation.md
│   └── ble_capture_workflow_t_1000_e_uitleg.md
├── meshcore_bridge.py               # Bridge entry point
├── meshcore_bridge/                  # Bridge daemon package
│   ├── __init__.py
│   ├── __main__.py                  # CLI, dual-worker setup, NiceGUI server
│   ├── config.py                    # YAML config loading (BridgeConfig dataclass)
│   ├── bridge_engine.py             # Core bridge logic: poll, forward, dedup, loop prevention
│   └── gui/                         # Bridge dashboard (DOMCA themed)
│       ├── __init__.py
│       ├── dashboard.py             # Bridge status dashboard page
│       └── panels/
│           ├── __init__.py
│           ├── status_panel.py      # Device A/B connection status + statistics
│           └── log_panel.py         # Forwarded message log
├── bridge_config.yaml               # Bridge configuration template (YAML)
├── BRIDGE.md                        # Bridge documentation
├── .gitattributes
├── .gitignore
├── LICENSE
├── CHANGELOG.md
└── README.md
```

## 15. Roadmap

This project is under active development. The most common features from the official MeshCore Companion apps are being implemented gradually. Planned additions include:

- [x] **Cross-frequency bridge** — standalone daemon connecting two devices on different frequencies via configurable channel forwarding (see [11. Cross-Frequency Bridge](#11-cross-frequency-bridge))
- [x] **BBS — Bulletin Board System** — offline message board with DM-based commands, category/region filtering and automatic abbreviations (see [9.14. BBS](#914-bbs--bulletin-board-system))
- [ ] **Observer mode** — passively monitor mesh traffic without transmitting, useful for network analysis, coverage mapping and long-term logging. The systemd installer (`install_scripts/install_observer.sh`) is already available; the daemon itself is in development
- [ ] **Room Server administration** — authenticate as admin to manage Room Server settings and users directly from the GUI
- [ ] **Repeater management** — connect to repeater nodes to view status and adjust configuration

Have a feature request or want to contribute? Open an issue or submit a pull request.

## 16. Disclaimer

This is an **independent community project** and is not affiliated with or endorsed by the official [MeshCore](https://github.com/meshcore-dev) development team. It is built on top of the open-source `meshcore` Python library.

## 17. License

MIT License - see LICENSE file

## 18. Author

**PE1HVH** — [GitHub](https://github.com/pe1hvh)

## 19. Acknowledgments

- [MeshCore](https://github.com/meshcore-dev) — Mesh networking firmware and protocol
- [meshcore_py](https://github.com/meshcore-dev/meshcore_py) — Python bindings for MeshCore
- [meshcore-cli](https://github.com/meshcore-dev/meshcore-cli) — Command line interface
- [meshcoredecoder](https://github.com/meshcore-dev/meshcoredecoder) — LoRa packet decoder and channel crypto
- [NiceGUI](https://nicegui.io/) — Python GUI framework
