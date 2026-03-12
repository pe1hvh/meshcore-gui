"""Map panel — browser-managed Leaflet map hosted inside NiceGUI."""

from __future__ import annotations

import json
from uuid import uuid4
from typing import Dict

from nicegui import ui

from meshcore_gui.services.map_snapshot_service import MapSnapshotService


class MapPanel:
    """Interactive map panel hosted by NiceGUI and rendered by Leaflet."""

    _persisted_theme_mode = 'auto'

    def __init__(self) -> None:
        self._map_theme_mode = self.__class__._persisted_theme_mode  # auto | dark | light
        self._ui_dark = True
        self._theme_toggle = None
        self._container_id = f'meshcore-leaflet-map-{uuid4().hex}'
        self._snapshot_service = MapSnapshotService()
        self._has_contacts = False
        self._has_device = False

    @property
    def has_markers(self) -> bool:
        """Return whether the last rendered snapshot contained contacts."""
        return self._has_contacts

    def render(self) -> None:
        """Render the card and inject the browser-side Leaflet container."""
        self._inject_assets()

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
            ui.element('div').props(f'id={self._container_id}').classes(
                'meshcore-leaflet-host w-full h-72'
            )
            self._apply_theme_only()

    def set_ui_dark_mode(self, value: bool | None) -> None:
        """Update the map theme when the NiceGUI dark mode changes."""
        self._ui_dark = bool(value) if value is not None else True
        if self._map_theme_mode == 'auto':
            self._apply_theme_only()

    def _set_map_theme_mode(self, mode: str) -> None:
        """Apply a new theme mode without recreating the Leaflet map."""
        if mode not in ('auto', 'dark', 'light'):
            return
        self._map_theme_mode = mode
        self.__class__._persisted_theme_mode = mode
        self._apply_theme_only()

    def _apply_theme_only(self) -> None:
        """Push only the effective theme to the browser map runtime."""
        theme = self._snapshot_service.resolve_theme(
            self._map_theme_mode,
            self._ui_dark,
        )
        self._dispatch_to_browser(theme=theme)

    def _center_on_device(self) -> None:
        """Center the browser map on the already-rendered device marker."""
        if not self._has_device:
            return
        self._dispatch_to_browser(snapshot={'__command__': 'center_on_device'})

    def update(self, data: Dict) -> None:
        """Send the latest compact map snapshot to the browser."""
        snapshot = self._snapshot_service.build_snapshot(
            data=data,
            theme_mode=self._map_theme_mode,
            ui_dark=self._ui_dark,
            force_center=bool(data.get('force_center', False)),
        )
        payload = snapshot.to_dict()
        self._has_contacts = bool(payload['contacts'])
        self._has_device = payload['device'] is not None

        # Theme updates are sent over a dedicated channel. Regular data snapshots
        # must never carry theme state, otherwise the 500 ms refresh loop can
        # overwrite a freshly selected browser theme with an older/default value.
        payload.pop('theme', None)
        self._dispatch_to_browser(snapshot=payload)

    def _dispatch_to_browser(
        self,
        snapshot: Dict | None = None,
        theme: str | None = None,
    ) -> None:
        """Send a boot/apply request to the browser runtime."""
        command = (
            'window.MeshCoreLeafletBoot && '
            f'window.MeshCoreLeafletBoot({json.dumps(self._container_id)}, '
            f'{json.dumps(snapshot)}, {json.dumps(theme)});'
        )
        ui.run_javascript(command)

    @staticmethod
    def _inject_assets() -> None:
        """Load Leaflet assets and the custom runtime exactly once per page."""
        ui.add_head_html(
            r'''
<script>
(function () {
  const ASSET_STATE = window.__meshcoreLeafletAssets = window.__meshcoreLeafletAssets || {
    panelRequested: false,
  };

  function ensureStylesheet(id, href) {
    if (document.getElementById(id)) {
      return;
    }
    const link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function ensureScript(id, src, onload) {
    const existing = document.getElementById(id);
    if (existing) {
      if (onload) {
        if (existing.dataset.loaded === 'true') {
          onload();
        } else {
          existing.addEventListener('load', onload, { once: true });
        }
      }
      return;
    }
    const script = document.createElement('script');
    script.id = id;
    script.src = src;
    script.async = false;
    script.addEventListener('load', function () {
      script.dataset.loaded = 'true';
      if (onload) {
        onload();
      }
    }, { once: true });
    document.head.appendChild(script);
  }

  function ensurePanelRuntime() {
    if (ASSET_STATE.panelRequested) {
      return;
    }
    ASSET_STATE.panelRequested = true;
    ensureScript(
      'meshcore-leaflet-panel-js',
      '/static/leaflet_map_panel.js'
    );
  }

  ensureStylesheet(
    'meshcore-leaflet-vendor-css',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
  );
  ensureStylesheet(
    'meshcore-leaflet-markercluster-css',
    'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css'
  );
  ensureStylesheet(
    'meshcore-leaflet-markercluster-default-css',
    'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css'
  );
  ensureStylesheet(
    'meshcore-leaflet-panel-css',
    '/static/leaflet_map_panel.css'
  );

  ensureScript(
    'meshcore-leaflet-vendor-js',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
    function () {
      ensureScript(
        'meshcore-leaflet-markercluster-js',
        'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js',
        ensurePanelRuntime
      );
    }
  );
})();
</script>
'''
        )
