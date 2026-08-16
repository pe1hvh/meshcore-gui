"""
Route visualization page for MeshCore GUI.

Standalone NiceGUI page that shows a Leaflet map with the message
route, a hop count summary, and a details table.

v4.1 changes
~~~~~~~~~~~~~
- Uses :class:`~meshcore_gui.models.Message` and
  :class:`~meshcore_gui.models.RouteNode` instead of plain dicts.
"""

import json
from typing import Dict, List, Optional
from uuid import uuid4

from nicegui import ui

from meshcore_gui.gui.constants import (
    get_type_display,
    get_type_icon,
    get_type_label,
    resolve_contact_icon,
)
from meshcore_gui.gui.dashboard import _DOMCA_HEAD
from meshcore_gui.config import DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM
from meshcore_gui.core.models import Message, RouteNode
from meshcore_gui.services.route_builder import RouteBuilder
from meshcore_gui.core.protocols import SharedDataReadAndLookup


_ROUTE_MAP_ASSETS = r"""
<script>
(function () {
  if (window.__meshcoreLeafletAssetsRequested) {
    return;
  }
  window.__meshcoreLeafletAssetsRequested = true;

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

  ensureStylesheet('meshcore-leaflet-vendor-css', 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
  ensureStylesheet('meshcore-leaflet-markercluster-css', 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css');
  ensureStylesheet('meshcore-leaflet-markercluster-default-css', 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css');
  ensureStylesheet('meshcore-leaflet-panel-css', '/static/leaflet_map_panel.css');

  ensureScript('meshcore-leaflet-vendor-js', 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', function () {
    ensureScript('meshcore-leaflet-panel-js', '/static/leaflet_map_panel.js');
    ensureScript('meshcore-leaflet-markercluster-js', 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js');
  });
})();
</script>
"""


