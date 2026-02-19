# MeshCore GUI
![Status](https://img.shields.io/badge/Status-Production-green.svg)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-orange.svg)

A graphical user interface for MeshCore mesh network devices via Bluetooth Low Energy (BLE) for on your desktop or as a headless service on your local network.

## Table of Contents

- [1. Why This Project Exists](#1-why-this-project-exists)
- [2. Features](#2-features)
- [3. Screenshots](#3-screenshots)
- [4. Requirements](#4-requirements)
  - [4.1. Platform Support](#41-platform-support)
- [5. Installation](#5-installation)
  - [5.1. System Dependencies](#51-system-dependencies)
  - [5.2. Clone the Repository](#52-clone-the-repository)
  - [5.3. Create Virtual Environment](#53-create-virtual-environment)
  - [5.4. Install Python Packages](#54-install-python-packages)
  - [5.5. BLE Pairing Setup](#55-ble-pairing-setup-linux-only--required)
- [6. Usage](#6-usage)
  - [6.1. Activate the Virtual Environment](#61-activate-the-virtual-environment)
  - [6.2. Find Your BLE Device Address](#62-find-your-ble-device-address)
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
- [10. Architecture](#10-architecture)
- [11. Known Limitations](#11-known-limitations)
- [12. Troubleshooting](#12-troubleshooting)
  - [12.1. Linux](#121-linux)
  - [12.2. macOS](#122-macos)
  - [12.3. Windows](#123-windows)
  - [12.4. All Platforms](#124-all-platforms)
- [13. Development](#13-development)
  - [13.1. Debug Mode](#131-debug-mode)
  - [13.2. Project Structure](#132-project-structure)
- [14. Roadmap](#14-roadmap)
- [15. Disclaimer](#15-disclaimer)
- [16. License](#16-license)
- [17. Author](#17-author)
- [18. Acknowledgments](#18-acknowledgments)

---

## 1. Why This Project Exists

MeshCore devices like the SenseCAP T1000-E can be managed through two interfaces: USB serial and BLE (Bluetooth Low Energy). The official companion apps communicate with devices over BLE, but they are mobile-only. If you want to manage your MeshCore device from a desktop or laptop, the usual approach is to **flash USB-serial firmware** via the web flasher. However, this replaces the BLE Companion firmware, which means you can no longer use the device with mobile companion apps (Android/iOS).

This project provides a **native desktop GUI** that connects to your MeshCore device over BLE:

- **No firmware changes required** — your device stays on BLE Companion firmware and remains fully compatible with the mobile apps
- **Cross-platform** — written in Python using cross-platform libraries, runs on Linux, macOS and Windows
- **Headless capable** — since the interface is web-based (powered by NiceGUI), it also runs headless on devices like a Raspberry Pi, accessible from any browser on your local network
- **Message archive** — all messages are persisted to disk with configurable retention, so you maintain a searchable history of mesh traffic
- **Bots and observation** — run a keyword-triggered auto-reply bot or passively observe mesh traffic 24/7 without dedicated hardware, using any device that has Bluetooth
- **Room Server support** — login to Room Servers directly from the GUI with dedicated message panels per room

> **Note:** This project is under active development. Not all features from the official MeshCore Companion apps have been implemented yet. Contributions and feedback are welcome.

> **Note:** This application has been tested on Linux (Ubuntu 24.04) and Raspberry Pi 5 (Debian Bookworm, headless). macOS and Windows should work since all dependencies (`bleak`, `nicegui`, `meshcore`) are cross-platform, but this has not been verified. Feedback and contributions for other platforms are welcome.

Under the hood it uses `bleak` for Bluetooth Low Energy (which talks to BlueZ on Linux, CoreBluetooth on macOS, and WinRT on Windows), `meshcore` as the protocol layer, `meshcoredecoder` for raw LoRa packet decryption and route extraction, and `NiceGUI` for the web-based interface.

> **Linux users:** BLE on Linux can be temperamental. BlueZ occasionally gets into a bad state, especially after repeated connect/disconnect cycles. Since v5.11.0 MeshCore GUI includes a **built-in BLE PIN agent** and **automatic reconnect with bond cleanup**, eliminating the need for external tools like `bt-agent` or manual `bluetoothctl remove` commands. If you run into connection issues, see the [Troubleshooting Guide](docs/TROUBLESHOOTING.md). On macOS and Windows, BLE is generally more stable out of the box.


## 2. Features

- **Real-time Dashboard** — Device info, contacts, messages and RX log
- **Interactive Map** — Leaflet map with markers for own position and contacts
- **Channel Messages** — Send and receive messages on channels
- **Direct Messages** — Click on a contact to send a DM
- **Contact Maintenance** — Pin/unpin contacts to protect them from deletion, bulk-delete unpinned contacts from the device, and toggle automatic contact addition from mesh adverts
- **Message Filtering** — Filter messages per channel via checkboxes
- **Message Route Visualization** — Click any message to open a detailed route page showing the path (hops) through the mesh network on an interactive map, with a hop summary, route table and reply panel
- **Message Archive** — All messages and RX log entries are persisted to disk with configurable retention. Browse archived messages via the archive viewer with filters (channel, time range, text search), pagination and inline route tables
<!-- ADDED: Message Archive feature was missing from features list -->
- **Room Server Support** — Login to Room Servers directly from the GUI. Each Room Server gets a dedicated panel with message display, send functionality and login/logout controls. Passwords are stored securely outside the repository. Message author attribution correctly resolves the real sender from signed messages
<!-- ADDED: Room Server feature (v5.7.0) -->
- **Dynamic Channel Discovery** — Channels are automatically discovered from the device at startup via BLE probing, eliminating the need to manually configure `CHANNELS_CONFIG`
<!-- ADDED: Dynamic channel discovery (v5.7.0) -->
- **Keyword Bot** — Built-in auto-reply bot that responds to configurable keywords on selected channels, with cooldown and loop prevention
- **Packet Decoding** — Raw LoRa packets from RX log are decoded and decrypted using channel keys, providing message hashes, path hashes and hop data
- **Message Deduplication** — Dual-strategy dedup (hash-based and content-based) prevents duplicate messages from appearing
- **Local Cache** — Device info, contacts and channel keys are cached to disk (`~/.meshcore-gui/cache/`) so the GUI is instantly populated on startup from the last known state, even before BLE connects. Contacts from the device are merged with cached contacts so offline nodes are preserved. Channel keys that fail to load at startup are retried in the background every 30 seconds
- **Periodic Contact Refresh** — Contacts are automatically refreshed from the device at a configurable interval (default: 5 minutes) and merged with the cache
- **Threaded Architecture** — BLE communication in separate thread for stable UI
- **BLE Connection Stability** — Built-in D-Bus PIN agent (no external `bt-agent` needed), automatic bond cleanup on startup, and automatic reconnect with linear backoff after disconnect

## 3. Screenshots

<img width="1000" height="873" alt="a_Screenshots" src="https://github.com/user-attachments/assets/bd19de9a-05f7-43fd-8acd-3b92cdf6c7fa" />
<img width="944" height="877" alt="Screenshot from 2026-02-18 09-27-59" src="https://github.com/user-attachments/assets/6b0b19f4-9886-4cca-bd36-50b4c3797e02" />
<img width="944" height="877" alt="Screenshot from 2026-02-18 09-28-27" src="https://github.com/user-attachments/assets/374694fa-ab2d-4b96-b81f-6a351af7710a" />

## 4. Requirements

- Python 3.10+
- Bluetooth Low Energy compatible adapter (built-in or USB)
- MeshCore device with BLE Companion firmware

### 4.1. Platform Support

| Platform | BLE Backend | Status |
|---|---|---|
| Linux (Ubuntu/Debian) | BlueZ/D-Bus | ✅ Tested |
| Raspberry Pi 5 (Debian Bookworm) | BlueZ/D-Bus | ✅ Tested (headless) |
| macOS | CoreBluetooth | ⬜ Untested |
| Windows 10/11 | WinRT | ⬜ Untested |

## 5. Installation

### 5.1. System Dependencies

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv bluetooth bluez
sudo usermod -aG bluetooth $USER
```

> **Important:** Log out and back in after adding yourself to the `bluetooth` group. Without this step, BLE connections will fail with permission errors.

**Raspberry Pi (Raspberry Pi OS Lite):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv bluetooth bluez git
sudo usermod -aG bluetooth $USER
```

**macOS:**
```bash
# Python 3.10+ via Homebrew (if not already installed)
brew install python
```
No additional Bluetooth packages needed — macOS has CoreBluetooth built in.

**Windows:**
- Install [Python 3.10+](https://www.python.org/downloads/) (check "Add to PATH" during installation)
- No additional Bluetooth packages needed — Windows 10/11 has WinRT built in.

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

```bash
pip install nicegui meshcore bleak meshcoredecoder
```

### 5.5. BLE Pairing Setup (Linux only — required)

MeshCore GUI includes a built-in D-Bus PIN agent that handles BLE pairing automatically at runtime. However, **one-time setup is required** to grant the agent permission to access BlueZ via D-Bus.

> **Note:** On macOS and Windows, BLE pairing is handled natively by the OS. Skip this step.

**Option A — Automated (recommended):**

```bash
bash install_ble_stable.sh
```

This creates the D-Bus policy file and optionally sets up a systemd service.

**Option B — Manual:**

```bash
sudo tee /etc/dbus-1/system.d/meshcore-ble.conf << EOF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="$(whoami)">
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.Agent1"/>
    <allow send_interface="org.bluez.AgentManager1"/>
  </policy>
</busconfig>
EOF
```

**Verify** the file exists before proceeding:

```bash
ls /etc/dbus-1/system.d/meshcore-ble.conf
```

> **⚠️ Without this step, the application will show "Not Paired" errors and BLE connections will fail repeatedly.**

The PIN defaults to `123456` and can be overridden at startup with `--ble-pin=PIN`, or by editing `BLE_PIN` in `meshcore_gui/config.py`.

> **Migrating from bt-agent:** If you previously used `bt-agent.service` for PIN pairing, it is no longer needed. Remove it:
> ```bash
> sudo systemctl disable --now bt-agent
> sudo apt remove bluez-tools   # optional
> rm -f ~/.meshcore-ble-pin
> ```

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

### 6.2. Find Your BLE Device Address

**Linux:**
```bash
bluetoothctl scan on
```
Look for your MeshCore device and note the MAC address (e.g., `AA:BB:CC:DD:EE:FF`).

**macOS / Windows:**
```bash
python -c "
import asyncio
from bleak import BleakScanner
async def scan():
    devices = await BleakScanner.discover(5.0)
    for d in devices:
        if 'MeshCore' in (d.name or ''):
            print(f'{d.address}  {d.name}')
asyncio.run(scan())
"
```
On macOS the address will be a UUID (e.g., `12345678-ABCD-...`) rather than a MAC address.

### 6.3. Configure Channels (optional)

Channels are automatically discovered from the device at startup via BLE. No manual configuration is required.

If you want to cache the discovered channel list to disk (for faster startup), set `CHANNEL_CACHE_ENABLED = True` in `meshcore_gui/config.py`. By default, channels are always fetched fresh from the device.

> **Note:** The maximum number of channel slots probed can be adjusted via `MAX_CHANNELS` in `config.py` (default: 8, which matches the MeshCore protocol limit).

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

| Flag | Description | Default |
|------|-------------|---------|
| `--debug-on` | Enable verbose debug logging (stdout + log file) | Off |
| `--port=PORT` | Web server port | `8081` |
| `--ble-pin=PIN` | BLE pairing PIN | `123456` |

All flags are optional and can be combined in any order:

```bash
python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on --port=8082 --ble-pin=171227
```

### 7.2. Method 1: Interactive (foreground)

The simplest way to start — runs in your current terminal. Output is visible directly. Press `Ctrl+C` to stop.

```bash
python meshcore_gui.py AA:BB:CC:DD:EE:FF
```

Open your browser at `http://localhost:8081` (or the port you specified with `--port`).

This is the recommended method during development or when debugging, because you see all output immediately in your terminal.

### 7.3. Method 2: Background with Visible Output (nohup + tail)

Runs in the background but keeps the output visible in your terminal. Useful for SSH sessions where you want to monitor the application while keeping the terminal usable.

```bash
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
tail -f ~/meshcore.log
```

The first command starts the application in the background and writes all output to `~/meshcore.log`. The `&` at the end returns control to your terminal. The second command follows the log file in real-time — press `Ctrl+C` to stop following (the application keeps running).

### 7.4. Method 3: Background with Terminal Free (nohup)

Runs entirely in the background. Your terminal is free and the application survives closing your SSH session. Ideal for headless devices where you start the application once and leave it running.

```bash
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
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

The included install script auto-detects your username, project directory and Python venv path, then creates and enables the service. It also installs the D-Bus policy for BLE PIN pairing.

```bash
cd ~/meshcore-gui
BLE_ADDRESS=AA:BB:CC:DD:EE:FF bash install_ble_stable.sh
```

#### 7.5.2. Manual Setup

**Step 1 — Create the service file:**

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
ExecStart=/home/your-username/meshcore-gui/venv/bin/python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on --port=8081 --ble-pin=123456
Restart=on-failure
RestartSec=30
Environment=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket

[Install]
WantedBy=multi-user.target
```

Replace `your-username`, `AA:BB:CC:DD:EE:FF`, port and PIN with your actual values. Bond cleanup and PIN pairing are handled automatically by the built-in agent — no `ExecStartPre` or `bt-agent` dependency needed.

**Step 2 — Enable and start:**

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
python meshcore_gui.py AA:BB:CC:DD:EE:FF --port=8081 --ble-pin=123456 &
python meshcore_gui.py 11:22:33:44:55:66 --port=8082 --ble-pin=654321 &
```

Each instance gets its own log file, cache and archive, all keyed by the BLE address.

### 7.8. Migrating Existing Data

If you are moving from an existing installation, copy the data directory to preserve your cache, pinned contacts, room server passwords and message archive:

```bash
scp -r ~/.meshcore-gui user@headless-device:~/
```

### 7.9. Raspberry Pi 5 Notes

The Raspberry Pi 5 is a good fit for running MeshCore GUI headless:

- **BLE**: Built-in Bluetooth 5.0/BLE — no USB dongle required
- **RAM**: 2 GB is sufficient; 4 GB or more provides extra headroom for long-running operation
- **OS**: Raspberry Pi OS Lite (64-bit, Bookworm) — no desktop environment needed
- **Storage**: 16 GB+ SD card or NVMe; the application stores cache and archive data in `~/.meshcore-gui/`
- **Power**: Low idle power consumption (~5W), suitable for 24/7 operation

Make sure your user is in the `bluetooth` group:

```bash
sudo usermod -aG bluetooth $USER
```

If your MeshCore device has BLE PIN pairing enabled, make sure the D-Bus policy file is installed (see step 5 under Installation, or use `install_ble_stable.sh`). The built-in PIN agent handles pairing automatically.

## 8. Configuration

| Setting | Location | Description |
|---------|----------|-------------|
| `OPERATOR_CALLSIGN` | `meshcore_gui/config.py` | Operator callsign shown on landing page and drawer footer (default: `"PE1HVH"`) |
| `LANDING_SVG_PATH` | `meshcore_gui/config.py` | Path to the landing page SVG file; supports `{callsign}` placeholder (default: `static/landing_default.svg`) |
| `DEBUG` | `meshcore_gui/config.py` | Set to `True` for verbose logging (or use `--debug-on`) |
| `MAX_CHANNELS` | `meshcore_gui/config.py` | Maximum channel slots to probe on device (default: 8) |
| `CHANNEL_CACHE_ENABLED` | `meshcore_gui/config.py` | Cache discovered channels to disk for faster startup (default: `False` — always fresh from device) |
| `BLE_PIN` | `meshcore_gui/config.py` | BLE pairing PIN for the MeshCore device (default: `123456`). Override at startup with `--ble-pin=PIN` |
| `RECONNECT_MAX_RETRIES` | `meshcore_gui/config.py` | Maximum reconnect attempts after a BLE disconnect (default: 5) |
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
| BLE Address | CLI argument | Device MAC address (or UUID on macOS) |
| `--port=PORT` | CLI flag | Web server port (default: `8081`) |
| `--ble-pin=PIN` | CLI flag | BLE pairing PIN override (default: `123456`) |
| `--debug-on` | CLI flag | Enable verbose debug logging |

## 9. Functionality

### 9.1. Device Info
- Name, frequency, SF/BW, TX power, location, firmware version

### 9.2. Contacts
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
Route table data (path hashes, resolved repeater names and channel names) is captured at receive time and stored in the archive. This means route tables (names and IDs) remain correct even when contacts are renamed, removed or offline. Sender identity is resolved via pubkey lookup with an automatic name-based fallback when the pubkey lookup fails. Map visualization still depends on live contact GPS data — see [11. Known Limitations](#11-known-limitations).

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

All incoming messages and RX log entries are automatically persisted to disk in `~/.meshcore-gui/archive/`. One JSON file per data type per BLE device address.

Click the **📚 Archive** button in the Messages panel header to open the archive viewer in a new tab. The archive viewer provides:

- **Pagination** — 50 messages per page, with Previous/Next navigation
- **Channel filter** — Filter by specific channel or view all
- **Time range filter** — Last 24 hours, 7 days, 30 days, 90 days, or all time
- **Text search** — Case-insensitive search in message text
- **Inline route tables** — Expandable route display per message (sender, repeaters, receiver with names and IDs)
- **Reply from archive** — Expandable reply panel per message with pre-filled @sender mention

Old data is automatically cleaned up based on configurable retention periods (`MESSAGE_RETENTION_DAYS`, `RXLOG_RETENTION_DAYS` in `config.py`).

### 9.9. Local Cache

Device info, contacts and channel keys are automatically cached to disk in `~/.meshcore-gui/cache/`. One JSON file is created per BLE device address.

**Startup behaviour:**
1. Cache is loaded first — GUI is immediately populated with the last known state
2. BLE connection is established in the background
3. Fresh data from the device updates both the GUI and the cache

**Channel key loading:**

Channel key loading uses a cache-first strategy with BLE fallback:

1. Cached keys are loaded first and never overwritten by name-derived fallbacks
2. Each channel is queried from the device at startup
3. Channels that fail are retried in the background every 30 seconds
4. Successfully loaded keys are immediately written to the cache for next startup

> **Note:** Prior to v5.6.0, BLE commands frequently timed out due to a race condition in the meshcore SDK. The patched SDK resolves this — see [11. Known Limitations](#11-known-limitations) for installation instructions. Since v5.7.0, channels are discovered dynamically from the device, eliminating the need for manual `CHANNELS_CONFIG` setup.

**Contact merge strategy:**
- New contacts from the device are added to the cache with a `last_seen` timestamp
- Existing contacts are updated (fresh data wins)
- Contacts only in cache (node offline) are preserved

If BLE connection fails, the GUI remains usable with cached data and shows an offline status.

### 9.10. Keyword Bot

The built-in bot automatically replies to messages containing recognised keywords. Enable or disable it via the 🤖 BOT checkbox in the filter bar.

<!-- CHANGED: Bot device name switching feature added in v5.5.0 -->
**Device name switching:** When the BOT checkbox is enabled, the device name is automatically changed to the configured `BOT_DEVICE_NAME` (default: `;NL-OV-ZWL-STDSHGN-WKC Bot`). The original device name is saved and restored when bot mode is disabled. This allows the mesh network to identify the node as a bot by its name.

**Default keywords:**

<!-- CHANGED: Removed "Zwolle Bot:" prefix from example replies — bot replies no longer include a name prefix (v5.5.0) -->

| Keyword | Reply |
|---------|-------|
| `test` | `<sender>, rcvd \| SNR <snr> \| path(<hops>); <repeaters>` |
| `ping` | `Pong!` |
| `help` | `test, ping, help` |

**Safety guards:**
- Only replies on configured channels (`BOT_CHANNELS`)
- Ignores own messages and messages from other bots (names ending in "Bot")
- Cooldown period between replies (default: 5 seconds)

**Customisation:** Edit `BOT_KEYWORDS` in `meshcore_gui/services/bot.py`. Templates support `{sender}`, `{snr}` and `{path}` variables.

### 9.11. RX Log
- Received packets with SNR and type

### 9.12. Actions
- Refresh data
- Send advertisement

## 10. Architecture

<!-- CHANGED: Architecture diagram updated — added RoomServerPanel and RoomPasswordStore (v5.7.0) -->

```
┌─────────────────┐     ┌─────────────────┐
│   Main Thread   │     │   BLE Thread    │
│   (NiceGUI)     │     │   (asyncio)     │
│                 │     │                 │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ Dashboard │◄─┼──┬──┼─►│ BLEWorker │  │
│  └───────────┘  │  │  │  └─────┬─────┘  │
│        │        │  │  │        │        │
│        ▼        │  │  │   ┌────┴────┐   │
│  ┌───────────┐  │  │  │   │Commands │   │
│  │  Timer    │  │  │  │   │Events   │   │
│  │  (500ms)  │  │  │  │   │Decoder  │   │
│  └───────────┘  │  │  │   └────┬────┘   │
│        │        │  │  │        │        │
│  ┌─────┴─────┐  │  │  │   ┌────┴────┐   │
│  │  Panels   │  │  │  │   │   Bot   │   │
│  │  RoutePage│  │  │  │   │  Dedup  │   │
│  │ ArchivePg │  │  │  │   │  Cache  │   │
│  │ RoomSrvPnl│  │  │  │   └─────────┘   │
│  └───────────┘  │  │  │   ┌─────────┐   │
│                 │  │  │   │BleAgent │   │
│                 │  │  │   │Reconnect│   │
│                 │  │  │   └─────────┘   │
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
              └─────────────┘     └───────────────┘
```

- **BLEWorker**: Runs in separate thread with its own asyncio loop, with built-in PIN agent, automatic bond cleanup, disconnect detection, auto-reconnect and background retry for missing channel keys
- **BleAgentManager**: Built-in D-Bus PIN agent that registers with BlueZ and handles pairing requests automatically (replaces external `bt-agent.service`)
- **reconnect_loop**: Bond cleanup via D-Bus + reconnect with linear backoff after disconnect (replaces manual `bluetoothctl remove`)
- **CommandHandler**: Executes commands (send message, advert, refresh, purge unpinned, set auto-add, set bot name, restore name, login room, send room msg, remove single contact)
- **EventHandler**: Processes incoming BLE events (messages, RX log) with path hash caching between RX_LOG and fallback handlers, and resolves repeater names at receive time for self-contained archive data
- **PacketDecoder**: Decodes raw LoRa packets and extracts route data
- **MeshBot**: Keyword-triggered auto-reply on configured channels with automatic device name switching
- **DualDeduplicator**: Prevents duplicate messages (hash-based + content-based)
- **DeviceCache**: Local JSON cache per device for instant startup and offline resilience
- **MessageArchive**: Persistent storage for messages and RX log with configurable retention and automatic cleanup
- **PinStore**: Persistent pin state storage per device (JSON-backed)
- **ContactCleanerService**: Bulk-delete logic for unpinned contacts with statistics
- **RoomServerPanel**: Per-room-server card management with login/logout, message display and send functionality
- **RoomPasswordStore**: Persistent Room Server password storage per device in `~/.meshcore-gui/room_passwords/` (JSON-backed, analogous to PinStore)
- **SharedData**: Thread-safe data sharing between BLE and GUI via Protocol interfaces
- **DashboardPage**: Main GUI with modular panels (device, contacts, map, messages, etc.)
- **RoutePage**: Standalone route visualization page opened per message
- **ArchivePage**: Archive viewer with filters, pagination and inline route tables
- **Communication**: Via command queue (GUI→BLE) and shared state with flags (BLE→GUI)

## 11. Known Limitations

1. **Channel discovery timing** — Dynamic channel discovery probes the device at startup; on very slow BLE connections, some channels may be missed on first attempt. Channels are retried in the background and cached for subsequent startups when `CHANNEL_CACHE_ENABLED = True`
2. **BLE command reliability** — Resolved. The meshcore SDK previously had a race condition where device responses were missed. This was fixed via the subscribe-before-send pattern ([PR #52](https://github.com/meshcore-dev/meshcore_py/pull/52)) and is included in the current release of `meshcore`. No special installation required.
3. **Initial load time** — GUI waits for BLE data before the first render is complete (mitigated by cache: if cached data exists, the GUI populates instantly)
4. **Archive route map visualization** — Route table names and IDs are now stored at receive time and display correctly regardless of current contacts. However, the route *map* still depends on GPS coordinates from contacts currently in memory; archived messages without recent contact data may show incomplete map markers
<!-- CHANGED: Partially resolved in v1.7.1 — route table self-contained, map still depends on live GPS -->
5. **Room Server message latency** — Room Server messages travel over LoRa RF and arrive asynchronously (10–75 seconds per message). With many logged-in clients, receiving all historical messages can take 10+ minutes due to the round-robin push protocol

## 12. Troubleshooting

### 12.1. Linux

For comprehensive Linux BLE troubleshooting (including the `EOFError` / `start_notify` issue), see [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

#### 12.1.1. Quick Fixes

##### GUI remains empty / BLE connection fails

1. Check the service logs:
   ```bash
   journalctl -u meshcore-gui -n 50 --no-pager
   ```
2. The built-in PIN agent should handle pairing automatically. If you see D-Bus permission errors, ensure the policy file is installed:
   ```bash
   ls /etc/dbus-1/system.d/meshcore-ble.conf
   ```
   If missing, run `install_ble_stable.sh` or create it manually (see step 5 under Installation).
3. If bond state is corrupted, manually remove and restart:
   ```bash
   bluetoothctl remove AA:BB:CC:DD:EE:FF
   sudo systemctl restart meshcore-gui
   ```
4. Kill any existing GUI instance and free the port:
   ```bash
   pkill -9 -f meshcore_gui
   sleep 3
   ```
5. Restart the GUI:
   ```bash
   python meshcore_gui.py AA:BB:CC:DD:EE:FF
   ```

##### Bluetooth permissions

```bash
sudo usermod -a -G bluetooth $USER
# Log out and back in
```

### 12.2. macOS

- Make sure Bluetooth is enabled in System Settings
- Grant your terminal app Bluetooth access when prompted
- Use the UUID address from BleakScanner, not a MAC address

### 12.3. Windows

- Make sure Bluetooth is enabled in Settings → Bluetooth & devices
- Run the terminal as a regular user (not as Administrator — WinRT BLE can behave unexpectedly with elevated privileges)

### 12.4. All Platforms

#### 12.4.1. Device Not Found

Make sure the MeshCore device is powered on and in BLE Companion mode. Run the BleakScanner script from the Usage section to verify it is visible.

#### 12.4.2. Messages Not Arriving

- Check if your channels are correctly configured
- Use `meshcli` to verify that messages are arriving

#### 12.4.3. Clearing the Cache

If cached data causes issues (e.g. stale contacts), delete the cache file:

```bash
rm ~/.meshcore-gui/cache/*.json
```

The cache will be recreated on the next successful BLE connection.

## 13. Development

### 13.1. Debug Mode

Enable via command line flag:

```bash
python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on
```

Or set `DEBUG = True` in `meshcore_gui/config.py`.

Debug output is written to both stdout and a per-device rotating log file at `~/.meshcore-gui/logs/<ADDRESS>_meshcore_gui.log` (e.g. `F0_9E_9E_75_A3_01_meshcore_gui.log`).

### 13.2. Project Structure

<!-- CHANGED: Project structure updated — added archive_page.py and message_archive.py -->

```
meshcore-gui/
├── meshcore_gui.py                  # Entry point
├── install_ble_stable.sh            # Automated installer (systemd, D-Bus policy, path detection)
├── meshcore_gui/                    # Application package
│   ├── __init__.py
│   ├── __main__.py                  # Alternative entry: python -m meshcore_gui
│   ├── config.py                    # OPERATOR_CALLSIGN, LANDING_SVG_PATH, DEBUG flag, channel discovery settings (MAX_CHANNELS, CHANNEL_CACHE_ENABLED), BLE_PIN, RECONNECT_* settings, refresh interval, retention settings, BOT_DEVICE_NAME, per-device log file naming
│   ├── ble/                         # BLE communication layer
│   │   ├── __init__.py
│   │   ├── worker.py                # BLE thread, connection lifecycle, cache-first startup, disconnect detection, auto-reconnect, background key retry
│   │   ├── ble_agent.py             # Built-in BlueZ D-Bus PIN agent (replaces bt-agent.service)
│   │   ├── ble_reconnect.py         # Bond cleanup via D-Bus + reconnect loop with linear backoff
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
│   │       ├── room_server_panel.py # Per-room-server card with login/logout and messages
│   │       └── rxlog_panel.py       # RX log table
│   └── services/                    # Business logic
│       ├── __init__.py
│       ├── bot.py                   # Keyword-triggered auto-reply bot
│       ├── cache.py                 # Local JSON cache per BLE device
│       ├── contact_cleaner.py       # Bulk-delete logic for unpinned contacts
│       ├── dedup.py                 # Message deduplication
│       ├── message_archive.py       # Persistent message and RX log archive
│       ├── pin_store.py             # Persistent pin state storage per device
│       ├── room_password_store.py   # Persistent Room Server password storage per device
│       └── route_builder.py         # Route data construction
├── docs/
│   ├── TROUBLESHOOTING.md           # BLE troubleshooting guide (Linux)
│   ├── MeshCore_GUI_Design.docx     # Design document
│   ├── ble_capture_workflow_t_1000_e_explanation.md
│   └── ble_capture_workflow_t_1000_e_uitleg.md
├── .gitattributes
├── .gitignore
├── LICENSE
├── CHANGELOG.md
└── README.md
```

## 14. Roadmap

This project is under active development. The most common features from the official MeshCore Companion apps are being implemented gradually. Planned additions include:

- [ ] **Observer mode** — passively monitor mesh traffic without transmitting, useful for network analysis, coverage mapping and long-term logging
- [ ] **Room Server administration** — authenticate as admin to manage Room Server settings and users directly from the GUI
- [ ] **Repeater management** — connect to repeater nodes to view status and adjust configuration

Have a feature request or want to contribute? Open an issue or submit a pull request.

## 15. Disclaimer

This is an **independent community project** and is not affiliated with or endorsed by the official [MeshCore](https://github.com/meshcore-dev) development team. It is built on top of the open-source `meshcore` Python library and `bleak` BLE library.

## 16. License

MIT License - see LICENSE file

## 17. Author

**PE1HVH** — [GitHub](https://github.com/pe1hvh)

## 18. Acknowledgments

- [MeshCore](https://github.com/meshcore-dev) — Mesh networking firmware and protocol
- [meshcore_py](https://github.com/meshcore-dev/meshcore_py) — Python bindings for MeshCore
- [meshcore-cli](https://github.com/meshcore-dev/meshcore-cli) — Command line interface
- [meshcoredecoder](https://github.com/meshcore-dev/meshcoredecoder) — LoRa packet decoder and channel crypto
- [NiceGUI](https://nicegui.io/) — Python GUI framework
- [Bleak](https://github.com/hbldh/bleak) — Cross-platform Bluetooth Low Energy library
