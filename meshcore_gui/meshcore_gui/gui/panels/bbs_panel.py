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

    The settings section lets users create, configure and delete boards.
    Each board can span one or more device channels (from SharedData).
    Configuration is persisted via BbsConfigStore.

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
        self._new_board_name_input = None
        self._new_board_channel_checks: Dict[int, object] = {}

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
            ui.label(
                'Create boards and assign device channels. '
                'One board can cover multiple channels.'
            ).classes('text-xs text-gray-500')
            ui.separator()

            # New board form
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.label('New board:').classes('text-sm text-gray-600')
                self._new_board_name_input = ui.input(
                    placeholder='Board name...',
                ).classes('text-xs').style('min-width: 160px')
                ui.button(
                    'Create', on_click=self._on_create_board,
                ).props('no-caps').classes('text-xs')

            ui.separator()
            self._boards_settings_container = ui.column().classes('w-full gap-3')
            with self._boards_settings_container:
                ui.label('No boards configured yet.').classes(
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
                ui.label('No boards configured.').classes(
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
    # Settings -- board list
    # ------------------------------------------------------------------

    def _rebuild_boards_settings(self) -> None:
        """Rebuild the settings section for all configured boards."""
        if not self._boards_settings_container:
            return
        self._boards_settings_container.clear()
        boards = self._config_store.get_boards()
        with self._boards_settings_container:
            if not boards:
                ui.label('No boards configured yet.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            for board in boards:
                self._render_board_settings_row(board)

    def _render_board_settings_row(self, board: BbsBoard) -> None:
        """Render one settings expansion for a single board.

        Args:
            board: Board to render.
        """
        with ui.expansion(
            board.name, value=False,
        ).classes('w-full').props('dense'):
            with ui.column().classes('w-full gap-2 p-2'):

                # Name
                name_input = ui.input(
                    label='Board name', value=board.name,
                ).classes('w-full text-xs')

                # Channel assignment
                ui.label('Channels (select which device channels belong to this board):').classes(
                    'text-xs text-gray-600'
                )
                ch_checks: Dict[int, object] = {}
                with ui.row().classes('flex-wrap gap-2'):
                    if not self._device_channels:
                        ui.label('No device channels known yet.').classes(
                            'text-xs text-gray-400 italic'
                        )
                    for ch in self._device_channels:
                        idx = ch.get('idx', ch.get('index', 0))
                        ch_name = ch.get('name', f'Ch {idx}')
                        cb = ui.checkbox(
                            f'[{idx}] {ch_name}',
                            value=idx in board.channels,
                        ).classes('text-xs')
                        ch_checks[idx] = cb

                # Categories
                cats_input = ui.input(
                    label='Categories (comma-separated)',
                    value=', '.join(board.categories),
                ).classes('w-full text-xs')

                # Regions
                regions_input = ui.input(
                    label='Regions (comma-separated, leave empty for none)',
                    value=', '.join(board.regions),
                ).classes('w-full text-xs')

                # Retention
                retention_input = ui.input(
                    label='Retention (hours)',
                    value=str(board.retention_hours),
                ).classes('text-xs').style('max-width: 160px')

                # Whitelist
                wl_input = ui.input(
                    label='Allowed keys (comma-separated hex, empty = all)',
                    value=', '.join(board.allowed_keys),
                ).classes('w-full text-xs')

                with ui.row().classes('gap-2'):
                    def _save(
                        bid=board.id,
                        ni=name_input,
                        cc=ch_checks,
                        ci=cats_input,
                        ri=regions_input,
                        ret=retention_input,
                        wli=wl_input,
                    ) -> None:
                        new_name = (ni.value or '').strip() or bid
                        selected_channels = [
                            idx for idx, cb in cc.items() if cb.value
                        ]
                        categories = [
                            c.strip().upper()
                            for c in (ci.value or '').split(',') if c.strip()
                        ] or list(DEFAULT_CATEGORIES)
                        regions = [
                            r.strip()
                            for r in (ri.value or '').split(',') if r.strip()
                        ]
                        try:
                            retention_hours = int(ret.value or DEFAULT_RETENTION_HOURS)
                        except ValueError:
                            retention_hours = DEFAULT_RETENTION_HOURS
                        allowed_keys = [
                            k.strip()
                            for k in (wli.value or '').split(',') if k.strip()
                        ]
                        updated = BbsBoard(
                            id=bid,
                            name=new_name,
                            channels=selected_channels,
                            categories=categories,
                            regions=regions,
                            retention_hours=retention_hours,
                            allowed_keys=allowed_keys,
                        )
                        self._config_store.set_board(updated)
                        debug_print(
                            f'BBS settings: saved board {bid} '
                            f'channels={selected_channels}'
                        )
                        ui.notify(f'Board "{new_name}" saved.', type='positive')
                        self._rebuild_board_buttons()
                        self._rebuild_boards_settings()

                    def _delete(bid=board.id, bname=board.name) -> None:
                        self._config_store.delete_board(bid)
                        if self._active_board and self._active_board.id == bid:
                            self._active_board = None
                        debug_print(f'BBS settings: deleted board {bid}')
                        ui.notify(f'Board "{bname}" deleted.', type='warning')
                        self._rebuild_board_buttons()
                        self._rebuild_boards_settings()

                    ui.button('Save', on_click=_save).props('no-caps').classes('text-xs')
                    ui.button(
                        'Delete', on_click=_delete,
                    ).props('no-caps flat color=negative').classes('text-xs')

    # ------------------------------------------------------------------
    # Settings -- create new board
    # ------------------------------------------------------------------

    def _on_create_board(self) -> None:
        """Handle the Create button for a new board."""
        name = (self._new_board_name_input.value or '').strip() if self._new_board_name_input else ''
        if not name:
            ui.notify('Enter a board name first.', type='warning')
            return

        board_id = _slug(name)
        # Make id unique if needed
        base_id = board_id
        counter = 2
        while self._config_store.board_id_exists(board_id):
            board_id = f'{base_id}_{counter}'
            counter += 1

        board = BbsBoard(
            id=board_id,
            name=name,
            channels=[],
            categories=list(DEFAULT_CATEGORIES),
            regions=[],
            retention_hours=DEFAULT_RETENTION_HOURS,
            allowed_keys=[],
        )
        self._config_store.set_board(board)
        debug_print(f'BBS settings: created board {board_id}')
        if self._new_board_name_input:
            self._new_board_name_input.value = ''
        ui.notify(f'Board "{name}" created. Assign channels in the settings below.', type='positive')
        self._rebuild_board_buttons()
        self._rebuild_boards_settings()

    # ------------------------------------------------------------------
    # External update hook
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Called by the dashboard timer with the SharedData snapshot.

        Rebuilds the settings channel checkboxes when the device channel
        list changes.

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