class RoutePage:
    """
    Route visualization page rendered at ``/route/{msg_index}``.

    Args:
        shared: SharedDataReadAndLookup for data access and contact lookups
    """

    def __init__(self, shared: SharedDataReadAndLookup) -> None:
        self._shared = shared
        self._builder = RouteBuilder(shared)

    def render(self, msg_key: str) -> None:
        """Render the route page for a message."""
        data = self._shared.get_snapshot()
        messages: List[Message] = data['messages']
        msg: Optional[Message] = None

        try:
            idx = int(msg_key)
            if 0 <= idx < len(messages):
                msg = messages[idx]
        except (ValueError, TypeError):
            pass

        if msg is None and msg_key:
            for message in messages:
                if message.message_hash and message.message_hash == msg_key:
                    msg = message
                    break

        if msg is None and msg_key:
            archive = data.get('archive')
            if archive:
                msg_dict = archive.get_message_by_hash(msg_key)
                if msg_dict:
                    msg = Message.from_dict(msg_dict)

        if msg is None:
            ui.label('❌ Message not found').classes('text-xl p-8')
            ui.button('Back to Dashboard', on_click=lambda: ui.navigate.to('/')).classes(
                'mt-4'
            )
            return

        route = self._builder.build(msg, data)
        route['message'] = msg

        ui.page_title(f'Route — {msg.sender or "Unknown"}')
        ui.add_head_html(_DOMCA_HEAD)
        ui.add_head_html(_ROUTE_MAP_ASSETS)
        ui.dark_mode(True)

        with ui.header().classes('items-center px-4 py-2 shadow-md'):
            ui.button(
                icon='arrow_back',
                on_click=lambda: ui.run_javascript('window.history.back()'),
            ).props('flat round dense color=white').tooltip('Back')
            ui.label('🗺️ MeshCore Route').classes(
                'text-lg font-bold domca-header-text'
            ).style("font-family: 'JetBrains Mono', monospace")
            ui.space()
            ui.label('Route Detail').classes('text-sm opacity-70 domca-header-text')

        with ui.column().classes('domca-panel gap-4').style('padding-top: 1rem'):
            self._render_message_info(msg, data)
            self._render_hop_summary(msg, route)
            self._render_map(data, route)
            self._render_send_panel(msg, data)
            self._render_route_table(msg, data, route)

    @staticmethod
    def _render_message_info(msg: Message, data: Dict) -> None:
        sender = msg.sender or 'Unknown'
        direction = '→ Sent' if msg.direction == 'out' else '← Received'
        sender_icon = resolve_contact_icon(
            data.get('contacts', {}),
            pubkey=msg.sender_pubkey,
            name=msg.sender,
            fallback_type=1 if msg.direction == 'out' else None,
        )
        ui.label(
            f'Message Route — {sender_icon} {sender} ({direction})'
        ).classes('font-bold text-lg')
        ui.label(
            f"{msg.display_timestamp()}  {sender_icon} {sender}: {msg.text[:120]}"
        ).classes('text-sm text-gray-600')

    @staticmethod
    def _render_hop_summary(msg: Message, route: Dict) -> None:
        msg_path_len = route['msg_path_len']
        path_nodes: List[RouteNode] = route['path_nodes']
        resolved_hops = len(path_nodes)
        path_source = route.get('path_source', 'none')
        expected_repeaters = max(msg_path_len - 1, 0)

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-4'):
                if msg.direction == 'in':
                    if msg_path_len == 0:
                        ui.label('📡 Direct (0 hops)').classes(
                            'text-lg font-bold text-green-600'
                        )
                    else:
                        hop_text = '1 hop' if msg_path_len == 1 else f'{msg_path_len} hops'
                        ui.label(f'📡 {hop_text}').classes(
                            'text-lg font-bold text-blue-600'
                        )
                else:
                    ui.label('📡 Outgoing message').classes(
                        'text-lg font-bold text-gray-600'
                    )

                if route['snr'] is not None:
                    ui.label(
                        f'📶 SNR: {route["snr"]:.1f} dB'
                    ).classes('text-sm text-gray-600')

            if expected_repeaters > 0 and resolved_hops > 0:
                source_label = (
                    'from received packet'
                    if path_source == 'rx_log'
                    else 'from stored contact route'
                )
                rpt = 'repeater' if expected_repeaters == 1 else 'repeaters'
                ui.label(
                    f'✅ {resolved_hops} of {expected_repeaters} '
                    f'{rpt} identified ({source_label})'
                ).classes('text-xs text-gray-500 mt-1')
            elif msg_path_len > 0 and resolved_hops == 0:
                ui.label(
                    f'ℹ️ {msg_path_len} '
                    f'hop{"s" if msg_path_len != 1 else ""} — '
                    f'repeater identities not resolved'
                ).classes('text-xs text-gray-500 mt-1')

    @staticmethod
    def _render_map(data: Dict, route: Dict) -> None:
        """Render the route map in browser JS using the shared MAP icons.

        The Leaflet container is always rendered.  When no nodes carry GPS
        coordinates a notice is shown inside the card, but the map itself
        still initialises so the user sees the configured home area.
        MeshCoreRouteMapBoot handles an empty nodes array gracefully by
        displaying the map at payload.center with no markers.
        """
        with ui.card().classes('w-full'):
            payload = RoutePage._build_route_map_payload(data, route)

            # Show a notice when no node carries GPS, but do NOT skip the
            # Leaflet container.  The JS runtime renders the map at the
            # configured home area (DEFAULT_MAP_CENTER) with no markers.
            if not payload['nodes']:
                ui.label(
                    '📍 No GPS location data — map shows home area'
                ).classes('text-xs text-gray-400 italic px-2 pt-2')

            container_id = f'route-map-{uuid4().hex}'
            ui.element('div').props(f'id={container_id}').classes(
                'w-full'
            ).style('height:24rem;border-radius:0.5rem;overflow:hidden;')

            boot_script = (
                '(function bootRouteMap(retries){'
                f'const id={json.dumps(container_id)};'
                f'const payload={json.dumps(payload, ensure_ascii=False)};'
                "if(typeof window.MeshCoreRouteMapBoot==='function'){window.MeshCoreRouteMapBoot(id,payload);return;}"
                "if(retries>120){console.error('MeshCoreRouteMapBoot unavailable',{id});return;}"
                'window.setTimeout(function(){bootRouteMap(retries+1);},60);'
                '})(0);'
            )
            ui.timer(0.1, lambda script=boot_script: ui.run_javascript(script), once=True)

    @staticmethod
    def _build_route_map_payload(data: Dict, route: Dict) -> Dict:
        """Build the JS payload for the route map using shared node types."""
        nodes = []

        sender: RouteNode = route['sender']
        if sender and sender.has_location:
            nodes.append({
                'name': sender.name or 'Unknown',
                'lat': sender.lat,
                'lon': sender.lon,
                'node_type': int(sender.type or 0),
                'short_key': sender.pubkey[:2].upper() if sender.pubkey else '-',
                'role': get_type_label(sender.type),
            })
        elif sender is None:
            fallback_contact = RoutePage._find_sender_contact(
                route['message'],
                data.get('contacts', {}),
            )
            if fallback_contact:
                fb_key, fb_contact = fallback_contact
                fb_lat = fb_contact.get('adv_lat', 0)
                fb_lon = fb_contact.get('adv_lon', 0)
                if fb_lat or fb_lon:
                    fb_type = int(fb_contact.get('type', 0) or 0)
                    nodes.append({
                        'name': fb_contact.get('adv_name') or route['message'].sender or 'Unknown',
                        'lat': fb_lat,
                        'lon': fb_lon,
                        'node_type': fb_type,
                        'short_key': fb_key[:2].upper() if fb_key else '-',
                        'role': get_type_label(fb_type),
                    })

        for node in route['path_nodes']:
            if not node.has_location:
                continue
            nodes.append({
                'name': node.name or 'Unknown',
                'lat': node.lat,
                'lon': node.lon,
                'node_type': int(node.type or 0),
                'short_key': node.pubkey[:2].upper() if node.pubkey else '-',
                'role': get_type_label(node.type),
            })

        self_node: RouteNode = route['self_node']
        if self_node.has_location:
            self_type = int(self_node.type or 1)
            nodes.append({
                'name': self_node.name or 'Local device',
                'lat': self_node.lat,
                'lon': self_node.lon,
                'node_type': self_type,
                'short_key': '-',
                'role': get_type_label(self_type),
            })

        return {
            'center': [
                data['adv_lat'] or DEFAULT_MAP_CENTER[0],
                data['adv_lon'] or DEFAULT_MAP_CENTER[1],
            ],
            'zoom': DEFAULT_MAP_ZOOM,
            'nodes': nodes,
        }

    @staticmethod
    def _render_route_table(msg: Message, data: Dict, route: Dict) -> None:
        msg_path_len = route['msg_path_len']
        path_nodes: List[RouteNode] = route['path_nodes']
        resolved_hops = len(path_nodes)
        path_source = route.get('path_source', 'none')

        with ui.card().classes('w-full'):
            ui.label('📋 Route Details').classes('font-bold text-gray-600')

            rows = []
            sender: RouteNode = route['sender']
            if sender:
                rows.append({
                    'hop': 'Start',
                    'name': sender.name,
                    'hash': sender.pubkey[:2].upper() if sender.pubkey else '-',
                    'type': get_type_display(sender.type),
                    'location': f"{sender.lat:.4f}, {sender.lon:.4f}" if sender.has_location else '-',
                    'role': f'{get_type_icon(sender.type)} Sender',
                })
            else:
                fallback_contact = RoutePage._find_sender_contact(msg, data.get('contacts', {}))
                if fallback_contact:
                    fb_key, fb_contact = fallback_contact
                    fb_lat = fb_contact.get('adv_lat', 0)
                    fb_lon = fb_contact.get('adv_lon', 0)
                    fb_has_loc = fb_lat != 0 or fb_lon != 0
                    fb_type = int(fb_contact.get('type', 0) or 0)
                    rows.append({
                        'hop': 'Start',
                        'name': fb_contact.get('adv_name') or msg.sender or 'Unknown',
                        'hash': fb_key[:2].upper() if fb_key else '-',
                        'type': get_type_display(fb_type),
                        'location': f"{fb_lat:.4f}, {fb_lon:.4f}" if fb_has_loc else '-',
                        'role': f'{get_type_icon(fb_type)} Sender',
                    })
                else:
                    rows.append({
                        'hop': 'Start',
                        'name': msg.sender or 'Unknown',
                        'hash': msg.sender_pubkey[:2].upper() if msg.sender_pubkey else '-',
                        'type': get_type_display(0),
                        'location': '-',
                        'role': f'{get_type_icon(0)} Sender',
                    })

            for index, node in enumerate(path_nodes):
                rows.append({
                    'hop': str(index + 1),
                    'name': node.name,
                    'hash': node.pubkey[:2].upper() if node.pubkey else '-',
                    'type': get_type_display(node.type),
                    'location': f"{node.lat:.4f}, {node.lon:.4f}" if node.has_location else '-',
                    'role': f'{get_type_icon(node.type)} Repeater',
                })

            if not path_nodes and 0 < msg_path_len < 255:
                for index in range(msg_path_len):
                    rows.append({
                        'hop': str(index + 1),
                        'name': '-',
                        'hash': '-',
                        'type': get_type_display(0),
                        'location': '-',
                        'role': f'{get_type_icon(0)} Repeater',
                    })

            self_node: RouteNode = route['self_node']
            self_type = int(self_node.type or 1)
            rows.append({
                'hop': 'End',
                'name': self_node.name,
                'hash': '-',
                'type': get_type_display(self_type),
                'location': f"{self_node.lat:.4f}, {self_node.lon:.4f}" if self_node.has_location else '-',
                'role': f'{get_type_icon(self_type)} Receiver' if msg.direction == 'in' else f'{get_type_icon(self_type)} Sender',
            })

            ui.table(
                columns=[
                    {'name': 'hop', 'label': 'Hop', 'field': 'hop', 'align': 'center'},
                    {'name': 'role', 'label': 'Role', 'field': 'role'},
                    {'name': 'name', 'label': 'Name', 'field': 'name'},
                    {'name': 'hash', 'label': 'ID', 'field': 'hash', 'align': 'center'},
                    {'name': 'type', 'label': 'Type', 'field': 'type'},
                    {'name': 'location', 'label': 'Location', 'field': 'location'},
                ],
                rows=rows,
            ).props('dense flat bordered').classes('w-full')

            if msg_path_len == 0 and msg.direction == 'in':
                ui.label(
                    'ℹ️ Direct message — no intermediate hops.'
                ).classes('text-xs text-gray-400 italic mt-2')
            elif path_source == 'rx_log':
                ui.label(
                    'ℹ️ Path extracted from received LoRa packet (RX_LOG). '
                    'Each ID is the first byte of a node\'s public key.'
                ).classes('text-xs text-gray-400 italic mt-2')
            elif path_source == 'contact_out_path':
                ui.label(
                    'ℹ️ Path from sender\'s stored contact route (out_path). '
                    'Last known route, not necessarily this message\'s path.'
                ).classes('text-xs text-gray-400 italic mt-2')
            elif msg_path_len > 0 and resolved_hops == 0:
                ui.label(
                    'ℹ️ Repeater identities could not be resolved.'
                ).classes('text-xs text-gray-400 italic mt-2')
            elif msg.direction == 'out':
                ui.label(
                    'ℹ️ Hop information is only available for received messages.'
                ).classes('text-xs text-gray-400 italic mt-2')

    def _render_send_panel(self, msg: Message, data: Dict) -> None:
        """Send widget pre-filled with route acknowledgement message."""
        path_hashes = msg.path_hashes

        parts = [f"@[{msg.sender or 'Unknown'}] Received in Zwolle path({msg.path_len})"]
        if path_hashes:
            path_str = '>'.join(h.upper() for h in path_hashes)
            parts.append(f'; {path_str}')
        prefilled = ''.join(parts)

        ch_options = {ch['idx']: f"[{ch['idx']}] {ch['name']}" for ch in data['channels']}
        default_ch = self._default_reply_channel(msg, ch_options)

        with ui.card().classes('w-full'):
            ui.label('📤 Reply').classes('font-bold text-gray-600')
            with ui.row().classes('w-full items-center gap-2'):
                msg_input = ui.input(value=prefilled).classes('flex-grow')
                ch_select = ui.select(options=ch_options, value=default_ch).classes('w-32')

                def send(inp=msg_input, sel=ch_select):
                    text = inp.value
                    if text:
                        self._shared.put_command({
                            'action': 'send_message',
                            'channel': sel.value,
                            'text': text,
                        })
                        inp.value = ''

                ui.button('Send', on_click=send).classes('bg-blue-500 text-white')

    @staticmethod
    def _default_reply_channel(msg: Message, ch_options: Dict[int, str]) -> int:
        """Determine the channel the reply select should default to.

        The reply belongs on the channel the message arrived on, so that
        opening the route page from e.g. ``#noodnet-ov`` pre-selects that
        channel instead of the first entry in the channel list.

        Falls back to the first available channel when the message is a
        DM (``channel is None``) or when its channel index is no longer
        present on the device — a slot can be vacated by the
        post-discovery cache sync introduced in 1.22.2.

        Args:
            msg:        The message this route page was opened for.
            ch_options: ``{channel_idx: label}`` options for the select.

        Returns:
            Channel index to pre-select.
        """
        if msg.channel is not None and msg.channel in ch_options:
            return msg.channel
        return next(iter(ch_options), 0)

    @staticmethod
    def _find_sender_contact(msg: Message, contacts: Dict) -> Optional[tuple]:
        """Defensive fallback: find sender contact data in snapshot."""
        if msg.sender_pubkey:
            pk_lower = msg.sender_pubkey.lower()
            for key, contact in contacts.items():
                key_lower = key.lower()
                if key_lower.startswith(pk_lower) or pk_lower.startswith(key_lower):
                    return (key, contact)

        if msg.sender:
            name_lower = msg.sender.lower()
            for key, contact in contacts.items():
                adv_name = contact.get('adv_name', '')
                if adv_name and adv_name.lower() == name_lower:
                    return (key, contact)

        return None
