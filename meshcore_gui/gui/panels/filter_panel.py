"""Filter panel — channel filter checkboxes and bot toggle."""

from typing import Callable, Dict, List

from nicegui import ui


class FilterPanel:
    """Channel filter checkboxes and bot on/off toggle.

    Args:
        set_bot_enabled: Callable to toggle the bot in SharedData.
        put_command:     Callable to enqueue a command.
    """

    def __init__(
        self,
        set_bot_enabled: Callable[[bool], None],
        put_command: Callable[[dict], None],
    ) -> None:
        self._set_bot_enabled = set_bot_enabled
        self._put_command = put_command
        self._container = None
        self._bot_checkbox = None
        self._channel_filters: Dict = {}
        self._last_channels: List[Dict] = []
        self._suppress_bot_event = False

    @property
    def channel_filters(self) -> Dict:
        """Current filter checkboxes (key: channel idx or ``'DM'``)."""
        return self._channel_filters

    @property
    def last_channels(self) -> List[Dict]:
        """Channel list from the most recent update."""
        return self._last_channels

    def render(self) -> None:
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center gap-4 justify-center'):
                ui.label('📻 Filter:').classes('text-sm text-gray-600')
                self._container = ui.row().classes('gap-4')

    def _on_bot_toggle(self, value: bool) -> None:
        """Handle BOT checkbox toggle: update flag and queue name change."""
        if self._suppress_bot_event:
            return
        self._set_bot_enabled(value)
        self._put_command({
            'action': 'set_device_name',
            'bot_enabled': value,
        })

    def update(self, data: Dict) -> None:
        """Rebuild checkboxes when channel data changes."""
        if not self._container or not data['channels']:
            return

        self._container.clear()
        self._channel_filters = {}

        with self._container:
            self._bot_checkbox = ui.checkbox(
                '🤖 BOT',
                value=data.get('bot_enabled', False),
                on_change=lambda e: self._on_bot_toggle(e.value),
            )
            self._bot_checkbox.tooltip('Enabling BOT changes the device name')
            ui.label('⚠️ BOT changes device name').classes(
                'text-xs text-amber-500'
            )
            ui.label('│').classes('text-gray-300')

            cb_dm = ui.checkbox('DM', value=True)
            self._channel_filters['DM'] = cb_dm

            for ch in data['channels']:
                cb = ui.checkbox(f"[{ch['idx']}] {ch['name']}", value=True)
                self._channel_filters[ch['idx']] = cb

        self._last_channels = data['channels']
        if self._bot_checkbox is not None:
            desired = data.get('bot_enabled', False)
            if self._bot_checkbox.value != desired:
                self._suppress_bot_event = True
                self._bot_checkbox.value = desired
                self._suppress_bot_event = False
