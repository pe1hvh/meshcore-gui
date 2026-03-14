"""BBS panel — offline Bulletin Board System viewer and post form."""

from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.config import debug_print
from meshcore_gui.services.bbs_service import BbsMessage, BbsService


class BbsPanel:
    """BBS panel: channel selector, region/category filters, message list and post form.

    All data access goes through :class:`~meshcore_gui.services.bbs_service.BbsService`.
    No direct SQLite access in this class (SOLID: SRP / DIP).

    Args:
        put_command:     Callable to enqueue a command dict for the worker.
        bbs_service:     Shared ``BbsService`` instance.
        channels_config: ``BBS_CHANNELS`` list from ``config.py``.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        bbs_service: BbsService,
        channels_config: List[Dict],
    ) -> None:
        self._put_command = put_command
        self._service = bbs_service
        self._channels_config = channels_config

        # Indexed for fast lookup
        self._channels_by_idx: Dict[int, Dict] = {
            cfg["channel"]: cfg for cfg in channels_config
        }

        # UI state
        self._active_channel_idx: int = (
            channels_config[0]["channel"] if channels_config else 0
        )
        self._active_region: Optional[str] = None
        self._active_category: Optional[str] = None

        # UI element references
        self._msg_list_container = None
        self._region_select = None
        self._region_row = None
        self._category_select = None
        self._text_input = None
        self._post_region_select = None
        self._post_region_row = None
        self._post_category_select = None

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the complete BBS panel layout."""
        with ui.card().classes('w-full'):
            ui.label('📋 BBS — Bulletin Board System').classes('font-bold text-gray-600')

            # ── Channel selector ──────────────────────────────────────
            with ui.row().classes('w-full items-center gap-4'):
                ui.label('Channel:').classes('text-sm text-gray-600')
                for cfg in self._channels_config:
                    idx = cfg["channel"]
                    name = cfg["name"]
                    ui.button(
                        name,
                        on_click=lambda i=idx: self._select_channel(i),
                    ).props('flat no-caps').classes('text-xs')

            ui.separator()

            # ── Filter row ────────────────────────────────────────────
            with ui.row().classes('w-full items-center gap-4'):
                ui.label('Filter:').classes('text-sm text-gray-600')

                # Region filter (hidden when channel has no regions)
                self._region_row = ui.row().classes('items-center gap-2')
                with self._region_row:
                    ui.label('Region:').classes('text-xs text-gray-600')
                    self._region_select = ui.select(
                        options=[],
                        value=None,
                        on_change=lambda e: self._on_region_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                # Category filter
                with ui.row().classes('items-center gap-2'):
                    ui.label('Category:').classes('text-xs text-gray-600')
                    self._category_select = ui.select(
                        options=[],
                        value=None,
                        on_change=lambda e: self._on_category_filter(e.value),
                    ).classes('text-xs').style('min-width: 120px')

                ui.button('🔄 Refresh', on_click=self._refresh_messages).props('flat no-caps').classes('text-xs')

            ui.separator()

            # ── Message list ──────────────────────────────────────────
            self._msg_list_container = ui.column().classes(
                'w-full gap-1 h-72 overflow-y-auto bg-gray-50 rounded p-2'
            )

            ui.separator()

            # ── Post form ─────────────────────────────────────────────
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.label('Post:').classes('text-sm text-gray-600')

                # Post region select (hidden when channel has no regions)
                self._post_region_row = ui.row().classes('items-center gap-1')
                with self._post_region_row:
                    self._post_region_select = ui.select(
                        options=[],
                        label='Region',
                    ).classes('text-xs').style('min-width: 110px')

                # Post category select
                self._post_category_select = ui.select(
                    options=[],
                    label='Category',
                ).classes('text-xs').style('min-width: 110px')

                self._text_input = ui.input(
                    placeholder='Message text…',
                ).classes('flex-grow text-sm')

                ui.button('Send', on_click=self._on_post).props('no-caps').classes('text-xs')

        # Initial render for the default channel
        self._select_channel(self._active_channel_idx)

    # ------------------------------------------------------------------
    # Channel selection
    # ------------------------------------------------------------------

    def _select_channel(self, channel_idx: int) -> None:
        """Switch the active channel and rebuild filter options.

        Args:
            channel_idx: MeshCore channel index to activate.
        """
        self._active_channel_idx = channel_idx
        self._active_region = None
        self._active_category = None

        cfg = self._channels_by_idx.get(channel_idx, {})
        regions: List[str] = cfg.get("regions", [])
        categories: List[str] = cfg.get("categories", [])

        # Region filter visibility
        has_regions = bool(regions)
        if self._region_row:
            self._region_row.set_visibility(has_regions)
        if self._post_region_row:
            self._post_region_row.set_visibility(has_regions)

        # Populate region selects
        region_opts = ["(all)"] + regions
        if self._region_select:
            self._region_select.options = region_opts
            self._region_select.value = "(all)"
        if self._post_region_select:
            self._post_region_select.options = regions
            self._post_region_select.value = regions[0] if regions else None

        # Populate category selects
        cat_opts = ["(all)"] + categories
        if self._category_select:
            self._category_select.options = cat_opts
            self._category_select.value = "(all)"
        if self._post_category_select:
            self._post_category_select.options = categories
            self._post_category_select.value = categories[0] if categories else None

        self._refresh_messages()

    # ------------------------------------------------------------------
    # Filter callbacks
    # ------------------------------------------------------------------

    def _on_region_filter(self, value: Optional[str]) -> None:
        """Handle region filter change.

        Args:
            value: Selected region string, or ``'(all)'``.
        """
        self._active_region = None if (not value or value == "(all)") else value
        self._refresh_messages()

    def _on_category_filter(self, value: Optional[str]) -> None:
        """Handle category filter change.

        Args:
            value: Selected category string, or ``'(all)'``.
        """
        self._active_category = None if (not value or value == "(all)") else value
        self._refresh_messages()

    # ------------------------------------------------------------------
    # Message list refresh
    # ------------------------------------------------------------------

    def _refresh_messages(self) -> None:
        """Query the BBS service and rebuild the message list UI."""
        if not self._msg_list_container:
            return

        messages = self._service.get_all_messages(
            channel=self._active_channel_idx,
            region=self._active_region,
            category=self._active_category,
        )

        self._msg_list_container.clear()
        with self._msg_list_container:
            if not messages:
                ui.label('No messages.').classes('text-xs text-gray-400 italic')
            for msg in messages:
                self._render_message_row(msg)

    def _render_message_row(self, msg: BbsMessage) -> None:
        """Render a single message row in the message list.

        Args:
            msg: ``BbsMessage`` to display.
        """
        ts = msg.timestamp[:16].replace("T", " ")
        region_label = f" [{msg.region}]" if msg.region else ""
        header = f"{ts}  {msg.sender}  [{msg.category}]{region_label}"

        with ui.column().classes('w-full gap-0 py-1 border-b border-gray-200'):
            ui.label(header).classes('text-xs text-gray-500')
            ui.label(msg.text).classes('text-sm')

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------

    def _on_post(self) -> None:
        """Handle the Send button: validate inputs and post a BBS message."""
        cfg = self._channels_by_idx.get(self._active_channel_idx, {})
        regions: List[str] = cfg.get("regions", [])
        categories: List[str] = cfg.get("categories", [])

        text = (self._text_input.value or "").strip() if self._text_input else ""
        if not text:
            ui.notify("Message text cannot be empty.", type="warning")
            return

        category = (
            self._post_category_select.value
            if self._post_category_select
            else (categories[0] if categories else "")
        )
        if not category:
            ui.notify("Please select a category.", type="warning")
            return

        region = ""
        if regions and self._post_region_select:
            region = self._post_region_select.value or ""

        # Build and persist the message (GUI post — sender is the local device)
        msg = BbsMessage(
            channel=self._active_channel_idx,
            region=region,
            category=category,
            sender="Me",
            sender_key="",
            text=text,
        )
        self._service.post_message(msg)

        # Optionally also broadcast via the mesh (put_command enqueues for worker)
        region_part = f"{region} " if region else ""
        mesh_text = f"!bbs post {region_part}{category} {text}"
        self._put_command({
            "action": "send_message",
            "channel": self._active_channel_idx,
            "text": mesh_text,
        })

        debug_print(f"BBS panel: posted to ch={self._active_channel_idx} {mesh_text[:60]}")

        if self._text_input:
            self._text_input.value = ""
        self._refresh_messages()
        ui.notify("Message posted.", type="positive")

    # ------------------------------------------------------------------
    # External update hook (called from dashboard timer)
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Called by the dashboard timer.  Refreshes if new data arrived.

        Currently a lightweight no-op: the BBS panel refreshes on user
        interaction.  Override for real-time auto-refresh if desired.

        Args:
            data: SharedData snapshot (unused; kept for interface consistency).
        """
        # No-op: BBS data is local SQLite, not pushed via SharedData.
        # Active refresh only happens on user action or channel switch.
