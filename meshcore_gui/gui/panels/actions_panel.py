"""Actions panel — refresh, advertise buttons and bot toggle."""

from typing import Callable, Dict

from nicegui import ui


class ActionsPanel:
    """Action buttons and bot toggle in the right column.

    Args:
        put_command:     Callable to enqueue a command dict for the worker.
        set_bot_enabled: Callable to toggle the bot in SharedData.
    """

    def __init__(self, put_command: Callable[[Dict], None], set_bot_enabled: Callable[[bool], None]) -> None:
        self._put_command = put_command
        self._set_bot_enabled = set_bot_enabled
        self._bot_checkbox = None
        self._name_input = None
        self._suppress_bot_event = False

    def render(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('⚡ Actions').classes('font-bold text-gray-600')
            with ui.row().classes('gap-2'):
                ui.button('🔄 Refresh', on_click=self._refresh)
                ui.button('📢 Advert', on_click=self._advert)
            with ui.row().classes('w-full items-center gap-2'):
                self._name_input = ui.input(
                    label='Device name',
                    placeholder='Set device name',
                ).classes('flex-grow')
                ui.button('Set', on_click=self._set_name)
            self._bot_checkbox = ui.checkbox(
                '🤖 BOT',
                value=False,
                on_change=lambda e: self._on_bot_toggle(e.value),
            )
            self._bot_checkbox.tooltip('Enabling BOT changes the device name')
            ui.label('⚠️ BOT changes device name').classes(
                'text-xs text-amber-500'
            )

    def update(self, data: Dict) -> None:
        """Update BOT checkbox state from snapshot data."""
        if self._bot_checkbox is not None:
            desired = data.get('bot_enabled', False)
            if self._bot_checkbox.value != desired:
                self._suppress_bot_event = True
                self._bot_checkbox.value = desired
                self._suppress_bot_event = False

    def _refresh(self) -> None:
        self._put_command({'action': 'refresh'})

    def _advert(self) -> None:
        self._put_command({'action': 'send_advert'})

    def _on_bot_toggle(self, value: bool) -> None:
        """Handle BOT checkbox toggle: update flag and queue name change."""
        if self._suppress_bot_event:
            return
        self._set_bot_enabled(value)
        self._put_command({
            'action': 'set_device_name',
            'bot_enabled': value,
        })

    def _set_name(self) -> None:
        """Send an explicit device name update."""
        if self._name_input is None:
            return
        name = (self._name_input.value or "").strip()
        if not name:
            return
        self._put_command({
            'action': 'set_device_name',
            'name': name,
        })
