# MeshCore GUI — Agent Notes

## Purpose
MeshCore GUI is a NiceGUI-based desktop/headless web UI for MeshCore radios. It supports **two transport modes**:
- **USB Serial** via `MeshCore.create_serial()` — for wired connections
- **Bluetooth LE** via `MeshCore.create_ble()` — for wireless T1000e devices

The transport is **auto-detected** from the device argument.

## Entry Points
- `meshcore_gui.py` (primary)
- `python -m meshcore_gui` (`meshcore_gui/__main__.py`)

### Common Run
```bash
# Serial
./.venv/bin/python meshcore_gui.py /dev/ttyACM0 --debug-on --baud=115200

# BLE
./venv/bin/python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on --ble-pin 123456
```

## Architecture (High-Level)
- **UI thread (NiceGUI)**: `meshcore_gui/gui/*`
- **Worker thread (transport + asyncio)**: `meshcore_gui/ble/worker.py`
  - `_BaseWorker` — shared main loop, caching, data loading
  - `SerialWorker` — USB serial transport
  - `BLEWorker` — Bluetooth LE transport (PIN agent, bond management)
  - `create_worker()` — factory function for auto-detection
- **Commands**: `meshcore_gui/ble/commands.py`
- **Events**: `meshcore_gui/ble/events.py`
- **Shared state**: `meshcore_gui/core/shared_data.py`
- **BLE PIN agent**: `meshcore_gui/ble/ble_agent.py` (D-Bus, Linux only)
- **BLE reconnect**: `meshcore_gui/ble/ble_reconnect.py` (bond cleanup)

## Transport Detection
`config.is_ble_address(device_id)` returns True when:
- Device ID starts with `literal:` prefix
- Device ID matches `XX:XX:XX:XX:XX:XX` MAC address pattern

Everything else is treated as a serial port path.

## Config (`meshcore_gui/config.py`)
- `TRANSPORT`: `"serial"` or `"ble"` (set at startup)
- Serial: `SERIAL_BAUDRATE`, `SERIAL_CX_DELAY`, `DEFAULT_TIMEOUT`
- BLE: `BLE_PIN`, `DEFAULT_TIMEOUT`
- Shared: `MESHCORE_LIB_DEBUG`, `RECONNECT_*`, `CONTACT_REFRESH_SECONDS`

## Dependencies
- **Serial mode**: `meshcore`, `nicegui`, `meshcoredecoder`
- **BLE mode**: additionally `bleak`, `dbus_fast` (Linux only)
- BLE dependencies are **lazily imported** — serial-only installs don't need them.

## Device Name Behavior
- BOT toggle changes device name via `set_device_name` command.
- Warning labels are shown next to BOT toggles.
- Explicit device name can be set via the **Actions** panel input.

## Map Centering
- Map is in `meshcore_gui/gui/panels/map_panel.py`.
- Centering happens on device updates or when the MAP panel is opened.
- There is a **Center on Device** button that uses the last known GPS.
- Leaflet size invalidation is called before centering to handle hidden panels.
- Map theme follows UI dark/light mode by default.
- Map theme can be overridden with the **Theme** toggle (Auto/Dark/Light).

## Panel URLs
- Drawer and sidebar actions navigate to `/?panel=<id>&channel=<optional>` so browser back restores the last panel.
- On load, the dashboard reads the query params and shows the requested panel.

## Route Viewer
- Clicking a message opens `/route/{msg_key}` in the **same tab**.
- The route page has **Back to Dashboard** and **Back to Archive** buttons.

## Refresh Behavior
- GUI refresh queues a full device reload.
- Contacts fetch is bounded by a timeout to prevent hangs.

## Persistent Data
Stored under `~/.meshcore-gui/`:
- `cache/`, `archive/`, `logs/`, `pins/`, `room_passwords/`

## Tests
- Tests live in `tests/`.
- `pytest` is not installed by default; use `pip install pytest` in the venv.

## Installer Scripts
- `install_serial.sh` — systemd service for serial connections
- `install_ble_stable.sh` — systemd service for BLE connections
