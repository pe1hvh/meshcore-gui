"""
Route visualization page for MeshCore GUI.

Standalone NiceGUI page that shows a Leaflet map with the message
route, a hop count summary, and a details table.

v4.1 changes
~~~~~~~~~~~~~
- Uses :class:`~meshcore_gui.models.Message` and
  :class:`~meshcore_gui.models.RouteNode` instead of plain dicts.
"""

from typing import Dict, List, Optional

from nicegui import ui

from meshcore_gui.gui.constants import TYPE_LABELS
from meshcore_gui.gui.dashboard import _DOMCA_HEAD
from meshcore_gui.config import debug_print, DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM
from meshcore_gui.core.models import Message, RouteNode
from meshcore_gui.services.route_builder import RouteBuilder
from meshcore_gui.core.protocols import SharedDataReadAndLookup


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

    def render(self, msg_key: str) -> None:
        """Render the route page for a message.

        *msg_key* is either a numeric index (from the main page) or
        a message hash (from the archive page).  Numeric indices are
        resolved from the in-memory message list; hashes are looked up
        in the persistent archive as fallback.
        """
        data = self._shared.get_snapshot()
        messages: List[Message] = data['messages']
        msg: Optional[Message] = None

        # Strategy 1: numeric index (main page click)
        try:
            idx = int(msg_key)
            if 0 <= idx < len(messages):
                msg = messages[idx]
        except (ValueError, TypeError):
            pass

        # Strategy 2: message hash lookup in memory
        if msg is None and msg_key:
            for m in messages:
                if m.message_hash and m.message_hash == msg_key:
                    msg = m
                    break

        # Strategy 3: archive fallback (hash)
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

        ui.page_title(f'Route — {msg.sender or "Unknown"}')

        # DOMCA theme (consistent with dashboard)
        ui.add_head_html(_DOMCA_HEAD)
        ui.dark_mode(True)

        with ui.header().classes('items-center px-4 py-2 shadow-md'):
            ui.button(
                icon='arrow_back',
                on_click=lambda: ui.navigate.to('/'),
            ).props('flat round dense color=white').tooltip('Back to Dashboard')
            ui.button(
                icon='history',
                on_click=lambda: ui.navigate.to('/archive'),
            ).props('flat round dense color=white').tooltip('Back to Archive')
            ui.label('🗺️ MeshCore Route').classes(
                'text-lg font-bold domca-header-text'
            ).style("font-family: 'JetBrains Mono', monospace")
            ui.space()
            ui.label('Route Detail').classes('text-sm opacity-70 domca-header-text')

        with ui.column().classes('domca-panel gap-4').style('padding-top: 1rem'):
            self._render_message_info(msg)
            self._render_hop_summary(msg, route)
            self._render_map(data, route)
            self._render_send_panel(msg, route, data)
            self._render_route_table(msg, data, route)

    # ------------------------------------------------------------------
    # Private — sub-sections
    # ------------------------------------------------------------------

    @staticmethod
    def _render_message_info(msg: Message) -> None:
        sender = msg.sender or 'Unknown'
        direction = '→ Sent' if msg.direction == 'out' else '← Received'
        ui.label(f'Message Route — {sender} ({direction})').classes('font-bold text-lg')
        ui.label(
            f"{msg.time}  {sender}: {msg.text[:120]}"
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
        """Leaflet map with route markers and polylines."""
        with ui.card().classes('w-full'):
            if not route['has_locations']:
                ui.label(
                    '📍 No location data available for map display'
                ).classes('text-gray-500 italic p-4')
                return

            center_lat = data['adv_lat'] or DEFAULT_MAP_CENTER[0]
            center_lon = data['adv_lon'] or DEFAULT_MAP_CENTER[1]

            route_map = ui.leaflet(
                center=(center_lat, center_lon), zoom=DEFAULT_MAP_ZOOM
            ).classes('w-full h-96')

            # Build ordered list of positions (or None)
            ordered = []

            sender: RouteNode = route['sender']
            if sender:
                ordered.append((sender.lat, sender.lon) if sender.has_location else None)
            else:
                ordered.append(None)

            for node in route['path_nodes']:
                ordered.append((node.lat, node.lon) if node.has_location else None)

            self_node: RouteNode = route['self_node']
            if self_node.has_location:
                ordered.append((self_node.lat, self_node.lon))
            else:
                ordered.append(None)

            all_points = [p for p in ordered if p is not None]
            for lat, lon in all_points:
                route_map.marker(latlng=(lat, lon))

            if len(all_points) >= 2:
                route_map.generic_layer(
                    name='polyline',
                    args=[all_points, {'color': '#2563eb', 'weight': 3}],
                )

            if all_points:
                lats = [p[0] for p in all_points]
                lons = [p[1] for p in all_points]
                route_map.set_center(
                    (sum(lats) / len(lats), sum(lons) / len(lons))
                )

    @staticmethod
    def _render_route_table(msg: Message, data: Dict, route: Dict) -> None:
        msg_path_len = route['msg_path_len']
        path_nodes: List[RouteNode] = route['path_nodes']
        resolved_hops = len(path_nodes)
        path_source = route.get('path_source', 'none')

        with ui.card().classes('w-full'):
            ui.label('📋 Route Details').classes('font-bold text-gray-600')

            rows = []

            # Sender
            sender: RouteNode = route['sender']
            if sender:
                rows.append({
                    'hop': 'Start',
                    'name': sender.name,
                    'hash': sender.pubkey[:2].upper() if sender.pubkey else '-',
                    'type': TYPE_LABELS.get(sender.type, '-'),
                    'location': f"{sender.lat:.4f}, {sender.lon:.4f}" if sender.has_location else '-',
                    'role': '📱 Sender',
                })
            else:
                # Defensive fallback: try to find contact in snapshot
                fallback_contact = RoutePage._find_sender_contact(
                    msg, data.get('contacts', {}),
                )
                if fallback_contact:
                    fb_key, fb_c = fallback_contact
                    fb_lat = fb_c.get('adv_lat', 0)
                    fb_lon = fb_c.get('adv_lon', 0)
                    fb_has_loc = fb_lat != 0 or fb_lon != 0
                    rows.append({
                        'hop': 'Start',
                        'name': fb_c.get('adv_name') or msg.sender or 'Unknown',
                        'hash': fb_key[:2].upper() if fb_key else '-',
                        'type': TYPE_LABELS.get(fb_c.get('type', 0), '-'),
                        'location': f"{fb_lat:.4f}, {fb_lon:.4f}" if fb_has_loc else '-',
                        'role': '📱 Sender',
                    })
                else:
                    rows.append({
                        'hop': 'Start',
                        'name': msg.sender or 'Unknown',
                        'hash': msg.sender_pubkey[:2].upper() if msg.sender_pubkey else '-',
                        'type': '-',
                        'location': '-',
                        'role': '📱 Sender',
                    })

            # Repeaters
            for i, node in enumerate(path_nodes):
                rows.append({
                    'hop': str(i + 1),
                    'name': node.name,
                    'hash': node.pubkey[:2].upper() if node.pubkey else '-',
                    'type': TYPE_LABELS.get(node.type, '-'),
                    'location': f"{node.lat:.4f}, {node.lon:.4f}" if node.has_location else '-',
                    'role': '📡 Repeater',
                })

            # Placeholder rows (capped at 254; 255 = firmware "unknown")
            if not path_nodes and 0 < msg_path_len < 255:
                for i in range(msg_path_len):
                    rows.append({
                        'hop': str(i + 1),
                        'name': '-', 'hash': '-', 'type': '-',
                        'location': '-', 'role': '📡 Repeater',
                    })

            # Own position
            self_node: RouteNode = route['self_node']
            rows.append({
                'hop': 'End',
                'name': self_node.name,
                'hash': '-',
                'type': 'Companion',
                'location': f"{self_node.lat:.4f}, {self_node.lon:.4f}" if self_node.has_location else '-',
                'role': '📱 Receiver' if msg.direction == 'in' else '📱 Sender',
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

            # Footnotes
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

    def _render_send_panel(
        self, msg: Message, route: Dict, data: Dict,
    ) -> None:
        """Send widget pre-filled with route acknowledgement message."""
        path_hashes = msg.path_hashes

        parts = [f"@[{msg.sender or 'Unknown'}] Received in Zwolle path({msg.path_len})"]
        if path_hashes:
            path_str = '>'.join(h.upper() for h in path_hashes)
            parts.append(f"; {path_str}")
        prefilled = ''.join(parts)

        ch_options = {
            ch['idx']: f"[{ch['idx']}] {ch['name']}"
            for ch in data['channels']
        }
        default_ch = data['channels'][0]['idx'] if data['channels'] else 0

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

    # ------------------------------------------------------------------
    # Private — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_sender_contact(
        msg: Message, contacts: Dict,
    ) -> Optional[tuple]:
        """Defensive fallback: find sender contact data in snapshot.

        Tries pubkey-based bidirectional prefix match first, then
        falls back to name-based lookup.  Used by ``_render_route_table``
        when ``RouteBuilder`` could not resolve the sender.

        Args:
            msg:      Message to find the sender for.
            contacts: Contact dict from the data snapshot.

        Returns:
            ``(pubkey, contact_dict)`` tuple or ``None``.
        """
        # Strategy 1: pubkey prefix match
        if msg.sender_pubkey:
            pk_lower = msg.sender_pubkey.lower()
            for key, contact in contacts.items():
                key_lower = key.lower()
                if key_lower.startswith(pk_lower) or pk_lower.startswith(key_lower):
                    return (key, contact)

        # Strategy 2: name match
        if msg.sender:
            name_lower = msg.sender.lower()
            for key, contact in contacts.items():
                adv_name = contact.get('adv_name', '')
                if adv_name and adv_name.lower() == name_lower:
                    return (key, contact)

        return None
