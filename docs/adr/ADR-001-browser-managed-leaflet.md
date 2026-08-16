# ADR-001: Browser-managed Leaflet runtime

**Status:** Accepted — 2026-02

## Context

De MeshCore GUI toont contacten en eigen positie op een Leaflet-kaart in
het centrum-paneel van de dashboard. De dashboard-update-loop draait elke
500 ms en pusht een snapshot van device- en contact-data naar de UI.

Eerdere implementaties stuurden de map-lifecycle vanuit Python aan
(NiceGUI-wrappers, JS-injection vanuit snapshot-handlers). Dat
veroorzaakte:

- Verdwijnende kaarten omdat `L.map(...)` in de refresh-loop opnieuw
  werd aangeroepen op een al geïnitialiseerd container-element
  (`Map container is already initialized`).
- Marker-flicker omdat de hele marker-laag elke 500 ms werd vervangen
  in plaats van incrementeel bijgewerkt.
- Viewport-resets en thema-resets omdat thema-state in snapshots zat
  en queued snapshots gebruikersacties overschreven.
- Cluster-bootstrap-fouten wanneer de cluster-laag werd aangehecht
  voordat `maxZoom` op map of tile-layer bekend was.

## Decision

**De Leaflet-map-lifecycle is volledig in handen van de browser.**
Python is data-leverancier en nooit aanroeper van Leaflet-API's.

Concreet:

- Leaflet wordt **één keer** geïnitialiseerd per DOM-container in
  `static/leaflet_map_panel.js`.
- Python (`MapPanel`, `MapSnapshotService`) stuurt **compacte JSON-
  snapshots**; de browser past deze incrementeel toe per stabiele
  node-id.
- **Thema-state loopt over een eigen kanaal**, niet door snapshots.
- **Viewport-state blijft bij de browser**; snapshots forceren geen
  center/zoom tijdens normale refresh-cycles.
- De **eigen-device-marker zit buiten** de contact-cluster-layer.
- `maxZoom` van map/tile-layer wordt gezet **vóór** clustering wordt
  aangehecht.

NiceGUI-map-wrappers (`ui.leaflet()` of vergelijkbaar) worden niet
gebruikt.

## Consequences

**Plus**

- Geen flicker, geen viewport-resets, geen thema-resets tijdens de
  refresh-cyclus.
- Reconnect na korte NiceGUI-disconnect blijft de map en lokale state
  intact.
- Map-state overleeft snapshot-coalescing: alleen het nieuwste payload
  wordt toegepast.

**Min**

- Leaflet-API's zijn niet vanuit Python aanroepbaar; uitbreidingen
  (heatmap, route-overlays, tile-switching) moeten als browser-runtime-
  uitbreiding worden geïmplementeerd.
- Debuggen vereist DevTools-inspectie van de runtime, niet alleen
  Python-logs.

**Bindende uitvloeisels** (zie `DEV_RULES.md`):

- Recreate map in 500 ms loop → verboden
- `L.map(...)` vanuit Python → verboden
- Thema in snapshots → verboden
- Device-marker in cluster-layer → verboden

## References

- `MAP_ARCHITECTURE.md`
- `DEV_RULES.md`
- `meshcore_gui/static/leaflet_map_panel.js`
- `meshcore_gui/services/map_snapshot_service.py`
- `meshcore_gui/gui/panels/map_panel.py`
