"""
Sources panel — table of discovered archive file sources.

Shows all ``*_messages.json`` files found in the archive directory
with per-source metadata: address, file path, entry counts.
"""

from typing import Dict, List, Optional

from nicegui import ui

from meshcore_observer.archive_watcher import ArchiveWatcher


class SourcesPanel:
    """Archive sources overview panel.

    Args:
        watcher: ArchiveWatcher instance for source metadata.
    """

    def __init__(self, watcher: ArchiveWatcher) -> None:
        self._watcher = watcher
        self._table: Optional[ui.table] = None

    def render(self) -> None:
        """Build the sources panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("storage", color="primary").classes("text-lg")
                ui.label("Archive Sources").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

            self._table = ui.table(
                columns=[
                    {"name": "address", "label": "Source", "field": "address",
                     "align": "left"},
                    {"name": "messages", "label": "Messages", "field": "messages",
                     "align": "right"},
                    {"name": "rxlog", "label": "RX Log", "field": "rxlog",
                     "align": "right"},
                    {"name": "path", "label": "File", "field": "path",
                     "align": "left"},
                ],
                rows=[],
            ).props("dense flat").classes("w-full text-xs")

    def update(self) -> None:
        """Refresh sources table from watcher state."""
        if not self._table:
            return

        sources = self._watcher.get_sources()
        rows = [
            {
                "address": s["address"],
                "messages": str(s["message_count"]),
                "rxlog": str(s["rxlog_count"]),
                "path": s["path"].split("/")[-1] if "/" in s["path"] else s["path"],
            }
            for s in sources
        ]
        self._table.rows = rows
        self._table.update()
