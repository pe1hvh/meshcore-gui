# ADR-004: Ingebouwde D-Bus PIN-agent (vervangt `bt-agent.service`)

**Status:** Accepted — 2026-02 (v5.11)

## Context

MeshCore-devices vereisen BLE PIN-pairing (default `123456`). Bleak kan
zelf geen passkey leveren — BlueZ verwacht een geregistreerde
`org.bluez.Agent1`-implementatie die op pairing-callbacks reageert.

De eerste werkende oplossing was het `bluez-tools`-pakket met
`bt-agent` als systemd-service, gevoed door een PIN-bestand
(`~/.meshcore-ble-pin`). Dat werkte, maar:

- Vereiste extra OS-pakket (`apt install bluez-tools`).
- Vereiste een aparte systemd-unit en D-Bus-policy per host.
- Was gevoelig voor "twee agents tegelijk"-conflicten (manueel gestarte
  `bt-agent &` plus systemd-service).
- Splitste pairing-state tussen GUI-config en een los config-bestand.

## Decision

**Implementeer de pairing-agent intern**, in `meshcore_gui/ble/ble_agent.py`,
gebruikmakend van `dbus_fast` (al een bleak-dependency).

Componenten:

- `BluezAgent(ServiceInterface)` — implementeert
  `org.bluez.Agent1` met callbacks voor `RequestPinCode`,
  `RequestPasskey`, `DisplayPasskey`, `RequestConfirmation` en
  `AuthorizeService`. Antwoordt op alle PIN-requests met de geconfigureerde
  `BLE_PIN` (default `"123456"`).
- `BleAgentManager` — `start(pin)` exporteert de agent op D-Bus-pad
  `/meshcore/ble_agent` en registreert hem als default agent met
  capability `KeyboardOnly`. `stop()` deregistreert en sluit de
  D-Bus-verbinding.

`BLEWorker` start de agent **vóór** elke connect-poging en cleanupt
in `finally`. PIN staat in `config.py` (`BLE_PIN`).

## Consequences

**Plus**

- Geen externe dependency op `bluez-tools`.
- Geen aparte systemd-service of D-Bus-policy meer nodig voor het
  agent-pad (system-bus policy voor `org.bluez.Agent1` blijft).
- Eén bron voor de PIN: `config.py`.
- Lifecycle gebonden aan de Worker — geen verweesde agents.

**Min**

- Vereist `dbus_fast` als runtime-dependency (was er al via bleak,
  maar nu expliciet).
- D-Bus-policy in `/etc/dbus-1/system.d/` blijft per-host nodig zodat
  de niet-root user mag praten met `org.bluez`.
- Eén PIN per device-fleet (de agent matcht op `*`). Voor multi-PIN
  scenario's moet de agent uitgebreid worden.

**Bindende uitvloeisels**

- Nieuwe code voor pairing/agent-registratie hoort in
  `meshcore_gui/ble/ble_agent.py` of in `meshcore-ble-connect`. Niet
  in `worker.py` of GUI-code.
- `INSTALLATIE.md` is daarmee historisch — de daar beschreven
  `bt-agent`-stappen zijn **niet** meer aanbevolen.

## References

- `MeshCore_GUI_Design.docx` §3.18 — `BleAgentManager`
- `INSTALLATIE.md` (legacy)
- `TROUBLESHOOTING.md` — Solution 2 (legacy bt-agent flow)
- ADR-003 — Subprocess-BLE-connect (complementair)
- `meshcore_gui/ble/ble_agent.py`
- `meshcore_gui/config.py` — `BLE_PIN`
