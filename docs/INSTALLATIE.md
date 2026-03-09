# MeshCore GUI — BLE Stabiliteit: Installatie-instructies (Legacy)

> **Let op:** Dit document is BLE-specifiek en wordt bewaard als referentie. De huidige GUI gebruikt USB-serieel; gebruik het handmatige systeemd-voorbeeld in de README.

## Wat is gewijzigd

### Nieuwe bestanden
| Bestand | Doel |
|---------|------|
| `meshcore_gui/ble/ble_agent.py` | Ingebouwde BlueZ D-Bus PIN agent (vervangt `bt-agent.service`) |
| `meshcore_gui/ble/ble_reconnect.py` | Bond-opruiming + automatische reconnect logica |
| `install_ble_stable.sh` | Generiek installatiescript (detecteert paden/user automatisch) |

### Gewijzigde bestanden
| Bestand | Wijziging |
|---------|-----------|
| `meshcore_gui/ble/worker.py` | Agent startup, disconnect detectie, auto-reconnect loop |
| `meshcore_gui/config.py` | Nieuwe constanten: `BLE_PIN`, `RECONNECT_MAX_RETRIES`, `RECONNECT_BASE_DELAY` |

---

## Snelle installatie (aanbevolen)

```bash
# 1. Verwijder eerst een eventuele kapotte service
sudo systemctl stop meshcore-gui 2>/dev/null
sudo systemctl disable meshcore-gui 2>/dev/null
sudo rm -f /etc/systemd/system/meshcore-gui.service
sudo systemctl daemon-reload
sudo systemctl reset-failed 2>/dev/null

# 2. Kopieer de nieuwe/gewijzigde bestanden naar je project
cp ble_agent.py     ~/meshcore-gui/meshcore_gui/ble/
cp ble_reconnect.py ~/meshcore-gui/meshcore_gui/ble/
cp worker.py        ~/meshcore-gui/meshcore_gui/ble/
cp config.py        ~/meshcore-gui/meshcore_gui/

# 3. Ga naar je project directory en voer het installatiescript uit
cd ~/meshcore-gui
BLE_ADDRESS=FF:05:D6:71:83:8D bash install_ble_stable.sh
```

Het script detecteert automatisch:
- De juiste project directory (waar je het uitvoert)
- De huidige user
- Het pad naar de venv Python
- Het correcte entry point

---

## Handmatige installatie

Als je het script niet wilt gebruiken:

### 1. Kopieer Python bestanden
```bash
# Pas het pad aan naar jouw project directory
PROJECT=~/meshcore-gui

cp ble_agent.py     $PROJECT/meshcore_gui/ble/
cp ble_reconnect.py $PROJECT/meshcore_gui/ble/
cp worker.py        $PROJECT/meshcore_gui/ble/
cp config.py        $PROJECT/meshcore_gui/
```

### 2. Upgrade meshcore library
```bash
cd $PROJECT
source venv/bin/activate
pip install --upgrade meshcore
```

### 3. D-Bus policy installeren
Maak `/etc/dbus-1/system.d/meshcore-ble.conf` met je eigen username:
```bash
sudo tee /etc/dbus-1/system.d/meshcore-ble.conf << 'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="JOUW_USERNAME">
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.Agent1"/>
    <allow send_interface="org.bluez.AgentManager1"/>
  </policy>
</busconfig>
EOF
```

### 4. Systemd service installeren
Maak `/etc/systemd/system/meshcore-gui.service` met je eigen paden:
```bash
sudo tee /etc/systemd/system/meshcore-gui.service << EOF
[Unit]
Description=MeshCore GUI (BLE)
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT
ExecStart=$PROJECT/venv/bin/python meshcore_gui.py JOUW_BLE_ADRES --debug-on
Restart=on-failure
RestartSec=30
Environment=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable meshcore-gui
sudo systemctl start meshcore-gui
```

---

## Verwijderen

### Via het script
```bash
cd ~/meshcore-gui
bash install_ble_stable.sh --uninstall
```

### Handmatig
```bash
sudo systemctl stop meshcore-gui
sudo systemctl disable meshcore-gui
sudo rm -f /etc/systemd/system/meshcore-gui.service
sudo rm -f /etc/dbus-1/system.d/meshcore-ble.conf
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

---

## Verificatie

```bash
# Service status
sudo systemctl status meshcore-gui

# Live logs
journalctl -u meshcore-gui -f

# Test PIN pairing (vanuit een andere terminal)
bluetoothctl remove <BLE_ADRES>
sudo systemctl restart meshcore-gui

# Test disconnect recovery
# Zet device uit → wacht 30s → zet weer aan → check logs
```

---

## Configuratie (config.py)

```python
BLE_PIN = "123456"              # T1000e pairing PIN
RECONNECT_MAX_RETRIES = 5       # Max pogingen per disconnect
RECONNECT_BASE_DELAY = 5.0      # Wachttijd × poging nummer (5s, 10s, 15s...)
```

Pas deze waarden aan in `meshcore_gui/config.py` als je een ander device of andere timing nodig hebt.
