"""
RX log panel — aggregated RX log entries from all archive sources.

Displays entries sorted by ``timestamp_utc`` (newest first),
with source tagging.  Filters follow the source filter from the
messages panel.
"""

from typing import Dict, List, Optional, Tuple

from nicegui import ui


class RxLogPanel:
    """Aggregated RX log table panel.

    Args:
        max_display: Maximum number of entries to display.
    """

    def __init__(self, max_display: int = 50) -> None:
        self._max_display = max_display
        self._entries: List[dict] = []
        self._table: Optional[ui.table] = None
        self._source_filter: str = ""

    def render(self) -> None:
        """Build the RX log panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("radio", color="primary").classes("text-lg")
                ui.label("RX Log").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

            self._table = ui.table(
                columns=[
                    {"name": "time", "label": "Time", "field": "time",
                     "align": "left"},
                    {"name": "source", "label": "Source", "field": "source",
                     "align": "left"},
                    {"name": "snr", "label": "SNR", "field": "snr",
                     "align": "right"},
                    {"name": "rssi", "label": "RSSI", "field": "rssi",
                     "align": "right"},
                    {"name": "type", "label": "Type", "field": "type",
                     "align": "left"},
                    {"name": "hops", "label": "Hops", "field": "hops",
                     "align": "right"},
                    {"name": "path", "label": "Path", "field": "path",
                     "align": "left",
                     "classes": "rxlog-path-cell",
                     "headerClasses": "rxlog-path-header"},
                    {"name": "hash", "label": "Hash", "field": "hash",
                     "align": "left"},
                ],
                rows=[],
            ).props("dense flat").classes("w-full text-xs")

            ui.add_css("""
                .rxlog-path-cell {
                    max-width: 180px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .rxlog-path-header { max-width: 180px; }
            """)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def add_entries(self, new_entries: List[Tuple[str, dict]]) -> None:
        """Add new RX log entries from a poll result.

        Args:
            new_entries: List of (source_address, entry_dict) tuples.
        """
        for _source, entry in new_entries:
            self._entries.append(entry)

        # Sort by timestamp (newest first) and trim
        self._entries.sort(
            key=lambda e: e.get("timestamp_utc", ""),
            reverse=True,
        )
        self._entries = self._entries[:self._max_display * 2]

    # ------------------------------------------------------------------
    # Filter (shared with messages panel)
    # ------------------------------------------------------------------

    def set_source_filter(self, source: str) -> None:
        """Apply a source filter (called by dashboard orchestrator)."""
        self._source_filter = source

    # ------------------------------------------------------------------
    # Update UI
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Refresh the RX log table."""
        if not self._table:
            return

        filtered = self._entries
        if self._source_filter:
            filtered = [e for e in filtered if e.get("_source") == self._source_filter]

        display = filtered[:self._max_display]

        rows = [
            {
                "time": e.get("time", e.get("timestamp_utc", "")[:19]),
                "source": self._short_source(e.get("_source", "")),
                "snr": f"{e['snr']:.1f}" if isinstance(e.get("snr"), (int, float)) else "-",
                "rssi": f"{e['rssi']:.0f}" if isinstance(e.get("rssi"), (int, float)) else "-",
                "type": e.get("payload_type", "?"),
                "hops": str(e.get("hops", 0)),
                "path": self._build_path(e),
                "hash": (e.get("message_hash") or "")[:12],
            }
            for e in display
        ]
        self._table.rows = rows
        self._table.update()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_path(entry: dict) -> str:
        """Build a display path: Sender → [repeaters →] Receiver."""
        parts: list = []
        if entry.get("sender"):
            parts.append(entry["sender"])
        path_names = entry.get("path_names", [])
        if path_names:
            parts.extend(path_names)
        if entry.get("receiver"):
            parts.append(entry["receiver"])
        return " → ".join(parts) if parts else "-"

    @staticmethod
    def _short_source(address: str) -> str:
        """Shorten a source address for display."""
        if not address:
            return "-"
        short = address
        for prefix in ("bridge_a_", "bridge_b_", "_dev_"):
            if short.startswith(prefix):
                short = short[len(prefix):]
        return short[:20] if len(short) > 20 else short
