"""
Main dashboard page for MeshCore GUI.

Contains the three-column layout with device info, contacts, map,
messaging, filters and RX log.  The 500 ms update timer lives here.
"""

from typing import Dict, List

import logging

from nicegui import ui

from meshcore_gui.config import TYPE_ICONS, TYPE_NAMES
from meshcore_gui.protocols import SharedDataReader


# Suppress the harmless "Client has been deleted" warning that NiceGUI
# emits when a browser tab is refreshed while a ui.timer is active.
class _DeletedClientFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'Client has been deleted' not in record.getMessage()

logging.getLogger('nicegui').addFilter(_DeletedClientFilter())


class DashboardPage:
    """
    Main dashboard rendered at ``/``.

    Args:
        shared: SharedDataReader for data access and command dispatch
    """

    def __init__(self, shared: SharedDataReader) -> None:
        self._shared = shared

        # UI element references
        self._status_label = None
        self._device_label = None
        self._channel_select = None
        self._channels_filter_container = None
        self._channel_filters: Dict = {}
        self._bot_checkbox = None
        self._contacts_container = None
        self._map_widget = None
        self._messages_container = None
        self._rxlog_table = None
        self._msg_input = None

        # Map markers tracking
        self._markers: List = []

        # Channel data for message display
        self._last_channels: List[Dict] = []

        # Local first-render flag — each new browser tab gets its own
        # DashboardPage instance and must render device/contacts once.
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the complete dashboard layout and start the timer."""
        # Reset per-tab state — same DashboardPage instance is reused
        # across browser reconnects, so force a fresh first-render.
        self._initialized = False
        self._markers.clear()
        self._channel_filters = {}
        self._last_channels = []

        ui.dark_mode(False)

        # Header
        with ui.header().classes('bg-blue-600 text-white'):
            ui.label('🔗 MeshCore').classes('text-xl font-bold')
            ui.space()
            self._status_label = ui.label('Starting...').classes('text-sm')

        # Three columns
        with ui.row().classes('w-full h-full gap-2 p-2'):
            with ui.column().classes('w-64 gap-2'):
                self._render_device_panel()
                self._render_contacts_panel()

            with ui.column().classes('flex-grow gap-2'):
                self._render_map_panel()
                self._render_input_panel()
                self._render_channels_filter()
                self._render_messages_panel()

            with ui.column().classes('w-64 gap-2'):
                self._render_actions_panel()
                self._render_rxlog_panel()

        # 500 ms update timer
        ui.timer(0.5, self._update_ui)

    # ------------------------------------------------------------------
    # Panel builders
    # ------------------------------------------------------------------

    def _render_device_panel(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('📡 Device').classes('font-bold text-gray-600')
            self._device_label = ui.label('Connecting...').classes(
                'text-sm whitespace-pre-line'
            )

    def _render_contacts_panel(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('👥 Contacts').classes('font-bold text-gray-600')
            self._contacts_container = ui.column().classes(
                'w-full gap-1 max-h-96 overflow-y-auto'
            )

    def _render_map_panel(self) -> None:
        with ui.card().classes('w-full'):
            self._map_widget = ui.leaflet(
                center=(52.5, 6.0), zoom=9
            ).classes('w-full h-72')

    def _render_input_panel(self) -> None:
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center gap-2'):
                self._msg_input = ui.input(
                    placeholder='Message...'
                ).classes('flex-grow')

                self._channel_select = ui.select(
                    options={0: '[0] Public'}, value=0
                ).classes('w-32')

                ui.button(
                    'Send', on_click=self._send_message
                ).classes('bg-blue-500 text-white')

    def _render_channels_filter(self) -> None:
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center gap-4 justify-center'):
                ui.label('📻 Filter:').classes('text-sm text-gray-600')
                self._channels_filter_container = ui.row().classes('gap-4')

    def _render_messages_panel(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('💬 Messages').classes('font-bold text-gray-600')
            self._messages_container = ui.column().classes(
                'w-full h-40 overflow-y-auto gap-0 text-sm font-mono '
                'bg-gray-50 p-2 rounded'
            )

    def _render_actions_panel(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('⚡ Actions').classes('font-bold text-gray-600')
            with ui.row().classes('gap-2'):
                ui.button('🔄 Refresh', on_click=self._cmd_refresh)
                ui.button('📢 Advert', on_click=self._cmd_send_advert)

    def _render_rxlog_panel(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('📊 RX Log').classes('font-bold text-gray-600')
            self._rxlog_table = ui.table(
                columns=[
                    {'name': 'time', 'label': 'Time', 'field': 'time'},
                    {'name': 'snr', 'label': 'SNR', 'field': 'snr'},
                    {'name': 'type', 'label': 'Type', 'field': 'type'},
                ],
                rows=[],
            ).props('dense flat').classes('text-xs max-h-48 overflow-y-auto')

    # ------------------------------------------------------------------
    # Timer-driven UI update
    # ------------------------------------------------------------------

    def _update_ui(self) -> None:
        """Periodic UI refresh — called every 500 ms."""
        try:
            if not self._status_label or not self._device_label:
                return

            data = self._shared.get_snapshot()
            is_first = not self._initialized

            self._status_label.text = data['status']

            if data['device_updated'] or is_first:
                self._update_device_info(data)
            if data['channels_updated'] or is_first:
                self._update_channels(data)
            if data['contacts_updated'] or is_first:
                self._update_contacts(data)
            if data['contacts'] and (
                data['contacts_updated'] or not self._markers or is_first
            ):
                self._update_map(data)

            self._refresh_messages(data)

            if data['rxlog_updated'] and self._rxlog_table:
                self._update_rxlog(data)

            self._shared.clear_update_flags()

            if is_first and data['channels'] and data['contacts']:
                self._initialized = True
                self._shared.mark_gui_initialized()

        except Exception as e:
            err = str(e).lower()
            if "deleted" not in err and "client" not in err:
                print(f"GUI update error: {e}")

    # ------------------------------------------------------------------
    # Data → UI updaters
    # ------------------------------------------------------------------

    def _update_device_info(self, data: Dict) -> None:
        lines = []
        if data['name']:
            lines.append(f"📡 {data['name']}")
        if data['public_key']:
            lines.append(f"🔑 {data['public_key'][:16]}...")
        if data['radio_freq']:
            lines.append(f"📻 {data['radio_freq']:.3f} MHz")
            lines.append(f"⚙️ SF{data['radio_sf']} / {data['radio_bw']} kHz")
        if data['tx_power']:
            lines.append(f"⚡ TX: {data['tx_power']} dBm")
        if data['adv_lat'] and data['adv_lon']:
            lines.append(f"📍 {data['adv_lat']:.4f}, {data['adv_lon']:.4f}")
        if data['firmware_version']:
            lines.append(f"🏷️ {data['firmware_version']}")
        self._device_label.text = "\n".join(lines) if lines else "Loading..."

    def _update_channels(self, data: Dict) -> None:
        if not self._channels_filter_container or not data['channels']:
            return

        self._channels_filter_container.clear()
        self._channel_filters = {}

        with self._channels_filter_container:
            # BOT toggle — controls auto-reply, not display filtering
            self._bot_checkbox = ui.checkbox(
                '🤖 BOT',
                value=data.get('bot_enabled', False),
                on_change=lambda e: self._shared.set_bot_enabled(e.value),
            )

            # Visual separator
            ui.label('│').classes('text-gray-300')

            # Display filters: DM + channels
            cb_dm = ui.checkbox('DM', value=True)
            self._channel_filters['DM'] = cb_dm
            for ch in data['channels']:
                cb = ui.checkbox(f"[{ch['idx']}] {ch['name']}", value=True)
                self._channel_filters[ch['idx']] = cb

        self._last_channels = data['channels']

        if self._channel_select and data['channels']:
            opts = {
                ch['idx']: f"[{ch['idx']}] {ch['name']}"
                for ch in data['channels']
            }
            self._channel_select.options = opts
            if self._channel_select.value not in opts:
                self._channel_select.value = list(opts.keys())[0]
            self._channel_select.update()

    def _update_contacts(self, data: Dict) -> None:
        if not self._contacts_container:
            return

        self._contacts_container.clear()

        with self._contacts_container:
            for key, contact in data['contacts'].items():
                ctype = contact.get('type', 0)
                icon = TYPE_ICONS.get(ctype, '○')
                name = contact.get('adv_name', key[:12])
                type_name = TYPE_NAMES.get(ctype, '-')
                lat = contact.get('adv_lat', 0)
                lon = contact.get('adv_lon', 0)
                has_loc = lat != 0 or lon != 0

                tooltip = (
                    f"{name}\nType: {type_name}\n"
                    f"Key: {key[:16]}...\nClick to send DM"
                )
                if has_loc:
                    tooltip += f"\nLat: {lat:.4f}\nLon: {lon:.4f}"

                with ui.row().classes(
                    'w-full items-center gap-2 p-1 '
                    'hover:bg-gray-100 rounded cursor-pointer'
                ).on('click', lambda e, k=key, n=name: self._open_dm_dialog(k, n)):
                    ui.label(icon).classes('text-sm')
                    ui.label(name[:15]).classes(
                        'text-sm flex-grow truncate'
                    ).tooltip(tooltip)
                    ui.label(type_name).classes('text-xs text-gray-500')
                    if has_loc:
                        ui.label('📍').classes('text-xs')

    def _update_map(self, data: Dict) -> None:
        if not self._map_widget:
            return

        for marker in self._markers:
            try:
                self._map_widget.remove_layer(marker)
            except Exception:
                pass
        self._markers.clear()

        if data['adv_lat'] and data['adv_lon']:
            m = self._map_widget.marker(
                latlng=(data['adv_lat'], data['adv_lon'])
            )
            self._markers.append(m)
            self._map_widget.set_center((data['adv_lat'], data['adv_lon']))

        for key, contact in data['contacts'].items():
            lat = contact.get('adv_lat', 0)
            lon = contact.get('adv_lon', 0)
            if lat != 0 or lon != 0:
                m = self._map_widget.marker(latlng=(lat, lon))
                self._markers.append(m)

    def _update_rxlog(self, data: Dict) -> None:
        rows = [
            {
                'time': e['time'],
                'snr': f"{e['snr']:.1f}",
                'type': e['payload_type'],
            }
            for e in data['rx_log'][:20]
        ]
        self._rxlog_table.rows = rows
        self._rxlog_table.update()

    def _refresh_messages(self, data: Dict) -> None:
        if not self._messages_container:
            return

        channel_names = {ch['idx']: ch['name'] for ch in self._last_channels}

        filtered = []
        for orig_idx, msg in enumerate(data['messages']):
            ch = msg['channel']
            if ch is None:
                if self._channel_filters.get('DM') and not self._channel_filters['DM'].value:
                    continue
            else:
                if ch in self._channel_filters and not self._channel_filters[ch].value:
                    continue
            filtered.append((orig_idx, msg))

        self._messages_container.clear()

        with self._messages_container:
            for orig_idx, msg in reversed(filtered[-50:]):
                direction = '→' if msg['direction'] == 'out' else '←'
                ch = msg['channel']

                ch_label = (
                    f"[{channel_names.get(ch, f'ch{ch}')}]"
                    if ch is not None
                    else '[DM]'
                )

                sender = msg.get('sender', '')
                path_len = msg.get('path_len', 0)
                has_path = bool(msg.get('path_hashes'))
                if msg['direction'] == 'in' and path_len > 0:
                    hop_tag = f' [{path_len}h{"✓" if has_path else ""}]'
                else:
                    hop_tag = ''

                if sender:
                    line = f"{msg['time']} {direction} {ch_label}{hop_tag} {sender}: {msg['text']}"
                else:
                    line = f"{msg['time']} {direction} {ch_label}{hop_tag} {msg['text']}"

                ui.label(line).classes(
                    'text-xs leading-tight cursor-pointer '
                    'hover:bg-blue-50 rounded px-1'
                ).on('click', lambda e, i=orig_idx: ui.navigate.to(
                    f'/route/{i}', new_tab=True
                ))

    # ------------------------------------------------------------------
    # DM dialog
    # ------------------------------------------------------------------

    def _open_dm_dialog(self, pubkey: str, contact_name: str) -> None:
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label(f'💬 DM to {contact_name}').classes('font-bold text-lg')
            msg_input = ui.input(placeholder='Type your message...').classes('w-full')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                def send_dm():
                    text = msg_input.value
                    if text:
                        self._shared.put_command({
                            'action': 'send_dm',
                            'pubkey': pubkey,
                            'text': text,
                            'contact_name': contact_name,
                        })
                        dialog.close()

                ui.button('Send', on_click=send_dm).classes('bg-blue-500 text-white')
        dialog.open()

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    def _send_message(self) -> None:
        text = self._msg_input.value
        channel = self._channel_select.value
        if text:
            self._shared.put_command({
                'action': 'send_message',
                'channel': channel,
                'text': text,
            })
            self._msg_input.value = ''

    def _cmd_send_advert(self) -> None:
        self._shared.put_command({'action': 'send_advert'})

    def _cmd_refresh(self) -> None:
        self._shared.put_command({'action': 'refresh'})
