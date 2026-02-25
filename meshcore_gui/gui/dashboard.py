"""
Main dashboard page for MeshCore GUI.

Thin orchestrator that owns the layout and the 500 ms update timer.
All visual content is delegated to individual panel classes in
:mod:`meshcore_gui.gui.panels`.
"""

import logging
from urllib.parse import urlencode

from nicegui import ui

from meshcore_gui import config

from meshcore_gui.core.protocols import SharedDataReader
from meshcore_gui.gui.panels import (
    ActionsPanel,
    ContactsPanel,
    DevicePanel,
    MapPanel,
    MessagesPanel,
    RoomServerPanel,
    RxLogPanel,
)
from meshcore_gui.gui.archive_page import ArchivePage
from meshcore_gui.services.pin_store import PinStore
from meshcore_gui.services.room_password_store import RoomPasswordStore


# Suppress the harmless "Client has been deleted" warning that NiceGUI
# emits when a browser tab is refreshed while a ui.timer is active.
class _DeletedClientFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'Client has been deleted' not in record.getMessage()

logging.getLogger('nicegui').addFilter(_DeletedClientFilter())


# ── DOMCA Theme ──────────────────────────────────────────────────────
# Fonts + CSS variables adapted from domca.nl style.css for NiceGUI/Quasar.
# Dark/light variable sets switch via Quasar's body--dark / body--light classes.

