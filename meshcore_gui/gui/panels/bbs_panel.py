"""BBS panel -- board-based Bulletin Board System viewer and configuration."""

import re
from typing import Callable, Dict, List, Optional, Tuple

from nicegui import ui

from meshcore_gui.config import debug_print
from meshcore_gui.services.bbs_config_store import (
    BbsBoard,
    BbsConfigStore,
    DEFAULT_CATEGORIES,
    DEFAULT_RETENTION_DAYS,
)
from meshcore_gui.services.bbs_service import BbsMessage, BbsService
from meshcore_gui.core.protocols import SharedDataReadAndLookup


def _slug(name: str) -> str:
    """Convert a board name to a safe id slug.

    Args:
        name: Human-readable board name.

    Returns:
        Lowercase alphanumeric + underscore string.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "board"


# ---------------------------------------------------------------------------
# Main BBS panel (message view only — settings live on /bbs-settings)
# ---------------------------------------------------------------------------

class BbsPanel:
    """BBS panel: whitelist info, category buttons, message list and post form.

    Settings are on a separate page (/bbs-settings), reachable via the
    gear icon in the panel header.

    The linked channels are shown as a read-only ``Whitelist:`` label:
    they are the channels on which senders register with ``!bbs``; all
    of them feed one board.  Messages can be deleted only here, via the
    delete icon on each message row — there is no mesh delete command.

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
        self._active_category: Optional[str] = None

        # UI refs
        self._board_btn_row = None
        self._category_btn_row = None
        self._msg_list_container = None
        self._post_region_row = None
        self._post_region_select = None
        self._post_category_select = None
        self._text_input = None

        # Button refs for active highlight
        self._board_buttons: Dict[str, object] = {}
        self._category_buttons: Dict[str, object] = {}

        # Cached device channels (updated by update())
        self._device_channels: List[Dict] = []
        self._last_ch_fingerprint: tuple = ()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the BBS message view panel layout."""
        with ui.card().classes('w-full'):
            # Header row with gear icon
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('BBS -- Bulletin Board System').classes('font-bold text-gray-600')
                ui.button(
                    icon='settings',
                    on_click=lambda: ui.navigate.to('/bbs-settings'),
                ).props('flat round dense').tooltip('BBS Settings')

            # Board selector row
            self._board_btn_row = ui.row().classes('w-full items-center gap-1 flex-wrap')
            with self._board_btn_row:
                ui.label('No active boards — open Settings to enable a channel.').classes(
                    'text-xs text-gray-400 italic'
                )

            ui.separator()

            # Category filter row (clickable buttons, replaces dropdown)
            self._category_btn_row = ui.row().classes('w-full items-center gap-1 flex-wrap')
            with self._category_btn_row:
                ui.label('Select a board first.').classes('text-xs text-gray-400 italic')

            ui.separator()

            # Message list
            self._msg_list_container = ui.column().classes(
                'w-full gap-1 overflow-y-auto overflow-x-hidden bg-gray-50 rounded p-2'
            ).style('max-height: calc(100vh - 24rem); min-height: 8rem')

            ui.separator()

            # Post row — keep selects for sending
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
                ).classes('flex-grow text-sm min-w-0')

                ui.button('Send', on_click=self._on_post).props('no-caps').classes('text-xs')

        # Initial render
        self._rebuild_board_buttons()

    # ------------------------------------------------------------------
    # Board selector
    # ------------------------------------------------------------------

    def _rebuild_board_buttons(self) -> None:
        """Rebuild the whitelist info label from the current config.

        One node has one board; its channels are whitelist entry points,
        not separate boards.  They are therefore shown as a read-only
        label instead of a (single, misleading) selector button.
        """
        if not self._board_btn_row:
            return
        self._board_btn_row.clear()
        self._board_buttons = {}
        boards = self._config_store.get_boards()
        with self._board_btn_row:
            if not boards:
                ui.label('No active boards — open Settings to enable a channel.').classes(
                    'text-xs text-gray-400 italic'
                )
                return
            for board in boards:
                ui.label(f'Whitelist: {board.name}').classes(
                    'text-xs text-gray-400'
                ).tooltip('Channels on which senders register with !bbs')

        ids = [b.id for b in boards]
        if boards and (self._active_board is None or self._active_board.id not in ids):
            self._select_board(boards[0])
        elif self._active_board and self._active_board.id in self._board_buttons:
            self._board_buttons[self._active_board.id].classes('domca-menu-active')

    def _select_board(self, board: BbsBoard) -> None:
        """Activate a board and rebuild category buttons.

        Args:
            board: Board to activate.
        """
        self._active_board = board
        self._active_category = None

        # Update board button highlights
        for bid, btn in self._board_buttons.items():
            if bid == board.id:
                btn.classes('domca-menu-active', remove='')
            else:
                btn.classes(remove='domca-menu-active')

        # Update post selects
        if self._post_region_row:
            self._post_region_row.set_visibility(bool(board.regions))
        if self._post_region_select:
            self._post_region_select.options = board.regions
            self._post_region_select.value = board.regions[0] if board.regions else None
        if self._post_category_select:
            self._post_category_select.options = board.categories
            self._post_category_select.value = board.categories[0] if board.categories else None

        self._rebuild_category_buttons()
        self._refresh_messages()

    # ------------------------------------------------------------------
    # Category buttons
    # ------------------------------------------------------------------

    def _rebuild_category_buttons(self) -> None:
        """Rebuild clickable category filter buttons for the active board."""
        if not self._category_btn_row:
            return
        self._category_btn_row.clear()
        self._category_buttons = {}
        if self._active_board is None:
            with self._category_btn_row:
                ui.label('Select a board first.').classes('text-xs text-gray-400 italic')
            return
        with self._category_btn_row:
            # "All" button
            all_btn = ui.button(
                'ALL',
                on_click=lambda: self._on_category_filter(None),
            ).props('flat no-caps').classes('text-xs domca-menu-btn')
            self._category_buttons['__all__'] = all_btn

            for cat in self._active_board.categories:
                btn = ui.button(
                    cat,
                    on_click=lambda c=cat: self._on_category_filter(c),
                ).props('flat no-caps').classes('text-xs domca-menu-btn')
                self._category_buttons[cat] = btn

        # Highlight the current active category
        self._update_category_highlight()

    def _on_category_filter(self, category: Optional[str]) -> None:
        """Handle category button click.

        Args:
            category: Category string, or None for all.
        """
        self._active_category = category
        self._update_category_highlight()
        self._refresh_messages()

    def _update_category_highlight(self) -> None:
        """Apply domca-menu-active to the currently selected category button."""
        active_key = self._active_category if self._active_category else '__all__'
        for key, btn in self._category_buttons.items():
            if key == active_key:
                btn.classes('domca-menu-active', remove='')
            else:
                btn.classes(remove='domca-menu-active')

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
                region=None,
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
        with ui.column().classes('w-full min-w-0 gap-0 py-1 border-b border-gray-200'):
            with ui.row().classes('w-full items-center justify-between no-wrap'):
                ui.label(header).classes('text-xs text-gray-500').style(
                    'word-break: break-all; overflow-wrap: break-word'
                )
                ui.button(
                    icon='delete',
                    on_click=lambda m=msg, h=header: self._open_delete_dialog(m, h),
                ).props('flat round dense').tooltip('Delete message')
            ui.label(msg.text).classes('text-sm').style(
                'word-break: break-word; overflow-wrap: break-word'
            )

    # ------------------------------------------------------------------
    # Delete (GUI only — no mesh command reaches BbsService.delete_message)
    # ------------------------------------------------------------------

    def _open_delete_dialog(self, msg: BbsMessage, header: str) -> None:
        """Ask for confirmation and delete *msg* from the BBS.

        Args:
            msg:    Message to delete (must carry its database ``id``).
            header: Display header of the message row, shown in the dialog.
        """
        if msg.id is None:
            ui.notify('Message has no id; cannot delete.', type='warning')
            return

        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Delete BBS message?').classes('font-bold text-lg')
            ui.label(header).classes('text-xs text-gray-500')
            ui.label(msg.text[:60]).classes('text-sm')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                def confirm_delete() -> None:
                    dialog.close()
                    if self._service.delete_message(msg.id):
                        debug_print(f'BBS panel: deleted message id={msg.id}')
                        ui.notify('Message deleted.', type='positive')
                    else:
                        ui.notify('Message no longer exists.', type='warning')
                    self._refresh_messages()

                ui.button('Delete', on_click=confirm_delete).classes(
                    'bg-blue-500 text-white'
                )

        dialog.open()

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

        target_channel = self._active_board.channels[0]

        msg = BbsMessage(
            channel=target_channel,
            region=region, category=category,
            sender='Me', sender_key='', text=text,
        )
        self._service.post_message(msg)

        debug_print(
            f'BBS panel: locally posted to board={self._active_board.id} '
            f'ch={target_channel} [{category}] {text[:60]}'
        )

        if self._text_input:
            self._text_input.value = ''
        self._refresh_messages()
        ui.notify('Message posted.', type='positive')

    # ------------------------------------------------------------------
    # External update hook
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Called by the dashboard timer with the SharedData snapshot.

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
            self._rebuild_board_buttons()


# ---------------------------------------------------------------------------
# Separate settings page (/bbs-settings)
# ---------------------------------------------------------------------------

class BbsSettingsPage:
    """Standalone BBS settings page, registered at /bbs-settings.

    One node = one board.  The page shows a single channel selector
    populated from the active device channels, plus a categories field,
    a retention field per category with a default for other categories
    (v1.26.0), and a collapsible Advanced section for regions and
    allowed keys.  There is no board creation or deletion UI.

    Args:
        shared:       SharedData instance (for device channel list).
        config_store: BbsConfigStore instance.
    """

    def __init__(
        self,
        shared: SharedDataReadAndLookup,
        config_store: BbsConfigStore,
    ) -> None:
        self._shared = shared
        self._config_store = config_store
        self._device_channels: List[Dict] = []
        self._container = None

    def render(self) -> None:
        """Render the BBS settings page."""
        from meshcore_gui.gui.dashboard import _DOMCA_HEAD  # lazy — avoids circular import
        data = self._shared.get_snapshot()
        self._device_channels = data.get('channels', [])

        ui.page_title('BBS Settings')
        ui.add_head_html(_DOMCA_HEAD)
        ui.dark_mode(True)

        with ui.header().classes('items-center px-4 py-2 shadow-md'):
            ui.button(
                icon='arrow_back',
                on_click=lambda: ui.run_javascript('window.history.back()'),
            ).props('flat round dense color=white').tooltip('Back')
            ui.label('📋 BBS Settings').classes(
                'text-lg font-bold domca-header-text'
            ).style("font-family: 'JetBrains Mono', monospace")
            ui.space()

        with ui.column().classes('domca-panel gap-4').style('padding-top: 1rem'):
            with ui.card().classes('w-full'):
                ui.label('BBS Settings').classes('font-bold text-gray-600')
                ui.separator()

                self._container = ui.column().classes('w-full gap-3')
                with self._container:
                    if not self._device_channels:
                        ui.label('Connect device to see channels.').classes(
                            'text-xs text-gray-400 italic'
                        )
                    else:
                        self._render_settings()

    # ------------------------------------------------------------------
    # Settings rendering
    # ------------------------------------------------------------------

    def _render_settings(self) -> None:
        """Render the board settings block."""
        board = self._config_store.get_single_board()
        active_channels = set(board.channels) if board else set()
        cats_value = (
            ', '.join(board.categories) if board
            else ', '.join(DEFAULT_CATEGORIES)
        )
        retention_values = self._retention_values(board)
        adv_regions_value = ', '.join(board.regions) if board else ''
        adv_keys_value = ', '.join(board.allowed_keys) if board else ''

        # ── Channel checkboxes ───────────────────────────────────────
        ch_checks: Dict[int, object] = {}
        with ui.column().classes('w-full gap-1'):
            ui.label('Channels:').classes('text-xs text-gray-600')
            with ui.column().classes('w-full gap-1 pl-2'):
                for ch in self._device_channels:
                    idx = ch.get('idx', ch.get('index', 0))
                    name = ch.get('name', f'Ch {idx}')
                    cb = ui.checkbox(
                        f'[{idx}] {name}',
                        value=idx in active_channels,
                    ).classes('text-xs')
                    ch_checks[idx] = cb

        # ── Categories + retention ───────────────────────────────────
        with ui.row().classes('w-full items-center gap-2 mt-1'):
            ui.label('Categories:').classes('text-xs text-gray-600 w-24 shrink-0')
            cats_input = ui.input(value=cats_value).classes('text-xs flex-grow')

        retention_inputs = self._render_retention_section(cats_input, retention_values)

        # ── Advanced (collapsed) ─────────────────────────────────────
        with ui.expansion('Advanced', value=False).classes('w-full mt-2').props('dense'):
            ui.label('Regions and allowed keys').classes('text-xs text-gray-500 pb-1')

            regions_input = ui.input(
                label='Regions (comma-separated)',
                value=adv_regions_value,
            ).classes('w-full text-xs')

            keys_input = ui.input(
                label='Allowed keys (empty = auto-learned from channel activity)',
                value=adv_keys_value,
            ).classes('w-full text-xs')

        # ── Save ─────────────────────────────────────────────────────
        def _save(
            cc=ch_checks,
            ci=cats_input,
            rgi=regions_input,
            ki=keys_input,
        ) -> None:
            selected = [idx for idx, cb in cc.items() if cb.value]
            if not selected:
                ui.notify('Select at least one channel.', type='warning')
                return

            ch_names = {
                ch.get('idx', ch.get('index', 0)): ch.get('name', '?')
                for ch in self._device_channels
            }
            categories = self._parse_categories(ci.value)
            retention = self._collect_retention(categories, retention_inputs)
            if retention is None:
                ui.notify(
                    'Retention must be a whole number of days (0 = keep forever).',
                    type='warning',
                )
                return
            default_days, category_days = retention
            regions = [r.strip() for r in (rgi.value or '').split(',') if r.strip()]
            # Only pass allowed_keys if the field was explicitly filled;
            # empty field means "keep auto-learned keys"
            raw_keys = [k.strip() for k in (ki.value or '').split(',') if k.strip()]
            allowed_keys = raw_keys if raw_keys else None

            self._config_store.configure_board(
                channel_indices=selected,
                channel_names=ch_names,
                categories=categories,
                regions=regions,
                allowed_keys=allowed_keys,
                default_retention_days=default_days,
                category_retention_days=category_days,
            )
            ch_labels = ', '.join(f"[{i}] {ch_names.get(i, '?')}" for i in sorted(selected))
            debug_print(f'BBS settings: configured channels {ch_labels}')
            ui.notify(f'BBS saved — {ch_labels}.', type='positive')
            self._rebuild()

        ui.button('Save', on_click=_save).props('no-caps').classes('text-xs mt-2')

    # ------------------------------------------------------------------
    # Retention per category (v1.26.0)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_categories(text: Optional[str]) -> List[str]:
        """Parse the comma-separated categories field.

        Args:
            text: Field value, e.g. ``'urgent, status'``.

        Returns:
            Upper-case category names in input order, without empty
            entries; ``DEFAULT_CATEGORIES`` when nothing remains.
        """
        return [
            c.strip().upper() for c in (text or '').split(',') if c.strip()
        ] or list(DEFAULT_CATEGORIES)

    @staticmethod
    def _parse_days(value: object) -> Optional[int]:
        """Parse a retention field.

        Args:
            value: Field value (string or number).

        Returns:
            Whole number of days ``>= 0`` (``0`` = keep forever), or
            ``None`` when the value is empty, not a whole number, or
            negative.
        """
        try:
            days = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return days if days >= 0 else None

    @staticmethod
    def _retention_values(board: Optional[BbsBoard]) -> Dict[str, str]:
        """Return the initial retention field texts for *board*.

        Args:
            board: Configured board, or ``None`` when none exists yet.

        Returns:
            Mapping upper-case category → days as text, plus key ``'*'``
            for the default of other categories.  Without a board only
            ``'*'`` is set, to ``DEFAULT_RETENTION_DAYS``.
        """
        if board is None:
            return {'*': str(DEFAULT_RETENTION_DAYS)}
        values = {
            cat.upper(): str(board.retention_days_for(cat)) for cat in board.categories
        }
        values['*'] = str(board.default_retention_days)
        return values

    @classmethod
    def _collect_retention(
        cls, categories: List[str], inputs: Dict[str, object],
    ) -> Optional[Tuple[int, Dict[str, int]]]:
        """Read and validate the retention fields.

        Args:
            categories: Upper-case category names to save.
            inputs:     Mapping category → input element, plus ``'*'``
                        for the default; a category without an input
                        element gets the default.

        Returns:
            Tuple of (default days, days per category), or ``None`` when
            any field is not a whole number ``>= 0``.
        """
        default_input = inputs.get('*')
        default_days = cls._parse_days(
            default_input.value if default_input is not None else DEFAULT_RETENTION_DAYS
        )
        if default_days is None:
            return None
        category_days: Dict[str, int] = {}
        for cat in categories:
            inp = inputs.get(cat)
            days = cls._parse_days(inp.value) if inp is not None else default_days
            if days is None:
                return None
            category_days[cat] = days
        return default_days, category_days

    def _render_retention_section(
        self, cats_input, values: Dict[str, str],
    ) -> Dict[str, object]:
        """Render the retention block and keep it in step with the categories.

        The rows are rebuilt when *cats_input* loses focus; values
        already entered are kept for categories that remain, new
        categories start with the current default.

        Args:
            cats_input: Categories input element (comma-separated names).
            values:     Initial field texts, see :meth:`_retention_values`.

        Returns:
            Mapping category → input element plus ``'*'`` for the
            default.  The same dict is refilled on every rebuild, so the
            save handler always reads the current fields.
        """
        inputs: Dict[str, object] = {}
        with ui.column().classes('w-full gap-1'):
            ui.label('Retain (days, 0 = keep forever):').classes('text-xs text-gray-600')
            rows = ui.column().classes('w-full gap-0 pl-2')
        self._render_retention_rows(
            rows, self._parse_categories(cats_input.value), values, inputs,
        )

        def _on_categories_changed() -> None:
            """Rebuild the rows from the edited category list."""
            current = {cat: str(inp.value) for cat, inp in inputs.items()}
            self._render_retention_rows(
                rows, self._parse_categories(cats_input.value), current, inputs,
            )

        cats_input.on('blur', _on_categories_changed)
        return inputs

    @staticmethod
    def _render_retention_rows(
        container,
        categories: List[str],
        values: Dict[str, str],
        inputs: Dict[str, object],
    ) -> None:
        """(Re)build one retention row per category plus the default row.

        Clears *container*, then adds a row *name — days input — "days"*
        per category and a final *Other categories* row for the board
        default.  *inputs* is emptied and refilled with the new input
        elements.

        Args:
            container:  NiceGUI column that holds the rows.
            categories: Upper-case category names, in display order.
            values:     Field text per category and ``'*'`` for the
                        default; a missing category gets the default text.
            inputs:     Mapping category → input element, ``'*'`` = default
                        (mutated).
        """
        default_value = values.get('*', str(DEFAULT_RETENTION_DAYS))
        container.clear()
        inputs.clear()
        with container:
            for cat in categories:
                with ui.row().classes('items-center gap-2'):
                    ui.label(cat).classes('text-xs w-32 shrink-0')
                    inputs[cat] = ui.input(
                        value=values.get(cat, default_value),
                    ).classes('text-xs').style('max-width: 80px')
                    ui.label('days').classes('text-xs text-gray-600')
            with ui.row().classes('items-center gap-2'):
                ui.label('Other categories').classes(
                    'text-xs text-gray-500 italic w-32 shrink-0'
                ).tooltip('Messages in a category that is no longer listed')
                inputs['*'] = ui.input(value=default_value).classes('text-xs').style(
                    'max-width: 80px'
                )
                ui.label('days').classes('text-xs text-gray-600')

    def _rebuild(self) -> None:
        """Clear and re-render the settings container in-place."""
        if not self._container:
            return
        data = self._shared.get_snapshot()
        self._device_channels = data.get('channels', [])
        self._container.clear()
        with self._container:
            if not self._device_channels:
                ui.label('Connect device to see channels.').classes(
                    'text-xs text-gray-400 italic'
                )
            else:
                self._render_settings()
