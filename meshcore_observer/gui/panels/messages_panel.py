"""
Messages panel — aggregated message feed from all archive sources.

Displays messages sorted by ``timestamp_utc`` (newest first),
with optional source and channel filtering.
"""

from typing import Dict, List, Optional, Tuple

from nicegui import ui


class MessagesPanel:
    """Aggregated message feed panel.

    Maintains an in-memory buffer of messages from all sources,
    sorted by UTC timestamp.

    Args:
        max_display: Maximum number of messages to display.
    """

    def __init__(self, max_display: int = 100) -> None:
        self._max_display = max_display
        self._messages: List[dict] = []
        self._table: Optional[ui.table] = None

        # Filters
        self._source_filter: str = ""
        self._channel_filter: str = ""
        self._source_select: Optional[ui.select] = None
        self._channel_select: Optional[ui.select] = None

    def render(self) -> None:
        """Build the messages panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("chat", color="primary").classes("text-lg")
                ui.label("Messages").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

                ui.space()

                # Source filter (REQ-10)
                self._source_select = ui.select(
                    options={"": "All sources"},
                    value="",
                    on_change=lambda e: self._on_source_filter(e.value),
                ).props("dense outlined").classes("text-xs min-w-[140px]")

                # Channel filter (REQ-11)
                self._channel_select = ui.select(
                    options={"": "All channels"},
                    value="",
                    on_change=lambda e: self._on_channel_filter(e.value),
                ).props("dense outlined").classes("text-xs min-w-[140px]")

            self._table = ui.table(
                columns=[
                    {"name": "time", "label": "Time", "field": "time",
                     "align": "left", "sortable": True},
                    {"name": "source", "label": "Source", "field": "source",
                     "align": "left"},
                    {"name": "channel", "label": "Channel", "field": "channel",
                     "align": "left"},
                    {"name": "sender", "label": "Sender", "field": "sender",
                     "align": "left"},
                    {"name": "text", "label": "Text", "field": "text",
                     "align": "left",
                     "classes": "msg-text-cell",
                     "headerClasses": "msg-text-header"},
                    {"name": "snr", "label": "SNR", "field": "snr",
                     "align": "right"},
                    {"name": "hops", "label": "Hops", "field": "hops",
                     "align": "right"},
                ],
                rows=[],
            ).props("dense flat").classes("w-full text-xs")

            ui.add_css("""
                .msg-text-cell {
                    max-width: 300px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .msg-text-header { max-width: 300px; }
            """)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def add_messages(self, new_messages: List[Tuple[str, dict]]) -> None:
        """Add new messages from a poll result.

        Args:
            new_messages: List of (source_address, message_dict) tuples.
        """
        for _source, msg in new_messages:
            self._messages.append(msg)

        # Sort by timestamp (newest first) and trim
        self._messages.sort(
            key=lambda m: m.get("timestamp_utc", ""),
            reverse=True,
        )
        self._messages = self._messages[:self._max_display * 2]

    # ------------------------------------------------------------------
    # Update UI
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Refresh the messages table with current filter state."""
        if not self._table:
            return

        # Update filter dropdowns with discovered values
        self._update_filter_options()

        # Apply filters
        filtered = self._messages
        if self._source_filter:
            filtered = [m for m in filtered if m.get("_source") == self._source_filter]
        if self._channel_filter:
            filtered = [m for m in filtered if m.get("channel_name") == self._channel_filter]

        display = filtered[:self._max_display]

        rows = [
            {
                "time": m.get("time", m.get("timestamp_utc", "")[:19]),
                "source": self._short_source(m.get("_source", "")),
                "channel": m.get("channel_name", m.get("channel", "-")),
                "sender": m.get("sender", ""),
                "text": m.get("text", ""),
                "snr": f"{m['snr']:.1f}" if m.get("snr") is not None else "-",
                "hops": str(m.get("path_len", 0)),
            }
            for m in display
        ]
        self._table.rows = rows
        self._table.update()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_source_filter(self, value: str) -> None:
        """Handle source filter change."""
        self._source_filter = value
        self.update()

    def _on_channel_filter(self, value: str) -> None:
        """Handle channel filter change."""
        self._channel_filter = value
        self.update()

    def _update_filter_options(self) -> None:
        """Update dropdown options from current message data."""
        if self._source_select:
            sources = sorted({m.get("_source", "") for m in self._messages if m.get("_source")})
            options = {"": "All sources"}
            options.update({s: self._short_source(s) for s in sources})
            self._source_select.options = options
            self._source_select.update()

        if self._channel_select:
            channels = sorted({m.get("channel_name", "") for m in self._messages if m.get("channel_name")})
            options = {"": "All channels"}
            options.update({c: c for c in channels})
            self._channel_select.options = options
            self._channel_select.update()

    @staticmethod
    def _short_source(address: str) -> str:
        """Shorten a source address for display."""
        if not address:
            return "-"
        # Remove common prefixes for readability
        short = address
        for prefix in ("bridge_a_", "bridge_b_", "_dev_"):
            if short.startswith(prefix):
                short = short[len(prefix):]
        return short[:20] if len(short) > 20 else short
