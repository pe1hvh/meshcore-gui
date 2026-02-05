# MeshCore GUI v4.0 — Changelog

## Probleem dat is opgelost

Bij het opstarten van de GUI bufferde het systeem RX_LOG-pakketten die tijdens de
initialisatiefase binnenkwamen (send_appstart, send_device_query, get_contacts).
Deze pakketten werden later foutief gekoppeld aan het eerste echte channel message,
wat resulteerde in onmogelijke route-informatie (bijv. "22 of 7 repeaters identified").

Daarnaast gebruikte de oude code SNR-matching om RX_LOG-entries te koppelen aan
channel messages. Dit werkte niet betrouwbaar omdat het companion protocol en
RX_LOG verschillende SNR-waarden rapporteren voor hetzelfde fysieke pakket
(bijv. companion=13.5, RX_LOG=14.0).

## Drie defensieve lagen

### Laag 1: Startup buffer clearing (`ble_worker.py:126-135`)

Na `start_auto_message_fetching()` worden de RX path buffer én het SharedData
archive geleegd. Alle pakketten die tijdens de init-fase zijn binnengekomen
worden weggegooid voordat het eerste echte channel message kan arriveren.

```python
await self.mc.start_auto_message_fetching()
self._rx_path_buffer.clear()
self.shared.clear_rx_archive()
```

### Laag 2: Path_len sanity checks (alle matching paden)

In elke matching-methode wordt gecontroleerd of het aantal hashes in een RX_LOG
entry niet wild afwijkt van het door het companion protocol gerapporteerde hop
count. De margin is configureerbaar via `PATH_LEN_SANITY_MARGIN = 5`.

Aanwezig in:
- Forward matching (`ble_worker.py:366`)
- Retroactive matching (`ble_worker.py:304`)
- Archive matching (`shared_data.py:354`)

Voorbeeld: een 7-hop bericht accepteert maximaal 12 hashes (7 + 5).
Een entry met 22 hashes wordt geweigerd.

### Laag 3: Display-time guard (`route_page.py:89`)

Laatste vangnet bij het renderen van de route-pagina. Als het aantal resolved
hops meer is dan 2× de path_len, wordt de match als false positive beschouwd
en verworpen.

```python
if msg_path_len > 0 and resolved_hops > 2 * msg_path_len:
    resolved_hops = 0
    route['path_nodes'] = []
```

## Andere wijzigingen

- **Temporal matching i.p.v. SNR** — Alle RX_LOG correlatie gebruikt nu
  tijdproximiteit (binnen 3 seconden) in plaats van SNR-vergelijking.
  SNR wordt nog steeds weergegeven in de UI maar niet meer gebruikt voor matching.

- **`PATH_LEN_SANITY_MARGIN`** als configureerbare constante in `config.py`

## Bestanden gewijzigd

| Bestand | Wijziging |
|---------|-----------|
| `meshcore_gui.py` | Versie → 4.0 |
| `meshcore_gui/__init__.py` | `__version__` → "4.0" |
| `meshcore_gui/config.py` | + `PATH_LEN_SANITY_MARGIN = 5` |
| `meshcore_gui/ble_worker.py` | Startup clear, temporal matching, path_len checks |
| `meshcore_gui/shared_data.py` | `clear_rx_archive()`, `find_rx_path()` met path_len check |
| `meshcore_gui/route_page.py` | Display-time sanity guard |
| `meshcore_gui/route_builder.py` | Geeft `msg_path_len` door aan archive lookup |
| `meshcore_gui/protocols.py` | + `clear_rx_archive()` in Writer protocol |

## Installatie

Vervang je huidige bestanden:

```bash
# Backup
cp -r meshcore_gui meshcore_gui.bak
cp meshcore_gui.py meshcore_gui.py.bak

# Vervang
cp -r meshcore-gui-v4.0/meshcore_gui ./
cp meshcore-gui-v4.0/meshcore_gui.py ./
```

## Verwacht gedrag na update

Met `--debug-on` zie je nu bij opstarten:

```
DEBUG: Startup buffer+archive cleared — only post-init packets will be matched
BLE: Ready!
```

En bij een 7-hop bericht met correcte match:
```
DEBUG: Forward match: dt=0.42s, hashes=7
```

In plaats van het oude gedrag:
```
DEBUG: No RX_LOG match: msg_snr=13.5, buffer_snrs=[14.0, 14.0, ...]
DEBUG: RX archive match: snr=14.0, hashes=[...22 total], time_diff=0.81s
```
