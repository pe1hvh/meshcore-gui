"""
Log panel — forwarded message log for bridge troubleshooting.

Displays the last N forwarded messages with direction indicator,
sender, timestamp and message text.  Layout follows the DOMCA
theme and message panel style used by meshcore_gui.
"""

from typing import Optional

from nicegui import ui

from meshcore_bridge.bridge_engine import BridgeEngine


class LogPanel:
    """Forwarded message log panel for the bridge dashboard.

    Shows a scrollable list of forwarded messages, newest first,
    with direction indicators (A→B / B→A).
    """

    def __init__(self, engine: BridgeEngine) -> None:
        self._engine = engine
        self._log_container: Optional[ui.column] = None
        self._last_count: int = 0

    def render(self) -> None:
        """Build the log panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("history", color="primary").classes("text-lg")
                ui.label("Forwarded Messages").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

            self._log_container = ui.column().classes(
                "w-full gap-0 max-h-96 overflow-y-auto"
            ).style(
                "font-family: 'JetBrains Mono', monospace; font-size: 0.75rem"
            )

            with self._log_container:
                ui.label("Waiting for messages...").classes(
                    "text-xs opacity-40 py-2"
                )

    def update(self) -> None:
        """Refresh the log if new entries are available."""
        log_entries = self._engine.get_log()
        current_count = len(log_entries)

        if current_count == self._last_count:
            return

        self._last_count = current_count

        if not self._log_container:
            return

        self._log_container.clear()
        with self._log_container:
            if not log_entries:
                ui.label("Waiting for messages...").classes(
                    "text-xs opacity-40 py-2"
                )
                return

            for entry in log_entries[:200]:
                direction_color = (
                    "text-blue-400" if "A→B" in entry.direction
                    else "text-green-400"
                )
                with ui.row().classes("w-full items-baseline gap-1 py-0.5"):
                    ui.label(entry.time).classes("text-xs opacity-50 shrink-0")
                    ui.label(entry.direction).classes(
                        f"text-xs font-bold shrink-0 {direction_color}"
                    )
                    ui.label(f"{entry.sender}:").classes(
                        "text-xs font-bold shrink-0"
                    )
                    ui.label(entry.text).classes(
                        "text-xs opacity-80 truncate"
                    )
