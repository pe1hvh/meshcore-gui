# v5.5 Integration Guide — Subprocess BLE Connection

## Overzicht

Deze wijziging lost het BlueZ 5.82 probleem op door `meshcore-ble-connect`
als **persistent subprocess** te draaien dat de D-Bus/BLE connectie openhoudt,
terwijl `BleakClient` er alleen GATT service discovery overheen doet.

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

## Architectuur

```
┌─────────────────────────────────────────────┐
│  meshcore-gui (worker.py)                   │
│                                             │
│  1. ensure_bond() → bond OK                 │
│  2. start subprocess:                       │
│     meshcore-ble-connect MAC --pin X        │
│     --connect                               │
│  3. wait for "READY" op stdout              │
│  4. BleakScanner.find_device_by_address()   │
│     → populeert bleak's interne cache       │
│  5. BleakClient(addr).connect()             │
│     → bleak ziet Connected=True in BlueZ    │
│     → slaat Device1.Connect() over          │
│     → doet alleen GATT service discovery    │
│  6. MeshCore.create_ble(client=client)      │
│  7. Main loop draait                        │
│  8. subprocess health check elke 100ms      │
└──────────────┬──────────────────────────────┘
               │ subprocess (stdout PIPE)
               │
┌──────────────▼──────────────────────────────┐
│  meshcore-ble-connect --connect             │
│                                             │
│  1. Bond flow (ensure/pair/trust)           │
│  2. Device1.Connect() via D-Bus             │
│  3. Poll ServicesResolved tot True           │
│  4. print("READY") → stdout                 │
│  5. Monitor Connected property              │
│     → print("DISCONNECTED") bij verlies     │
│  6. Wacht op SIGTERM of disconnect          │
│  7. Device1.Disconnect() bij shutdown       │
└─────────────────────────────────────────────┘
```

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

## Risico-mitigatie

Het document noemde het risico dat bleak mogelijk opnieuw `Device1.Connect()`
aanroept. Dit is opgelost door:

1. **`BleakScanner.find_device_by_address()`** vóór `BleakClient.connect()` —
   dit triggert bleak's `BlueZManager` singleton om bestaande BlueZ device
   objecten te ontdekken via `GetManagedObjects()`.
2. De manager ziet `Connected=True` op het device (gezet door het subprocess)
   → `BleakClient.connect()` slaat `Device1.Connect()` over.
3. Bleak doet alleen GATT service resolution over de bestaande connectie.

Als de scanner het device niet vindt (het adverteert mogelijk niet terwijl
het connected is), probeert bleak alsnog. De `GetManagedObjects` call bij
manager initialisatie vangt dit op in de meeste gevallen.
