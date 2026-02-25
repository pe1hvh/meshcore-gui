# MeshCore GUI - Legacy BLE Troubleshooting Guide

> **Note:** This guide applies to BLE connections only and is kept for historical reference. The current GUI uses USB serial; for serial issues, verify the correct port (e.g. `/dev/ttyUSB0`) and user permissions (e.g. `dialout` on Linux).

## Problem 1: EOFError during start_notify

BLE connection to MeshCore device fails with `EOFError` during `start_notify` on the UART TX characteristic. The error originates in `dbus_fast` (the D-Bus library used by `bleak`) and looks like this:

```
File "src/dbus_fast/_private/unmarshaller.py", line 395, in dbus_fast._private.unmarshaller.Unmarshaller._read_sock_with_fds
EOFError
```

Basic BLE connect works fine, but subscribing to notifications (`start_notify`) crashes.

## Problem 2: PIN or Key Missing / Authentication Failure

BLE connection fails immediately after connecting with `failed to discover services, device disconnected` or `le-connection-abort-by-local`. In `btmon`, the trace shows:

```
Encryption Change - Status: PIN or Key Missing (0x06)
Disconnect - Reason: Authentication Failure (0x05)
```

This happens when the MeshCore device requires BLE PIN pairing (e.g., PIN `123456`) but no BlueZ agent is running to handle the passkey exchange. Bleak cannot provide a PIN by itself — it relies on a BlueZ agent to handle pairing.

**Symptoms:**
- `bluetoothctl connect` fails with `le-connection-abort-by-local`
- `bluetoothctl pair` asks for a passkey and succeeds
- meshcore-gui still fails because bleak creates its own connection without an agent
- btmon shows repeated connect → encrypt → `PIN or Key Missing` → disconnect cycles

## Problem 3: Port already in use

meshcore-gui fails to start with:

```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8081): address already in use
```