_DOMCA_HEAD = '''
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#0d1f35">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="DOMCA">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
/* ── DOMCA theme variables (dark) ── */
body.body--dark {
  --bg: #0A1628;
  --grid: #0077B6;   --grid-op: 0.15;
  --mesh-bg: #48CAE4; --mesh-bg-op: 0.08;
  --line: #0077B6;   --line-op: 0.6;
  --wave: #48CAE4;   --node: #00B4D8; --node-center: #CAF0F8;
  --hub-text: #0A1628; --outer: #0077B6;
  --title: #48CAE4;  --subtitle: #48CAE4;
  --tagline: #90E0EF; --tag-op: 0.5;
  --badge-stroke: #0077B6; --badge-text: #48CAE4;
  --callsign: #0077B6;
}
/* ── DOMCA theme variables (light) ── */
body.body--light {
  --bg: #FFFFFF;
  --grid: #023E8A;   --grid-op: 0.04;
  --mesh-bg: #0077B6; --mesh-bg-op: 0.05;
  --line: #0096C7;   --line-op: 0.35;
  --wave: #0096C7;   --node: #0077B6; --node-center: #FFFFFF;
  --hub-text: #FFFFFF; --outer: #0096C7;
  --title: #0077B6;  --subtitle: #0077B6;
  --tagline: #0096C7; --tag-op: 0.4;
  --badge-stroke: #0077B6; --badge-text: #0077B6;
  --callsign: #0096C7;
}

/* ── DOMCA page background ── */
body.body--dark  { background: #0A1628 !important; }
body.body--light { background: #f4f8fb !important; }
body.body--dark .q-page  { background: #0A1628 !important; }
body.body--light .q-page { background: #f4f8fb !important; }

/* ── DOMCA header ── */
body.body--dark .q-header  { background: #0d1f35 !important; }
body.body--light .q-header { background: #0077B6 !important; }

/* ── DOMCA drawer — distinct from page background ── */
body.body--dark .domca-drawer  { background: #0f2340 !important; border-right: 1px solid rgba(0,119,182,0.25) !important; }
body.body--light .domca-drawer { background: rgba(244,248,251,0.97) !important; }
.domca-drawer .q-btn__content  { justify-content: flex-start !important; }

/* ── DOMCA cards — dark mode readable ── */
body.body--dark .q-card {
  background: #112240 !important;
  color: #e0f0f8 !important;
  border: 1px solid rgba(0,119,182,0.15) !important;
}
body.body--dark .q-card .text-gray-600 { color: #48CAE4 !important; }
body.body--dark .q-card .text-gray-500 { color: #8badc4 !important; }
body.body--dark .q-card .text-gray-400 { color: #6a8fa8 !important; }
body.body--dark .q-card .text-xs       { color: #c0dce8 !important; }
body.body--dark .q-card .text-sm       { color: #d0e8f2 !important; }
body.body--dark .q-card .text-red-400  { color: #f87171 !important; }

/* ── Dark mode: message area, inputs, tables ── */
body.body--dark .bg-gray-50  { background: #0c1a2e !important; color: #c0dce8 !important; }
body.body--dark .bg-gray-100 { background: #152a45 !important; }
body.body--dark .hover\\:bg-gray-100:hover { background: #1a3352 !important; }
body.body--dark .hover\\:bg-blue-50:hover  { background: #0d2a4a !important; }
body.body--dark .bg-yellow-50 { background: rgba(72,202,228,0.06) !important; }

body.body--dark .q-field__control { background: #0c1a2e !important; color: #e0f0f8 !important; }
body.body--dark .q-field__native  { color: #e0f0f8 !important; }
body.body--dark .q-field__label   { color: #8badc4 !important; }

body.body--dark .q-table { background: #112240 !important; color: #c0dce8 !important; }
body.body--dark .q-table thead th { color: #48CAE4 !important; }
body.body--dark .q-table tbody td { color: #c0dce8 !important; }

body.body--dark .q-checkbox__label { color: #c0dce8 !important; }
body.body--dark .q-btn--flat:not(.domca-menu-btn):not(.domca-sub-btn) { color: #48CAE4 !important; }

body.body--dark .q-separator { background: rgba(0,119,182,0.2) !important; }

/* ── DOMCA menu link styling ── */
body.body--dark .domca-menu-btn        { color: #8badc4 !important; }
body.body--dark .domca-menu-btn:hover  { color: #48CAE4 !important; }
body.body--light .domca-menu-btn       { color: #3d6380 !important; }
body.body--light .domca-menu-btn:hover { color: #0077B6 !important; }

body.body--dark .domca-ext-link  { color: #8badc4 !important; }
body.body--light .domca-ext-link { color: #3d6380 !important; }

/* ── DOMCA active menu item ── */
body.body--dark .domca-menu-active  { color: #48CAE4 !important; background: rgba(72,202,228,0.1) !important; }
body.body--light .domca-menu-active { color: #0077B6 !important; background: rgba(0,119,182,0.08) !important; }

/* ── DOMCA submenu item styling ── */
body.body--dark .domca-sub-btn        { color: #6a8fa8 !important; }
body.body--dark .domca-sub-btn:hover  { color: #48CAE4 !important; }
body.body--light .domca-sub-btn       { color: #5a7a90 !important; }
body.body--light .domca-sub-btn:hover { color: #0077B6 !important; }

/* ── DOMCA expansion panel in drawer ── */
.domca-drawer .q-expansion-item {
  font-family: 'JetBrains Mono', monospace !important;
  letter-spacing: 2px;
  font-size: 0.8rem;
}
.domca-drawer .q-expansion-item .q-item {
  padding: 0.35rem 1.2rem !important;
  min-height: 32px !important;
}
.domca-drawer .q-expansion-item .q-expansion-item__content {
  padding: 0 !important;
}
.domca-drawer .q-expansion-item + .q-expansion-item {
  margin-top: 0 !important;
}
body.body--dark .domca-drawer .q-expansion-item { color: #8badc4 !important; }
body.body--dark .domca-drawer .q-expansion-item__container { background: transparent !important; }
body.body--dark .domca-drawer .q-item { color: #8badc4 !important; }
body.body--light .domca-drawer .q-expansion-item { color: #3d6380 !important; }
body.body--light .domca-drawer .q-item { color: #3d6380 !important; }

/* ── Landing page centering ── */
.domca-landing {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 64px);
  padding: 0.5rem;
}
.domca-landing svg {
  width: min(90vw, 800px);
  height: auto;
  display: block;
}

/* ── Panel container — responsive single column ── */
.domca-panel {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  padding: 0.5rem;
}

/* ── Responsive heights — override fixed Tailwind heights in panels ── */
.domca-panel .h-40  { height: calc(100vh - 20rem) !important; min-height: 10rem; }
.domca-panel .h-32  { height: calc(100vh - 24rem) !important; min-height: 8rem; }
.domca-panel .h-72  { height: calc(100vh - 12rem) !important; min-height: 14rem; }
.domca-panel .max-h-48 { max-height: calc(100vh - 16rem) !important; min-height: 6rem; }

/* ── Allow narrow viewports down to 320px ── */
body, .q-layout, .q-page {
  min-width: 0 !important;
}
.q-drawer { max-width: 80vw !important; width: 260px !important; min-width: 200px !important; }

/* ── Mobile optimisations ── */
@media (max-width: 640px) {
  .domca-landing svg { width: 98vw; }
  .domca-panel       { padding: 0.25rem; }
  .domca-panel .q-card { border-radius: 8px !important; }
}
@media (max-width: 400px) {
  .domca-landing { padding: 0.25rem; }
  .domca-landing svg { width: 100vw; }
  .q-header { padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
}

/* ── Footer label ── */
.domca-footer {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 2px;
  opacity: 0.3;
}

/* ── Header text: icon-only on narrow viewports ── */
@media (max-width: 599px) {
  .domca-header-text { display: none !important; }
}
</style>
'''

