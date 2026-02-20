# MeshCore GUI — BLE Stabiliteit: Installatie-instructies

## Wat is gewijzigd (v1.9.13)

### Nieuwe bestanden
| Bestand | Doel |
|---------|------|
| `meshcore_gui/ble/ble_connector.py` | Optionele integratie met externe BLE bond manager |

### Gewijzigde bestanden
| Bestand | Wijziging |
|---------|-----------|
| `meshcore_gui/ble/worker.py` | Bond verificatie vóór elke connect-poging, graceful degradation |
| `meshcore_gui/config.py` | `BLE_CONNECT_TIMEOUT`, `MESHCORE_BLE_PIN` env var support |
| `meshcore_gui/__main__.py` | `--pin` als alias voor `--ble-pin` |

---

## Snelle installatie

```bash
# 1. Kopieer de nieuwe/gewijzigde bestanden naar je project
cp ble_connector.py ~/meshcore-gui/meshcore_gui/ble/
cp worker.py        ~/meshcore-gui/meshcore_gui/ble/
cp config.py        ~/meshcore-gui/meshcore_gui/
cp __main__.py      ~/meshcore-gui/meshcore_gui/

# 2. Test
python -m meshcore_gui literal:FF:05:D6:71:83:8D --pin=123456
```

---

## Optionele dependency

[`meshcore-ble-connect`](https://github.com/PE1HVH/meshcore-ble-connect) kan apart geïnstalleerd worden voor verbeterd BLE bond management. Als het aanwezig is, wordt het automatisch gebruikt. Als het niet geïnstalleerd is, werkt de ingebouwde BLE agent zoals voorheen.

---

## PIN configuratie

De PIN kan op drie manieren worden ingesteld (in prioriteitsvolgorde):

1. **CLI parameter** (hoogste prioriteit): `--pin=123456` of `--ble-pin=123456`
2. **Environment variable**: `MESHCORE_BLE_PIN=123456` (handig voor systemd)
3. **config.py** default: `BLE_PIN = "123456"` (laagste prioriteit)

---

## Verificatie

```bash
# Service status
sudo systemctl status meshcore-gui

# Live logs
journalctl -u meshcore-gui -f

# Test disconnect recovery
# Zet device uit → wacht 30s → zet weer aan → check logs
```

---

## Configuratie (config.py)

```python
BLE_PIN = "123456"              # T1000e pairing PIN (of via MESHCORE_BLE_PIN env var)
BLE_CONNECT_TIMEOUT = 60        # Timeout voor externe bond manager (indien aanwezig)
RECONNECT_MAX_RETRIES = 5       # Max pogingen per disconnect
RECONNECT_BASE_DELAY = 5.0      # Wachttijd × poging nummer (5s, 10s, 15s...)
```
