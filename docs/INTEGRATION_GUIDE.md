# v5.5 Integration Guide — Subprocess BLE Connection

## Overzicht

Deze wijziging lost het BlueZ 5.82 probleem op door `meshcore-ble-connect`
als **persistent subprocess** te draaien dat de D-Bus/BLE connectie openhoudt,
terwijl `BleakClient` er alleen GATT service discovery overheen doet.

De architectuur, de flow en de risico-mitigatie staan in
**`docs/adr/ADR-003-subprocess-ble-connect.md`**. Dit document bevat alleen
de installatie- en delivery-stappen.

---

## Gewijzigde bestanden

### meshcore-ble-connect (5 bestanden)

| Bestand | Wijziging |
|---|---|
| `constants.py` | Versie → 1.1.0. Nieuwe constanten: `SERVICES_RESOLVED_TIMEOUT`, `DISCONNECT_POLL_INTERVAL`. Nieuwe exit codes: `CONNECT_FAILED` (5), `DISCONNECTED` (6). |
| `exceptions.py` | Nieuwe exception: `ConnectHoldError`. |
| `__main__.py` | Nieuw `--connect` flag. Mutual exclusion met `--check-only`. Doorgifte `connect_hold=` aan `BleConnectApp`. |
| `app.py` | Nieuw `connect_hold` parameter. Na bond OK → `_enter_connect_hold()` → `device.connect_and_hold()`. Werkt bij zowel bestaande bond als verse pairing. |
| `device.py` | Nieuwe methoden: `connect_and_hold()`, `is_connected()`, `is_services_resolved()`, `_wait_for_services_resolved()`, `_monitor_connection()`. Signal handling (SIGTERM/SIGINT) voor clean shutdown. |

### meshcore-gui (1 bestand)

| Bestand | Wijziging |
|---|---|
| `worker.py` | Nieuwe methoden: `_connect_via_subprocess()`, `_kill_connect_subprocess()`. Gewijzigd: `_connect()` gebruikt subprocess als primary path wanneer `_use_ble_connect=True`. Subprocess health check in main loop. Cleanup in finally block. |

---

## Installatie

```bash
# 1. Update meshcore-ble-connect
cd ~/meshcore-ble-connect
# Vervang de 5 gewijzigde bestanden in meshcore_ble_connect/
pip install -e . --break-system-packages

# 2. Test --connect mode standalone
meshcore-ble-connect FF:05:D6:71:83:8D --pin 123456 --connect --verbose
# Verwacht: READY op stdout, proces blijft draaien
# Ctrl+C om te stoppen

# 3. Update worker.py
cp worker.py ~/meshcore-gui/meshcore_gui/ble/worker.py

# 4. Start meshcore-gui
cd ~/meshcore-gui && python -m meshcore_gui
```

## Fallback gedrag

Als het subprocess faalt (bijv. op BlueZ < 5.78 waar het niet nodig is),
valt `_connect()` automatisch terug op de directe `MeshCore.create_ble(address)`
aanroep. Dit garandeert backwards compatibility.
