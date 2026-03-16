"""Actions panel -- refresh, advertise buttons and device name setter."""

from typing import Callable, Dict

from nicegui import ui


class ActionsPanel:
    """Action buttons in the right column.

    Provides Refresh, Advertise and Set device name controls.
    The BOT toggle has been moved to the dedicated BotPanel.

    Args:
        put_command: Callable to enqueue a command dict for the worker.
    """

    def __init__(self, put_command: Callable[[Dict], None]) -> None:
        self._put_command = put_command
        self._name_input = None

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

    def update(self, data: Dict) -> None:  # noqa: ARG002
        """No-op — actions panel has no dynamic state after bot removal."""

    def _refresh(self) -> None:
        self._put_command({'action': 'refresh'})

    def _advert(self) -> None:
        self._put_command({'action': 'send_advert'})

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
