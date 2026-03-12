# CHANGELOG

<!-- CHANGED: Title changed from "CHANGELOG: Message & Metadata Persistence" to "CHANGELOG" — 
     a root-level CHANGELOG.md should be project-wide, not feature-specific. -->

All notable changes to MeshCore GUI are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

---
## [1.13.2] - 2026-03-11 — Map Display Bugfix

### Fixed
- 🛠 **MAP panel blank when contacts list is empty at startup** — dashboard update loop
  had two separate conditional map-update blocks that both silently stopped firing after
  tick 1 when `data['contacts']` was empty. Map panel received no further snapshots and
  remained blank indefinitely.
- 🛠 **Leaflet map initialized on hidden (zero-size) container** — `processPending` in
  the browser runtime called `L.map()` on the host element while it was still
  `display:none` (Vue v-show, panel not yet visible). This produced a broken 0×0 map
  that never recovered because `ensureMap` returned the cached broken state on all
  subsequent calls. Fixed by adding a `clientWidth/clientHeight` guard in `ensureMap`:
  initialization is deferred until the host has real dimensions.
- 🛠 **Route map container had no height** — `route_page.py` used the Tailwind class
  `h-96` for the Leaflet host `<div>`. NiceGUI/Quasar does not include Tailwind CSS,
  so `h-96` had no effect and the container rendered at height 0. Leaflet initialized
  on a zero-height element and produced a blank map.
- 🛠 **Route map not rendered when no node has GPS coordinates** — `_render_map`
  returned early before creating the Leaflet container when `payload['nodes']` was
  empty. Fixed: container is always created; a notice label is shown instead.

### Changed
- 🔄 `meshcore_gui/static/leaflet_map_panel.js` — Added size guard in `ensureMap`:
  returns `null` when host has `clientWidth === 0 && clientHeight === 0` and no map
  state exists yet. `processPending` now explicitly reschedules itself until the panel
  becomes visible, instead of silently returning and leaving the map pending forever.
- 🔄 `meshcore_gui/gui/dashboard.py` — Consolidated two conditional map-update blocks
  into a single unconditional update while the MAP panel is active. Added `h-96` to the
  DOMCA CSS height overrides for consistency with the route page map container.
- 🔄 `meshcore_gui/gui/route_page.py` — Replaced `h-96` Tailwind class on the route
  map host `<div>` with an explicit inline `style` (height: 24rem). Removed early
  `return` guard so the Leaflet container is always created.

### Impact
- MAP panel now renders reliably on first open regardless of contact/GPS availability
- Route map now always shows with correct height even when route nodes have no GPS
- No breaking changes outside the three files listed above

---
## [1.13.1] - 2026-03-09 — Message Icon Consistency

### Fixed
- Route map markers now use the same JS-rendered node icons as the main MAP instead of NiceGUI default blue markers.
- Route detail pages now bootstrap their Leaflet assets explicitly so the shared map icon runtime is available there too
- Route maps are now rendered browser-side through the shared Leaflet JS runtime for icon consistency with MAP, Messages, and Archive.

### Changed
- 🔄 `meshcore_gui/gui/constants.py` — Added shared helper functions to resolve node-type icons and labels from the same contact type mapping used by the map and contacts panel
- 🔄 `meshcore_gui/core/models.py` — `Message.format_line()` now supports an optional sender prefix so message-related views can prepend the same node icon set without changing existing formatting logic
- 🔄 `meshcore_gui/gui/panels/messages_panel.py` — Message rows now prepend the sender with the same node icon mapping as the map/contact views
- 🔄 `meshcore_gui/gui/archive_page.py` — Archive rows now use the same sender icon mapping as the live messages panel and map/contact views
- 🔄 `meshcore_gui/gui/route_page.py` — Route header and route detail table now show node-type icons derived from the shared contact type mapping instead of generic hardcoded role icons

### Impact
- Message-driven views now use one consistent icon language across map, contacts, messages, archive and route detail
- Existing map runtime and panel behavior remain unchanged
- No breaking changes outside icon rendering

## [1.13.0] - 2026-03-09 — Leaflet Map Runtime Stabilization

### Added
- ✅ `meshcore_gui/static/leaflet_map_panel.js` — Dedicated browser-side Leaflet runtime responsible for map lifecycle, marker registry and theme handling independent from NiceGUI redraw cycles
- ✅ `meshcore_gui/static/leaflet_map_panel.css` — Styling for browser-side node markers and map container
- ✅ `meshcore_gui/services/map_snapshot_service.py` — Snapshot service that normalizes device/contact map data into a compact payload for the browser runtime
- ✅ Browser-side map state management for center, zoom and theme
- ✅ Theme persistence across reconnect events via browser storage fallback

### Changed
- 🔄 `meshcore_gui/gui/panels/map_panel.py` — Replaced NiceGUI Leaflet wrapper usage with a pure browser-managed Leaflet container while preserving the existing card layout, theme toggle and center-on-device control
- 🔄 Leaflet bootstrap moved out of inline Python into a dedicated browser runtime loaded from `/static`
- 🔄 Map initialization now occurs only once per container; NiceGUI refresh cycles no longer recreate the map
- 🔄 Dashboard update loop now sends compact map snapshots instead of triggering redraws
- 🔄 Snapshot processing in the browser is coalesced so only the newest payload is applied
- 🔄 Map markers are managed in separate device/contact layers and updated incrementally by stable node id
- 🔄 Theme switching moved to a dedicated theme channel instead of being embedded in snapshot data

### Fixed
- 🛠 **Map disappearing during dashboard refresh cycles** — prevented repeated map reinitialization caused by the 500 ms NiceGUI update loop
- 🛠 **Markers disappearing between refreshes** — marker updates are now incremental and keyed by node id
- 🛠 **Blank map container on load** — browser bootstrap now waits for DOM host, Leaflet runtime and panel runtime before initialization
- 🛠 **Race condition between queued snapshot and theme selection** — explicit theme changes can no longer be overwritten by stale snapshot payloads
- 🛠 **Viewport jumping back to default center/zoom** — stored viewport is no longer reapplied on each snapshot update
- 🛠 **Theme reverting to default during reconnect** — effective map theme is restored before snapshot processing resumes

### Impact
- Leaflet map is now managed entirely in the browser and is no longer recreated on each dashboard refresh
- Node markers remain stable and no longer flicker or disappear during the 500 ms update cycle
- Theme switching and viewport state persist reliably across reconnect events
- No breaking changes outside the map subsystem
---
## [1.12.1] - 2026-03-08 — Minor change bot
### Changed
- 🔄 `meshcore_gui/services/bot.py`: remove path id's
### Impact
- No breaking changes — all existing functionality preserved serial.

---

## [1.12.0] - 2026-02-26 — MeshCore Observer Fase 1

