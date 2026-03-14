"""BBS panel -- board-based Bulletin Board System viewer and configuration."""

import re
from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.config import debug_print
from meshcore_gui.services.bbs_config_store import (
    BbsBoard,
    BbsConfigStore,
    DEFAULT_CATEGORIES,
    DEFAULT_RETENTION_HOURS,
)
from meshcore_gui.services.bbs_service import BbsMessage, BbsService


def _slug(name: str) -> str:
    """Convert a board name to a safe id slug.

    Args:
        name: Human-readable board name.

    Returns:
        Lowercase alphanumeric + underscore string.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "board"


class BbsPanel:
    """BBS panel: board selector, filters, message list, post form and settings.

    The settings section automatically derives one board per device channel.
    Boards are enabled/disabled per channel; no manual board creation needed.
    Advanced options (regions, allowed keys, channel combining) are hidden
    in a collapsible section for administrator use.

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
        self._active_board: Optional[BbsBoard] = None
        self._active_region: Optional[str] = None
        self._active_category: Optional[str] = None

        # UI refs -- message view
        self._board_btn_row = None
        self._region_row = None
        self._region_select = None
        self._category_select = None
        self._text_input = None
        self._post_region_row = None
        self._post_region_select = None
        self._post_category_select = None
        self._msg_list_container = None

        # UI refs -- settings
        self._boards_settings_container = None

        # Cached device channels (updated by update())
        self._device_channels: List[Dict] = []
        self._last_ch_fingerprint: tuple = ()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the complete BBS panel layout."""
        # ---- Message view card --------------------------------------
        with ui.card().classes('w-full'):
            ui.label('BBS -- Bulletin Board System').classes('font-bold text-gray-600')

            self._board_btn_row = ui.row().classes('w-full items-center gap-2 flex-wrap')
            with self._board_btn_row:
                ui.label('Board:').classes('text-sm text-gray-600')

            ui.separator()

            with ui.row().classes('w-full items-center gap-4 flex-wrap'):
                ui.label('Filter:').classes('text-sm text-gray-600')

                self._region_row = ui.row().classes('items-center gap-2')
                with self._region_row:
                    ui.label('Region:').classes('text-xs text-gray-600')
                    self._region_select = ui.select(
                        options=[], value=None,
                        on_change=lambda e: self._on_region_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                with ui.row().classes('items-center gap-2'):
                    ui.label('Category:').classes('text-xs text-gray-600')
                    self._category_select = ui.select(
                        options=[], value=None,
                        on_change=lambda e: self._on_category_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                ui.button(
                    'Refresh', on_click=self._refresh_messages,
                ).props('flat no-caps').classes('text-xs')

            ui.separator()

            self._msg_list_container = ui.column().classes(
                'w-full gap-1 h-72 overflow-y-auto bg-gray-50 rounded p-2'
            )

            ui.separator()

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

        # ---- Settings card ------------------------------------------
        with ui.card().classes('w-full'):
            ui.label('BBS Settings').classes('font-bold text-gray-600')
            ui.separator()

            self._boards_settings_container = ui.column().classes('w-full gap-3')
            with self._boards_settings_container:
                ui.label('Connect device to see channels.').classes(
                    'text-xs text-gray-400 italic'
                )

        # Initial render
        self._rebuild_board_buttons()
        self._rebuild_boards_settings()

    # ------------------------------------------------------------------
    # Board selector (message view)
    # ------------------------------------------------------------------

    def _rebuild_board_buttons(self) -> None:
        """Rebuild board selector buttons from current config."""
        if not self._board_btn_row:
            return
        self._board_btn_row.clear()
        boards = self._config_store.get_boards()
        with self._board_btn_row:
            ui.label('Board:').classes('text-sm text-gray-600')
            if not boards:
                ui.label('No active boards.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            for board in boards:
                ui.button(
                    board.name,
                    on_click=lambda b=board: self._select_board(b),
                ).props('flat no-caps').classes('text-xs')

        # Auto-select first board if none active or active was deleted
        ids = [b.id for b in boards]
        if boards and (self._active_board is None or self._active_board.id not in ids):
            self._select_board(boards[0])

    def _select_board(self, board: BbsBoard) -> None:
        """Activate a board and rebuild filter selects.

        Args:
            board: Board to activate.
        """
        self._active_board = board
        self._active_region = None
        self._active_category = None

        has_regions = bool(board.regions)
        if self._region_row:
            self._region_row.set_visibility(has_regions)
        if self._post_region_row:
            self._post_region_row.set_visibility(has_regions)

        region_opts = ['(all)'] + board.regions
        if self._region_select:
            self._region_select.options = region_opts
            self._region_select.value = '(all)'
        if self._post_region_select:
            self._post_region_select.options = board.regions
            self._post_region_select.value = board.regions[0] if board.regions else None

        cat_opts = ['(all)'] + board.categories
        if self._category_select:
            self._category_select.options = cat_opts
            self._category_select.value = '(all)'
        if self._post_category_select:
            self._post_category_select.options = board.categories
            self._post_category_select.value = board.categories[0] if board.categories else None

        self._refresh_messages()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _on_region_filter(self, value: Optional[str]) -> None:
        self._active_region = None if (not value or value == '(all)') else value
        self._refresh_messages()

    def _on_category_filter(self, value: Optional[str]) -> None:
        self._active_category = None if (not value or value == '(all)') else value
        self._refresh_messages()

    # ------------------------------------------------------------------
    # Message list
    # ------------------------------------------------------------------

    def _refresh_messages(self) -> None:
        if not self._msg_list_container:
            return
        self._msg_list_container.clear()
        with self._msg_list_container:
            if self._active_board is None:
                ui.label('Select a board above.').classes('text-xs text-gray-400 italic')
                return
            if not self._active_board.channels:
                ui.label('No channels assigned to this board.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            messages = self._service.get_all_messages(
                channels=self._active_board.channels,
                region=self._active_region,
                category=self._active_category,
            )
            if not messages:
                ui.label('No messages.').classes('text-xs text-gray-400 italic')
                return
            for msg in messages:
                self._render_message_row(msg)

    def _render_message_row(self, msg: BbsMessage) -> None:
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
        if self._active_board is None:
            ui.notify('Select a board first.', type='warning')
            return
        if not self._active_board.channels:
            ui.notify('No channels assigned to this board.', type='warning')
            return

        text = (self._text_input.value or '').strip() if self._text_input else ''
        if not text:
            ui.notify('Message text cannot be empty.', type='warning')
            return

        category = (
            self._post_category_select.value if self._post_category_select
            else (self._active_board.categories[0] if self._active_board.categories else '')
        )
        if not category:
            ui.notify('Please select a category.', type='warning')
            return

        region = ''
        if self._active_board.regions and self._post_region_select:
            region = self._post_region_select.value or ''

        # Post on first assigned channel (primary channel for outgoing)
        target_channel = self._active_board.channels[0]

        msg = BbsMessage(
            channel=target_channel,
            region=region, category=category,
            sender='Me', sender_key='', text=text,
        )
        self._service.post_message(msg)

        region_part = f'{region} ' if region else ''
        mesh_text = f'!bbs post {region_part}{category} {text}'
        self._put_command({
            'action': 'send_message',
            'channel': target_channel,
            'text': mesh_text,
        })
        debug_print(
            f'BBS panel: posted to board={self._active_board.id} '
            f'ch={target_channel} {mesh_text[:60]}'
        )

        if self._text_input:
            self._text_input.value = ''
        self._refresh_messages()
        ui.notify('Message posted.', type='positive')

    # ------------------------------------------------------------------
    # Settings -- channel list (standard view)
    # ------------------------------------------------------------------

    def _rebuild_boards_settings(self) -> None:
        """Rebuild settings: one row per device channel + collapsed advanced section."""
        if not self._boards_settings_container:
            return
        self._boards_settings_container.clear()
        with self._boards_settings_container:
            if not self._device_channels:
                ui.label('Connect device to see channels.').classes(
                    'text-xs text-gray-400 italic'
                )
                return

            # Standard view: one row per channel
            for ch in self._device_channels:
                self._render_channel_settings_row(ch)

            ui.separator()

            # Advanced section (collapsed)
            with ui.expansion('Advanced', value=False).classes('w-full').props('dense'):
                ui.label('Regions and key list per channel').classes(
                    'text-xs text-gray-500 pb-1'
                )
                advanced_any = False
                for ch in self._device_channels:
                    idx = ch.get('idx', ch.get('index', 0))
                    board = self._config_store.get_board(f'ch{idx}')
                    if board is not None:
                        self._render_channel_advanced_row(ch, board)
                        advanced_any = True
                if not advanced_any:
                    ui.label(
                        'Enable at least one channel to see advanced options.'
                    ).classes('text-xs text-gray-400 italic')

    def _render_channel_settings_row(self, ch: Dict) -> None:
        """Render the standard settings row for a single device channel.

        Shows enable toggle, categories, retention and a Save button.

        Args:
            ch: Device channel dict with 'idx'/'index' and 'name' keys.
        """
        idx = ch.get('idx', ch.get('index', 0))
        ch_name = ch.get('name', f'Ch {idx}')
        board_id = f'ch{idx}'
        board = self._config_store.get_board(board_id)

        is_active = board is not None
        cats_value = ', '.join(board.categories) if board else ', '.join(DEFAULT_CATEGORIES)
        retention_value = str(board.retention_hours) if board else str(DEFAULT_RETENTION_HOURS)

        with ui.card().classes('w-full p-2'):
            # Header row: channel name + active toggle
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(f'[{idx}] {ch_name}').classes('text-sm font-medium')
                active_toggle = ui.toggle(
                    {True: '● Active', False: '○ Off'},
                    value=is_active,
                ).classes('text-xs')

            # Categories
            with ui.row().classes('w-full items-center gap-2 mt-1'):
                ui.label('Categories:').classes('text-xs text-gray-600 w-24 shrink-0')
                cats_input = ui.input(value=cats_value).classes('text-xs flex-grow')

            # Retention
            with ui.row().classes('w-full items-center gap-2 mt-1'):
                ui.label('Retain:').classes('text-xs text-gray-600 w-24 shrink-0')
                retention_input = ui.input(value=retention_value).classes('text-xs').style(
                    'max-width: 80px'
                )
                ui.label('hrs').classes('text-xs text-gray-600')

            def _save(
                bid=board_id,
                bname=ch_name,
                bidx=idx,
                tog=active_toggle,
                ci=cats_input,
                ri=retention_input,
            ) -> None:
                if tog.value:
                    existing = self._config_store.get_board(bid)
                    categories = [
                        c.strip().upper()
                        for c in (ci.value or '').split(',') if c.strip()
                    ] or list(DEFAULT_CATEGORIES)
                    try:
                        ret_hours = int(ri.value or DEFAULT_RETENTION_HOURS)
                    except ValueError:
                        ret_hours = DEFAULT_RETENTION_HOURS
                    # Preserve extra combined channels and advanced fields if board existed
                    extra_channels = (
                        [c for c in existing.channels if c != bidx]
                        if existing else []
                    )
                    updated = BbsBoard(
                        id=bid,
                        name=bname,
                        channels=[bidx] + extra_channels,
                        categories=categories,
                        regions=existing.regions if existing else [],
                        retention_hours=ret_hours,
                        allowed_keys=existing.allowed_keys if existing else [],
                    )
                    self._config_store.set_board(updated)
                    debug_print(f'BBS settings: channel {bid} saved')
                    ui.notify(f'{bname} saved.', type='positive')
                else:
                    self._config_store.delete_board(bid)
                    if self._active_board and self._active_board.id == bid:
                        self._active_board = None
                    debug_print(f'BBS settings: channel {bid} disabled')
                    ui.notify(f'{bname} disabled.', type='warning')
                self._rebuild_board_buttons()
                self._rebuild_boards_settings()

            ui.button('Save', on_click=_save).props('no-caps').classes('text-xs mt-1')

    # ------------------------------------------------------------------
    # Settings -- advanced section (collapsed)
    # ------------------------------------------------------------------

    def _render_channel_advanced_row(self, ch: Dict, board: BbsBoard) -> None:
        """Render the advanced settings block for a single active channel.

        Shows regions, allowed keys and optional channel combining.

        Args:
            ch:    Device channel dict.
            board: Existing BbsBoard for this channel.
        """
        idx = ch.get('idx', ch.get('index', 0))
        ch_name = ch.get('name', f'Ch {idx}')
        board_id = f'ch{idx}'

        with ui.column().classes('w-full gap-1 py-2'):
            ui.label(f'[{idx}] {ch_name}').classes('text-sm font-medium')

            regions_input = ui.input(
                label="Regions (comma-separated)",
                value=', '.join(board.regions),
            ).classes('w-full text-xs')

            wl_input = ui.input(
                label='Allowed keys (empty = everyone on the channel)',
                value=', '.join(board.allowed_keys),
            ).classes('w-full text-xs')

            # Combine with other channels
            other_channels = [
                c for c in self._device_channels
                if c.get('idx', c.get('index', 0)) != idx
            ]
            ch_checks: Dict[int, object] = {}
            if other_channels:
                ui.label('Combine with channels:').classes('text-xs text-gray-600 mt-1')
                with ui.row().classes('flex-wrap gap-2'):
                    for other_ch in other_channels:
                        other_idx = other_ch.get('idx', other_ch.get('index', 0))
                        other_name = other_ch.get('name', f'Ch {other_idx}')
                        cb = ui.checkbox(
                            f'[{other_idx}] {other_name}',
                            value=other_idx in board.channels,
                        ).classes('text-xs')
                        ch_checks[other_idx] = cb

            def _save_adv(
                bid=board_id,
                bidx=idx,
                bname=ch_name,
                ri=regions_input,
                wli=wl_input,
                cc=ch_checks,
            ) -> None:
                existing = self._config_store.get_board(bid)
                if existing is None:
                    ui.notify('Enable this channel first.', type='warning')
                    return
                regions = [
                    r.strip() for r in (ri.value or '').split(',') if r.strip()
                ]
                allowed_keys = [
                    k.strip() for k in (wli.value or '').split(',') if k.strip()
                ]
                combined = [bidx] + [oidx for oidx, cb in cc.items() if cb.value]
                updated = BbsBoard(
                    id=bid,
                    name=bname,
                    channels=combined,
                    categories=existing.categories,
                    regions=regions,
                    retention_hours=existing.retention_hours,
                    allowed_keys=allowed_keys,
                )
                self._config_store.set_board(updated)
                debug_print(f'BBS settings (advanced): {bid} saved')
                ui.notify(f'{bname} saved.', type='positive')
                self._rebuild_board_buttons()
                self._rebuild_boards_settings()

            ui.button('Save', on_click=_save_adv).props('no-caps').classes('text-xs mt-1')
            ui.separator()

    # ------------------------------------------------------------------
    # External update hook
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Called by the dashboard timer with the SharedData snapshot.

        Rebuilds the settings channel list when the device channel list
        changes.

        Args:
            data: SharedData snapshot dict.
        """
        device_channels = data.get('channels', [])
        fingerprint = tuple(
            (ch.get('idx', 0), ch.get('name', '')) for ch in device_channels
        )
        if fingerprint != self._last_ch_fingerprint:
            self._last_ch_fingerprint = fingerprint
            self._device_channels = device_channels
            self._rebuild_boards_settings()
