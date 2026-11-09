"""Actions panel -- refresh, advertise buttons, device name and default region setter."""

from typing import TYPE_CHECKING, Callable, Dict, Optional

from nicegui import ui

from meshcore_gui.services.region_service import normalize_region_name

if TYPE_CHECKING:
    from meshcore_gui.services.channel_region_store import ChannelRegionStore


class ActionsPanel:
    """Action buttons, shown below the device info in the DEVICE panel.

    Provides Refresh, Advertise, Set device name and — when a region store
    is supplied — Set default region controls.
    The BOT toggle has been moved to the dedicated BotPanel.

    Args:
        put_command:  Callable to enqueue a command dict for the worker.
        region_store: Optional per-device region store; enables the
                      *Default region* row.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        region_store: Optional["ChannelRegionStore"] = None,
    ) -> None:
        self._put_command = put_command
        self._name_input = None
        self._region_store = region_store
        self._region_select = None
        # Device default last shown, so a re-read from the device updates
        # the select without overwriting a choice the user is making.
        self._shown_device_default: Optional[str] = None

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
            if self._region_store is not None:
                with ui.row().classes('w-full items-center gap-2'):
                    self._region_select = ui.select(
                        options={'': 'None'},
                        value='',
                        label='Default region',
                        new_value_mode='add-unique',
                        on_change=self._on_region_change,
                    ).classes('flex-grow')
                    self._region_select.tooltip(
                        'Region used by the device when a message has no '
                        'region of its own. Type a name to add a region.'
                    )
                    ui.button('Set', on_click=self._set_default_region)
                self._refresh_region_options()

    def update(self, data: Dict) -> None:  # noqa: ARG002
        """Refresh the default-region selector from the region store."""
        self._refresh_region_options()

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

    # -- Default region ------------------------------------------------

    def _refresh_region_options(self) -> None:
        """Rebuild the options; follow the device value when it changed.

        Skips the DOM update when nothing changed.
        """
        if self._region_select is None or self._region_store is None:
            return
        opts = {'': 'None'}
        for name in self._region_store.get_known_regions():
            opts[name] = f'#{name}'
        current = self._region_select.value
        if current and current not in opts:
            opts[current] = f'#{current}'
        device_default = self._region_store.get_device_default()
        changed = self._region_select.options != opts
        if changed:
            self._region_select.options = opts
        if device_default != self._shown_device_default:
            self._shown_device_default = device_default
            self._region_select.value = device_default
            changed = True
        if changed:
            self._region_select.update()

    def _on_region_change(self, event=None) -> None:
        """Normalize a typed region name and add it to the known regions."""
        if self._region_select is None or self._region_store is None:
            return
        value = self._region_select.value or ''
        name = normalize_region_name(str(value))
        if not name:
            return
        if name not in self._region_store.get_known_regions():
            self._region_store.add_known_region(name)
        if value != name:
            self._refresh_region_options()
            self._region_select.value = name

    def _set_default_region(self) -> None:
        """Send the selected default region to the device ('' clears it)."""
        if self._region_select is None:
            return
        region = normalize_region_name(str(self._region_select.value or ''))
        self._put_command({
            'action': 'set_default_region',
            'region': region,
        })
        ui.notify(
            f"Default region → {('#' + region) if region else 'none'}…",
            type='info',
            timeout=2500,
        )