### Added
- ✅ **MeshCore Observer daemon** — New standalone read-only daemon (`meshcore_observer.py`) that reads archive JSON files produced by meshcore_gui and meshcore_bridge, aggregates them, and presents a unified NiceGUI monitoring dashboard on port 9093.
- ✅ **ArchiveWatcher** — Core component that polls `~/.meshcore-gui/archive/` for `*_messages.json` and `*_rxlog.json` files, tracks mtime changes, and returns only new entries since previous poll. Thread-safe, zero writes, graceful on corrupt JSON.
- ✅ **Observer dashboard panels** — Sources overview, aggregated messages feed (sorted by timestamp), aggregated RX log table, and statistics panel with uptime/counters/per-source breakdown. Full DOMCA theme (dark + light mode).
- ✅ **Source filter** — Dropdown to filter messages and RX log by archive source.
- ✅ **Channel filter** — Dropdown to filter messages by channel name.
- ✅ **ObserverConfig** — YAML-based configuration with `from_yaml()` classmethod, defaults work without config file.
- ✅ **observer_config.yaml** — Documented config template with all options.
- ✅ **install_observer.sh** — systemd installer (`/opt/meshcore-observer/`, `/etc/meshcore/observer_config.yaml`), with `--uninstall` option.
- ✅ **RxLogEntry raw packet fields** — 5 new fields on `RxLogEntry` dataclass: `raw_payload`, `packet_len`, `payload_len`, `route_type`, `packet_type_num` (all with defaults, backward compatible).
- ✅ **EventHandler.on_rx_log() metadata** — Raw payload hex and packet metadata now passed through to RxLogEntry and archived (preparation for Fase 2 LetsMesh uplink).

### Changed
- 🔄 `meshcore_gui/core/models.py`: RxLogEntry +5 fields with defaults (backward compatible).
- 🔄 `meshcore_gui/ble/events.py`: on_rx_log() fills raw_payload and metadata (~10 lines added).
- 🔄 `meshcore_gui/services/message_archive.py`: add_rx_log() serializes the 5 new RxLogEntry fields.
- 🔄 `meshcore_gui/config.py`: Version bumped to `1.12.0`.

### Impact
- **No breaking changes** — All new RxLogEntry fields have defaults; existing archives and code work identically.
- **New daemon** — meshcore_observer is fully standalone; no imports from meshcore_gui (reads only JSON files).

---

### Added
- ✅ **Serial CLI flags** — `--baud=BAUD` and `--serial-cx-dly=SECONDS` for serial configuration at startup.

### Changed
- 🔄 **Connection layer** — Switched from BLE to serial (`MeshCore.create_serial`) with serial reconnect handling.
- 🔄 `config.py`: Added `SERIAL_BAUDRATE`, `SERIAL_CX_DELAY`, `DEFAULT_TIMEOUT`, `MESHCORE_LIB_DEBUG`; removed BLE PIN settings; version bumped to `1.10.0`.
- 🔄 `meshcore_gui.py` / `meshcore_gui/__main__.py`: Updated usage, banners and defaults for serial ports.
- 🔄 Docs: Updated README and core docs for serial usage; BLE documents marked as legacy.

### Impact
- No breaking changes — all existing functionality preserved serial.

---

## [1.9.11] - 2026-02-19 — Message Dedup Hotfix

### Fixed
- 🛠 **Duplicate messages after (re)connect** — `load_recent_from_archive()` appended archived messages on every connect attempt without clearing existing entries; after N failed connects, each message appeared N times. Method is now idempotent: clears the in-memory list before loading.
- 🛠 **Persistent duplicate messages** — Live BLE events for messages already loaded from archive were not suppressed because the `DualDeduplicator` was never seeded with archived content. Added `_seed_dedup_from_messages()` in `BLEWorker` after cache/archive load and after reconnect.
- 🛠 **Last-line-of-defence dedup in SharedData** — `add_message()` now maintains a fingerprint set (`message_hash` or `channel:sender:text`) and silently skips messages whose fingerprint is already tracked. This guards against duplicates regardless of their source.
- 🛠 **Messages panel empty on first click** — `_show_panel()` made the container visible but relied on the next 500 ms timer tick to populate it. Added an immediate `_messages.update()` call so content is rendered the moment the panel becomes visible.

### Changed
- 🔄 `core/shared_data.py`: Added `_message_fingerprints` set and `_message_fingerprint()` static method; `add_message()` checks fingerprint before insert and evicts fingerprints when messages are rotated out; `load_recent_from_archive()` clears messages and fingerprints before loading (idempotent)
- 🔄 `ble/worker.py`: Added `_seed_dedup_from_messages()` helper; called after `_apply_cache()` and after reconnect `_load_data()` to seed `DualDeduplicator` with existing messages
- 🔄 `gui/dashboard.py`: `_show_panel()` now forces an immediate `_messages.update()` when the messages panel is shown, eliminating the stale-content flash
- 🔄 `config.py`: Version bumped to `1.9.11`

### Impact
- Eliminates all duplicate message display scenarios: initial connect, failed retries, reconnect, and BLE event replay
- No breaking changes — all existing functionality preserved
- Fingerprint set is bounded to the same 100-message cap as the message list

---

## [1.9.10] - 2026-02-19 — Map Tooltips & Separate Own-Position Marker

### Added
- ✅ **Map marker tooltips** — All markers on the Leaflet map now show a tooltip on hover with the node name and type icon (📱, 📡, 🏠) from `TYPE_ICONS`
- ✅ **Separate own-position marker** — The device's own position is now tracked as a dedicated `_own_marker`, independent from contact markers. This prevents the own marker from being removed/recreated on every contact update cycle

### Changed
- 🔄 `gui/panels/map_panel.py`: Renamed `_markers` to `_contacts_markers`; added `_own_marker` attribute; own position marker is only updated when `device_updated` flag is set (not every timer tick); contact markers are only rebuilt when `contacts_updated` is set; added `TYPE_ICONS` import for tooltip icons
- 🔄 `gui/dashboard.py`: Added `self._map.update(data)` call in the `device_updated` block so the own-position marker updates when device info changes (e.g. GPS position update)
- 🔄 `config.py`: Version bumped to `1.9.10`

### Impact
- Map centering on own device now works correctly and updates only when position actually changes
- Contact markers are no longer needlessly destroyed and recreated on every UI timer tick — only on actual contact data changes
- Tooltips make it easy to identify nodes on the map without clicking
- No breaking changes — all existing map functionality preserved

