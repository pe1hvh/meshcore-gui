"""
Archive viewer page for MeshCore GUI.

Displays archived messages with filters and pagination.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from nicegui import ui

from meshcore_gui.core.models import Message
from meshcore_gui.core.protocols import SharedDataReadAndLookup


class ArchivePage:
    """Archive viewer page with filters and pagination.
    
    Shows archived messages in the same style as the main messages panel,
    with filters (date range, text search) and pagination.
    Channel filtering is driven by the drawer submenu via
    :meth:`set_channel_filter`.
    """
    
    def __init__(self, shared: SharedDataReadAndLookup, page_size: int = 50):
        """Initialize archive page.
        
        Args:
            shared: SharedData reader with contact lookup.
            page_size: Number of messages per page.
        """
        self._shared = shared
        self._page_size = page_size
        
        # Current page state
        self._current_page = 0
        self._channel_name_filter = None
        self._text_filter = ""
        self._days_back = 7  # Default: last 7 days

        # UI references for inline refresh
        self._channel_label = None
        self._filter_card = None
        self._msg_outer = None
        self._text_input = None
        self._days_select = None

    # -- Channel filter (set by dashboard submenu) ---------------------

    def set_channel_filter(self, channel) -> None:
        """Set the channel filter from the drawer submenu.

        Args:
            channel: None for all messages, 'DM' for DM only,
                     or str for a specific channel name.
        """
        self._channel_name_filter = channel
        self._current_page = 0

        # Update channel label
        if self._channel_label:
            if channel is None:
                self._channel_label.text = '\U0001f4da Archive — All'
            elif channel == 'DM':
                self._channel_label.text = '\U0001f4da Archive — DM'
            else:
                self._channel_label.text = f'\U0001f4da Archive — {channel}'

        # Inline refresh
        self._refresh_messages()

    # -- Render --------------------------------------------------------
        
    def render(self):
        """Render the archive page."""
        with ui.column().classes('w-full p-4 gap-4').style(
            'height: calc(100vh - 5rem); overflow: hidden'
        ):
            # Header row: channel label (left) + filter icon (right)
            with ui.row().classes('w-full items-center justify-between'):
                self._channel_label = ui.label(
                    '\U0001f4da Archive — All'
                ).classes('text-2xl font-bold')

                ui.button(
                    icon='filter_list',
                    on_click=lambda: self._filter_card.set_visibility(
                        not self._filter_card.visible
                    ),
                ).props('flat round dense').tooltip('Toggle filters')

            # Filters (days + text search — channel is driven by submenu)
            self._render_filters()
            
            # Messages container (refreshed inline)
            self._msg_outer = ui.column().classes(
                'w-full gap-2 flex-grow'
            ).style('overflow: hidden; min-height: 0')
            self._refresh_messages()
    
    def _render_filters(self):
        """Render filter controls (days + text search only)."""
        self._filter_card = ui.card().classes('w-full')
        self._filter_card.set_visibility(False)
        with self._filter_card:
            ui.label('Filters').classes('text-lg font-bold mb-2')
            
            with ui.row().classes('w-full gap-4 items-end'):
                # Days back filter
                with ui.column().classes('flex-none'):
                    ui.label('Time Range').classes('text-sm')
                    self._days_select = ui.select(
                        options={
                            1: 'Last 24 hours',
                            7: 'Last 7 days',
                            30: 'Last 30 days',
                            90: 'Last 90 days',
                            9999: 'All time',
                        },
                        value=self._days_back,
                    ).classes('w-48')
                    
                    def on_days_change(e):
                        self._days_back = e.value
                        self._current_page = 0
                        self._refresh_messages()
                    
                    self._days_select.on('update:model-value', on_days_change)
                
                # Text search
                with ui.column().classes('flex-1'):
                    ui.label('Search Text').classes('text-sm')
                    self._text_input = ui.input(
                        placeholder='Search in messages...',
                        value=self._text_filter,
                    ).classes('w-full')
                    
                    def on_text_change(e):
                        self._text_filter = e.value
                        self._current_page = 0
                    
                    self._text_input.on('change', on_text_change)
                
                # Search button (inline refresh — no page reload)
                ui.button(
                    'Search', on_click=lambda: self._refresh_messages()
                ).props('flat color=primary')
                
                # Clear filters
                def clear_filters():
                    self._channel_name_filter = None
                    self._text_filter = ""
                    self._days_back = 7
                    self._current_page = 0
                    # Reset UI elements
                    if self._text_input:
                        self._text_input.value = ''
                    if self._days_select:
                        self._days_select.value = 7
                    if self._channel_label:
                        self._channel_label.text = '\U0001f4da Archive — All'
                    self._refresh_messages()
                
                ui.button('Clear', on_click=clear_filters).props('flat')

    def _refresh_messages(self):
        """Rebuild message list inline (no page reload)."""
        if not self._msg_outer:
            return

        self._msg_outer.clear()

        snapshot = self._shared.get_snapshot()

        with self._msg_outer:
            self._render_messages(snapshot)

    def _render_messages(self, snapshot: dict):
        """Render messages with pagination.
        
        Args:
            snapshot: Current snapshot containing archive data.
        """
        if not snapshot.get('archive'):
            ui.label('Archive not available').classes('text-gray-500 italic')
            return
        
        archive = snapshot['archive']
        
        # Calculate date range
        now = datetime.now(timezone.utc)
        after = None if self._days_back >= 9999 else now - timedelta(days=self._days_back)
        
        # Handle DM filter separately (query_messages doesn't filter by channel=None)
        is_dm_filter = (self._channel_name_filter == 'DM')
        query_channel = None if is_dm_filter else self._channel_name_filter
        
        # Query messages
        messages, total_count = archive.query_messages(
            after=after,
            channel_name=query_channel,
            text_search=self._text_filter if self._text_filter else None,
            limit=self._page_size if not is_dm_filter else self._page_size * 5,
            offset=self._current_page * self._page_size if not is_dm_filter else 0,
        )
        
        # Post-filter for DM (channel is None)
        if is_dm_filter:
            messages = [m for m in messages if m.get('channel') is None]
            total_count = len(messages)
            # Apply pagination manually
            start = self._current_page * self._page_size
            messages = messages[start:start + self._page_size]
        
        # Pagination info
        total_pages = (total_count + self._page_size - 1) // self._page_size
        
        # Pagination header
        with ui.row().classes('w-full items-center justify-between'):
            ui.label(f'Showing {len(messages)} of {total_count} messages').classes('text-sm text-gray-600')
            
            if total_pages > 1:
                with ui.row().classes('gap-2'):
                    # Previous button
                    def go_prev():
                        if self._current_page > 0:
                            self._current_page -= 1
                            self._refresh_messages()
                    
                    ui.button('Previous', on_click=go_prev).props(
                        f'flat {"disabled" if self._current_page == 0 else ""}'
                    )
                    
                    # Page indicator
                    ui.label(f'Page {self._current_page + 1} / {total_pages}').classes('mx-2')
                    
                    # Next button
                    def go_next():
                        if self._current_page < total_pages - 1:
                            self._current_page += 1
                            self._refresh_messages()
                    
                    ui.button('Next', on_click=go_next).props(
                        f'flat {"disabled" if self._current_page >= total_pages - 1 else ""}'
                    )
        
        # Messages list (single-line format, same as main page)
        if not messages:
            ui.label('No messages found').classes('text-gray-500 italic mt-4')
        else:
            with ui.column().classes(
                    'w-full flex-grow overflow-y-auto gap-0 text-sm font-mono '
                    'bg-gray-50 p-2 rounded'
                ):
                    # Hide channel tag when viewing a specific channel/DM
                    hide_ch = self._channel_name_filter is not None

                    for msg_dict in messages:
                        msg = Message.from_dict(msg_dict)
                        line = msg.format_line(show_channel=not hide_ch)
                        msg_hash = msg_dict.get('message_hash', '')
                        
                        ui.label(line).classes(
                            'text-xs leading-tight cursor-pointer '
                            'hover:bg-blue-50 rounded px-1'
                        ).on('click', lambda e, h=msg_hash: self._open_route(h))
        
        # Pagination footer
        if total_pages > 1:
            with ui.row().classes('w-full items-center justify-center mt-4'):
                ui.button('Previous', on_click=go_prev).props(
                    f'flat {"disabled" if self._current_page == 0 else ""}'
                )
                ui.label(f'Page {self._current_page + 1} / {total_pages}').classes('mx-4')
                ui.button('Next', on_click=go_next).props(
                    f'flat {"disabled" if self._current_page >= total_pages - 1 else ""}'
                )
    
    @staticmethod
    def setup_route(shared: SharedDataReadAndLookup):
        """Setup the /archive route.
        
        Args:
            shared: SharedData reader with contact lookup.
        """
        @ui.page('/archive')
        def archive_page():
            page = ArchivePage(shared)
            page.render()

    @staticmethod
    def _open_route(msg_hash: str) -> None:
        if msg_hash:
            ui.navigate.to(f'/route/{msg_hash}')
        else:
            ui.notify('Route data not available for this message', type='warning')
