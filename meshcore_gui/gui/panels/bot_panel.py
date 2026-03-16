"""Bot panel -- enable/disable, private mode and channel assignment for MeshBot."""

from typing import Callable, Dict, List, Optional, Set

from nicegui import ui

from meshcore_gui.services.bot_config_store import BotConfigStore
from meshcore_gui.services.pin_store import PinStore


class BotPanel:
    """Dedicated BOT configuration panel.

    Provides:
    - Enable / disable toggle (immediately reflected in SharedData and
      persisted to BotConfigStore).
    - Private mode toggle: bot only replies to pinned contacts.
      Disabled (greyed out) when no pinned contacts exist; auto-disabled
      when the last pin is removed.
    - Interactive channel assignment via checkboxes built from the
      device channel list.  Selection is persisted on Save.

    Reference components:
    - Toggle styling: BOT checkbox in FilterPanel.
    - Button styling: buttons in ActionsPanel.

    Args:
        put_command:      Callable to enqueue a command dict for the worker.
        set_bot_enabled:  Callable to update the bot enabled flag in SharedData.
        bot_config_store: BotConfigStore instance for persistence.
        pin_store:        PinStore instance to check pinned contact count.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        set_bot_enabled: Callable[[bool], None],
        bot_config_store: BotConfigStore,
        pin_store: PinStore,
    ) -> None:
        self._put_command = put_command
        self._set_bot_enabled = set_bot_enabled
        self._store = bot_config_store
        self._pin_store = pin_store

        # UI refs
        self._enabled_checkbox = None
        self._private_mode_checkbox = None
        self._private_mode_warning = None
        self._channel_container = None
        self._channel_checkboxes: Dict[int, object] = {}  # idx -> ui.checkbox

        # State
        self._last_ch_fingerprint: tuple = ()
        self._suppress_enabled_event: bool = False

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the bot panel layout."""
        settings = self._store.get_settings()

        with ui.card().classes('w-full'):
            ui.label('🤖 BOT').classes('font-bold text-gray-600')

            # -- Enabled toggle ----------------------------------------
            with ui.row().classes('w-full items-center gap-2'):
                self._enabled_checkbox = ui.checkbox(
                    'Bot enabled',
                    value=settings.enabled,
                    on_change=lambda e: self._on_enabled_toggle(e.value),
                )
                self._enabled_checkbox.tooltip('Enabling BOT changes the device name')
                ui.label('⚠️ BOT changes device name').classes(
                    'text-xs text-amber-500'
                )

            ui.separator()

            # -- Private mode toggle -----------------------------------
            has_pins = len(self._pin_store.get_pinned()) > 0
            effective_private = settings.private_mode and has_pins

            with ui.column().classes('w-full gap-1'):
                with ui.row().classes('w-full items-center gap-2'):
                    self._private_mode_checkbox = ui.checkbox(
                        'Private mode — pinned contacts only',
                        value=effective_private,
                        on_change=lambda e: self._on_private_mode_toggle(e.value),
                    )
                    self._private_mode_checkbox.tooltip(
                        'When enabled the bot only responds to pinned contacts'
                    )
                    if not has_pins:
                        self._private_mode_checkbox.disable()

                self._private_mode_warning = ui.label(
                    '⚠️ No pinned contacts — pin contacts first to enable private mode'
                ).classes('text-xs text-amber-500')
                self._private_mode_warning.set_visibility(not has_pins)

            ui.separator()

            # -- Channel assignment ------------------------------------
            with ui.row().classes('w-full items-center gap-2'):
                ui.label('Channels:').classes('text-sm text-gray-600')
                self._channel_container = ui.row().classes('gap-2 flex-wrap')

            with ui.row().classes('w-full justify-end'):
                ui.button(
                    '💾 Save channels',
                    on_click=self._save_channels,
                ).tooltip('Save channel selection for the bot')

    # ------------------------------------------------------------------
    # Update (called from dashboard timer)
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Update panel state from snapshot data.

        Rebuilds channel checkboxes when the channel list changes.
        Updates the private-mode toggle disabled state based on
        the current pinned-contact count.

        Args:
            data: Snapshot dict from SharedData.
        """
        self._sync_enabled(data)
        self._sync_private_mode()
        self._rebuild_channels_if_changed(data.get('channels', []))

    # ------------------------------------------------------------------
    # Toggle handlers
    # ------------------------------------------------------------------

    def _on_enabled_toggle(self, value: bool) -> None:
        """Handle bot enabled toggle: update SharedData and persist."""
        if self._suppress_enabled_event:
            return
        self._set_bot_enabled(value)
        self._store.set_enabled(value)
        self._put_command({
            'action': 'set_device_name',
            'bot_enabled': value,
        })

    def _on_private_mode_toggle(self, value: bool) -> None:
        """Handle private mode toggle: validate pins and persist."""
        has_pins = len(self._pin_store.get_pinned()) > 0
        if value and not has_pins:
            # Guard: private mode cannot be enabled without pinned contacts.
            if self._private_mode_checkbox is not None:
                self._private_mode_checkbox.value = False
            return
        self._store.set_private_mode(value)

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def _sync_enabled(self, data: Dict) -> None:
        """Sync the enabled checkbox with the snapshot state."""
        if self._enabled_checkbox is None:
            return
        desired = data.get('bot_enabled', False)
        if self._enabled_checkbox.value != desired:
            self._suppress_enabled_event = True
            self._enabled_checkbox.value = desired
            self._suppress_enabled_event = False

    def _sync_private_mode(self) -> None:
        """Update private-mode toggle enabled/disabled state.

        When pinned contacts are removed, auto-disable private mode
        and grey out the checkbox.
        """
        if self._private_mode_checkbox is None:
            return

        has_pins = len(self._pin_store.get_pinned()) > 0

        if has_pins:
            self._private_mode_checkbox.enable()
            if self._private_mode_warning is not None:
                self._private_mode_warning.set_visibility(False)
        else:
            # Auto-disable private mode if all pins were removed.
            if self._private_mode_checkbox.value:
                self._private_mode_checkbox.value = False
                self._store.set_private_mode(False)
            self._private_mode_checkbox.disable()
            if self._private_mode_warning is not None:
                self._private_mode_warning.set_visibility(True)

    def _rebuild_channels_if_changed(self, channels: List[Dict]) -> None:
        """Rebuild channel checkboxes when the channel list changes.

        Pre-selects channels that are in the stored configuration.
        On first run (no stored channels), all channels are pre-selected.

        Args:
            channels: List of channel dicts with 'idx' and 'name' keys.
        """
        if not self._channel_container or not channels:
            return

        fingerprint = tuple((ch['idx'], ch['name']) for ch in channels)
        if fingerprint == self._last_ch_fingerprint:
            return

        self._last_ch_fingerprint = fingerprint
        saved_channels: Set[int] = self._store.get_settings().channels

        self._channel_container.clear()
        self._channel_checkboxes = {}

        with self._channel_container:
            for ch in channels:
                idx = ch['idx']
                name = ch['name']
                # First run (no saved channels) -> all selected.
                is_checked = (idx in saved_channels) if saved_channels else True
                cb = ui.checkbox(
                    f"[{idx}] {name}",
                    value=is_checked,
                )
                self._channel_checkboxes[idx] = cb

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_channels(self) -> None:
        """Persist the current channel checkbox selection to BotConfigStore."""
        selected: Set[int] = {
            idx
            for idx, cb in self._channel_checkboxes.items()
            if cb.value
        }
        self._store.set_channels(selected)
        ui.notify(
            f'Bot channels saved: {", ".join(f"[{i}]" for i in sorted(selected)) or "none"}',
            type='positive',
            position='top',
        )
