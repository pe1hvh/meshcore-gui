# Running Multiple MeshCore GUI Instances

> ⚠️ **WARNING: This guide has not been tested yet.** The configuration below is based on the application's architecture and should work, but has not been validated in practice. Please report any issues.

## Overview

MeshCore GUI supports running multiple instances simultaneously — for example, to monitor two different MeshCore devices from the same machine. Each instance gets its own web port, serial connection, and all persistent data (cache, archive, logs, pins, room passwords) is automatically separated by device identifier (serial port).

## Prerequisites

- MeshCore GUI v1.9.2 or later (with `--port` and serial CLI parameters)

## Quick Test (foreground)

Before creating services, verify that both instances start correctly:

**Terminal 1:**
```bash
cd ~/meshcore-gui
source venv/bin/activate
python meshcore_gui.py /dev/ttyUSB0 --debug-on --port=8081 --baud=115200
```

**Terminal 2:**
```bash
cd ~/meshcore-gui
source venv/bin/activate
python meshcore_gui.py /dev/ttyUSB1 --debug-on --port=8082 --baud=115200
```

Verify both are accessible at `http://localhost:8081` and `http://localhost:8082`.

## systemd Service Setup

### Service 1

```bash
sudo nano /etc/systemd/system/meshcore-gui-device1.service
```

```ini
[Unit]
Description=MeshCore GUI — Device 1 (/dev/ttyUSB0)

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

### Service 2

```bash
sudo nano /etc/systemd/system/meshcore-gui-device2.service
```

```ini
[Unit]
Description=MeshCore GUI — Device 2 (/dev/ttyUSB1)

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/meshcore-gui
ExecStart=/home/your-username/meshcore-gui/venv/bin/python meshcore_gui.py /dev/ttyUSB1 --debug-on --port=8082 --baud=115200
Restart=on-failure
RestartSec=30
[Install]
WantedBy=multi-user.target
```

Replace `your-username` and serial ports with your actual values.

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable meshcore-gui-device1 meshcore-gui-device2
sudo systemctl start meshcore-gui-device1
sudo systemctl start meshcore-gui-device2
```

## Data Separation

All persistent data is automatically separated by device identifier. No additional configuration is needed.

| Data | Path example (device `/dev/ttyUSB0`) |
|------|------------------------------------------|
| Web interface | `http://host:8081` (via `--port`) |
| Cache | `~/.meshcore-gui/cache/_dev_ttyUSB0.json` |
| Message archive | `~/.meshcore-gui/archive/_dev_ttyUSB0_messages.json` |
| RX log archive | `~/.meshcore-gui/archive/_dev_ttyUSB0_rxlog.json` |
| Debug log | `~/.meshcore-gui/logs/_dev_ttyUSB0_meshcore_gui.log` |
| Pin state | `~/.meshcore-gui/pins/_dev_ttyUSB0_pins.json` |
| Room passwords | `~/.meshcore-gui/room_passwords/_dev_ttyUSB0_rooms.json` |

## Useful Commands

| Command | Description |
|---------|-------------|
| `sudo systemctl status meshcore-gui-device1` | Check status of device 1 |
| `sudo systemctl status meshcore-gui-device2` | Check status of device 2 |
| `sudo journalctl -u meshcore-gui-device1 -f` | Follow live log of device 1 |
| `sudo journalctl -u meshcore-gui-device2 -f` | Follow live log of device 2 |
| `sudo systemctl restart meshcore-gui-device1` | Restart device 1 (without affecting device 2) |
| `sudo systemctl stop meshcore-gui-device1` | Stop device 1 only |
| `sudo systemctl disable meshcore-gui-device1` | Prevent device 1 from starting on boot |

## Removing a Service

```bash
sudo systemctl stop meshcore-gui-device2
sudo systemctl disable meshcore-gui-device2
sudo rm /etc/systemd/system/meshcore-gui-device2.service
sudo systemctl daemon-reload
```

Optionally remove the device's persistent data:

```bash
rm ~/.meshcore-gui/cache/_dev_ttyUSB1.json
rm ~/.meshcore-gui/archive/_dev_ttyUSB1_*.json
rm ~/.meshcore-gui/logs/_dev_ttyUSB1_meshcore_gui.log
rm ~/.meshcore-gui/pins/_dev_ttyUSB1_pins.json
rm ~/.meshcore-gui/room_passwords/_dev_ttyUSB1_rooms.json
```
