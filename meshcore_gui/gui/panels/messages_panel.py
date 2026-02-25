"""Messages panel — filtered message display with channel selection and message input."""

from typing import Callable, Dict, List, Set

from nicegui import ui

from meshcore_gui.core.models import Message


class MessagesPanel:
    """Displays filtered messages with channel selection and message input.

    Channel filtering is driven by the drawer submenu via
    :meth:`set_active_channel`.  The message input, channel selector
    and send button appear below the message list.

    Args:
        put_command: Callable to enqueue a command dict for the worker.
    """

    def __init__(self, put_command: Callable[[Dict], None]) -> None:
        self._put_command = put_command
        self._container = None
        self._channel_filters: Dict = {}
        self._last_channels: List[Dict] = []
        self._msg_input = None
        self._channel_select = None
        self._last_fingerprint = None  # skip rebuild when unchanged

        # Active channel set by drawer submenu (None = all)
        self._active_channel = None
        self._channel_label = None

    # -- Properties (same as FilterPanel originals) --------------------

    @property
    def channel_filters(self) -> Dict:
        """Current filter checkboxes (key: channel idx or ``'DM'``)."""
        return self._channel_filters

    @property
    def last_channels(self) -> List[Dict]:
        """Channel list from the most recent update."""
        return self._last_channels

    # -- Active channel (set by dashboard submenu) ---------------------

    def set_active_channel(self, channel) -> None:
        """Set the active channel filter from the drawer submenu.

        Args:
            channel: None for all messages, 'DM' for DM only,
                     or int for a specific channel index.
        """
        self._active_channel = channel
        self._last_fingerprint = None  # force rebuild on next update

        # Update the header label
        if self._channel_label:
            if channel is None:
                self._channel_label.text = '\U0001f4ac Messages — All'
            elif channel == 'DM':
                self._channel_label.text = '\U0001f4ac Messages — DM'
            else:
                # Find channel name from last_channels
                name = str(channel)
                for ch in self._last_channels:
                    if ch['idx'] == channel:
                        name = f"[{ch['idx']}] {ch['name']}"
                        break
                self._channel_label.text = f'\U0001f4ac Messages — {name}'

    # -- Render --------------------------------------------------------

    def render(self) -> None:
        with ui.card().classes('w-full'):
            # Header row: Messages label with active channel indicator
            with ui.row().classes('w-full items-center gap-2'):
                self._channel_label = ui.label(
                    '\U0001f4ac Messages — All'
                ).classes('font-bold text-gray-600')

            # Message container
            self._container = ui.column().classes(
                'w-full h-40 overflow-y-auto gap-0 text-sm font-mono '
                'bg-gray-50 p-2 rounded'
            )

            # Send message row (moved from InputPanel)
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

    # -- Filter data update (keeps channel list up to date) ------------

    def update_filters(self, data: Dict) -> None:
        """Update channel data when channels change.

        Note: filter checkboxes have been replaced by drawer submenu
        selection.  This method now only updates the internal channel
        list used for display and the channel_filters compatibility
        dict.
        """
        if not data['channels']:
            return

        self._last_channels = data['channels']

        # Update the header label if active channel is set to a channel idx
        if self._active_channel is not None and self._active_channel != 'DM':
            self.set_active_channel(self._active_channel)

    # -- Channel selector (moved from InputPanel) ----------------------

    def update_channel_options(self, channels: List[Dict]) -> None:
        """Update the channel dropdown options.

        Includes an equality check to avoid sending redundant updates
        to the NiceGUI client on every 500 ms timer tick.
        """
        if not self._channel_select or not channels:
            return
        opts = {ch['idx']: f"[{ch['idx']}] {ch['name']}" for ch in channels}
        if self._channel_select.options == opts:
            return  # unchanged — skip DOM update
        self._channel_select.options = opts
        if self._channel_select.value not in opts:
            self._channel_select.value = list(opts.keys())[0]
        self._channel_select.update()

    # -- Send message (moved from InputPanel) --------------------------

    def _send_message(self) -> None:
        text = self._msg_input.value
        channel = self._channel_select.value
        if text:
            self._put_command({
                'action': 'send_message',
                'channel': channel,
                'text': text,
            })
            self._msg_input.value = ''

    # -- Message display -----------------------------------------------

    @staticmethod
    def _is_room_message(msg: Message, room_pubkeys: Set[str]) -> bool:
        """Return True if *msg* belongs to a Room Server.

        Matches when the message's ``sender_pubkey`` prefix-matches
        any tracked room pubkey (same logic as RoomServerPanel).
        """
        if not msg.sender_pubkey or not room_pubkeys:
            return False
        for rpk in room_pubkeys:
            if (msg.sender_pubkey.startswith(rpk[:16])
                    or rpk.startswith(msg.sender_pubkey[:16])):
                return True
        return False

    def update(
        self,
        data: Dict,
        channel_filters: Dict,
        last_channels: List[Dict],
        room_pubkeys: Set[str] | None = None,
    ) -> None:
        """Refresh messages applying current filter state.

        Filtering is driven by ``_active_channel`` (set via drawer
        submenu).  The ``channel_filters`` and ``last_channels``
        parameters are kept for API compatibility but are not used
        when ``_active_channel`` is set.

        Args:
            data:            Snapshot dict from SharedData.
            channel_filters: ``{channel_idx: checkbox, 'DM': checkbox}``
                             from filter checkboxes (legacy, unused when
                             _active_channel is set).
            last_channels:   Channel list from filter state.
            room_pubkeys:    Pubkeys of Room Servers to exclude from
                             the general message view (shown in
                             RoomServerPanel instead).
        """
        if not self._container:
            return

        room_pks = room_pubkeys or set()
        channel_names = {ch['idx']: ch['name'] for ch in last_channels}
        messages: List[Message] = data['messages']

        # Apply filters
        filtered = []
        for orig_idx, msg in enumerate(messages):
            # Skip room server messages (shown in RoomServerPanel)
            if self._is_room_message(msg, room_pks):
                continue

            # Apply active channel filter (from drawer submenu)
            if self._active_channel is not None:
                if self._active_channel == 'DM':
                    # Show only DM messages (channel is None)
                    if msg.channel is not None:
                        continue
                else:
                    # Show only messages for specific channel index
                    if msg.channel != self._active_channel:
                        continue
            else:
                # No active channel filter (ALL) — use checkbox filters
                # as fallback for backwards compatibility
                if msg.channel is None:
                    if channel_filters.get('DM') and not channel_filters['DM'].value:
                        continue
                else:
                    if msg.channel in channel_filters and not channel_filters[msg.channel].value:
                        continue

            filtered.append((orig_idx, msg))

        # Rebuild only when content changed
        fingerprint = tuple((orig_idx, id(msg)) for orig_idx, msg in filtered)
        if fingerprint == self._last_fingerprint:
            return
        self._last_fingerprint = fingerprint

        self._container.clear()

        with self._container:
            # Hide channel tag when viewing a specific channel/DM
            hide_ch = self._active_channel is not None

            for orig_idx, msg in reversed(filtered[-50:]):
                line = msg.format_line(channel_names, show_channel=not hide_ch)

                ui.label(line).classes(
                    'text-xs leading-tight cursor-pointer '
                    'hover:bg-blue-50 rounded px-1'
                ).on('click', lambda e, i=orig_idx: self._open_route(i))

    @staticmethod
    def _open_route(msg_index: int) -> None:
        ui.navigate.to(f'/route/{msg_index}')