### Credits
- Based on [PR #16](https://github.com/pe1hvh/meshcore-gui/pull/16) by [@rich257](https://github.com/rich257)

---

## [1.9.9] - 2026-02-18 — Variable Landing Page & Operator Callsign

### Added
- ✅ **Configurable operator callsign** — New `OPERATOR_CALLSIGN` constant in `config.py` (default: `"PE1HVH"`). Used in the landing page SVG and the drawer footer copyright label. Change this single value to personalize the entire GUI for a different operator
- ✅ **External landing page SVG** — The DOMCA splash screen is now loaded from a standalone file (`static/landing_default.svg`) instead of being hardcoded in `dashboard.py`. New `LANDING_SVG_PATH` constant in `config.py` points to the SVG file. The placeholder `{callsign}` in the SVG is replaced at runtime with `OPERATOR_CALLSIGN`
- ✅ **Landing page customization** — To use a custom landing page: copy `landing_default.svg` (or create your own SVG), use `{callsign}` wherever the operator callsign should appear, and point `LANDING_SVG_PATH` to your file. The default SVG includes an instructive comment block explaining the placeholder mechanism

### Changed
- 🔄 `config.py`: Added `OPERATOR_CALLSIGN` and `LANDING_SVG_PATH` constants in new **OPERATOR / LANDING PAGE** section; version bumped to `1.9.9`
- 🔄 `gui/dashboard.py`: Removed hardcoded `_DOMCA_SVG` string (~70 lines); added `_load_landing_svg()` helper that reads SVG from disk and replaces `{callsign}` placeholder; CSS variable `--pe1hvh` renamed to `--callsign`; drawer footer copyright label now uses `config.OPERATOR_CALLSIGN`

### Added (files)
- ✅ `static/landing_default.svg` — The original DOMCA splash SVG extracted as a standalone file, with `{callsign}` placeholder and `--callsign` CSS variable. Serves as both the default landing page and a reference template for custom SVGs

### Impact
- Out-of-the-box behavior is identical to v1.9.8 (same DOMCA branding, same PE1HVH callsign)
- Operators personalize by changing 1–2 lines in `config.py` — no code modifications needed
- Fallback: if the SVG file is missing, a minimal placeholder text is shown instead of a crash
- No breaking changes — all existing dashboard functionality (panels, menus, timer, theming) unchanged

---

## [1.9.8] - 2026-02-17 — Bugfix: Route Page Sender ID, Type & Location Not Populated

### Fixed
- 🛠 **Sender ID, Type and Location empty in Route Page** — After the v4.1 refactoring to `RouteBuilder`/`RouteNode`, the sender contact lookup relied solely on `SharedData.get_contact_by_prefix()` (live lock-based) and `get_contact_by_name()`. When both failed (e.g. empty `sender_pubkey` from RX_LOG decode, or name mismatch), `route['sender']` remained `None` and the route table fell through to a hardcoded fallback with `type: '-'`, `location: '-'`. The contact data was available in the snapshot `data['contacts']` but was never searched
- 🛠 **Route table fallback row ignored available contact data** — When `route['sender']` was `None`, the `_render_route_table` method used a static fallback row without attempting to find the contact in the data snapshot. Even when the contact was present in `data['contacts']` with valid type and location, these fields showed as `'-'`

### Changed
- 🔄 `services/route_builder.py`: Added two additional fallback strategies in `build()` after the existing SharedData lookups: (3) bidirectional pubkey prefix match against `data['contacts']` snapshot, (4) case-insensitive `adv_name` match against `data['contacts']` snapshot. Added helper methods `_find_contact_by_pubkey()` and `_find_contact_by_adv_name()` for snapshot-based lookups
- 🔄 `gui/route_page.py`: Added defensive fallback in `_render_route_table()` sender section — when `route['sender']` is `None`, attempts to find the contact in the snapshot via `_find_sender_contact()` before falling back to the static `'-'` row. Added `_find_sender_contact()` helper method

### Impact
- Sender ID (hash), Type and Location are now populated correctly in the route table when the contact is known
- Four-layer lookup chain ensures maximum resolution: (1) SharedData pubkey lookup, (2) SharedData name lookup, (3) snapshot pubkey lookup, (4) snapshot name lookup
- Defensive fallback in route_page guarantees data is shown even if RouteBuilder misses it
- No breaking changes — all existing route page behavior, styling and data flows unchanged

---

## [1.9.7] - 2026-02-17 — Layout Fix: Archive Filter Toggle & Route Page Styling

### Changed
- 🔄 `gui/archive_page.py`: Archive filter card now hidden by default; toggle visibility via a `filter_list` icon button placed right-aligned on the same row as the "📚 Archive" title. Header restructured from single label to `ui.row()` with `justify-between` layout
- 🔄 `gui/route_page.py`: Route page now uses DOMCA theme (imported from `dashboard.py`) with dark mode as default, consistent with the main dashboard. Header restyled from `bg-blue-600` to Quasar-themed header with JetBrains Mono font. Content container changed from `w-full max-w-4xl mx-auto` to `domca-panel` class for consistent responsive sizing
- 🔄 `gui/dashboard.py`: Added `domca-header-text` CSS class with `@media (max-width: 599px)` rule to hide header text on narrow viewports; applied to version label and status label
- 🔄 `gui/route_page.py`: Header label also uses `domca-header-text` class for consistent responsive behaviour

### Added
- ✅ **Archive filter toggle** — `filter_list` icon button in archive header row toggles the filter card visibility on click
- ✅ **Route page close button** — `X` (close) icon button added right-aligned in the route page header; calls `window.close()` to close the browser tab
- ✅ **Responsive header** — On viewports < 600px, header text labels are hidden; only icon buttons (menu, dark mode toggle, close) remain visible

### Impact
- Archive page is cleaner by default — filters only shown when needed
- Route page visually consistent with the main dashboard (DOMCA theme, dark mode, responsive panel width)
- Headers degrade gracefully on mobile (< 600px): only icon buttons visible, no text overflow
- No functional changes — all event handlers, callbacks, data bindings, logic and imports are identical to the input

---

## [1.9.6] - 2026-02-17 — Bugfix: Channel Discovery Reliability

### Fixed
- 🛠 **Channels not appearing (especially on mobile)** — Channel discovery aborted too early on slow BLE connections. The `_discover_channels()` probe used a single attempt per channel slot and stopped after just 2 consecutive empty responses. On mobile BLE stacks (WebBluetooth via NiceGUI) where GATT responses are slower, this caused discovery to abort before finding any channels, falling back to only `[0] Public`
- 🛠 **Race condition: channel update flag lost between threads** — `get_snapshot()` and `clear_update_flags()` were two separate calls, each acquiring the lock independently. If the BLE worker set `channels_updated = True` between these two calls, the GUI consumed the flag via `get_snapshot()` but then `clear_update_flags()` reset it — causing the channel submenu and dropdown to never populate
- 🛠 **Channels disappear on browser reconnect** — When a browser tab is closed and reopened, `render()` creates new (empty) NiceGUI containers for the drawer submenus, but did not reset `_last_channel_fingerprint`. The `_update_submenus()` method compared the new fingerprint against the stale one, found them equal, and skipped the rebuild — leaving the new containers permanently empty. Fixed by resetting both `_last_channel_fingerprint` and `_last_rooms_fingerprint` in `render()`

### Changed
- 🔄 `core/shared_data.py`: New atomic method `get_snapshot_and_clear_flags()` that reads the snapshot and resets all update flags in a single lock acquisition. Internally refactored to `_build_snapshot_unlocked()` helper. Existing `get_snapshot()` and `clear_update_flags()` retained for backward compatibility
- 🔄 `ble/worker.py`: `_discover_channels()` — `max_attempts` increased from 1 to 2 per channel slot; inter-attempt `delay` increased from 0.5s to 1.0s; consecutive error threshold raised from 2 to 3; inter-channel pause increased from 0.15s to 0.3s for mobile BLE stack breathing room
- 🔄 `gui/dashboard.py`: `_update_ui()` now uses `get_snapshot_and_clear_flags()` instead of separate `get_snapshot()` + `clear_update_flags()`; `render()` now resets `_last_channel_fingerprint` and `_last_rooms_fingerprint` to `None` so that `_update_submenus()` rebuilds into the freshly created containers; channel-dependent updates (`update_filters`, `update_channel_options`, `_update_submenus`) now run unconditionally when channel data exists — safe because each method has internal idempotency checks
- 🔄 `gui/panels/messages_panel.py`: `update_channel_options()` now includes an equality check on options dict to skip redundant `.update()` calls to the NiceGUI client on every 500ms timer tick

### Impact
- Channel discovery now survives transient BLE timeouts that are common on mobile connections
- Atomic snapshot eliminates the threading race condition that caused channels to silently never appear
- Browser close+reopen no longer loses channels — the single-instance timer race on the shared `DashboardPage` is fully mitigated
- No breaking changes — all existing API methods retained, all other functionality unchanged

---

## [1.9.5] - 2026-02-16 — Layout Fix: RX Log Table Responsive Sizing

### Fixed
- 🛠 **RX Log table did not adapt to panel/card size** — The table used `max-h-48` (a maximum height cap) instead of a responsive fixed height, causing it to remain small regardless of available space. Changed to `h-40` which is overridden by the existing dashboard CSS to `calc(100vh - 20rem)` — the same responsive pattern used by the Messages panel
- 🛠 **RX Log table did not fill card width** — Added `w-full` class to the table element so it stretches to the full width of the parent card
- 🛠 **RX Log card did not fill panel height** — Added `flex-grow` class to the card container so it expands to fill the available panel space

### Changed
- 🔄 `gui/panels/rxlog_panel.py`: Card classes `'w-full'` → `'w-full flex-grow'` (line 45); table classes `'text-xs max-h-48 overflow-y-auto'` → `'w-full text-xs h-40 overflow-y-auto'` (line 65)

### Impact
- RX Log table now fills the panel consistently on both desktop and mobile viewports
- Layout is consistent with other panels (Messages, Contacts) that use the same `h-40` responsive height pattern
- No functional changes — all event handlers, callbacks, data bindings, logica and imports are identical to the input

---

## [1.9.4] - 2026-02-16 — BLE Address Log Prefix & Entry Point Cleanup

### Added
- ✅ **BLE address prefix in log filename** — Log file is now named `<BLE_ADDRESS>_meshcore_gui.log` (e.g. `AA_BB_CC_DD_EE_FF_meshcore_gui.log`) instead of the generic `meshcore_gui.log`. Makes it easy to identify which device produced which log file when running multiple instances
  - New helper `_sanitize_ble_address()` strips `literal:` prefix and replaces colons with underscores
  - New function `configure_log_file(ble_address)` updates `LOG_FILE` at runtime before the logger is initialised
  - Rotated backups follow the same naming pattern automatically

### Removed
- ❌ **`meshcore_gui/meshcore_gui.py`** — Redundant copy of `main()` that was never imported. All three entry points (`meshcore_gui.py` root, `__main__.py`, and `meshcore_gui/meshcore_gui.py`) contained near-identical copies of the same logic, causing changes to be missed (as demonstrated by this fix). `__main__.py` is now the single source of truth; root `meshcore_gui.py` is a thin wrapper that imports from it

### Changed
- 🔄 `config.py`: Added `_sanitize_ble_address()` and `configure_log_file()`; version bumped to `1.9.4`
- 🔄 `__main__.py`: Added `config.configure_log_file(ble_address)` call before any debug output
- 🔄 `meshcore_gui.py` (root): Reduced to 4-line wrapper importing `main` from `__main__`

### Impact
- Log files are now identifiable per BLE device
- Single source of truth for `main()` eliminates future sync issues between entry points
- Both startup methods (`python meshcore_gui.py` and `python -m meshcore_gui`) remain functional
- No breaking changes — defaults and all existing behaviour unchanged
---

## [1.9.3] - 2026-02-16 — Bugfix: Map Default Location & Payload Type Decoding

### Fixed
- 🛠 **Map centred on hardcoded Zwolle instead of device location** — All Leaflet maps used magic-number coordinates `(52.5, 6.0)` as initial centre and fallback. These are now replaced by a single configurable constant `DEFAULT_MAP_CENTER` in `config.py`. Once the device reports a valid `adv_lat`/`adv_lon`, maps re-centre on the actual device position (existing behaviour, unchanged)
- 🛠 **Payload type shown as raw integer** — Payload type is now retrieved from the decoded payload and translated to human-readable text using MeshCoreDecoder functions, instead of displaying the raw numeric type value

### Changed
- 🔄 `config.py`: Added `DEFAULT_MAP_CENTER` (default: `(52.5168, 6.0830)`) and `DEFAULT_MAP_ZOOM` (default: `9`) constants in new **MAP DEFAULTS** section. Version bumped to `1.9.2`
- 🔄 `gui/panels/map_panel.py`: Imports `DEFAULT_MAP_CENTER` and `DEFAULT_MAP_ZOOM` from config; `ui.leaflet(center=...)` uses config constants instead of hardcoded values
- 🔄 `gui/route_page.py`: Imports `DEFAULT_MAP_CENTER` and `DEFAULT_MAP_ZOOM` from config; fallback coordinates (`or 52.5` / `or 6.0`) replaced by `DEFAULT_MAP_CENTER[0]` / `[1]`; zoom uses `DEFAULT_MAP_ZOOM`

### Impact
- Map default location is now a single-point-of-change in `config.py`
- Payload type is displayed as readable text instead of a raw number
- No breaking changes — all existing map behaviour (re-centre on device position, contact markers) unchanged

## [1.9.2] - 2026-02-15 — CLI Parameters & Cleanup

### Added
- ✅ **`--port=PORT` CLI parameter** — Web server port is now configurable at startup (default: `8081`). Allows running multiple instances simultaneously on different ports
- ✅ **`--ble-pin=PIN` CLI parameter** — BLE pairing PIN is now configurable at startup (default: `123456`). Eliminates the need to edit `config.py` for devices with a non-default PIN, and works in systemd service files
- ✅ **Per-device log file** — Debug log file now includes the BLE address in its filename (e.g. `F0_9E_9E_75_A3_01_meshcore_gui.log`), so multiple instances log to separate files

### Fixed
- 🛠 **BLE PIN not applied from CLI** — `ble/worker.py` imported `BLE_PIN` as a constant at module load time (`from config import BLE_PIN`), capturing the default value `"123456"` before CLI parsing could override `config.BLE_PIN`. Changed to runtime access via `config.BLE_PIN` so the `--ble-pin` parameter is correctly passed to the BLE agent

### Removed
- ❌ **Redundant `meshcore_gui/meshcore_gui.py`** — This file was a near-identical copy of both `meshcore_gui.py` (top-level) and `meshcore_gui/__main__.py`, but was never imported or referenced. Removed to eliminate maintenance risk. The two remaining entry points cover all startup methods: `python meshcore_gui.py` and `python -m meshcore_gui`

### Impact
- Multiple instances can run side-by-side with different ports, PINs and log files
- Service deployments no longer require editing `config.py` — all runtime settings via CLI
- No breaking changes — all defaults are unchanged

---

## [1.9.1] - 2026-02-14 — Bugfix: Dual Reconnect Conflict

### Fixed
- 🛠 **Library reconnect interfered with application reconnect** — The meshcore library's internal `auto_reconnect` (visible in logs as `"Attempting reconnection 1/3"`) ran a fast 3-attempt reconnect cycle without bond cleanup. This prevented the application's own `reconnect_loop` (which does `remove_bond()` + backoff) from succeeding, because BlueZ retained a stale bond → `"failed to discover service"`

### Changed
- 🔄 `ble/worker.py`: Set `auto_reconnect=False` in both `MeshCore.create_ble()` call sites (`_connect()` and `_create_fresh_connection()`), so only the application's bond-aware `reconnect_loop` handles reconnection
- 🔄 `ble/worker.py`: Added `"failed to discover"` and `"service discovery"` to disconnect detection keywords for defensive coverage

### Impact
- Eliminates the ~9 second wasted library reconnect cycle after every BLE disconnect
- Application's `reconnect_loop` (with bond cleanup) now runs immediately after disconnect detection
- No breaking changes — the application reconnect logic was already fully functional

---

## [1.9.0] - 2026-02-14 — BLE Connection Stability

### Added
- ✅ **Built-in BLE PIN agent** — New `ble/ble_agent.py` registers a D-Bus agent with BlueZ to handle PIN pairing requests automatically. Eliminates the need for external `bt-agent.service` and `bluez-tools` package
  - Uses `dbus_fast` (already a dependency of `bleak`, no new packages)
  - Supports `RequestPinCode`, `RequestPasskey`, `DisplayPasskey`, `RequestConfirmation`, `AuthorizeService` callbacks
  - Configurable PIN via `BLE_PIN` in `config.py` (default: `123456`)
- ✅ **Automatic bond cleanup** — New `ble/ble_reconnect.py` provides `remove_bond()` function that removes stale BLE bonds via D-Bus, equivalent to `bluetoothctl remove <address>`. Called automatically on startup and before each reconnect attempt
- ✅ **Automatic reconnect after disconnect** — BLEWorker main loop now detects BLE disconnects (via connection error exceptions) and automatically triggers a reconnect sequence: bond removal → linear backoff wait → fresh connection → re-wire handlers → reload device data
  - Configurable via `RECONNECT_MAX_RETRIES` (default: 5) and `RECONNECT_BASE_DELAY` (default: 5.0s)
  - After all retries exhausted: waits 60s then starts a new retry cycle (infinite recovery)
- ✅ **Generic install script** — `install_ble_stable.sh` auto-detects user, project directory, venv path and entry point to generate systemd service and D-Bus policy. Supports `--uninstall` flag

### Changed
- 🔄 **`ble/worker.py`** — `_async_main()` rewritten with three phases: (1) start PIN agent, (2) remove stale bond, (3) connect + main loop with disconnect detection. Reconnect logic re-wires all event handlers and reloads device data after successful reconnection
- 🔄 **`config.py`** — Added `BLE_PIN`, `RECONNECT_MAX_RETRIES`, `RECONNECT_BASE_DELAY` constants

### Removed
- ❌ **`bt-agent.service` dependency** — No longer needed; PIN pairing is handled by the built-in agent
- ❌ **`bluez-tools` system package** — No longer needed
- ❌ **`~/.meshcore-ble-pin` file** — No longer needed
- ❌ **Manual `bluetoothctl remove` before startup** — Handled automatically
- ❌ **`ExecStartPre` in systemd service** — Bond cleanup is internal

### Impact
- Zero external dependencies for BLE pairing on Linux
- Automatic recovery from the T1000e ~2 hour BLE disconnect issue
- No manual intervention needed after BLE connection loss
- Single systemd service (`meshcore-gui.service`) manages everything
- No breaking changes to existing functionality

---

## [1.8.0] - 2026-02-14 — DRY Message Construction & Archive Layout Unification

### Fixed
- 🛠 **Case-sensitive prefix matching** — `get_contact_name_by_prefix()` and `get_contact_by_prefix()` in `shared_data.py` failed to match path hashes (uppercase, e.g. `'B8'`) against contact pubkeys (lowercase, e.g. `'b8a3f2...'`). Added `.lower()` to both sides of the comparison, consistent with `_resolve_path_names()` which already had it
- 🛠 **Route page 404 from archive** — Archive page linked to `/route/{hash}` but route was registered as `/route/{msg_index:int}`, causing a JSON parse error for hex hash strings. Route parameter changed to `str` with 3-strategy lookup (index → memory hash → archive fallback)
- 🛠 **Three entry points out of sync** — `meshcore_gui.py` (root), `meshcore_gui/meshcore_gui.py` (inner) and `meshcore_gui/__main__.py` had diverging route registrations. All three now use identical `/route/{msg_key}` with `str` parameter

### Changed
- 🔄 **`core/models.py` — DRY factory methods and formatting**
  - `Message.now_timestamp()`: static method replacing 7× hardcoded `datetime.now().strftime('%H:%M:%S')` across `events.py` and `commands.py`
  - `Message.incoming()`: classmethod factory for received messages (`direction='in'`, auto-timestamp)
  - `Message.outgoing()`: classmethod factory for sent messages (`sender='Me'`, `direction='out'`, auto-timestamp)
  - `Message.format_line(channel_names)`: single-line display formatting (`"12:34:56 ← [Public] [2h✓] PE1ABC: Hello mesh!"`), replacing duplicate inline formatting in `messages_panel.py` and `archive_page.py`
- 🔄 **`ble/events.py`** — 4× `Message(...)` constructors replaced by `Message.incoming()`; `datetime` import removed
- 🔄 **`ble/commands.py`** — 3× `Message(...)` constructors replaced by `Message.outgoing()`; `datetime` import removed
- 🔄 **`gui/panels/messages_panel.py`** — 15 lines inline formatting replaced by single `msg.format_line(channel_names)` call
- 🔄 **`gui/archive_page.py` — Layout unified with main page**
  - Multi-row card layout replaced by single-line `msg.format_line()` in monospace container (same style as main page)
  - DM added to channel filter dropdown (post-filter on `channel is None`)
  - Message click opens `/route/{message_hash}` in new tab (was: no click handler on archive messages)
  - Removed `_render_message_card()` (98 lines) and `_render_archive_route()` (75 lines)
  - Removed `RouteBuilder` dependency and `TYPE_LABELS` import
  - File reduced from 445 to 267 lines
- 🔄 **`gui/route_page.py`** — `render(msg_index: int)` → `render(msg_key: str)` with 3-strategy message lookup: (1) numeric index from in-memory list, (2) hash match in memory, (3) `archive.get_message_by_hash()` fallback
- 🔄 **`services/message_archive.py`** — New method `get_message_by_hash(hash)` for single-message lookup by packet hash
- 🔄 **`__main__.py` + `meshcore_gui.py` (both)** — Route changed from `/route/{msg_index}` (int) to `/route/{msg_key}` (str)

### Impact
- DRY: timestamp formatting 7→1 definition, message construction 7→2 factories, line formatting 2→1 method
- Archive page visually consistent with main messages panel (single-line, monospace)
- Archive messages now clickable to open route visualization (was: only in-memory messages)
- Case-insensitive prefix matching fixes path name resolution for contacts with uppercase path hashes
- No breaking changes to BLE protocol handling, dedup, bot, or data storage

### Known Limitations
- DM filter in archive uses post-filtering (query without channel filter + filter on `channel is None`); becomes exact when `query_messages()` gets native DM support

### Parked for later
- Multi-path tracking (enrich RxLogEntry with multiple path observations)
- Events correlation improvements (only if proven data loss after `.lower()` fix)

---

## [1.7.0] - 2026-02-13 — Archive Channel Name Persistence

### Added
- ✅ **Channel name stored in archive** — Messages now persist `channel_name` alongside the numeric `channel` index in `<ADDRESS>_messages.json`, so archived messages retain their human-readable channel name even when the device is not connected
  - `Message` dataclass: new field `channel_name: str` (default `""`, backward compatible)
  - `SharedData.add_message()`: automatically resolves `channel_name` from the live channels list when not already set (new helper `_resolve_channel_name()`)
  - `MessageArchive.add_message()`: writes `channel_name` to the JSON dict
- ✅ **Archive channel selector built from archived data** — Channel filter dropdown on `/archive` now populated via `SELECT DISTINCT channel_name` on the archive instead of the live BLE channels list
  - New method `MessageArchive.get_distinct_channel_names()` returns sorted unique channel names from stored messages
  - Selector shows only channels that actually have archived messages
- ✅ **Archive filter on channel name** — `MessageArchive.query_messages()` parameter changed from `channel: Optional[int]` to `channel_name: Optional[str]` (exact match on name string)

### Changed
- 🔄 `core/models.py`: Added `channel_name` field to `Message` dataclass and `from_dict()`
- 🔄 `core/shared_data.py`: `add_message()` resolves channel name; added `_resolve_channel_name()` helper
- 🔄 `services/message_archive.py`: `channel_name` persisted in JSON; `query_messages()` filters by name; new `get_distinct_channel_names()` method
- 🔄 `gui/archive_page.py`: Channel selector built from `archive.get_distinct_channel_names()`; filter state changed from `_channel_filter` (int) to `_channel_name_filter` (str); message cards show `channel_name` directly from archive

### Fixed
- 🛠 **Main page empty after startup** — After a restart the messages panel showed no messages until new live BLE traffic arrived. `SharedData.load_recent_from_archive()` now loads up to 100 recent archived messages during the cache-first startup phase, so historical messages are immediately visible
  - New method `SharedData.load_recent_from_archive(limit)` — reads from `MessageArchive.query_messages()` and populates the in-memory list without re-archiving
  - `BLEWorker._apply_cache()` calls `load_recent_from_archive()` at the end of cache loading

### Impact
- Archived messages now self-contained — channel name visible without live BLE connection
- Main page immediately shows historical messages after startup (no waiting for live BLE traffic)
- Backward compatible — old archive entries without `channel_name` fall back to `"Ch <idx>"`
- No breaking changes to existing functionality

---

## [1.6.0] - 2026-02-13 — Dashboard Layout Consolidation

### Changed
- 🔄 **Messages panel consolidated** — Filter checkboxes (DM + channels) and message input (text field, channel selector, Send button) are now integrated into the Messages panel, replacing the separate Filter and Input panels
  - DM + channel checkboxes displayed centered in the Messages header row, between the "💬 Messages" label and the "📚 Archive" button
  - Message input row (text field, channel selector, Send button) placed below the message list within the same card
  - `messages_panel.py`: Constructor now accepts `put_command` callable; added `update_filters(data)`, `update_channel_options(channels)` methods and `channel_filters`, `last_channels` properties (all logic 1:1 from FilterPanel/InputPanel); `update()` signature unchanged
- 🔄 **Actions panel expanded** — BOT toggle checkbox moved from Filter panel to Actions panel, below the Refresh/Advert buttons
  - `actions_panel.py`: Constructor now accepts `set_bot_enabled` callable; added `update(data)` method for BOT state sync; `_on_bot_toggle()` logic 1:1 from FilterPanel
- 🔄 **Dashboard layout simplified** — Centre column reduced from 4 panels (Map → Input → Filter → Messages) to 2 panels (Map → Messages)
  - `dashboard.py`: FilterPanel and InputPanel no longer rendered; all dependencies rerouted to MessagesPanel and ActionsPanel; `_update_ui()` call-sites updated accordingly

### Removed (from layout, files retained)
- ❌ **Filter panel** no longer rendered as separate panel — `filter_panel.py` retained in codebase but not instantiated in dashboard
- ❌ **Input panel** no longer rendered as separate panel — `input_panel.py` retained in codebase but not instantiated in dashboard

### Impact
- Cleaner, more compact dashboard: 2 fewer panels in the centre column
- All functionality preserved — message filtering, send, BOT toggle, archive all work identically
- No breaking changes to BLE, services, core or other panels

---

<!-- ADDED: v1.5.0 feature + bugfix entry -->

## [1.5.0] - 2026-02-11 — Room Server Support, Dynamic Channel Discovery & Contact Management

### Added
- ✅ **Room Server panel** — Dedicated per-room-server message panel in the centre column below Messages. Each Room Server (type=3 contact) gets its own `ui.card()` with login/logout controls and message display
  - Click a Room Server contact to open an add/login dialog with password field
  - After login: messages are displayed in the room card; send messages directly from the room panel
  - Password row + login button automatically replaced by Logout button after successful login
  - Room Server author attribution via `signature` field (txt_type=2) — real message author is resolved from the 4-byte pubkey prefix, not the room server pubkey
  - New panel: `gui/panels/room_server_panel.py` — per-room card management with login state tracking
- ✅ **Room Server password store** — Passwords stored outside the repository in `~/.meshcore-gui/room_passwords/<ADDRESS>.json`
  - New service: `services/room_password_store.py` — JSON-backed persistent password storage per BLE device, analogous to `PinStore`
  - Room panels are restored from stored passwords on app restart
- ✅ **Dynamic channel discovery** — Channels are now auto-discovered from the device at startup via `get_channel()` BLE probing, replacing the hardcoded `CHANNELS_CONFIG`
  - Single-attempt probe per channel slot with early stop after 2 consecutive empty slots
  - Channel name and encryption key extracted in a single pass (combined discovery + key loading)
  - Configurable channel caching via `CHANNEL_CACHE_ENABLED` (default: `False` — always fresh from device)
  - `MAX_CHANNELS` setting (default: 8) controls how many slots are probed
- ✅ **Individual contact deletion** — 🗑️ delete button per unpinned contact in the contacts list, with confirmation dialog
  - New command: `remove_single_contact` in BLE command handler
  - Pinned contacts are protected (no delete button shown)
- ✅ **"Also delete from history" option** — Checkbox in the Clean up confirmation dialog to also remove locally cached contact data

<!-- ADDED: Research document reference -->
- ✅ **Room Server protocol research** — `RoomServer_Companion_App_Onderzoek.md` documents the full companion app message flow (login, push protocol, signature mechanism, auto_message_fetching)

### Changed
- 🔄 `config.py`: Removed `CHANNELS_CONFIG` constant; added `MAX_CHANNELS` (default: 8) and `CHANNEL_CACHE_ENABLED` (default: `False`)
- 🔄 `ble/worker.py`: Replaced hardcoded channel loading with `_discover_channels()` method; added `_try_get_channel_info()` helper; `_apply_cache()` respects `CHANNEL_CACHE_ENABLED` setting; removed `_load_channel_keys()` (integrated into discovery pass)
- 🔄 `ble/commands.py`: Added `login_room`, `send_room_msg` and `remove_single_contact` command handlers
- 🔄 `gui/panels/contacts_panel.py`: Contact click now dispatches by type — type=3 (Room Server) opens room dialog, others open DM dialog; added `on_add_room` callback parameter; added 🗑️ delete button per unpinned contact
- 🔄 `gui/panels/messages_panel.py`: Room Server messages filtered from general message view via `_is_room_message()` with prefix matching; `update()` accepts `room_pubkeys` parameter
- 🔄 `gui/dashboard.py`: Added `RoomServerPanel` in centre column; `_update_ui()` passes `room_pubkeys` to Messages panel; added `_on_add_room_server` callback
- 🔄 `gui/panels/filter_panel.py`: Channel filter checkboxes now built dynamically from discovered channels (no hardcoded references)
- 🔄 `services/bot.py`: Removed stale comment referencing hardcoded channels

### Fixed
- 🛠 **Room Server messages appeared as DM** — Messages from Room Servers (txt_type=2) were displayed in the general Messages panel as direct messages. They are now filtered out and shown exclusively in the Room Server panel
- 🛠 **Historical room messages not shown after login** — Post-login fetch loop was polling `get_msg()` before room server had time to push messages over LoRa RF (10–75s per message). Removed redundant fetch loop; the library's `auto_message_fetching` handles `MESSAGES_WAITING` events correctly and event-driven
- 🛠 **Author attribution incorrect for room messages** — Room server messages showed the room server name as sender instead of the actual message author. Now correctly resolved from the `signature` field (4-byte pubkey prefix) via contact lookup

### Impact
- Room Servers are now first-class citizens in the GUI with dedicated panels
- Channel configuration no longer requires manual editing of `config.py`
- Contact list management is more granular with per-contact deletion
- No breaking changes to existing functionality (messages, DM, map, archive, bot, etc.)

---

## [1.4.0] - 2026-02-09 — SDK Event Race Condition Fix

### Fixed
- 🛠 **BLE startup delay of ~2 minutes eliminated** — The meshcore Python SDK (`commands/base.py`) dispatched device response events before `wait_for_events()` registered its subscription. On busy networks with frequent `RX_LOG_DATA` events, this caused `send_device_query()` and `get_channel()` to fail repeatedly with `no_event_received`, wasting 110+ seconds in timeouts

### Changed
- 📄 `meshcore` SDK `commands/base.py`: Rewritten `send()` method to subscribe to expected events **before** transmitting the BLE command (subscribe-before-send pattern), matching the approach used by the companion apps (meshcore.js, iOS, Android). Submitted upstream as [meshcore_py PR #52](https://github.com/meshcore-dev/meshcore_py/pull/52)

### Impact
- Startup time reduced from ~2+ minutes to ~10 seconds on busy networks
- All BLE commands (`send_device_query`, `get_channel`, `get_bat`, `send_appstart`, etc.) now succeed on first attempt instead of requiring multiple retries
- No changes to meshcore_gui code required — the fix is entirely in the meshcore SDK

### Temporary Installation
Until the fix is merged upstream, install the patched meshcore SDK:
```bash
pip install --force-reinstall git+https://github.com/PE1HVH/meshcore_py.git@fix/event-race-condition
```

---

<!-- ADDED: v1.3.2 bugfix entry -->

## [1.3.2] - 2026-02-09 — Bugfix: Bot Device Name Restoration After Restart

### Fixed
- 🛠 **Bot device name not properly restored after restart/crash** — After a restart or crash with bot mode previously active, the original device name was incorrectly stored as the bot name (e.g. `NL-OV-ZWL-STDSHGN-WKC Bot`) instead of the real device name (e.g. `PE1HVH T1000e`). The original device name is now correctly preserved and restored when bot mode is disabled

### Changed
- 🔄 `commands.py`: `set_bot_name` handler now verifies that the stored original name is not already the bot name before saving
- 🔄 `shared_data.py`: `original_device_name` is only written when it differs from `BOT_DEVICE_NAME` to prevent overwriting with the bot name on restart

---

<!-- ADDED: v1.3.1 bugfix entry -->

## [1.3.1] - 2026-02-09 — Bugfix: Auto-add AttributeError

### Fixed
- 🛠 **Auto-add error on first toggle** — Setting auto-add for the first time raised `AttributeError: 'telemetry_mode_base'`. The `set_manual_add_contacts()` SDK call now handles missing `telemetry_mode_base` attribute gracefully

### Changed
- 🔄 `commands.py`: `set_auto_add` handler wraps `set_manual_add_contacts()` call with attribute check and error handling for missing `telemetry_mode_base`

---

<!-- ADDED: New v1.3.0 entry at top -->

## [1.3.0] - 2026-02-08 — Bot Device Name Management

### Added
- ✅ **Bot device name switching** — When the BOT checkbox is enabled, the device name is automatically changed to a configurable bot name; when disabled, the original name is restored
  - Original device name is saved before renaming so it can be restored on BOT disable
  - Device name written to device via BLE `set_name()` SDK call
  - Graceful handling of BLE failures during name change
- ✅ **`BOT_DEVICE_NAME` constant** in `config.py` — Configurable fixed device name used when bot mode is active (default: `;NL-OV-ZWL-STDSHGN-WKC Bot`)

### Changed
- 🔄 `config.py`: Added `BOT_DEVICE_NAME` constant for bot mode device name
- 🔄 `bot.py`: Removed hardcoded `BOT_NAME` prefix ("Zwolle Bot") from bot reply messages — bot replies no longer include a name prefix
- 🔄 `filter_panel.py`: BOT checkbox toggle now triggers device name save/rename via command queue
- 🔄 `commands.py`: Added `set_bot_name` and `restore_name` command handlers for device name switching
- 🔄 `shared_data.py`: Added `original_device_name` field for storing the pre-bot device name

### Removed
- ❌ `BOT_NAME` constant from `bot.py` — bot reply prefix removed; replies no longer prepend a bot display name

---

## [1.2.0] - 2026-02-08 — Contact Maintenance Feature

### Added
- ✅ **Pin/Unpin contacts** (Iteration A) — Toggle to pin individual contacts, protecting them from bulk deletion
  - Persistent pin state stored in `~/.meshcore-gui/cache/<ADDRESS>_pins.json`
  - Pinned contacts visually marked with yellow background
  - Pinned contacts sorted to top of contact list
  - Pin state survives app restart
  - New service: `services/pin_store.py` — JSON-backed persistent pin storage

- ✅ **Bulk delete unpinned contacts** (Iteration B) — Remove all unpinned contacts from device in one action
  - "🧹 Clean up" button in contacts panel with confirmation dialog
  - Shows count of contacts to be removed vs. pinned contacts kept
  - Progress status updates during removal
  - Automatic device resync after completion
  - New service: `services/contact_cleaner.py` — ContactCleanerService with purge statistics

- ✅ **Auto-add contacts toggle** (Iteration C) — Control whether device automatically adds new contacts from mesh adverts
  - "📥 Auto-add" checkbox in contacts panel (next to Clean up button)
  - Syncs with device via `set_manual_add_contacts()` SDK call
  - Inverted logic handled internally (UI "Auto-add ON" = `set_manual_add_contacts(false)`)
  - Optimistic update with automatic rollback on BLE failure
  - State synchronized from device on each GUI update cycle

### Changed
- 🔄 `contacts_panel.py`: Added pin checkbox per contact, purge button, auto-add toggle, DM dialog (all existing functionality preserved)
- 🔄 `commands.py`: Added `purge_unpinned` and `set_auto_add` command handlers
- 🔄 `shared_data.py`: Added `auto_add_enabled` field with thread-safe getter/setter
- 🔄 `protocols.py`: Added `set_auto_add_enabled` and `is_auto_add_enabled` to Writer and Reader protocols
- 🔄 `dashboard.py`: Passes `PinStore` and `set_auto_add_enabled` callback to ContactsPanel
- 🔄 **UI language**: All Dutch strings in `contacts_panel.py` and `commands.py` translated to English

---

### Fixed
- 🛠 **Route table names and IDs not displayed** — Route tables in both current messages (RoutePage) and archive messages (ArchivePage) now correctly show node names and public key IDs for sender, repeaters and receiver

### Changed
- 🔄 **CHANGELOG.md**: Corrected version numbering to semantic versioning, fixed inaccurate references (archive button location, filter state persistence)
- 🔄 **README.md**: Added Message Archive feature, updated project structure, configuration table and architecture diagram
- 🔄 **MeshCore_GUI_Design.docx**: Added ArchivePage, MessageArchive, Models components; updated project structure, protocols, configuration and version history

---

## [1.1.0] - 2026-02-07 — Archive Viewer Feature


### Added
- ✅ **Archive Viewer Page** (`/archive`) — Full-featured message archive browser
  - Pagination (50 messages per page, configurable)
  - Channel filter dropdown (All + configured channels)
  - Time range filter (24h, 7d, 30d, 90d, All time)
  - Text search (case-insensitive)
  - Filter state stored in instance variables (reset on page reload)
  - Message cards with same styling as main messages panel
  - Clickable messages for route visualization (where available)
  - **💬 Reply functionality** — Expandable reply panel per message
  - **🗺️ Inline route table** — Expandable route display per archive message with sender, repeaters and receiver (names, IDs, node types)
  - *(Note: Reply panels and inline route tables removed in v1.8.0, replaced by click-to-route navigation via message hash)*

<!-- CHANGED: "Filter state persistence (app.storage.user)" replaced with "Filter state stored in 
     instance variables" — the code (archive_page.py:36-40) uses self._current_page etc., 
     not app.storage.user. The comment in the code is misleading. -->

<!-- ADDED: "Inline route table" entry — _render_archive_route() in archive_page.py:333-407 
     was not documented. -->
  
- ✅ **MessageArchive.query_messages()** method
  - Filter by: time range, channel, text search, sender
  - Pagination support (limit, offset)
  - Returns tuple: (messages, total_count)
  - Sorting: Newest first
  
- ✅ **UI Integration**
  - "📚 Archive" button in Messages panel header (opens in new tab)
  - Back to Dashboard button in archive page

<!-- CHANGED: "📚 View Archive button in Actions panel" corrected — the button is in 
     MessagesPanel (messages_panel.py:25), not in ActionsPanel (actions_panel.py). 
     ActionsPanel only contains Refresh and Advert buttons. -->

- ✅ **Reply Panel**
  - Expandable reply per message (💬 Reply button)
  - Pre-filled with @sender mention
  - Channel selector
  - Send button with success notification
  - Auto-close expansion after send

### Changed
- 🔄 `SharedData.get_snapshot()`: Now includes `'archive'` field
- 🔄 `MessagesPanel`: Added archive button in header row
- 🔄 Both entry points (`__main__.py` and `meshcore_gui.py`): Register `/archive` route

<!-- CHANGED: "ActionsPanel: Added archive button" corrected to "MessagesPanel" -->

### Performance
- Query: ~10ms for 10k messages with filters
- Memory: ~10KB per page (50 messages)
- No impact on main UI (separate page)

### Known Limitations
- ~~Route visualization only works for messages in recent buffer (last 100)~~ — Fixed in v1.8.0: archive messages now support click-to-route via `get_message_by_hash()` fallback
- Text search is linear scan (no indexing yet)
- Sender filter exists in API but not in UI yet

---

## [1.0.3] - 2026-02-07 — Critical Bugfix: Archive Overwrite Prevention


### Fixed
- 🛠 **CRITICAL**: Fixed bug where archive was overwritten instead of appended on restart
- 🛠 Archive now preserves existing data when read errors occur
- 🛠 Buffer is retained for retry if existing archive cannot be read

### Changed
- 🔄 `_flush_messages()`: Early return on read error instead of overwriting
- 🔄 `_flush_rxlog()`: Early return on read error instead of overwriting
- 🔄 Better error messages for version mismatch and JSON decode errors

### Details
**Problem:** If the existing archive file had a JSON parse error or version mismatch, 
the flush operation would proceed with `existing_messages = []`, effectively 
overwriting all historical data with only the new buffered messages.

**Solution:** The flush methods now:
1. Try to read existing archive first
2. If read fails (JSON error, version mismatch, IO error), abort the flush
3. Keep buffer intact for next retry
4. Only clear buffer after successful write

**Impact:** No data loss on restart or when archive files have issues.

### Testing
- ✅ Added `test_append_on_restart_not_overwrite()` integration test
- ✅ Verifies data is appended across multiple sessions
- ✅ All existing tests still pass

---

## [1.0.2] - 2026-02-07 — RxLog message_hash Enhancement


### Added
- ✅ `message_hash` field added to `RxLogEntry` model
- ✅ RxLog entries now include message_hash for correlation with messages
- ✅ Archive JSON includes message_hash in rxlog entries

### Changed
- 🔄 `events.py`: Restructured `on_rx_log()` to extract message_hash before creating RxLogEntry
- 🔄 `message_archive.py`: Updated rxlog archiving to include message_hash field
- 🔄 Tests updated to verify message_hash persistence

### Benefits
- **Correlation**: Link RX log entries to their corresponding messages
- **Analysis**: Track which packets resulted in messages
- **Debugging**: Better troubleshooting of packet processing

---

## [1.0.1] - 2026-02-07 — Entry Point Fix


### Fixed
- ✅ `meshcore_gui.py` (root entry point) now passes ble_address to SharedData
- ✅ Archive works correctly regardless of how application is started

### Changed
- 🔄 Both entry points (`meshcore_gui.py` and `meshcore_gui/__main__.py`) updated

---

## [1.0.0] - 2026-02-07 — Message & Metadata Persistence


### Added
- ✅ MessageArchive class for persistent storage
- ✅ Configurable retention periods (MESSAGE_RETENTION_DAYS, RXLOG_RETENTION_DAYS, CONTACT_RETENTION_DAYS)
- ✅ Automatic daily cleanup of old data
- ✅ Batch writes for performance
- ✅ Thread-safe with separate locks
- ✅ Atomic file writes
- ✅ Contact retention in DeviceCache
- ✅ Archive statistics API
- ✅ Comprehensive tests (20+ unit, 8+ integration)
- ✅ Full documentation

### Storage Locations
- `~/.meshcore-gui/archive/<ADDRESS>_messages.json`
- `~/.meshcore-gui/archive/<ADDRESS>_rxlog.json`

### Requirements Completed
- R1: All incoming messages persistent ✅
- R2: All incoming RxLog entries persistent ✅
- R3: Configurable retention ✅
- R4: Automatic cleanup ✅
- R5: Backward compatibility ✅
- R6: Contact retention ✅
- R7: Archive stats API ✅

- Fix3: Leaflet asset injection is now per page render instead of process-global, and browser bootstrap now retries until the host element, Leaflet runtime, and MeshCore panel runtime are all available. This fixes blank map containers caused by missing or late-loaded JS/CSS assets.

- Fix5: Removed per-snapshot map invalidate calls, stopped forcing a default dark theme during map bootstrap, and added client-side interaction/resize guards so zooming stays responsive and the theme no longer jumps back during status-loop updates.


## 2026-03-09 map hotfix v2
- regular map snapshots no longer carry theme state
- explicit theme changes are now handled only via the dedicated theme channel
- initial map render now sends an ensure_map command plus an immediate theme sync
- added no-op ensure_map handling in the Leaflet runtime to avoid accidental fallback behaviour

## [1.13.0] - 2026-03-09

### Added
- Leaflet marker clustering using Leaflet.markercluster for contact nodes.
- Browser-side cluster rendering with the device marker kept outside the cluster layer.
- Cluster performance tuning with `chunkedLoading: true`.
- Spiderfy support at max zoom for overlapping markers.

### Fixed
- Wrong asset load order causing `L is not defined` in MarkerClusterGroup.
- Cluster initialization failure caused by missing `maxZoom` on map startup.
- Retry cascade causing `Map container is already initialized`.

### Changed
- Map lifecycle is browser-owned: NiceGUI hosts the container, Leaflet owns map state.
- Contact markers are updated incrementally in the existing cluster layer.
