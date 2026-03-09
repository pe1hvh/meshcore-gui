# Map Architecture — MeshCore GUI

## Overview

The MeshCore GUI map subsystem is implemented as a **browser-managed Leaflet runtime** embedded inside a NiceGUI container.

The key design decision is that the **map lifecycle is owned by the browser**, not by the Python UI update loop.

NiceGUI acts only as a container and data provider.

This architecture prevents map resets, marker flicker, and viewport jumps during the 500 ms dashboard refresh cycle.

---

# Architecture

```
NiceGUI Dashboard
      │
      │ snapshot (500 ms)
      ▼
MapPanel (Python)
      │
      │ JSON payload
      ▼
Leaflet Runtime (Browser)
      │
      ├─ Map instance (persistent)
      ├─ Marker registry
      ├─ Theme state
      └─ Viewport state
```

---

# Component Responsibilities

## MapPanel (Python)

Location:

```
meshcore_gui/gui/panels/map_panel.py
```

Responsibilities:

* provides the map container
* injects the Leaflet runtime assets
* sends compact map snapshots
* handles UI actions:

  * theme toggle
  * center on device

MapPanel **does NOT control the Leaflet map directly**.

It only sends data.

---

## MapSnapshotService

Location:

```
meshcore_gui/services/map_snapshot_service.py
```

Responsibilities:

* converts device/contact data into a compact JSON snapshot
* ensures stable node identifiers
* prepares payloads for the browser runtime

Example snapshot structure:

```json
{
  "device": {...},
  "contacts": [...],
  "force_center": false
}
```

Snapshots are emitted every **500 ms** by the dashboard update loop.

---

## Leaflet Runtime

Location:

```
meshcore_gui/static/leaflet_map_panel.js
```

Responsibilities:

* initialize the Leaflet map once
* maintain persistent map instance
* manage marker registry
* apply snapshots incrementally
* manage map theme and viewport state

Key design rules:

```
map is created once
markers updated incrementally
snapshots never recreate the map
```

---

# Update Flow

```
SharedData
    │
    ▼
Dashboard update loop (500 ms)
    │
    ▼
MapSnapshotService
    │
    ▼
MapPanel
    │
    ▼
Leaflet Runtime
```

Snapshots are **coalesced** so the browser applies only the newest payload.

---

# Theme Handling

Theme changes are handled via a **dedicated theme channel**.

Snapshots do **not** carry theme information.

Reason:

Embedding theme state in snapshots caused race conditions where queued snapshots overwrote explicit user selections.

Theme state is managed in the browser runtime and restored on reconnect.

---

# Marker Model

Markers are keyed by **stable node id**.

```
device marker
contact markers
```

Updates are applied incrementally:

```
add marker
update marker
remove marker
```

This prevents marker flicker during the refresh loop.

---

# Important Constraints

Developers must **not**:

* recreate the Leaflet map inside the dashboard refresh loop
* embed theme state in snapshots
* call Leaflet APIs directly from Python
* force viewport resets during normal snapshot updates

Violating these rules will reintroduce:

* disappearing maps
* marker flicker
* viewport resets
* theme resets

---

# Reconnect Behaviour

When the NiceGUI connection temporarily drops:

1. the Leaflet runtime persists in the browser
2. the map instance remains intact
3. theme and viewport state are restored
4. snapshot updates resume once the connection returns

---

# Future Extensions

Possible improvements without breaking the architecture:

* marker clustering
* heatmap layers
* route overlays
* tile provider switching

All extensions must remain **browser-managed**.

---

# Summary

The MeshCore map subsystem follows a strict separation:

```
Python → data
Browser → map lifecycle
```

This prevents UI refresh cycles from interfering with map state and ensures smooth rendering even with frequent dashboard updates.