# ── Landing SVG loader ────────────────────────────────────────────────
# Reads the SVG from config.LANDING_SVG_PATH and replaces {callsign}
# with config.OPERATOR_CALLSIGN.  Falls back to a minimal placeholder
# when the file is missing.


def _load_landing_svg() -> str:
    """Load the landing page SVG from disk.

    Returns:
        SVG markup string with ``{callsign}`` replaced by the
        configured operator callsign.
    """
    path = config.LANDING_SVG_PATH
    try:
        raw = path.read_text(encoding="utf-8")
        return raw.replace("{callsign}", config.OPERATOR_CALLSIGN)
    except FileNotFoundError:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100">'
            '<text x="200" y="55" text-anchor="middle" '
            'font-family="\'JetBrains Mono\',monospace" font-size="14" '
            f'fill="var(--title)">Landing SVG not found: {path.name}</text>'
            '</svg>'
        )


# ── Standalone menu items (no submenus) ──────────────────────────────

_STANDALONE_ITEMS = [
    ('\U0001f465', 'CONTACTS', 'contacts'),
    ('\U0001f5fa\ufe0f', 'MAP',      'map'),
    ('\U0001f4e1', 'DEVICE',   'device'),
    ('\u26a1',     'ACTIONS',  'actions'),
    ('\U0001f4ca', 'RX LOG',   'rxlog'),
]

_EXT_LINKS = config.EXT_LINKS

# ── Shared button styles ─────────────────────────────────────────────

_SUB_BTN_STYLE = (
    "font-family: 'JetBrains Mono', monospace; "
    "letter-spacing: 1px; font-size: 0.72rem; "
    "padding: 0.2rem 1.2rem 0.2rem 2.4rem"
)

_MENU_BTN_STYLE = (
    "font-family: 'JetBrains Mono', monospace; "
    "letter-spacing: 2px; font-size: 0.8rem; "
    "padding: 0.35rem 1.2rem"
)