This means a previous meshcore-gui instance is still running (or the port hasn't been released yet).

---

## Diagnostic Steps

### 1. Check adapter status

```bash
hciconfig -a
```

Expected: `UP RUNNING`. If it shows `DOWN`, reset with:

```bash
sudo hciconfig hci0 down
sudo hciconfig hci0 up
```

### 2. Check if adapter is detected

```bash
lsusb | grep -i blue
```

### 3. Check power supply (Raspberry Pi)

```bash
vcgencmd get_throttled
```

Expected: `throttled=0x0`. Any other value indicates power issues that can cause BLE instability.

### 4. Test basic BLE connection (without notify)

```bash
python -c "
import asyncio
from bleak import BleakClient
async def test():
    async with BleakClient('AA:BB:CC:DD:EE:FF') as c:
        print('Connected:', c.is_connected)
asyncio.run(test())
"
```

If this works but meshcli/meshcore_gui fails, the problem is specifically `start_notify`.

### 5. Test start_notify in isolation

```bash
python -c "
import asyncio
from bleak import BleakClient
UART_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
async def test():
    async with BleakClient('AA:BB:CC:DD:EE:FF') as c:
        def cb(s, d): print(f'RX: {d.hex()}')
        await c.start_notify(UART_TX, cb)
        print('Notify OK!')
        await asyncio.sleep(2)
asyncio.run(test())
"
```

If this also fails with `EOFError`, the issue is confirmed at the BlueZ/D-Bus level.

### 6. Test notifications via bluetoothctl (outside Python)

```bash
bluetoothctl
scan on
# Wait for device to appear
connect AA:BB:CC:DD:EE:FF
# Wait for "Connection successful"
menu gatt
select-attribute 6e400003-b5a3-f393-e0a9-e50e24dcca9e
notify on
```

If `connect` fails with `le-connection-abort-by-local`, the problem is at the BlueZ or device level. No Python fix will help.

### 7. Check if pairing is required (PIN or Key Missing)

If `bluetoothctl connect` fails with `le-connection-abort-by-local`, try pairing instead:

```bash
bluetoothctl
scan on
pair AA:BB:CC:DD:EE:FF
# If it asks for a passkey, the device requires PIN pairing
```

If pairing succeeds but meshcore-gui still fails, the issue is a missing BlueZ agent (see Solution 2).

### 8. Use btmon for HCI-level debugging

```bash
sudo btmon
```

In another terminal, start meshcore-gui. Look for:
- `Encryption Change - Status: PIN or Key Missing (0x06)` → pairing/agent issue (Solution 2)
- Successful encryption but no service discovery → stale bond (Solution 1)

### 9. Check what is using port 8081

```bash
lsof -i :8081
```

If another process holds the port, see Solution 3.

---

## Solution 1: Stale BLE Pairing State (EOFError)

The root cause is a stale BLE pairing state between the Linux adapter and the MeshCore device. The fix requires a clean reconnect sequence:

### Step 1 - Remove the device from BlueZ

```bash
bluetoothctl
remove AA:BB:CC:DD:EE:FF
exit
```

### Step 2 - Hard power cycle the MeshCore device

Physically power off the T1000-e (not just a software reset). Wait 10 seconds, then power it back on.

### Step 3 - Scan and reconnect from scratch

```bash
bluetoothctl
scan on
```

Wait until the device appears: `[NEW] Device AA:BB:CC:DD:EE:FF MeshCore-...`

Then immediately connect:

```
connect AA:BB:CC:DD:EE:FF
```

### Step 4 - Verify notifications work

```
menu gatt
select-attribute 6e400003-b5a3-f393-e0a9-e50e24dcca9e
notify on
```

If this succeeds, disconnect cleanly:

```
notify off
back
disconnect AA:BB:CC:DD:EE:FF
exit
```

### Step 5 - Verify channels with meshcli

```bash
meshcli -d AA:BB:CC:DD:EE:FF
> get_channels
```

Confirm output matches `CHANNELS_CONFIG` in `meshcore_gui.py`, then:

```
> exit
```

### Step 6 - Start the GUI

```bash
cd ~/meshcore-gui
source venv/bin/activate
python meshcore_gui.py AA:BB:CC:DD:EE:FF
```

---

## Solution 2: Missing BlueZ Agent for PIN Pairing

When the MeshCore device requires BLE PIN pairing, bleak cannot provide the PIN by itself. BlueZ needs a running agent that responds to pairing requests with the correct passkey.

**Why this happens:** `bluetoothctl` acts as its own agent (which is why manual pairing works), but when bleak connects independently, there is no agent to handle the passkey exchange. Even if the device was previously paired via `bluetoothctl`, the bond can become invalid when:
- The MeshCore device is reset or firmware-updated
- Another device (e.g., companion app) pairs with the MeshCore device and overwrites its bond slot
- The bond keys get out of sync for any reason

### Step 1 - Install bluez-tools

```bash
sudo apt install bluez-tools
```

### Step 2 - Create a PIN file

```bash
echo "* 123456" > ~/.meshcore-ble-pin
chmod 600 ~/.meshcore-ble-pin
```

The format is `<address-or-wildcard> <pin>`. Use `*` to match any device, or specify a specific address:

```
FF:05:D6:71:83:8D 123456
```

### Step 3 - Remove any existing (corrupt) bond

```bash
bluetoothctl remove AA:BB:CC:DD:EE:FF
```

### Step 4 - Start the agent and meshcore-gui

```bash
bt-agent -c KeyboardOnly -p ~/.meshcore-ble-pin &
python meshcore_gui.py AA:BB:CC:DD:EE:FF
```

### Step 5 - Make the agent permanent (systemd service)

Create the service file:

```bash
sudo tee /etc/systemd/system/bt-agent.service << 'EOF'
[Unit]
Description=Bluetooth PIN Agent for MeshCore
After=bluetooth.service
Requires=bluetooth.service

[Service]
ExecStart=/usr/bin/bt-agent -c KeyboardOnly -p /home/hans/.meshcore-ble-pin
Restart=always
User=hans

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl enable bt-agent
sudo systemctl start bt-agent
```

Verify it is running:

```bash
sudo systemctl status bt-agent
```

Now meshcore-gui can connect at any time without manual pairing. The agent survives reboots.

**Important:** Only run ONE bt-agent instance. Multiple agents conflict with each other. If you have both a manual `bt-agent &` process and the systemd service running, kill the manual one:

```bash
pkill -f bt-agent
sudo systemctl start bt-agent
```

---

## Solution 3: Port 8081 Already in Use

This happens when a previous meshcore-gui instance is still running or hasn't fully released the port.

### Quick fix - Kill previous instance and free the port

```bash
pkill -9 -f meshcore_gui
sleep 3
```

Verify the port is free:

```bash
lsof -i :8081
```

If nothing shows up, the port is free. Start meshcore-gui:

```bash
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
```

### If the port is still in use after killing

Sometimes TCP sockets linger in `TIME_WAIT` state. Wait 30 seconds or force it:

```bash
sleep 30
lsof -i :8081
```

### Running in background with nohup

To run meshcore-gui in the background (survives terminal close):

```bash
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &
```

Check if it started successfully:

```bash
sleep 5
tail -30 ~/meshcore.log
```

**Tip:** Always redirect output to a log file (not `/dev/null`) so you can diagnose problems:

```bash
# Good - keeps logs for debugging
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > ~/meshcore.log 2>&1 &

# Bad - hides all errors
nohup python meshcore_gui.py AA:BB:CC:DD:EE:FF --debug-on > /dev/null 2>&1 &
```

---

## Things That Did NOT Help

| Action | Result |
|---|---|
| `sudo systemctl restart bluetooth` | No effect |
| `sudo hciconfig hci0 down/up` | No effect |
| `sudo rmmod btusb && sudo modprobe btusb` | No effect |
| `sudo usbreset "8087:0026"` | No effect |
| `sudo reboot` | No effect |
| Clearing BlueZ cache (`/var/lib/bluetooth/*/cache`) | No effect |
| Recreating Python venv | No effect |
| Downgrading `dbus_fast` / `bleak` | No effect |
| Downgrading `linux-firmware` | No effect |
| Adding `pin="123456"` to `MeshCore.create_ble()` | Pairing fails — bleak's `pair()` cannot provide a passkey without a BlueZ agent |
| Pre-connecting via `bluetoothctl connect` before meshcore-gui | Bleak creates its own connection and doesn't reuse the existing one |

---

## Key Takeaways

### EOFError / stale bond
When `start_notify` fails with `EOFError` but basic BLE connect works, the issue is almost always a stale BLE state between the host adapter and the peripheral device. The fix is:

1. **Remove** the device from bluetoothctl
2. **Hard power cycle** the peripheral device
3. **Re-scan** and reconnect from scratch

### PIN or Key Missing / Authentication Failure
When btmon shows `PIN or Key Missing (0x06)` and connections drop immediately after encryption negotiation, the fix is:

1. **Remove** the corrupt bond from bluetoothctl
2. **Run `bt-agent`** with the correct PIN file so BlueZ can handle pairing requests
3. **Install as systemd service** for persistence across reboots

### Port already in use
When meshcore-gui fails with `[Errno 98] address already in use`:

1. **Kill** any existing meshcore-gui process: `pkill -9 -f meshcore_gui`
2. **Wait** a few seconds for the port to be released
3. **Verify** the port is free: `lsof -i :8081`

---

## Recommended Startup Sequence

For the most reliable BLE connection, always follow this order:

1. Ensure `bt-agent` is running (if device requires PIN pairing): `sudo systemctl status bt-agent`
2. Ensure no other meshcore-gui instance is running: `pkill -f meshcore_gui` and `lsof -i :8081`
3. Ensure no other application holds the BLE connection (BT manager, bluetoothctl, meshcli, companion app)
4. Verify the device is visible: `bluetoothctl scan on`
5. Check channels: `meshcli -d <BLE_ADDRESS>` → `get_channels` → `exit`
6. Start the GUI: `python meshcore_gui.py <BLE_ADDRESS>`
