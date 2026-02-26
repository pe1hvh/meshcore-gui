"""
Statistics panel — observer uptime and aggregate counters.

Displays observer process uptime, total messages and RX log entries
seen, number of active sources, and per-source breakdown.
"""

import time
from typing import Dict, Optional

from nicegui import ui

from meshcore_observer.archive_watcher import ArchiveWatcher


class StatsPanel:
    """Observer statistics panel.

    Args:
        watcher: ArchiveWatcher instance for aggregate stats.
    """

    def __init__(self, watcher: ArchiveWatcher) -> None:
        self._watcher = watcher
        self._start_time = time.monotonic()

        # UI element references
        self._uptime_label: Optional[ui.label] = None
        self._total_msg_label: Optional[ui.label] = None
        self._total_rxlog_label: Optional[ui.label] = None
        self._sources_label: Optional[ui.label] = None
        self._breakdown_container: Optional[ui.column] = None

    def render(self) -> None:
        """Build the statistics panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("analytics", color="primary").classes("text-lg")
                ui.label("Observer Statistics").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("Uptime:").classes("text-xs opacity-60 w-32")
                    self._uptime_label = ui.label("0s").classes("text-xs font-bold")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Total messages:").classes("text-xs opacity-60 w-32")
                    self._total_msg_label = ui.label("0").classes("text-xs font-bold")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Total RX log:").classes("text-xs opacity-60 w-32")
                    self._total_rxlog_label = ui.label("0").classes("text-xs font-bold")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Active sources:").classes("text-xs opacity-60 w-32")
                    self._sources_label = ui.label("0").classes("text-xs font-bold")

            ui.separator().classes("my-2")

            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon("list", color="primary").classes("text-sm")
                ui.label("Per Source").classes("text-xs font-bold")

            self._breakdown_container = ui.column().classes("gap-0 w-full")

    def update(self) -> None:
        """Refresh all statistics labels."""
        stats = self._watcher.get_stats()

        # Uptime
        if self._uptime_label:
            elapsed = int(time.monotonic() - self._start_time)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self._uptime_label.set_text(
                f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
            )

        if self._total_msg_label:
            self._total_msg_label.set_text(str(stats["total_messages_seen"]))
        if self._total_rxlog_label:
            self._total_rxlog_label.set_text(str(stats["total_rxlog_seen"]))
        if self._sources_label:
            self._sources_label.set_text(str(stats["active_sources"]))

        # Per-source breakdown
        if self._breakdown_container:
            sources = self._watcher.get_sources()
            self._breakdown_container.clear()
            with self._breakdown_container:
                if not sources:
                    ui.label("No sources detected yet.").classes(
                        "text-xs opacity-40 py-1"
                    )
                else:
                    for src in sources:
                        addr = src["address"]
                        msg_c = src["message_count"]
                        rxlog_c = src["rxlog_count"]
                        with ui.row().classes("items-center gap-2 py-0.5"):
                            ui.label(addr).classes("text-xs opacity-70 w-48 truncate")
                            ui.label(f"{msg_c} msg").classes("text-xs w-16")
                            ui.label(f"{rxlog_c} rx").classes("text-xs w-16")