class DashboardPage:
    """Main dashboard rendered at ``/``.

    Args:
        shared: SharedDataReader for data access and command dispatch.
    """

    def __init__(self, shared: SharedDataReader, pin_store: PinStore, room_password_store: RoomPasswordStore) -> None:
        self._shared = shared
        self._pin_store = pin_store
        self._room_password_store = room_password_store

        # Panels (created fresh on each render)
        self._device: DevicePanel | None = None
        self._contacts: ContactsPanel | None = None
        self._map: MapPanel | None = None
        self._messages: MessagesPanel | None = None
        self._actions: ActionsPanel | None = None
        self._rxlog: RxLogPanel | None = None
        self._room_server: RoomServerPanel | None = None

        # Header status label
        self._status_label = None

        # Local first-render flag
        self._initialized: bool = False

        # Panel switching state (layout)
        self._panel_containers: dict = {}
        self._active_panel: str = 'landing'
        self._drawer = None
        self._menu_buttons: dict = {}

        # Submenu containers (for dynamic channel/room items)
        self._msg_sub_container = None
        self._archive_sub_container = None
        self._rooms_sub_container = None
        self._last_channel_fingerprint = None
        self._last_rooms_fingerprint = None

        # Archive page reference (for inline channel switching)
        self._archive_page: ArchivePage | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the complete dashboard layout and start the timer."""
        self._initialized = False

        # Reset fingerprints: render() creates new (empty) NiceGUI
        # containers, so _update_submenus must rebuild into them even
        # when the channel/room data hasn't changed since last session.
        self._last_channel_fingerprint = None
        self._last_rooms_fingerprint = None

        # Create panel instances (UNCHANGED functional wiring)
        put_cmd = self._shared.put_command
        self._device = DevicePanel()
        self._contacts = ContactsPanel(put_cmd, self._pin_store, self._shared.set_auto_add_enabled, self._on_add_room_server)
        self._map = MapPanel()
        self._messages = MessagesPanel(put_cmd)
        self._actions = ActionsPanel(put_cmd, self._shared.set_bot_enabled)
        self._rxlog = RxLogPanel()
        self._room_server = RoomServerPanel(put_cmd, self._room_password_store)

        # Inject DOMCA theme (fonts + CSS variables)
        ui.add_head_html(_DOMCA_HEAD)

        # Default to dark mode (DOMCA theme)
        dark = ui.dark_mode(True)
        dark.on_value_change(lambda e: self._map.set_ui_dark_mode(e.value))
        self._map.set_ui_dark_mode(dark.value)

        # ── Left Drawer (must be created before header for Quasar) ────
        self._drawer = ui.left_drawer(value=False, bordered=True).classes(
            'domca-drawer'
        ).style('padding: 0')

        with self._drawer:
            # DOMCA branding (clickable → landing page)
            with ui.column().style('padding: 0.2rem 1.2rem 0'):
                ui.button(
                    'DOMCA',
                    on_click=lambda: self._navigate_panel('landing'),
                ).props('flat no-caps').style(
                    "font-family: 'Exo 2', sans-serif; font-size: 1.4rem; "
                    "font-weight: 800; color: var(--title); letter-spacing: 4px; "
                    "margin-bottom: 0.3rem; padding: 0"
                )

            self._menu_buttons = {}

            # ── 💬 MESSAGES (expandable with channel submenu) ──────
            with ui.expansion(
                '\U0001f4ac  MESSAGES', icon=None, value=False,
            ).props('dense header-class="q-pa-none"').classes('w-full'):
                self._msg_sub_container = ui.column().classes('w-full gap-0')
                with self._msg_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('messages', channel=None)
                    )
                    self._make_sub_btn(
                        'DM', lambda: self._navigate_panel('messages', channel='DM')
                    )
                    # Dynamic channel items populated by _update_submenus

            # ── 🏠 ROOMS (expandable with room submenu) ───────────
            with ui.expansion(
                '\U0001f3e0  ROOMS', icon=None, value=False,
            ).props('dense header-class="q-pa-none"').classes('w-full'):
                self._rooms_sub_container = ui.column().classes('w-full gap-0')
                with self._rooms_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('rooms')
                    )
                    # Pre-populate from persisted rooms
                    for entry in self._room_password_store.get_rooms():
                        short = entry.name or entry.pubkey[:12]
                        self._make_sub_btn(
                            f'\U0001f3e0 {short}',
                            lambda: self._navigate_panel('rooms'),
                        )

            # ── 📚 ARCHIVE (expandable with channel submenu) ──────
            with ui.expansion(
                '\U0001f4da  ARCHIVE', icon=None, value=False,
            ).props('dense header-class="q-pa-none"').classes('w-full'):
                self._archive_sub_container = ui.column().classes('w-full gap-0')
                with self._archive_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('archive', channel=None)
                    )
                    self._make_sub_btn(
                        'DM', lambda: self._navigate_panel('archive', channel='DM')
                    )
                    # Dynamic channel items populated by _update_submenus

            ui.separator().classes('my-1')

            # ── Standalone menu items (MAP, DEVICE, ACTIONS, RX LOG)
            for icon, label, panel_id in _STANDALONE_ITEMS:
                btn = ui.button(
                    f'{icon}  {label}',
                    on_click=lambda pid=panel_id: self._navigate_panel(pid),
                ).props('flat no-caps align=left').classes(
                    'w-full justify-start domca-menu-btn'
                ).style(_MENU_BTN_STYLE)
                self._menu_buttons[panel_id] = btn

            ui.separator().classes('my-2')

            # External links (same as domca.nl navigation)
            with ui.column().style('padding: 0 1.2rem'):
                for label, url in _EXT_LINKS:
                    ui.link(label, url, new_tab=True).classes(
                        'domca-ext-link'
                    ).style(
                        "font-family: 'JetBrains Mono', monospace; "
                        "letter-spacing: 2px; font-size: 0.72rem; "
                        "text-decoration: none; opacity: 0.6; "
                        "display: block; padding: 0.35rem 0"
                    )

            # Footer in drawer
            ui.space()
            ui.label(f'\u00a9 2026 {config.OPERATOR_CALLSIGN}').classes('domca-footer').style('padding: 0 1.2rem 1rem')

        # ── Header ────────────────────────────────────────────────
        with ui.header().classes('items-center px-4 py-2 shadow-md'):
            menu_btn = ui.button(
                icon='menu',
                on_click=lambda: self._drawer.toggle(),
            ).props('flat round dense color=white')

            # Swap icon: menu ↔ close
            self._drawer.on_value_change(
                lambda e: menu_btn.props(f'icon={"close" if e.value else "menu"}')
            )

            ui.label(f'\U0001f517 MeshCore v{config.VERSION}').classes(
                'text-lg font-bold ml-2 domca-header-text'
            ).style("font-family: 'JetBrains Mono', monospace")

            # Transport mode badge
            _is_ble = config.TRANSPORT == "ble"
            _badge_icon = '🔵' if _is_ble else '🟢'
            _badge_label = 'BLE' if _is_ble else 'Serial'
            ui.label(f'{_badge_icon} {_badge_label}').classes(
                'text-xs ml-2 domca-header-text'
            ).style(
                "font-family: 'JetBrains Mono', monospace; "
                "opacity: 0.65; letter-spacing: 1px"
            )

            ui.space()

            self._status_label = ui.label('Starting...').classes(
                'text-sm opacity-70 domca-header-text'
            )

            ui.button(
                icon='brightness_6',
                on_click=lambda: dark.toggle(),
            ).props('flat round dense color=white').tooltip('Toggle dark / light')

        # ── Main Content Area ─────────────────────────────────────
        self._panel_containers = {}

        # Landing page (SVG splash from file — visible by default)
        landing = ui.column().classes('domca-landing w-full')
        with landing:
            ui.html(_load_landing_svg())
        self._panel_containers['landing'] = landing

        # Panel containers (hidden by default, shown on menu click)
        panel_defs = [
            ('messages', self._messages),
            ('contacts', self._contacts),
            ('map',      self._map),
            ('device',   self._device),
            ('actions',  self._actions),
            ('rxlog',    self._rxlog),
            ('rooms',    self._room_server),
        ]

        for panel_id, panel_obj in panel_defs:
            container = ui.column().classes('domca-panel')
            container.set_visibility(False)
            with container:
                panel_obj.render()
            self._panel_containers[panel_id] = container

        # Archive panel (inline — replaces separate /archive page)
        archive_container = ui.column().classes('domca-panel')
        archive_container.set_visibility(False)
        with archive_container:
            self._archive_page = ArchivePage(self._shared)
            self._archive_page.render()
        self._panel_containers['archive'] = archive_container

        self._active_panel = 'landing'

        # Start update timer
        self._apply_url_state()
        ui.timer(0.5, self._update_ui)

    # ------------------------------------------------------------------
    # Submenu button helper (layout only)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_sub_btn(label: str, on_click) -> ui.button:
        """Create a submenu button in the drawer."""
        return ui.button(
            label,
            on_click=on_click,
        ).props('flat no-caps align=left').classes(
            'w-full justify-start domca-sub-btn'
        ).style(_SUB_BTN_STYLE)

    # ------------------------------------------------------------------
    # Dynamic submenu updates (layout — called from _update_ui)
    # ------------------------------------------------------------------

    def _update_submenus(self, data: dict) -> None:
        """Rebuild channel/room submenu items when data changes.

        Only the dynamic items are rebuilt; the container is cleared and
        ALL items (static + dynamic) are re-rendered.
        """
        # ── Channel submenus (Messages + Archive) ──
        channels = data.get('channels', [])
        ch_fingerprint = tuple((ch['idx'], ch['name']) for ch in channels)

        if ch_fingerprint != self._last_channel_fingerprint and channels:
            self._last_channel_fingerprint = ch_fingerprint

            # Rebuild Messages submenu
            if self._msg_sub_container:
                self._msg_sub_container.clear()
                with self._msg_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('messages', channel=None)
                    )
                    self._make_sub_btn(
                        'DM', lambda: self._navigate_panel('messages', channel='DM')
                    )
                    for ch in channels:
                        idx = ch['idx']
                        name = ch['name']
                        self._make_sub_btn(
                            f"[{idx}] {name}",
                            lambda i=idx: self._navigate_panel('messages', channel=i),
                        )

            # Rebuild Archive submenu
            if self._archive_sub_container:
                self._archive_sub_container.clear()
                with self._archive_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('archive', channel=None)
                    )
                    self._make_sub_btn(
                        'DM', lambda: self._navigate_panel('archive', channel='DM')
                    )
                    for ch in channels:
                        idx = ch['idx']
                        name = ch['name']
                        self._make_sub_btn(
                            f"[{idx}] {name}",
                            lambda n=name: self._navigate_panel('archive', channel=n),
                        )

        # ── Room submenus ──
        rooms = self._room_password_store.get_rooms()
        rooms_fingerprint = tuple((r.pubkey, r.name) for r in rooms)

        if rooms_fingerprint != self._last_rooms_fingerprint:
            self._last_rooms_fingerprint = rooms_fingerprint

            if self._rooms_sub_container:
                self._rooms_sub_container.clear()
                with self._rooms_sub_container:
                    self._make_sub_btn(
                        'ALL', lambda: self._navigate_panel('rooms')
                    )
                    for entry in rooms:
                        short = entry.name or entry.pubkey[:12]
                        self._make_sub_btn(
                            f'\U0001f3e0 {short}',
                            lambda: self._navigate_panel('rooms'),
                        )

    # ------------------------------------------------------------------
    # Panel switching (layout helper — no functional logic)
    # ------------------------------------------------------------------

    def _apply_url_state(self) -> None:
        """Apply panel selection from URL query params on first render."""
        try:
            params = ui.context.client.request.query_params
        except Exception:
            return

        panel = params.get('panel') or 'landing'
        channel = params.get('channel')

        if panel not in self._panel_containers:
            panel = 'landing'
            channel = None

        if panel == 'messages':
            if channel is None or channel.lower() == 'all':
                channel = None
            elif channel.upper() == 'DM':
                channel = 'DM'
            else:
                channel = int(channel) if channel.isdigit() else None
        elif panel == 'archive':
            if channel is None or channel.lower() == 'all':
                channel = None
            elif channel.upper() == 'DM':
                channel = 'DM'
        else:
            channel = None

        self._show_panel(panel, channel)

    def _build_panel_url(self, panel_id: str, channel=None) -> str:
        params = {'panel': panel_id}
        if channel is not None:
            params['channel'] = str(channel)
        return '/?' + urlencode(params)

    def _navigate_panel(self, panel_id: str, channel=None) -> None:
        """Navigate with panel id in the URL so browser back restores state."""
        ui.navigate.to(self._build_panel_url(panel_id, channel))

    def _show_panel(self, panel_id: str, channel=None) -> None:
        """Show the selected panel, hide all others, close the drawer.

        Args:
            panel_id: Panel to show (e.g. 'messages', 'archive', 'rooms').
            channel:  Optional channel filter.
                      For messages: None=all, 'DM'=DM only, int=channel idx.
                      For archive:  None=all, 'DM'=DM only, str=channel name.
        """
        for pid, container in self._panel_containers.items():
            container.set_visibility(pid == panel_id)
        self._active_panel = panel_id

        # Apply channel filter to messages panel
        if panel_id == 'messages' and self._messages:
            self._messages.set_active_channel(channel)
            # Force immediate rebuild so the panel is populated the
            # moment it becomes visible, instead of waiting for the
            # next 500 ms timer tick (which caused the "empty on first
            # click, populated on second click" symptom).
            data = self._shared.get_snapshot()
            self._messages.update(
                data,
                self._messages.channel_filters,
                self._messages.last_channels,
                room_pubkeys=(
                    self._room_server.get_room_pubkeys()
                    if self._room_server else None
                ),
            )

        # Apply channel filter to archive panel
        if panel_id == 'archive' and self._archive_page:
            self._archive_page.set_channel_filter(channel)

        # Force map recenter when opening map panel (Leaflet may be hidden on load)
        if panel_id == 'map' and self._map:
            data = self._shared.get_snapshot()
            data['force_center'] = True
            self._map.update(data)

        # Update active menu highlight (standalone buttons only)
        for pid, btn in self._menu_buttons.items():
            if pid == panel_id:
                btn.classes('domca-menu-active', remove='')
            else:
                btn.classes(remove='domca-menu-active')

        # Close drawer after selection
        if self._drawer:
            self._drawer.hide()

    # ------------------------------------------------------------------
    # Room Server callback (from ContactsPanel)
    # ------------------------------------------------------------------

    def _on_add_room_server(self, pubkey: str, name: str, password: str) -> None:
        """Handle adding a Room Server from the contacts panel.

        Delegates to the RoomServerPanel which persists the entry,
        creates the UI card and sends the login command.
        """
        if self._room_server:
            self._room_server.add_room(pubkey, name, password)

    # ------------------------------------------------------------------
    # Timer-driven UI update
    # ------------------------------------------------------------------

    def _update_ui(self) -> None:
        try:
            if not self._status_label:
                return

            # Atomic snapshot + flag clear: eliminates race condition
            # where worker sets channels_updated between separate
            # get_snapshot() and clear_update_flags() calls.
            data = self._shared.get_snapshot_and_clear_flags()
            is_first = not self._initialized

            # Mark initialised immediately — even if a panel update
            # crashes below, we must NOT retry the full first-render
            # path every 500 ms (that causes the infinite rebuild).
            if is_first:
                self._initialized = True

            # Always update status
            self._status_label.text = data['status']

            # Device info
            if data['device_updated'] or is_first:
                self._device.update(data)
                # to show own position if changed
                self._map.update(data)

            # Channel-dependent UI: always ensure consistency when
            # channels exist.  Because a single DashboardPage instance
            # is shared across browser sessions (render() is called on
            # each new connection), the old session's timer can steal
            # the is_first flag before the new timer fires.  Running
            # these unconditionally is safe because each method has an
            # internal fingerprint/equality check that prevents
            # unnecessary DOM updates.
            if data['channels']:
                self._messages.update_filters(data)
                self._messages.update_channel_options(data['channels'])
                self._update_submenus(data)

            # BOT checkbox state (only on actual change or first render
            # to avoid overwriting user interaction mid-toggle)
            if data['channels_updated'] or is_first:
                self._actions.update(data)

            # Contacts
            if data['contacts_updated'] or is_first:
                self._contacts.update(data)

            # Map
            if data['contacts'] and (
                data['contacts_updated'] or not self._map.has_markers or is_first
            ):
                self._map.update(data)

            # Messages (always — for live filter changes)
            self._messages.update(
                data,
                self._messages.channel_filters,
                self._messages.last_channels,
                room_pubkeys=self._room_server.get_room_pubkeys() if self._room_server else None,
            )

            # Room Server panels (always — for live messages + contact changes)
            self._room_server.update(data)

            # RX Log
            if data['rxlog_updated']:
                self._rxlog.update(data)

            # Signal worker that GUI is ready for data
            if is_first and data['channels'] and data['contacts']:
                self._shared.mark_gui_initialized()

        except Exception as e:
            err = str(e).lower()
            if "deleted" not in err and "client" not in err:
                import traceback
                print(f"GUI update error: {e}")
                traceback.print_exc()
