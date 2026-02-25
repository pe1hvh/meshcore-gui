"""Map panel — Leaflet map with own position and contact markers."""

from typing import Dict, List

from nicegui import ui

from meshcore_gui.config import DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM
from meshcore_gui.gui.constants import TYPE_ICONS


class MapPanel:
    """Interactive Leaflet map in the centre column."""

    def __init__(self) -> None:
        self._map = None
        self._base_layer = None
        self._active_theme = None
        self._map_theme_mode = 'auto'  # auto | dark | light
        self._ui_dark = True
        self._theme_toggle = None
        self._contacts_markers: List = []
        self._own_marker = None
        self._last_device_lat = None
        self._last_device_lon = None

    @property
    def has_markers(self) -> bool:
        return bool(self._contacts_markers)

    def render(self) -> None:
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('🗺️ Map').classes('font-bold text-gray-600')
                with ui.row().classes('items-center gap-2'):
                    ui.label('Theme').classes('text-xs text-gray-500')
                    self._theme_toggle = ui.toggle(
                        {'auto': 'Auto', 'dark': 'Dark', 'light': 'Light'},
                        value=self._map_theme_mode,
                        on_change=lambda e: self._set_map_theme_mode(e.value),
                    ).props('dense')
                    ui.button('Center on Device', on_click=self._center_on_device)
            self._map = ui.leaflet(
                center=DEFAULT_MAP_CENTER, zoom=DEFAULT_MAP_ZOOM
            ).classes('w-full h-72')
            self._map.clear_layers()
            self._active_theme = None
            self._apply_map_theme()

    def set_ui_dark_mode(self, value: bool | None) -> None:
        """Update map theme when the UI dark mode changes."""
        self._ui_dark = bool(value) if value is not None else True
        if self._map_theme_mode == 'auto':
            self._apply_map_theme()

    def _set_map_theme_mode(self, mode: str) -> None:
        if mode not in ('auto', 'dark', 'light'):
            return
        self._map_theme_mode = mode
        self._apply_map_theme()

    def _apply_map_theme(self) -> None:
        if not self._map:
            return
        desired = self._map_theme_mode
        if desired == 'auto':
            desired = 'dark' if self._ui_dark else 'light'
        if desired == self._active_theme:
            return
        if self._base_layer is not None:
            try:
                self._map.remove_layer(self._base_layer)
            except Exception:
                pass
            self._base_layer = None

        if desired == 'dark':
            url = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
            options = {
                'attribution': (
                    '&copy; <a href="https://www.openstreetmap.org/copyright">'
                    'OpenStreetMap</a> contributors &copy; '
                    '<a href="https://carto.com/attributions">CARTO</a>'
                ),
                'maxZoom': 20,
            }
        else:
            url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
            options = {
                'attribution': (
                    '&copy; <a href="https://www.openstreetmap.org/copyright">'
                    'OpenStreetMap</a> contributors'
                ),
                'maxZoom': 19,
            }
        self._base_layer = self._map.tile_layer(url_template=url, options=options)
        self._active_theme = desired

    def _center_on_device(self) -> None:
        if not self._map:
            return
        if self._last_device_lat is None or self._last_device_lon is None:
            return
        try:
            self._map.run_method('invalidateSize')
        except Exception:
            pass
        self._map.set_center((self._last_device_lat, self._last_device_lon))

    def update(self, data: Dict) -> None:
        if not self._map:
            return

        # Own position
        force_center = bool(data.get('force_center', False))
        if (
            (data['device_updated'] or self._own_marker is None or force_center)
            and (data['adv_lat'] and data['adv_lon'])
        ):
            self._last_device_lat = data['adv_lat']
            self._last_device_lon = data['adv_lon']
            try:
                self._map.remove_layer(self._own_marker)
            except Exception:
                pass
            self._own_marker = self._map.marker(latlng=(data['adv_lat'], data['adv_lon']), options={'title': '📡 ' + data['name']})
            try:
                self._map.run_method('invalidateSize')
            except Exception:
                pass
            self._map.set_center((data['adv_lat'], data['adv_lon']))

        # Contact markers
        if data['contacts_updated'] or not self.has_markers:
            # Remove old markers
            for marker in self._contacts_markers:
                try:
                    self._map.remove_layer(marker)
                except Exception:
                    pass
            self._contacts_markers.clear()

            for key, contact in data['contacts'].items():
                lat = contact.get('adv_lat', 0)
                lon = contact.get('adv_lon', 0)
                if lat != 0 or lon != 0:
                    icon = TYPE_ICONS.get(contact.get('type', 0), '○')
                    marker = self._map.marker(latlng=(lat, lon), options={'title': icon + ' ' + contact.get('adv_name', key[:16])})
                    self._contacts_markers.append(marker)
