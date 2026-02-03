# MeshCore GUI

A graphical user interface for MeshCore mesh network devices via Bluetooth Low Energy (BLE) for on your desktop.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-orange.svg)

## Why This Project Exists

MeshCore devices like the SenseCAP T1000-E can be managed through two interfaces: USB serial and BLE (Bluetooth Low Energy). The official companion apps communicate with devices over BLE, but they are mobile-only. If you want to manage your MeshCore device from a desktop or laptop, the usual approach is to **flash USB-serial firmware** via the web flasher. However, this replaces the BLE Companion firmware, which means you can no longer use the device with mobile companion apps (Android/iOS).

This project provides a **native desktop GUI** that connects to your MeshCore device over BLE — no firmware changes required. Your device stays on BLE Companion firmware and remains fully compatible with the mobile apps. The application is written in Python using cross-platform libraries and runs on **Linux, macOS and Windows**.

> **Note:** This application has only been tested on Linux (Ubuntu 24.04). macOS and Windows should work since all dependencies (`bleak`, `nicegui`, `meshcore`) are cross-platform, but this has not been verified. Feedback and contributions for other platforms are welcome.

Under the hood it uses `bleak` for Bluetooth Low Energy (which talks to BlueZ on Linux, CoreBluetooth on macOS, and WinRT on Windows), `meshcore` as the protocol layer, and `NiceGUI` for the web-based interface.

> **Linux users:** BLE on Linux can be temperamental. BlueZ occasionally gets into a bad state, especially after repeated connect/disconnect cycles. If you run into connection issues, see the [Troubleshooting Guide](docs/TROUBLESHOOTING.md). On macOS and Windows, BLE is generally more stable out of the box.

## TODO

* **Message route visualization** — Display message paths on the map showing the route (hops) each message has taken through the mesh network
* **Message persistence** — Store sent and received messages to disk so chat history is preserved across sessions
* **Automatic channel discovery** — Robustly detect and subscribe to available channels without manual configuration
* **Auto-detect BLE address** — Automatically discover and store the BLE device address in config, eliminating manual entry
## Features

- **Real-time Dashboard** - Device info, contacts, messages and RX log
- **Interactive Map** - Leaflet map with markers for own position and contacts
- **Channel Messages** - Send and receive messages on channels
- **Direct Messages** - Click on a contact to send a DM
- **Message Filtering** - Filter messages per channel via checkboxes
- **Threaded Architecture** - BLE communication in separate thread for stable UI

## Screenshot
<img width="1002" height="532" alt="Screenshot from 2026-02-03 10-23-25" src="https://github.com/user-attachments/assets/d064e25e-a3c9-495b-a7f9-c09b636d28cb" />

## Requirements

- Python 3.10+
- Bluetooth Low Energy compatible adapter (built-in or USB)
- MeshCore device with BLE Companion firmware

### Platform support

| Platform | BLE Backend | Status |
|---|---|---|
| Linux (Ubuntu/Debian) | BlueZ/D-Bus | ✅ Tested |
| macOS | CoreBluetooth | ⬜ Untested |
| Windows 10/11 | WinRT | ⬜ Untested |

## Installation

### 1. System dependencies

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3-pip python3-venv bluetooth bluez
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

### 2. Clone the repository

```bash
git clone https://github.com/pe1hvh/meshcore-gui.git
cd meshcore-gui
```

### 3. Create virtual environment

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

### 4. Install Python packages

```bash
pip install nicegui meshcore bleak
```

## Usage

### 1. Activate the virtual environment

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

### 2. Find your BLE device address

**Linux:**
```bash
bluetoothctl scan on
```
Look for your MeshCore device and note the MAC address (e.g., `literal:AA:BB:CC:DD:EE:FF`).

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

### 3. Configure channels

Open `meshcore_gui.py` and adjust `CHANNELS_CONFIG` to your own channels:

```python
CHANNELS_CONFIG = [
    {'idx': 0, 'name': 'Public'},
    {'idx': 1, 'name': '#test'},
    {'idx': 2, 'name': 'MyChannel'},
    {'idx': 3, 'name': '#local'},
]
```

**Tip:** Use `meshcli` to determine your channels:

```bash
meshcli -d literal:AA:BB:CC:DD:EE:FF
> get_channel 0
> get_channel 1
# etc.
```

### 4. Start the GUI

```bash
python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
```

Replace `literal:AA:BB:CC:DD:EE:FF` with the MAC address of your device.

### 5. Open the interface

The GUI opens automatically in your browser at `http://localhost:8080`

## Configuration

| Setting | Description |
|---------|-------------|
| `DEBUG` | Set to `True` for verbose logging |
| `CHANNELS_CONFIG` | List of channels (hardcoded due to BLE timing issues) |
| BLE Address | Command line argument |

