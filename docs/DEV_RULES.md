### Map developer rules

To avoid regressions in the map subsystem, follow these rules:

**Do**

- Keep the Leaflet map lifecycle **inside the browser runtime**
- Initialize Leaflet **exactly once per DOM container**
- Send **compact snapshots only** from Python
- Update markers **incrementally by node id**
- Keep theme handling in a **dedicated theme channel**
- Allow the browser runtime to maintain **viewport state**
- Define map/tile `maxZoom` **before** attaching clustering layers

**Do NOT**

- Recreate the map inside the 500 ms dashboard update loop
- Call `L.map(...)` from snapshot handlers, timers or retry loops
- Use `ui.leaflet()` or any NiceGUI map wrapper
- Embed theme state inside snapshot payloads
- Force map center/zoom during normal refresh cycles
- Call Leaflet APIs directly from Python
- Place the device marker inside the contact cluster layer

Breaking these rules will reintroduce:

- disappearing maps  
- marker flicker  
- viewport resets  
- theme resets
- cluster bootstrap failures
- `Map container is already initialized` errors
