"""Input panel — message input field, channel selector and send button."""

from typing import Callable, Dict, List

from nicegui import ui


class InputPanel:
    """Message composition panel in the centre column.

    Args:
        put_command: Callable to enqueue a command dict for the worker.
    """

    def __init__(self, put_command: Callable[[Dict], None]) -> None:
        self._put_command = put_command
        self._msg_input = None
        self._channel_select = None

    @property
    def channel_select(self):
        """Expose channel_select so FilterPanel can update its options."""
        return self._channel_select

    def render(self) -> None:
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

    def update_channel_options(self, channels: List[Dict]) -> None:
        """Update the channel dropdown options."""
        if not self._channel_select or not channels:
            return
        opts = {ch['idx']: f"[{ch['idx']}] {ch['name']}" for ch in channels}
        self._channel_select.options = opts
        if self._channel_select.value not in opts:
            self._channel_select.value = list(opts.keys())[0]
        self._channel_select.update()

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
