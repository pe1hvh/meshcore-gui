# meshcore-gui

Python-applicatie met NiceGUI-webinterface voor het bedienen en monitoren
van een MeshCore mesh-radio-device. Communicatie via USB-serieel
(primair) of BLE (legacy). Architectuur-, functioneel- en feature-detail:
zie `docs/`.

## Doel van dit document

Richt-document voor wie aan deze codebase werkt: developers die overnemen
of uitbreiden, en AI-assistenten (Claude) in vervolgsessies. Bevat de
bindende regels, conventies en valkuilen die het gedrag bij **elke**
taak sturen. Beschrijft **niet** hoe het systeem technisch werkt —
zie `MeshCore_GUI_Design.docx` en de feature-docs. Beschrijft **niet**
hoe je installeert — zie `README.md` (§5 en §7) / `MULTI_INSTANCE.md`.
Beschrijft **niet** waarom architecturele keuzes zijn gemaakt — zie
`docs/adr/`.

## Architectuur in één scherm

- **Twee threads.** GUI (NiceGUI main thread) en Worker (asyncio event
  loop voor seriële of BLE I/O). Communicatie uitsluitend via
  `SharedData` (thread-safe) en de command queue.
- **Cache-first startup.** GUI vult eerst uit `~/.meshcore-gui/cache/`,
  Worker ververst daarna in de achtergrond.
- **Dual-layer persistence.** `SharedData` houdt actuele state in
  geheugen voor de UI; `MessageArchive` bewaart messages en RX-log met
  retentie (eigen lock, geen contention met GUI).
- **Browser-managed map.** Leaflet draait in de browser, Python stuurt
  alleen snapshots — `L.map()` wordt nooit vanuit Python opgeroepen.
  Zie `docs/adr/ADR-001-browser-managed-leaflet.md`.
- **Protocol-interfaces.** Consumers hangen aan `typing.Protocol`-
  contracten in `protocols.py`, niet aan de concrete `SharedData`-klasse.
  Zie `docs/adr/ADR-002-protocol-interfaces.md`.
- **Per-device data-isolatie.** Cache, archive, pins, room-passwords en
  logs zijn gescheiden per device-identifier (BLE-adres of serial-pad).

## Coding-conventies

- **PEP 8** — `snake_case` functies/variabelen, `PascalCase` klassen,
  `UPPER_SNAKE_CASE` constanten.
- **Type hints** op alle publieke methodes en parameters.
- **`@dataclass`** voor nieuwe data-modellen (zie `models.py`).
- **Engelse code, docstrings, UI-labels en tooltips.** Nederlandse
  documentatie en chat-communicatie.
- **Google-style docstrings.**
- Geen `from … import *`. `pathlib.Path` voor paden. 4 spaces indentatie.

## Bindende regels

### 🏛️ ADRs

ADRs in `docs/adr/` zijn dwingend. Lees de relevante ADR vóór een
wijziging die zijn scope raakt (map, protocols, BLE-subprocess,
PIN-agent, persistence).

### 📦 Threading & gedeelde state

- **Gedeelde state uitsluitend via `SharedData`** — geen module-globals,
  geen statische singletons. Consumers zien alleen de protocol-methodes
  die ze nodig hebben (`SharedDataReader`, `SharedDataWriter`,
  `ContactLookup`, `SharedDataReadAndLookup`).
- **GUI-thread mag niet blokkeren.** Geen `time.sleep` in NiceGUI-
  callbacks of timers. Gebruik `asyncio.sleep` of de Worker-thread.
- **Worker-blokkerende operaties horen niet in events of commands.**
  Periodieke taken (key-retry, contact-refresh) draaien als eigen
  loop met eigen interval.
- **MessageArchive heeft een eigen lock.** Niet kruislings vergrendelen
  met de SharedData-lock; archive-flush gebeurt onafhankelijk.

### 🗺️ Map-subsysteem

- **Leaflet-instantie wordt één keer aangemaakt in de browser.** Nooit
  vanuit Python `L.map(...)` opnieuw initialiseren — niet in snapshot-
  handlers, timers of retry-loops.
- **Geen NiceGUI map-wrappers** (`ui.leaflet()` of vergelijkbaar).
- **Snapshots zijn compact en incrementeel.** Markers worden bijgewerkt
  per stabiele node-id; thema en viewport-state blijven bij de browser.
- **Device-marker hoort buiten de cluster-layer.** `maxZoom` van
  map/tile-layer staat vóór de clustering-laag wordt aangehecht.

Volledige regels: `docs/adr/ADR-001-browser-managed-leaflet.md`.

### 🔌 BLE-stabiliteit (legacy-pad)

- **Ingebouwde D-Bus PIN-agent** is leidend. Geen externe `bt-agent.service`
  of `bluez-tools`-afhankelijkheid in nieuwe code.
  Zie `docs/adr/ADR-004-builtin-dbus-pin-agent.md`.
- **Persistente connectie via subprocess** (`meshcore-ble-connect --connect`)
  is het primaire pad voor BlueZ ≥ 5.78. Bleak doet alleen GATT-discovery
  over de bestaande connectie.
  Zie `docs/adr/ADR-003-subprocess-ble-connect.md`.
- **Bond-cleanup vóór elke reconnect.** Lineaire backoff
  (`delay = attempt × base_delay`), oneindige recovery-cyclus.

### 💾 Persistence

- **Append-only batched writes.** MessageArchive flusht periodiek
  (drempel of timer); ruwe Message/RxLogEntry-objecten worden niet
  individueel naar disk geschreven.
