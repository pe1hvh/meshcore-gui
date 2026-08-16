# ADR-005: Dual-layer persistence — `SharedData` + `MessageArchive` met onafhankelijke locks

**Status:** Accepted — 2026-02 (v5.1)

## Context

De GUI moet twee verschillende dingen tegelijk aankunnen:

1. **Real-time UI** — laatste 100 messages, laatste 50 RX-log-entries,
   met sub-second responsetijd in de 500 ms refresh-loop.
2. **Lange-termijn archief** — alle inkomende messages en RX-log-entries
   bewaren over dagen tot maanden, met retentie en query-mogelijkheden
   (filter, search, paginatie, hash-lookup voor route-pagina).

Deze twee belangen botsen in één datastructuur:

- Eén onbegrensde lijst geeft geheugendruk en trage UI-updates.
- Disk-I/O in de UI-thread bevriest NiceGUI.
- Gedeelde lock tussen UI-buffer en archive-flush geeft contention —
  archive-write blokkeert dan een dashboard-refresh.

## Decision

**Twee gescheiden lagen met eigen verantwoordelijkheden en eigen locks.**

```
SharedData (in-memory, UI)
  ├── messages: laatste 100
  ├── rx_log: laatste 50
  ├── threading.Lock()
  └── on add → MessageArchive

MessageArchive (persistent)
  ├── alle messages / rx-log → JSON
  ├── batch-buffer (10 items / 60 s)
  ├── retentie-cleanup (dagelijks)
  ├── threading.Lock()  ← onafhankelijk
  └── atomic write (temp + rename)
```

**Lock-volgorde** (om deadlock te voorkomen):

1. `SharedData.lock` acquired
2. `SharedData` roept `MessageArchive.add_*()`
3. `MessageArchive.lock` acquired binnen die call

Deze volgorde is consistent in álle write-paden.

**Storage-format:** één JSON-bestand per data-type per device-identifier:
- `~/.meshcore-gui/archive/<ADDRESS>_messages.json`
- `~/.meshcore-gui/archive/<ADDRESS>_rxlog.json`

Velden mogen alleen worden **toegevoegd** (default-waarde),
niet verwijderd of hernoemd. Schema-versie staat in elk bestand.

**Retentie** is configureerbaar in `config.py` (`MESSAGE_RETENTION_DAYS`,
`RXLOG_RETENTION_DAYS`, `CONTACT_RETENTION_DAYS`). Cleanup draait
dagelijks in de Worker-thread.

**Backward-compat:** `SharedData()` zonder device-identifier werkt
zonder archive (`archive=None`).

## Consequences

**Plus**

- UI blijft responsief: archive-flush blokkeert nooit een snapshot.
- Buffered batch-writes (drempel `BATCH_SIZE` of timer) houden disk-I/O
  laag; ~10 ms voor 1000 messages.
- Retentie-cleanup is een eigen periodieke taak, niet verweven met
  refresh-loop.
- Atomic writes (`tempfile + os.replace`) voorkomen halve archives bij
  crash.
- Per-device-isolatie maakt multi-instance triviaal (zie
  `MULTI_INSTANCE.md`).

**Min**

- Twee locks vereisen disciplinaire lock-volgorde. Afwijken
  introduceert deadlock-risico.
- Bij crash tijdens een nog-niet-geflushte batch verlies je tot
  `BATCH_SIZE` items of de laatste 60 s. Acceptabel voor mesh-
  observatie; niet acceptabel als dit financiële data was.
- JSON-array-append vereist read-modify-write in plaats van streaming
  append. Bestandsgrootte is voorlopig acceptabel (<10 MB / maand bij
  100 msg/dag); als het structureel groter wordt, is migratie naar
  JSONL of SQLite een logische vervolgstap.

**Bindende uitvloeisels**

- `MessageArchive` heeft een **eigen lock**. Niet kruislings vergrendelen
  met `SharedData.lock` buiten de gedefinieerde volgorde.
- Schema-velden: alleen toevoegen met default. Verwijderen/hernoemen
  vereist nieuwe ADR + migratie.
- Cleanup-interval staat **niet** afgestemd op de refresh-loop maar
  draait dagelijks in de Worker.

## References

- `FEATURE_MESSAGE_PERSISTENCE.md`
- `MeshCore_GUI_Design.docx` §3.13 — `MessageArchive`
- `MULTI_INSTANCE.md` — per-device data-isolatie
- `meshcore_gui/core/shared_data.py`
- `meshcore_gui/persistence/message_archive.py`
- `meshcore_gui/config.py` — `MESSAGE_RETENTION_DAYS` etc.