## Functionality

### Device Info
- Name, frequency, SF/BW, TX power, location, firmware version

### Contacts
- List of known nodes with type and location
- Click on a contact to send a DM

### Map
- OpenStreetMap with markers for own position and contacts
- Shows your own position (blue marker)
- Automatically centers on your own position

### Channel Messages
- Select a channel in the dropdown
- Type your message and click "Send"
- Received messages appear in the messages list
- Filter messages via the checkboxes

### Direct Messages (DM)
- Click on a contact in the contacts list
- A dialog opens where you can type your message
- Click "Send" to send the DM

### RX Log
- Received packets with SNR and type

### Actions
- Refresh data
- Send advertisement

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Main Thread   │     │   BLE Thread    │
│   (NiceGUI)     │     │   (asyncio)     │
│                 │     │                 │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │    GUI    │◄─┼──┬──┼─►│ BLEWorker │  │
│  └───────────┘  │  │  │  └───────────┘  │
│        │        │  │  │        │        │
│        ▼        │  │  │        ▼        │
│  ┌───────────┐  │  │  │  ┌───────────┐  │
│  │  Timer    │  │  │  │  │  MeshCore │  │
│  │  (500ms)  │  │  │  │  │    BLE    │  │
│  └───────────┘  │  │  │  └───────────┘  │
└─────────────────┘  │  └─────────────────┘
                     │
              ┌──────┴──────┐
              │ SharedData  │
              │ (thread-    │
              │  safe)      │
              └─────────────┘
```

- **BLEWorker**: Runs in separate thread with its own asyncio loop
- **SharedData**: Thread-safe data sharing between BLE and GUI
- **MeshCoreGUI**: NiceGUI interface in main thread
- **Communication**: Via queue (GUI→BLE) and shared state with flags (BLE→GUI)

## Known Limitations

1. **Channels hardcoded** - The `get_channel()` function in meshcore-py is unreliable via BLE
2. **send_appstart() sometimes fails** - Device info may remain empty with connection problems
3. **Initial load time** - GUI waits for BLE data before the first render is complete

## Troubleshooting

### Linux

For comprehensive Linux BLE troubleshooting (including the `EOFError` / `start_notify` issue), see [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

#### Quick fixes

##### GUI remains empty / BLE connection fails

1. First disconnect any existing BLE connections:
   ```bash
   bluetoothctl disconnect literal:AA:BB:CC:DD:EE:FF
   ```
2. Wait 2 seconds:
   ```bash
   sleep 2
   ```
3. Restart the GUI:
   ```bash
   python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
   ```

##### Bluetooth permissions

```bash
sudo usermod -a -G bluetooth $USER
# Log out and back in
```

### macOS

- Make sure Bluetooth is enabled in System Settings
- Grant your terminal app Bluetooth access when prompted
- Use the UUID address from BleakScanner, not a MAC address

### Windows

- Make sure Bluetooth is enabled in Settings → Bluetooth & devices
- Run the terminal as a regular user (not as Administrator — WinRT BLE can behave unexpectedly with elevated privileges)

### All platforms

#### Device not found

Make sure the MeshCore device is powered on and in BLE Companion mode. Run the BleakScanner script from the Usage section to verify it is visible.

#### Messages not arriving

- Check if your channels are correctly configured
- Use `meshcli` to verify that messages are arriving

## Development

### Debug mode

Set `DEBUG = True` in the script for verbose logging:

```python
DEBUG = True
```

### Project structure

```
meshcore-gui/
├── meshcore_gui.py           # Main application
├── README.md                 # This file
└── docs/
    ├── TROUBLESHOOTING.md    # BLE troubleshooting guide (Linux)
    └── MeshCore_GUI_Design.docx  # Design document
```

## Disclaimer

This is an **independent community project** and is not affiliated with or endorsed by the official [MeshCore](https://github.com/meshcore-dev) development team. It is built on top of the open-source `meshcore` Python library and `bleak` BLE library.

## License

MIT License - see LICENSE file

## Author

**PE1HVH** - [GitHub](https://github.com/pe1hvh)

## Acknowledgments

- [MeshCore](https://github.com/meshcore-dev) - Mesh networking firmware and protocol
- [meshcore_py](https://github.com/meshcore-dev/meshcore_py) - Python bindings for MeshCore
- [meshcore-cli](https://github.com/meshcore-dev/meshcore-cli) - Command line interface
- [NiceGUI](https://nicegui.io/) - Python GUI framework
- [Bleak](https://github.com/hbldh/bleak) - Cross-platform Bluetooth Low Energy library