- **Retentie is configureerbaar** via `MESSAGE_RETENTION_DAYS`,
  `RXLOG_RETENTION_DAYS`, `CONTACT_RETENTION_DAYS` in `config.py`.
  Cleanup draait dagelijks in de achtergrond.
- **Atomic writes via temp-file + rename.** Bij faalde write blijft de
  buffer staan voor retry.
- **Cache beschermt zichzelf.** Channel-keys uit cache worden nooit
  overschreven door name-derived fallbacks.

Detail: `FEATURE_MESSAGE_PERSISTENCE.md`,
`docs/adr/ADR-005-dual-layer-persistence.md`.

### ✨ Geen overengineering

- **YAGNI** — geen code voor toekomstige denkbare uitbreidingen.
- Geen Protocol/ABC zonder concrete tweede implementatie of
  testbaarheid-noodzaak. (Bestaande Protocols voldoen aan deze drempel.)
- Geen wrappers, facades, factories als één concrete class volstaat.
- Bij twijfel: kortste werkende oplossing wint.
- Voorstel voor extra abstractie: **STOP en motiveer concreet**.

### 🚫 Geen breaking changes zonder afspraak

- Publieke method-signatures van `SharedData`, de protocols, en publieke
  page-routes blijven backward-compatible.
- Archive-JSON-schema is permanent. Velden mogen alleen worden
  toegevoegd (default-waarde), niet verwijderd of hernoemd.
- Cache-JSON-schema idem.

### 🛡️ Bestaande functionaliteit

- Inventariseer per geraakt bestand vóór implementatie wat erin zit.
- Wat niet in de taak staat wordt niet gewijzigd.
- Bij refactoring: behoud bestaande publieke methods tenzij anders gevraagd.
- Bij twijfel: STOP en vraag.

## Werkproces in een chat-sessie

Drie verplichte checkpoints:

1. **Source verification** (eerst, altijd) — inventariseer alle code-sources;
   meld welke je ziet met timestamps; vraag welke leidend is; begin elke
   code-response met *"Werkend met: [bestandsnaam] (uploaded [timestamp])"*.
2. **Impact analyse** (vóór implementatie) — welke bestanden worden geraakt,
   welke functionaliteit zit erin; vraag bevestiging vóór je begint.
3. **Delivery validation** (vóór oplevering) — is bestaande functionaliteit
   nog intact? UI-consistentie (Engels, bestaande component-stijl)?
   ZIP-inhoud verifiëren?

**File-source-priority** (van hoog naar laag): meest recente upload >
losse bestanden (op upload-tijd) > MCP/GitHub (alleen op verzoek) >
chat-history (nooit als code-source). Bij conflict: STOP en vraag.

**XML = assignment spec, ZIP = authoritative source.** Lees de ZIP als
ground truth; implementeer per de XML-opdracht.

## Output- en delivery-conventies

Per bestand: pad, volledige source, korte uitleg wat verandert en waarom,
wat **niet** is veranderd.

ZIP-conventie: `meshcore_gui_Iteratie_[X]_result.zip` (X = iteratie-letter
uit input). Behoud directory-structuur exact (root `meshcore_gui/`, alle
root-level bestanden mee). Verifieer voor oplevering. User uploads bevatten
`input`, AI-resultaten `result`. Maximaal 1 ZIP per chat.

## Bekende valkuilen

- **NiceGUI middleware-stack is bevroren** voordat routes registreren.
  Gebruik `JSONResponse`-headers voor CORS, geen `add_middleware()`.
- **Tailwind `h-96` werkt niet** — er zit geen Tailwind-compiler in
  NiceGUI. Gebruik inline CSS of `style=`.
- **`v-show` verbergt met `display:none`** en breekt Leaflet-init.
  Gebruik conditional rendering.
- **`!h` is gereserveerd door MeshCore-firmware** en bereikt nooit een
  applicatie-handler. Gebruik alternatieven (`!i`, `!info`).
- **Channel-key brute-force.** Decoder en firmware berekenen verschillende
  channel-identifiers voor dezelfde secret; loop door alle bekende keys
  in plaats van op hash te matchen.
- **Dedup is twee onafhankelijke systemen.** `add_message` (hash-based)
  en bot-cooldown (per-sender) — beide nodig.
- **`time.sleep` in GUI-thread** bevriest NiceGUI. Gebruik `asyncio.sleep`
  of een aparte thread.

## Output-stijl

- Antwoorden in **Nederlands**.
- Geef advies, vraag bevestiging vóór implementatie.
- Volledige bestanden bij grotere wijzigingen, korte diffs voor mini-fixes.
- Geen ongevraagde *"je zou ook nog kunnen overwegen…"* — wat in de taak
  staat is de taak.

## Verwijzingen

- **`MeshCore_GUI_Design.docx`** — actueel ontwerpdocument: componenten,
  threading-model, klassediagram, configuratie, version history.
- **`FEATURE_MESSAGE_PERSISTENCE.md`** — persistence-laag in detail.
- **`MAP_ARCHITECTURE.md`** — map-subsysteem (browser-runtime).
- **`MULTI_INSTANCE.md`** — meerdere instances per host.
- **`README.md` §5.1.1 en `install_scripts/install_ble_stable.sh`** —
  BLE-stabiliteit (legacy-pad).
- **`INTEGRATION_GUIDE.md`** — subprocess-BLE-connect detail.
- **`README.md` §13.1.2** — BLE-troubleshooting (legacy).
- **`docs/adr/`** — Architecture Decision Records (waarom-vragen).
- **`CHANGELOG.md`** — wijzigingen per release.
- **`README.md`** — installatie en eerste gebruik.
