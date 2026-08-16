# ADR-003: Persistente BLE-connectie via subprocess (`meshcore-ble-connect`)

**Status:** Accepted — 2026-02 (v5.5)

## Context

Vanaf BlueZ 5.82 (en deels 5.78+) lukt het bleak niet meer betrouwbaar
om zelf de `Device1.Connect()` D-Bus-aanroep te doen vóór GATT-service-
discovery. Resultaat: `failed to discover services, device disconnected`,
`le-connection-abort-by-local`, en in `btmon` herhaalde
`PIN or Key Missing (0x06) → Authentication Failure (0x05)`-cycli.

`bluetoothctl` werkt wel, maar zodra bleak een eigen connectie opzet
ziet BlueZ deze als een nieuwe sessie zonder geldig agent-context.

De directe BLE-connect-flow vanuit `BLEWorker` werd daarmee
onbetrouwbaar op recente Linux-distributies.

## Decision

**Gebruik `meshcore-ble-connect` als persistent subprocess** dat de
D-Bus/BLE-connectie openhoudt; bleak doet alleen GATT-service-discovery
over de bestaande connectie.

Flow in `BLEWorker._connect()`:

1. `ensure_bond()` (subprocess pairing-flow met PIN-agent) — bond OK.
2. Start subprocess: `meshcore-ble-connect <MAC> --pin <X> --connect`.
3. Wacht op `READY` op subprocess-stdout.
4. `BleakScanner.find_device_by_address()` — populeert bleak's
   `BlueZManager`-singleton zodat hij `Connected=True` ziet via
   `GetManagedObjects()`.
5. `BleakClient(addr).connect()` — bleak slaat `Device1.Connect()`
   over, doet alleen GATT-discovery.
6. `MeshCore.create_ble(client=client)` — normale event-loop.
7. Subprocess-health-check elke 100 ms in main loop; cleanup in
   `finally`-blok.

Het subprocess monitort `Connected`-property en print `DISCONNECTED`
op stdout bij verlies; `BLEWorker` triggert dan reconnect.

**Fallback:** als het subprocess faalt te starten (bijv. op BlueZ < 5.78
waar het niet nodig is), valt `_connect()` terug op directe
`MeshCore.create_ble(address)`.

## Consequences

**Plus**

- Werkt op BlueZ 5.82+ zonder workarounds in `bleak`.
- Strikte separation of concerns: `meshcore-ble-connect` heeft één
  taak (D-Bus-connectie openhouden), GUI hoeft geen D-Bus-code te
  bevatten.
- Backwards compatible via fallback-pad.

**Min**

- Extra externe dependency (`meshcore-ble-connect` als geïnstalleerd
  CLI-tool in de venv).
- Subprocess-lifecycle moet bewaakt worden (signal handling, cleanup
  in `finally`, kill bij worker-shutdown).
- Potentieel risico dat bleak alsnog `Device1.Connect()` aanroept
  als de scanner het device niet ziet adverteren terwijl het connected
  is. In de praktijk vangt `GetManagedObjects()` dit op.

**Bindende uitvloeisels**

- Geen pairing- of D-Bus-code in `meshcore_gui/`. Bond-management en
  agent-registratie horen in de subprocess of in `BleAgentManager`
  (zie ADR-004).
- `meshcore-ble-connect` is een **separaat project** met eigen
  versionering. Geen systemd-files of install-docs van dat project
  in deze repo.

## References

- `INTEGRATION_GUIDE.md`
- ADR-004 — Built-in D-Bus PIN-agent (complementair)
- `meshcore_ble_connect/app.py`, `device.py`, `__main__.py`
- `meshcore_gui/ble/worker.py`
