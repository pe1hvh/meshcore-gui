"""
Route visualization page for MeshCore GUI.

Standalone NiceGUI page that opens in a new browser tab when a user
clicks on a message.  Shows a Leaflet map with the message route,
a hop count summary, and a details table.
"""

from typing import Dict

from nicegui import ui

from meshcore_gui.config import TYPE_LABELS, debug_print
from meshcore_gui.route_builder import RouteBuilder
from meshcore_gui.protocols import SharedDataReadAndLookup


class RoutePage:
    """
    Route visualization page rendered at ``/route/{msg_index}``.

    Args:
        shared: SharedDataReadAndLookup for data access and contact lookups
    """

    def __init__(self, shared: SharedDataReadAndLookup) -> None:
        self._shared = shared
        self._builder = RouteBuilder(shared)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def render(self, msg_index: int) -> None:
        """
        Render the route page for a specific message.

        Args:
            msg_index: Index into SharedData.messages list
        """
        data = self._shared.get_snapshot()

        # Validate
        if msg_index < 0 or msg_index >= len(data['messages']):
            ui.label('❌ Message not found').classes('text-xl p-8')
            return

        msg = data['messages'][msg_index]
        route = self._builder.build(msg, data)

        sender = msg.get('sender', 'Unknown')
        ui.page_title(f'Route — {sender}')
        ui.dark_mode(False)

        # Header
        with ui.header().classes('bg-blue-600 text-white'):
            ui.label('🗺️ MeshCore Route').classes('text-xl font-bold')

        with ui.column().classes('w-full max-w-4xl mx-auto p-4 gap-4'):
            self._render_message_info(msg)
            self._render_hop_summary(msg, route)
            self._render_map(data, route)
            self._render_route_table(msg, data, route)

    # ------------------------------------------------------------------
    # Private — sub-sections
    # ------------------------------------------------------------------

    @staticmethod
    def _render_message_info(msg: Dict) -> None:
        """Message header with sender name and text."""
        sender = msg.get('sender', 'Unknown')
        direction = '→ Sent' if msg['direction'] == 'out' else '← Received'
        ui.label(f'Message Route — {sender} ({direction})').classes('font-bold text-lg')
        ui.label(
            f"{msg['time']}  {sender}: "
            f"{msg['text'][:120]}"
        ).classes('text-sm text-gray-600')

    @staticmethod
    def _render_hop_summary(msg: Dict, route: Dict) -> None:
        """Hop count banner with SNR and path source."""
        msg_path_len = route['msg_path_len']
        resolved_hops = len(route['path_nodes'])
        path_source = route.get('path_source', 'none')
        expected_repeaters = max(msg_path_len - 1, 0)

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-4'):
                if msg['direction'] == 'in':
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

            # Resolution status
            if expected_repeaters > 0 and resolved_hops > 0:
                source_label = (
                    'from received packet'
                    if path_source == 'rx_log'
                    else 'from stored contact route'
                )
                rpt = 'repeater' if expected_repeaters == 1 else 'repeaters'
                ui.label(
                    f'✅ {resolved_hops} of {expected_repeaters} '
                    f'{rpt} identified '
                    f'({source_label})'
                ).classes('text-xs text-gray-500 mt-1')
            elif msg_path_len > 0 and resolved_hops == 0:
                ui.label(
                    f'ℹ️ {msg_path_len} '
                    f'hop{"s" if msg_path_len != 1 else ""} — '
                    f'repeater identities not resolved'
                ).classes('text-xs text-gray-500 mt-1')

    @staticmethod
    def _render_map(data: Dict, route: Dict) -> None:
        """Leaflet map with route markers and polylines.

        Lines are only drawn between nodes that are **adjacent** in the
        route and both have GPS coordinates.  A node without coordinates
        breaks the line so that no false connections are shown.
        """
        with ui.card().classes('w-full'):
            if not route['has_locations']:
                ui.label(
                    '📍 No location data available for map display'
                ).classes('text-gray-500 italic p-4')
                return

            center_lat = data['adv_lat'] or 52.5
            center_lon = data['adv_lon'] or 6.0

            route_map = ui.leaflet(
                center=(center_lat, center_lon), zoom=10
            ).classes('w-full h-96')

            # --- Build ordered list of positions (or None) ---
            ordered = []

            # Sender
            if route['sender']:
                s = route['sender']
                if s['lat'] or s['lon']:
                    ordered.append((s['lat'], s['lon']))
                else:
                    ordered.append(None)
            else:
                ordered.append(None)

            # Repeaters
            for node in route['path_nodes']:
                if node['lat'] or node['lon']:
                    ordered.append((node['lat'], node['lon']))
                else:
                    ordered.append(None)

            # Own position (receiver)
            if data['adv_lat'] or data['adv_lon']:
                ordered.append((data['adv_lat'], data['adv_lon']))
            else:
                ordered.append(None)

            # --- Place markers for all nodes with coordinates ---
            all_points = [p for p in ordered if p is not None]
            for lat, lon in all_points:
                route_map.marker(latlng=(lat, lon))

            # --- Draw line between all located nodes (skip unknowns) ---
            # Nodes without coordinates are simply skipped so the line
            # connects sender → known repeaters → receiver without gaps.
            if len(all_points) >= 2:
                route_map.generic_layer(
                    name='polyline',
                    args=[all_points, {'color': '#2563eb', 'weight': 3}],
                )

            # Center map on all located nodes
            if all_points:
                lats = [p[0] for p in all_points]
                lons = [p[1] for p in all_points]
                route_map.set_center(
                    (sum(lats) / len(lats), sum(lons) / len(lons))
                )

    @staticmethod
    def _render_route_table(msg: Dict, data: Dict, route: Dict) -> None:
        """Route details table with sender, hops and receiver."""
        msg_path_len = route['msg_path_len']
        resolved_hops = len(route['path_nodes'])
        path_source = route.get('path_source', 'none')

        with ui.card().classes('w-full'):
            ui.label('📋 Route Details').classes('font-bold text-gray-600')

            rows = []

            # Sender
            if route['sender']:
                s = route['sender']
                has_loc = s['lat'] != 0 or s['lon'] != 0
                rows.append({
                    'hop': 'Start',
                    'name': s['name'],
                    'hash': s.get('pubkey', '')[:2].upper() if s.get('pubkey') else '-',
                    'type': TYPE_LABELS.get(s['type'], '-'),
                    'location': f"{s['lat']:.4f}, {s['lon']:.4f}" if has_loc else '-',
                    'role': '📱 Sender',
                })
            else:
                sender_pubkey = msg.get('sender_pubkey', '')
                rows.append({
                    'hop': 'Start',
                    'name': msg.get('sender', 'Unknown'),
                    'hash': sender_pubkey[:2].upper() if sender_pubkey else '-',
                    'type': '-',
                    'location': '-',
                    'role': '📱 Sender',
                })

            # Resolved repeaters (from RX_LOG or out_path)
            for i, node in enumerate(route['path_nodes']):
                has_loc = node['lat'] != 0 or node['lon'] != 0
                rows.append({
                    'hop': str(i + 1),
                    'name': node['name'],
                    'hash': node.get('pubkey', '')[:2].upper() if node.get('pubkey') else '-',
                    'type': TYPE_LABELS.get(node['type'], '-'),
                    'location': f"{node['lat']:.4f}, {node['lon']:.4f}" if has_loc else '-',
                    'role': '📡 Repeater',
                })

            # Placeholder rows when no path data was resolved
            if not route['path_nodes'] and msg_path_len > 0:
                for i in range(msg_path_len):
                    rows.append({
                        'hop': str(i + 1),
                        'name': '-',
                        'hash': '-',
                        'type': '-',
                        'location': '-',
                        'role': '📡 Repeater',
                    })

            # Own position
            self_has_loc = data['adv_lat'] != 0 or data['adv_lon'] != 0
            rows.append({
                'hop': 'End',
                'name': data['name'] or 'Me',
                'hash': '-',
                'type': 'Companion',
                'location': f"{data['adv_lat']:.4f}, {data['adv_lon']:.4f}" if self_has_loc else '-',
                'role': '📱 Receiver' if msg['direction'] == 'in' else '📱 Sender',
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

            # Footnote based on path_source
            if msg_path_len == 0 and msg['direction'] == 'in':
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
                    'ℹ️ Repeater identities could not be resolved. '
                    'RX_LOG correlation may have missed the raw packet, '
                    'and sender has no stored out_path.'
                ).classes('text-xs text-gray-400 italic mt-2')
            elif msg['direction'] == 'out':
                ui.label(
                    'ℹ️ Hop information is only available for received messages.'
                ).classes('text-xs text-gray-400 italic mt-2')
