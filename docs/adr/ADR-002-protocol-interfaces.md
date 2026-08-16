# ADR-002: Protocol-interfaces (`typing.Protocol`) i.p.v. `abc.ABC`

**Status:** Accepted — 2026-02

## Context

De applicatie heeft één centrale, thread-safe data-store (`SharedData`)
die door meerdere consumenten wordt gebruikt:

- `BLEWorker` schrijft device-info, contacten, channels, messages en
  RX-log entries.
- `DashboardPage` leest snapshots en plaatst commands.
- `RouteBuilder` zoekt contacten op prefix.
- `RoutePage` en `ArchivePage` doen beide read en lookup.
- Widget-klassen ontvangen alleen plain dicts en callbacks.

Vóór de SOLID-refactor importeerden al deze consumenten direct
`shared_data.SharedData`. Dat:

- Verstopte dat de meeste consumenten maar een fractie van de 15+
  publieke methoden gebruiken (ISP-violation).
- Maakte testen lastig — een test-stub moest alle methoden bieden,
  ook de niet-gebruikte.
- Bond consumenten aan de concrete implementatie i.p.v. aan het
  contract dat ze nodig hebben (DIP-violation).

## Decision

**Definieer per consument een smal Protocol-contract in `protocols.py`;**
consumenten typen tegen het contract, niet tegen `SharedData`.

Geïntroduceerde Protocols:

| Protocol | Consument | Methoden |
|----------|-----------|----------|
| `SharedDataWriter` | `BLEWorker` | 10–15 (write + lookup) |
| `SharedDataReader` | `DashboardPage` | 4–6 (snapshot + commands) |
| `ContactLookup` | `RouteBuilder` | 1 |
| `SharedDataReadAndLookup` | `RoutePage`, `ArchivePage` | Reader + Lookup |
| `CommandSink` | `MeshBot`, GUI-pages | `put_command` |

`SharedData` blijft één concrete klasse die alle Protocols
**structureel** implementeert (zonder `from typing import Protocol`-
inheritance). De **composition root** (`meshcore_gui.py`) is de enige
plek die de concrete klasse kent.

`typing.Protocol` is gekozen **boven `abc.ABC`** omdat:

| Aspect | `abc.ABC` (nominal) | `typing.Protocol` (structural) |
|--------|---------------------|-------------------------------|
| Subclassing nodig | ja | nee |
| Duck typing | nee | ja |
| Test-stubs | moeten erven | hoeven alleen methoden te hebben |

## Consequences

**Plus**

- Elke consument ziet alleen wat hij nodig heeft (ISP).
- Test-stubs zijn lichtgewicht: alleen de methoden van het smalle
  contract.
- Refactoring van `SharedData`-internen raakt consumenten niet zolang
  de Protocol-signatures stabiel blijven (DIP).
- Widget-klassen hebben **nul** kennis van `SharedData` — ze krijgen
  plain dicts en callbacks.

**Min**

- `typing.Protocol` werkt vanaf Python 3.8 — geen probleem in deze
  codebase (3.10+).
- Vijf interface-classes zijn extra onderhoud bij echt brede signature-
  wijzigingen. Drempel voor nieuwe Protocols: alleen wanneer een
  consument een meetbaar smaller contract heeft, niet preventief.

**Niet introduceren**

- Geen `abc.ABC` met `@abstractmethod` voor deze use-case. De Protocol-
  variant levert hetzelfde type-veiligheidsniveau zonder verplichte
  subclassing.

## References

- `SOLID_ANALYSIS.md`
- `meshcore_gui/core/protocols.py`
- `meshcore_gui/core/shared_data.py`
- PEP 544 — Protocols: Structural subtyping
