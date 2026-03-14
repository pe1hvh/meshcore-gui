"""BBS panel -- offline Bulletin Board System viewer, post form and settings."""

from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.config import debug_print
from meshcore_gui.services.bbs_config_store import (
    BbsConfigStore,
    DEFAULT_CATEGORIES,
    DEFAULT_RETENTION_HOURS,
)
from meshcore_gui.services.bbs_service import BbsMessage, BbsService


class BbsPanel:
    """BBS panel: channel selector, filters, message list, post form and settings.

    The settings section lists all active device channels (from SharedData)
    and lets the user enable/disable BBS per channel and configure
    categories, regions and retention.  Configuration is persisted via
    BbsConfigStore to ~/.meshcore-gui/bbs/bbs_config.json.

    All data access goes through BbsService and BbsConfigStore.
    No direct SQLite access in this class (SOLID: SRP / DIP).

    Args:
        put_command:  Callable to enqueue a command dict for the worker.
        bbs_service:  Shared BbsService instance.
        config_store: Shared BbsConfigStore instance.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        bbs_service: BbsService,
        config_store: BbsConfigStore,
    ) -> None:
        self._put_command = put_command
        self._service = bbs_service
        self._config_store = config_store

        # Active view state
        self._active_channel_idx: Optional[int] = None
        self._active_region: Optional[str] = None
        self._active_category: Optional[str] = None

        # UI element references -- message view
        self._msg_list_container = None
        self._region_row = None
        self._region_select = None
        self._category_select = None
        self._text_input = None
        self._post_region_row = None
        self._post_region_select = None
        self._post_category_select = None
        self._channel_btn_row = None

        # UI element references -- settings
        self._settings_container = None
        self._last_device_channels: List[Dict] = []

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the complete BBS panel layout."""
        with ui.card().classes('w-full'):
            ui.label('BBS -- Bulletin Board System').classes('font-bold text-gray-600')

            # ---- Channel selector -----------------------------------
            self._channel_btn_row = ui.row().classes('w-full items-center gap-2 flex-wrap')
            with self._channel_btn_row:
                ui.label('Channel:').classes('text-sm text-gray-600')
                # Populated by _rebuild_channel_buttons()

            ui.separator()

            # ---- Filter row ----------------------------------------
            with ui.row().classes('w-full items-center gap-4 flex-wrap'):
                ui.label('Filter:').classes('text-sm text-gray-600')

                self._region_row = ui.row().classes('items-center gap-2')
                with self._region_row:
                    ui.label('Region:').classes('text-xs text-gray-600')
                    self._region_select = ui.select(
                        options=[],
                        value=None,
                        on_change=lambda e: self._on_region_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                with ui.row().classes('items-center gap-2'):
                    ui.label('Category:').classes('text-xs text-gray-600')
                    self._category_select = ui.select(
                        options=[],
                        value=None,
                        on_change=lambda e: self._on_category_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                ui.button(
                    'Refresh', on_click=self._refresh_messages
                ).props('flat no-caps').classes('text-xs')

            ui.separator()

            # ---- Message list --------------------------------------
            self._msg_list_container = ui.column().classes(
                'w-full gap-1 h-72 overflow-y-auto bg-gray-50 rounded p-2'
            )

            ui.separator()

            # ---- Post form -----------------------------------------
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.label('Post:').classes('text-sm text-gray-600')

                self._post_region_row = ui.row().classes('items-center gap-1')
                with self._post_region_row:
                    self._post_region_select = ui.select(
                        options=[], label='Region',
                    ).classes('text-xs').style('min-width: 110px')

                self._post_category_select = ui.select(
                    options=[], label='Category',
                ).classes('text-xs').style('min-width: 110px')

                self._text_input = ui.input(
                    placeholder='Message text...',
                ).classes('flex-grow text-sm')

                ui.button('Send', on_click=self._on_post).props('no-caps').classes('text-xs')

        # ---- Settings card -----------------------------------------
        with ui.card().classes('w-full'):
            ui.label('BBS Settings').classes('font-bold text-gray-600')
            ui.label(
                'Enable BBS on a channel to allow !bbs commands and store messages.'
            ).classes('text-xs text-gray-500')
            ui.separator()
            self._settings_container = ui.column().classes('w-full gap-2')
            with self._settings_container:
                ui.label('Waiting for device channels...').classes(
                    'text-xs text-gray-400 italic'
                )

    # ------------------------------------------------------------------
    # Channel selector (message view)
    # ------------------------------------------------------------------

    def _rebuild_channel_buttons(self, enabled_channels: List[Dict]) -> None:
        """Rebuild the channel selector buttons for enabled BBS channels.

        Args:
            enabled_channels: List of enabled channel config dicts.
        """
        if not self._channel_btn_row:
            return
        self._channel_btn_row.clear()
        with self._channel_btn_row:
            ui.label('Channel:').classes('text-sm text-gray-600')
            if not enabled_channels:
                ui.label('No BBS channels configured.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            for cfg in enabled_channels:
                idx = cfg['channel']
                name = cfg['name']
                ui.button(
                    name,
                    on_click=lambda i=idx: self._select_channel(i),
                ).props('flat no-caps').classes('text-xs')

        # Auto-select first channel when none is active yet
        if self._active_channel_idx is None and enabled_channels:
            self._select_channel(enabled_channels[0]['channel'])

    def _select_channel(self, channel_idx: int) -> None:
        """Switch the active channel and rebuild filter options.

        Args:
            channel_idx: MeshCore channel index to activate.
        """
        self._active_channel_idx = channel_idx
        self._active_region = None
        self._active_category = None

        cfg = self._config_store.get_channel(channel_idx) or {}
        regions: List[str] = cfg.get('regions', [])
        categories: List[str] = cfg.get('categories', [])

        has_regions = bool(regions)
        if self._region_row:
            self._region_row.set_visibility(has_regions)
        if self._post_region_row:
            self._post_region_row.set_visibility(has_regions)

        region_opts = ['(all)'] + regions
        if self._region_select:
            self._region_select.options = region_opts
            self._region_select.value = '(all)'
        if self._post_region_select:
            self._post_region_select.options = regions
            self._post_region_select.value = regions[0] if regions else None

        cat_opts = ['(all)'] + categories
        if self._category_select:
            self._category_select.options = cat_opts
            self._category_select.value = '(all)'
        if self._post_category_select:
            self._post_category_select.options = categories
            self._post_category_select.value = categories[0] if categories else None

        self._refresh_messages()

    # ------------------------------------------------------------------
    # Filter callbacks
    # ------------------------------------------------------------------

    def _on_region_filter(self, value: Optional[str]) -> None:
        self._active_region = None if (not value or value == '(all)') else value
        self._refresh_messages()

    def _on_category_filter(self, value: Optional[str]) -> None:
        self._active_category = None if (not value or value == '(all)') else value
        self._refresh_messages()

    # ------------------------------------------------------------------
    # Message list refresh
    # ------------------------------------------------------------------

    def _refresh_messages(self) -> None:
        """Query the BBS service and rebuild the message list UI."""
        if not self._msg_list_container:
            return
        self._msg_list_container.clear()
        with self._msg_list_container:
            if self._active_channel_idx is None:
                ui.label('Select a channel above.').classes('text-xs text-gray-400 italic')
                return
            messages = self._service.get_all_messages(
                channel=self._active_channel_idx,
                region=self._active_region,
                category=self._active_category,
            )
            if not messages:
                ui.label('No messages.').classes('text-xs text-gray-400 italic')
                return
            for msg in messages:
                self._render_message_row(msg)

    def _render_message_row(self, msg: BbsMessage) -> None:
        """Render a single message row.

        Args:
            msg: BbsMessage to display.
        """
        ts = msg.timestamp[:16].replace('T', ' ')
        region_label = f' [{msg.region}]' if msg.region else ''
        header = f'{ts}  {msg.sender}  [{msg.category}]{region_label}'
        with ui.column().classes('w-full gap-0 py-1 border-b border-gray-200'):
            ui.label(header).classes('text-xs text-gray-500')
            ui.label(msg.text).classes('text-sm')

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------

    def _on_post(self) -> None:
        """Handle the Send button: validate inputs and post a BBS message."""
        if self._active_channel_idx is None:
            ui.notify('Select a channel first.', type='warning')
            return

        cfg = self._config_store.get_channel(self._active_channel_idx) or {}
        regions: List[str] = cfg.get('regions', [])
        categories: List[str] = cfg.get('categories', [])

        text = (self._text_input.value or '').strip() if self._text_input else ''
        if not text:
            ui.notify('Message text cannot be empty.', type='warning')
            return

        category = (
            self._post_category_select.value
            if self._post_category_select else (categories[0] if categories else '')
        )
        if not category:
            ui.notify('Please select a category.', type='warning')
            return

        region = ''
        if regions and self._post_region_select:
            region = self._post_region_select.value or ''

        msg = BbsMessage(
            channel=self._active_channel_idx,
            region=region,
            category=category,
            sender='Me',
            sender_key='',
            text=text,
        )
        self._service.post_message(msg)

        # Broadcast on the mesh channel
        region_part = f'{region} ' if region else ''
        mesh_text = f'!bbs post {region_part}{category} {text}'
        self._put_command({
            'action': 'send_message',
            'channel': self._active_channel_idx,
            'text': mesh_text,
        })
        debug_print(f'BBS panel: posted to ch={self._active_channel_idx} {mesh_text[:60]}')

        if self._text_input:
            self._text_input.value = ''
        self._refresh_messages()
        ui.notify('Message posted.', type='positive')

    # ------------------------------------------------------------------
    # Settings panel
    # ------------------------------------------------------------------

    def _rebuild_settings(self, device_channels: List[Dict]) -> None:
        """Rebuild the settings rows for all device channels.

        Called from update() when the device channel list changes.

        Args:
            device_channels: Channel list from SharedData snapshot.
        """
        if not self._settings_container:
            return
        self._settings_container.clear()
        with self._settings_container:
            if not device_channels:
                ui.label('No channels received from device yet.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            for ch in device_channels:
                self._render_settings_row(ch)

    def _render_settings_row(self, device_ch: Dict) -> None:
        """Render one settings row for a single device channel.

        Args:
            device_ch: Channel dict from SharedData (keys: idx, name).
        """
        ch_idx = device_ch.get('idx', device_ch.get('index', 0))
        ch_name = device_ch.get('name', f'Ch {ch_idx}')
        bbs_cfg = self._config_store.get_channel(ch_idx)
        is_enabled = bbs_cfg.get('enabled', False) if bbs_cfg else False

        with ui.expansion(
            f'[{ch_idx}] {ch_name}',
            value=False,
        ).classes('w-full').props('dense'):

            with ui.column().classes('w-full gap-2 p-2'):

                # Enable / disable toggle
                enable_cb = ui.checkbox(
                    'Enable BBS on this channel',
                    value=is_enabled,
                )

                # Categories input
                cats_val = ', '.join(bbs_cfg.get('categories', DEFAULT_CATEGORIES)) if bbs_cfg else ', '.join(DEFAULT_CATEGORIES)
                cats_input = ui.input(
                    label='Categories (comma-separated)',
                    value=cats_val,
                ).classes('w-full text-xs')

                # Regions input
                regions_val = ', '.join(bbs_cfg.get('regions', [])) if bbs_cfg else ''
                regions_input = ui.input(
                    label='Regions (comma-separated, leave empty for none)',
                    value=regions_val,
                ).classes('w-full text-xs')

                # Retention
                ret_val = str(bbs_cfg.get('retention_hours', DEFAULT_RETENTION_HOURS)) if bbs_cfg else str(DEFAULT_RETENTION_HOURS)
                retention_input = ui.input(
                    label='Retention (hours)',
                    value=ret_val,
                ).classes('w-full text-xs').style('max-width: 160px')

                # Whitelist
                wl_val = ', '.join(bbs_cfg.get('allowed_keys', [])) if bbs_cfg else ''
                whitelist_input = ui.input(
                    label='Allowed keys (comma-separated hex, leave empty for all)',
                    value=wl_val,
                ).classes('w-full text-xs')

                # Save button
                def _save(
                    idx=ch_idx,
                    name=ch_name,
                    cb=enable_cb,
                    cats=cats_input,
                    regs=regions_input,
                    ret=retention_input,
                    wl=whitelist_input,
                ) -> None:
                    categories = [
                        c.strip().upper()
                        for c in (cats.value or '').split(',')
                        if c.strip()
                    ]
                    regions = [
                        r.strip()
                        for r in (regs.value or '').split(',')
                        if r.strip()
                    ]
                    try:
                        retention_hours = int(ret.value or DEFAULT_RETENTION_HOURS)
                    except ValueError:
                        retention_hours = DEFAULT_RETENTION_HOURS
                    allowed_keys = [
                        k.strip()
                        for k in (wl.value or '').split(',')
                        if k.strip()
                    ]
                    cfg_entry = {
                        'channel': idx,
                        'name': name,
                        'enabled': cb.value,
                        'categories': categories if categories else list(DEFAULT_CATEGORIES),
                        'regions': regions,
                        'retention_hours': retention_hours,
                        'allowed_keys': allowed_keys,
                    }
                    self._config_store.set_channel(cfg_entry)
                    debug_print(
                        f'BBS settings: saved ch={idx} enabled={cb.value} '
                        f'cats={categories} regions={regions}'
                    )
                    ui.notify(f'BBS settings saved for [{idx}] {name}', type='positive')
                    # Refresh channel buttons and message view
                    self._refresh_after_settings_save()

                ui.button('Save', on_click=_save).props('no-caps').classes('text-xs')

    def _refresh_after_settings_save(self) -> None:
        """Rebuild the channel selector buttons after a settings save."""
        enabled = self._config_store.get_enabled_channels()
        self._rebuild_channel_buttons(enabled)
        # Reset active channel if it was disabled
        if self._active_channel_idx is not None:
            cfg = self._config_store.get_channel(self._active_channel_idx)
            if not cfg or not cfg.get('enabled', False):
                self._active_channel_idx = None
                if self._msg_list_container:
                    self._msg_list_container.clear()
                    with self._msg_list_container:
                        ui.label('Select a channel above.').classes(
                            'text-xs text-gray-400 italic'
                        )

    # ------------------------------------------------------------------
    # External update hook (called from dashboard timer)
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Called by the dashboard timer with the SharedData snapshot.

        Rebuilds the settings panel when the device channel list changes.

        Args:
            data: SharedData snapshot dict.
        """
        device_channels = data.get('channels', [])

        # Rebuild settings only when the channel list changes
        ch_fingerprint = tuple(
            (ch.get('idx', 0), ch.get('name', '')) for ch in device_channels
        )
        last_fingerprint = tuple(
            (ch.get('idx', 0), ch.get('name', '')) for ch in self._last_device_channels
        )
        if ch_fingerprint != last_fingerprint:
            self._last_device_channels = device_channels
            self._rebuild_settings(device_channels)
            # Also rebuild channel buttons (config may have changed)
            enabled = self._config_store.get_enabled_channels()
            self._rebuild_channel_buttons(enabled)
