(function () {
  const DEFAULT_CENTER = [52.5164, 6.083];
  const DEFAULT_ZOOM = 13;
  const RETRY_DELAY_MS = 60;
  const MAX_RETRIES = 200;

  const PANEL = window.MeshCoreLeafletPanel = window.MeshCoreLeafletPanel || {};
  const maps = PANEL.maps = PANEL.maps || new Map();
  const pending = PANEL.pending = PANEL.pending || new Map();
  const watchers = PANEL.watchers = PANEL.watchers || new Map();
  const preferences = PANEL.preferences = PANEL.preferences || new Map();
  const THEME_STORAGE_KEY = 'meshcore_leaflet_theme';

  function loadStoredTheme() {
    try {
      return window.localStorage ? window.localStorage.getItem(THEME_STORAGE_KEY) : null;
    } catch (error) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      if (!window.localStorage) {
        return;
      }
      if (theme) {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
      } else {
        window.localStorage.removeItem(THEME_STORAGE_KEY);
      }
    } catch (error) {
      // ignore storage errors
    }
  }

  PANEL.ensureMap = function (containerId) {
    const existing = maps.get(containerId);
    const host = document.getElementById(containerId);

    if (!host || typeof window.L === 'undefined' || typeof window.L.markerClusterGroup !== 'function') {
      return null;
    }

    // Do not initialize the Leaflet map while the host container has no
    // rendered dimensions.  This happens when the map panel is hidden at
    // page load (display:none via Vue v-show).  Calling L.map() on a
    // zero-size element produces a broken map that never recovers.
    // processPending will retry on the next scheduled tick once the panel
    // becomes visible and the host gains real dimensions.
    if (!existing && host.clientWidth === 0 && host.clientHeight === 0) {
      return null;
    }

    if (existing) {
      if (existing.host !== host) {
        if (existing.resizeObserver) {
          existing.resizeObserver.disconnect();
        }
        existing.host = host;
        host.__meshcoreLeafletState = existing;
      }
      PANEL.invalidate(containerId);
      return existing;
    }

    if (host.__meshcoreLeafletState) {
      maps.set(containerId, host.__meshcoreLeafletState);
      PANEL.invalidate(containerId);
      return host.__meshcoreLeafletState;
    }

    if (host._leaflet_id) {
      throw new Error('Leaflet host already has a map but MeshCore runtime has no state; hard refresh required after previous failed init.');
    }

    const map = window.L.map(host, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      minZoom: 2,
      maxZoom: 19,
      zoomControl: true,
      preferCanvas: true,
    });

    const state = {
      containerId,
      map,
      host,
      theme: null,
      layers: {
        base: null,
        contacts: null,
        device: window.L.layerGroup().addTo(map),
      },
      contactMarkers: new Map(),
      deviceMarker: null,
      hasCentered: false,
      pendingInvalidate: false,
      userInteracting: false,
      interactionCooldownTimer: null,
      resizeObserver: null,
      lastCenter: map.getCenter(),
      lastZoom: map.getZoom(),
    };

    maps.set(containerId, state);
    host.__meshcoreLeafletState = state;

    try {
      state.layers.base = window.L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          maxZoom: 19,
        }
      ).addTo(map);
      state.theme = 'light';

      state.layers.contacts = window.L.markerClusterGroup({
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
        animate: false,
        chunkedLoading: true,
        maxClusterRadius: 50,
        iconCreateFunction(cluster) {
          return window.L.divIcon({
            html: '<div><span>' + cluster.getChildCount() + '</span></div>',
            className: 'meshcore-marker-cluster',
            iconSize: window.L.point(42, 42),
          });
        },
      }).addTo(map);
    } catch (error) {
      maps.delete(containerId);
      delete host.__meshcoreLeafletState;
      try {
        map.remove();
      } catch (removeError) {
        console.warn('Leaflet cleanup after failed init also failed', removeError);
      }
      throw error;
    }

    map.on('zoomstart movestart dragstart resize', () => {
      state.userInteracting = true;
      if (state.interactionCooldownTimer) {
        window.clearTimeout(state.interactionCooldownTimer);
        state.interactionCooldownTimer = null;
      }
    });

    const endInteraction = function () {
      state.lastCenter = state.map.getCenter();
      state.lastZoom = state.map.getZoom();
      if (state.interactionCooldownTimer) {
        window.clearTimeout(state.interactionCooldownTimer);
      }
      state.interactionCooldownTimer = window.setTimeout(() => {
        state.userInteracting = false;
        state.interactionCooldownTimer = null;
      }, 350);
    };

    map.on('zoomend moveend dragend', endInteraction);

    if (window.ResizeObserver) {
      state.resizeObserver = new window.ResizeObserver(() => {
        PANEL.invalidate(containerId);
      });
      state.resizeObserver.observe(host);
    }

    const preference = preferences.get(containerId) || {};
    if (!preference.theme) {
      const storedTheme = loadStoredTheme();
      if (storedTheme) {
        preference.theme = storedTheme;
        preferences.set(containerId, preference);
      }
    }
    if (preference.theme) {
      PANEL.setTheme(containerId, preference.theme);
    }

    PANEL.invalidate(containerId);
    return state;
  };

  PANEL.invalidate = function (containerId) {
    const state = maps.get(containerId);
    if (!state || state.pendingInvalidate) {
      return;
    }
    state.pendingInvalidate = true;
    window.requestAnimationFrame(() => {
      state.pendingInvalidate = false;
      try {
        state.map.invalidateSize({ pan: false, debounceMoveend: true });
      } catch (error) {
        console.warn('Leaflet invalidateSize failed', error);
      }
    });
  };

  PANEL.setTheme = function (containerId, theme) {
    const state = maps.get(containerId);
    if (!state || !theme || state.theme === theme || typeof window.L === 'undefined') {
      return;
    }

    if (state.layers.base) {
      state.map.removeLayer(state.layers.base);
      state.layers.base = null;
    }

    const dark = theme === 'dark';
    const url = dark
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    const options = dark
      ? {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
          maxZoom: 20,
        }
      : {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          maxZoom: 19,
        };

    state.layers.base = window.L.tileLayer(url, options).addTo(state.map);
    state.theme = theme;
    storeTheme(theme);
  };

  PANEL.centerOnDevice = function (containerId) {
    const state = maps.get(containerId);
    if (!state || !state.deviceMarker) {
      return;
    }
    const latLng = state.deviceMarker.getLatLng();
    state.map.setView(latLng, state.map.getZoom(), { animate: false });
    state.lastCenter = latLng;
    state.lastZoom = state.map.getZoom();
    state.hasCentered = true;
  };

  PANEL.applySnapshot = function (containerId, snapshot) {
    const state = maps.get(containerId);
    if (!state || !snapshot) {
      return;
    }

    const preference = preferences.get(containerId);
    if (preference && preference.theme) {
      PANEL.setTheme(containerId, preference.theme);
    }

    applyDevice(state, snapshot.device);
    applyContacts(state, snapshot.contacts || []);

    const shouldCenter = Boolean(
      state.deviceMarker &&
      !state.userInteracting &&
      (snapshot.force_center || !state.hasCentered)
    );

    if (shouldCenter) {
      const latLng = state.deviceMarker.getLatLng();
      state.map.setView(latLng, state.map.getZoom(), { animate: false });
      state.lastCenter = latLng;
      state.lastZoom = state.map.getZoom();
      state.hasCentered = true;
    }
  };

  function applyDevice(state, device) {
    if (!device) {
      if (state.deviceMarker) {
        state.layers.device.removeLayer(state.deviceMarker);
        state.deviceMarker = null;
      }
      return;
    }

    const icon = buildIcon('📡', 'is-device', 'Device', [40, 40], [20, 20]);
    const latLng = [device.lat, device.lon];
    const popupHtml = popup(device.name, 'Device', 'local');

    if (!state.deviceMarker) {
      state.deviceMarker = window.L.marker(latLng, {
        icon,
        keyboard: false,
        title: '📡 ' + device.name,
      });
      state.deviceMarker.bindPopup(popupHtml);
      state.layers.device.addLayer(state.deviceMarker);
      return;
    }

    state.deviceMarker.setLatLng(latLng);
    state.deviceMarker.setIcon(icon);
    state.deviceMarker.setPopupContent(popupHtml);
    state.deviceMarker.options.title = '📡 ' + device.name;
  }

  function applyContacts(state, contacts) {
    const nextIds = new Set();

    for (const contact of contacts) {
      nextIds.add(contact.id);
      const existing = state.contactMarkers.get(contact.id);
      const latLng = [contact.lat, contact.lon];
      const markerIcon = buildTypeIcon(contact.node_type);
      const markerTitle = markerTitlePrefix(contact.node_type) + ' ' + contact.name;
      const popupHtml = popup(contact.name, labelForType(contact.node_type), contact.short_key);

      if (!existing) {
        const marker = window.L.marker(latLng, {
          icon: markerIcon,
          keyboard: false,
          title: markerTitle,
        });
        marker.bindPopup(popupHtml);
        state.layers.contacts.addLayer(marker);
        state.contactMarkers.set(contact.id, marker);
        continue;
      }

      existing.setLatLng(latLng);
      existing.setIcon(markerIcon);
      existing.setPopupContent(popupHtml);
      existing.options.title = markerTitle;
      if (!state.layers.contacts.hasLayer(existing)) {
        state.layers.contacts.addLayer(existing);
      }
    }

    for (const [contactId, marker] of state.contactMarkers.entries()) {
      if (!nextIds.has(contactId)) {
        state.layers.contacts.removeLayer(marker);
        state.contactMarkers.delete(contactId);
      }
    }
  }

  function buildTypeIcon(nodeType) {
    switch (nodeType) {
      case 1:
        return buildIcon('📱', 'is-companion', 'Companion');
      case 2:
        return buildIcon('📡', 'is-repeater', 'Repeater');
      case 3:
        return buildIcon('🏠', 'is-room', 'Room Server');
      default:
        return buildIcon('○', 'is-unknown', 'Unknown');
    }
  }

  PANEL.buildTypeIcon = buildTypeIcon;
  PANEL.markerTitlePrefix = markerTitlePrefix;
  PANEL.labelForType = labelForType;
  PANEL.buildPopupHtml = popup;

  function markerTitlePrefix(nodeType) {
    switch (nodeType) {
      case 1:
        return '📱';
      case 2:
        return '📡';
      case 3:
        return '🏠';
      default:
        return '○';
    }
  }

  function labelForType(nodeType) {
    switch (nodeType) {
      case 1:
        return 'Companion';
      case 2:
        return 'Repeater';
      case 3:
        return 'Room Server';
      default:
        return 'Unknown';
    }
  }

  function buildIcon(symbol, extraClass, label, iconSize, iconAnchor) {
    const resolvedSize = iconSize || [34, 34];
    const resolvedAnchor = iconAnchor || [17, 17];

    return window.L.divIcon({
      className: '',
      html:
        '<div class="meshcore-leaflet-marker ' + extraClass + '" aria-label="' + label + '">' +
        symbol +
        '</div>',
      iconSize: resolvedSize,
      iconAnchor: resolvedAnchor,
      popupAnchor: [0, -16],
    });
  }

  function popup(name, label, shortKey) {
    return (
      '<div class="meshcore-leaflet-popup">' +
      '<strong>' + escapeHtml(name) + '</strong>' +
      '<div>Type: ' + escapeHtml(label) + '</div>' +
      '<div>Key: ' + escapeHtml(shortKey) + '</div>' +
      '</div>'
    );
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function scheduleProcess(containerId, retries) {
    window.requestAnimationFrame(() => {
      processPending(containerId, retries || 0);
    });
  }

  function processPending(containerId, retries) {
    const payload = pending.get(containerId);
    if (!payload) {
      return;
    }

    if (!isDomReady()) {
      if (retries >= MAX_RETRIES) {
        console.error('MeshCoreLeafletBoot timeout waiting for DOM readiness', { containerId });
        return;
      }
      window.setTimeout(() => {
        scheduleProcess(containerId, retries + 1);
      }, RETRY_DELAY_MS);
      return;
    }

    const host = document.getElementById(containerId);
    if (!host) {
      watchForHost(containerId, retries);
      return;
    }

    if (typeof window.L === 'undefined' || typeof window.L.markerClusterGroup !== 'function') {
      if (retries >= MAX_RETRIES) {
        console.error('MeshCoreLeafletBoot timeout waiting for Leaflet markercluster', { containerId });
        return;
      }
      window.setTimeout(() => {
        scheduleProcess(containerId, retries + 1);
      }, RETRY_DELAY_MS);
      return;
    }

    try {
      const state = PANEL.ensureMap(containerId);
      if (!state) {
        if (retries >= MAX_RETRIES) {
          console.error('MeshCoreLeafletBoot timeout waiting for visible map host', { containerId });
          return;
        }
        window.setTimeout(() => {
          scheduleProcess(containerId, retries + 1);
        }, RETRY_DELAY_MS);
        return;
      }
      const current = pending.get(containerId);
      if (!current) {
        return;
      }
      if (current.theme) {
        PANEL.setTheme(containerId, current.theme);
      }
      if (current.snapshot && current.snapshot.__command__ === 'center_on_device') {
        PANEL.centerOnDevice(containerId);
      } else if (current.snapshot && current.snapshot.__command__ === 'ensure_map') {
        // map has already been ensured above; no-op
      } else if (current.snapshot) {
        PANEL.applySnapshot(containerId, current.snapshot);
      }
      pending.delete(containerId);
    } catch (error) {
      console.error('MeshCoreLeafletBoot failed', error);
    }
  }

  function watchForHost(containerId, retries) {
    if (watchers.has(containerId)) {
      return;
    }

    const timer = window.setTimeout(() => {
      watchers.delete(containerId);
      const host = document.getElementById(containerId);
      if (host) {
        scheduleProcess(containerId, retries + 1);
        return;
      }
      if (retries >= MAX_RETRIES) {
        console.error('MeshCoreLeafletBoot timeout waiting for host element', { containerId });
        return;
      }
      scheduleProcess(containerId, retries + 1);
    }, RETRY_DELAY_MS);

    watchers.set(containerId, timer);
  }

  function isDomReady() {
    return document.readyState === 'interactive' || document.readyState === 'complete';
  }


  window.MeshCoreRouteMapBoot = function (containerId, payload) {
    if (!containerId || !payload) {
      return;
    }

    const host = document.getElementById(containerId);
    if (!host || typeof window.L === 'undefined') {
      window.setTimeout(() => window.MeshCoreRouteMapBoot(containerId, payload), RETRY_DELAY_MS);
      return;
    }

    if (host.__meshcoreRouteMap) {
      try {
        host.__meshcoreRouteMap.remove();
      } catch (error) {
        console.warn('MeshCoreRouteMap cleanup failed', error);
      }
      host.__meshcoreRouteMap = null;
      host.innerHTML = '';
    }

    const map = window.L.map(host, {
      center: payload.center || DEFAULT_CENTER,
      zoom: payload.zoom || DEFAULT_ZOOM,
      minZoom: 2,
      maxZoom: 19,
      zoomControl: true,
      preferCanvas: true,
    });
    host.__meshcoreRouteMap = map;

    window.L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }
    ).addTo(map);

    const points = [];
    for (const node of payload.nodes || []) {
      if (typeof node.lat !== 'number' || typeof node.lon !== 'number') {
        continue;
      }
      const latLng = [node.lat, node.lon];
      points.push(latLng);
      const nodeType = typeof node.node_type === 'number' ? node.node_type : 0;
      const name = node.name || 'Unknown';
      const shortKey = node.short_key || '-';
      const role = node.role || labelForType(nodeType);
      const marker = window.L.marker(latLng, {
        icon: buildTypeIcon(nodeType),
        keyboard: false,
        title: markerTitlePrefix(nodeType) + ' ' + name,
      });
      marker.bindPopup(popup(name, role, shortKey));
      marker.addTo(map);
    }

    if (points.length >= 2) {
      window.L.polyline(points, { color: '#2563eb', weight: 3 }).addTo(map);
      map.fitBounds(points, { padding: [24, 24], maxZoom: 16 });
    } else if (points.length === 1) {
      map.setView(points[0], payload.zoom || DEFAULT_ZOOM, { animate: false });
    }

    window.requestAnimationFrame(() => {
      try {
        map.invalidateSize({ pan: false, debounceMoveend: true });
      } catch (error) {
        console.warn('MeshCoreRouteMap invalidateSize failed', error);
      }
    });
  };

  window.MeshCoreLeafletBoot = function (containerId, snapshot, themeOnly) {
    const current = pending.get(containerId) || { snapshot: null, theme: null };
    const preference = preferences.get(containerId) || {};

    if (!preference.theme) {
      const storedTheme = loadStoredTheme();
      if (storedTheme) {
        preference.theme = storedTheme;
        preferences.set(containerId, preference);
      }
    }

    if (themeOnly) {
      preference.theme = themeOnly;
      preferences.set(containerId, preference);
      current.theme = themeOnly;
      storeTheme(themeOnly);
      if (maps.has(containerId)) {
        PANEL.setTheme(containerId, themeOnly);
      }
    } else if (!current.theme && preference.theme) {
      current.theme = preference.theme;
    }

    if (snapshot) {
      if (snapshot.__command__) {
        current.snapshot = snapshot;
      } else {
        current.snapshot = { ...snapshot };
      }
    }

    if (!current.snapshot && current.theme && !maps.has(containerId)) {
      pending.set(containerId, current);
      return;
    }

    pending.set(containerId, current);
    scheduleProcess(containerId, 0);
  };
})();
