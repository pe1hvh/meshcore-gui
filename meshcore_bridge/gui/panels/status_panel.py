"""
Status panel — connection status for both bridge devices.

Shows connectivity state, device info, radio frequency and
bridge engine statistics in a layout consistent with the DOMCA
theme used by meshcore_gui.
"""

from typing import Dict, Optional

from nicegui import ui

from meshcore_gui.core.shared_data import SharedData
from meshcore_bridge.bridge_engine import BridgeEngine
from meshcore_bridge.config import BridgeConfig


class StatusPanel:
    """Connection status panel for the bridge dashboard.

    Displays two device status cards (A and B) and a bridge
    statistics summary card.
    """

    def __init__(
        self,
        shared_a: SharedData,
        shared_b: SharedData,
        engine: BridgeEngine,
        config: BridgeConfig,
    ) -> None:
        self._a = shared_a
        self._b = shared_b
        self._engine = engine
        self._cfg = config

        # UI element references (populated by render)
        self._status_a: Optional[ui.label] = None
        self._status_b: Optional[ui.label] = None
        self._device_a_name: Optional[ui.label] = None
        self._device_b_name: Optional[ui.label] = None
        self._freq_a: Optional[ui.label] = None
        self._freq_b: Optional[ui.label] = None
        self._connected_a: Optional[ui.icon] = None
        self._connected_b: Optional[ui.icon] = None

        # Stats labels
        self._fwd_count: Optional[ui.label] = None
        self._fwd_a_to_b: Optional[ui.label] = None
        self._fwd_b_to_a: Optional[ui.label] = None
        self._dupes_blocked: Optional[ui.label] = None
        self._last_fwd: Optional[ui.label] = None
        self._uptime: Optional[ui.label] = None

    def render(self) -> None:
        """Build the status panel UI."""
        with ui.row().classes("w-full gap-4 flex-wrap"):
            self._render_device_card("A", self._cfg.device_a)
            self._render_device_card("B", self._cfg.device_b)
            self._render_stats_card()

    def _render_device_card(self, side: str, dev_cfg) -> None:
        """Render a single device status card."""
        with ui.card().classes("flex-1 min-w-[280px]"):
            with ui.row().classes("items-center gap-2 mb-2"):
                icon = ui.icon("link", color="green").classes("text-lg")
                ui.label(f"Device {side}").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")
                ui.label(f"({dev_cfg.label})").classes(
                    "text-xs opacity-60"
                ).style("font-family: 'JetBrains Mono', monospace")

            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("Port:").classes("text-xs opacity-60 w-20")
                    ui.label(dev_cfg.port).classes("text-xs").style(
                        "font-family: 'JetBrains Mono', monospace"
                    )

                with ui.row().classes("items-center gap-2"):
                    ui.label("Status:").classes("text-xs opacity-60 w-20")
                    status_lbl = ui.label("Connecting...").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Device:").classes("text-xs opacity-60 w-20")
                    name_lbl = ui.label("-").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Frequency:").classes("text-xs opacity-60 w-20")
                    freq_lbl = ui.label("-").classes("text-xs")

            # Store references for updates
            if side == "A":
                self._status_a = status_lbl
                self._device_a_name = name_lbl
                self._freq_a = freq_lbl
                self._connected_a = icon
            else:
                self._status_b = status_lbl
                self._device_b_name = name_lbl
                self._freq_b = freq_lbl
                self._connected_b = icon

    def _render_stats_card(self) -> None:
        """Render the bridge statistics card."""
        with ui.card().classes("flex-1 min-w-[280px]"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("swap_horiz", color="primary").classes("text-lg")
                ui.label("Bridge Statistics").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("Total forwarded:").classes("text-xs opacity-60 w-32")
                    self._fwd_count = ui.label("0").classes("text-xs font-bold")

                with ui.row().classes("items-center gap-2"):
                    ui.label("A → B:").classes("text-xs opacity-60 w-32")
                    self._fwd_a_to_b = ui.label("0").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("B → A:").classes("text-xs opacity-60 w-32")
                    self._fwd_b_to_a = ui.label("0").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Dupes blocked:").classes("text-xs opacity-60 w-32")
                    self._dupes_blocked = ui.label("0").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Last forward:").classes("text-xs opacity-60 w-32")
                    self._last_fwd = ui.label("-").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Uptime:").classes("text-xs opacity-60 w-32")
                    self._uptime = ui.label("0s").classes("text-xs")

    def update(self) -> None:
        """Refresh all status labels from current SharedData state."""
        self._update_device("A", self._a)
        self._update_device("B", self._b)
        self._update_stats()

    def _update_device(self, side: str, shared: SharedData) -> None:
        """Update device status labels for one side."""
        snap = shared.get_snapshot()

        if side == "A":
            status_lbl = self._status_a
            name_lbl = self._device_a_name
            freq_lbl = self._freq_a
            icon = self._connected_a
        else:
            status_lbl = self._status_b
            name_lbl = self._device_b_name
            freq_lbl = self._freq_b
            icon = self._connected_b

        if status_lbl:
            status_lbl.set_text(snap.get("status", "Unknown"))
        if name_lbl:
            name_lbl.set_text(snap.get("name", "-") or "-")
        if freq_lbl:
            freq = snap.get("radio_freq", 0)
            freq_lbl.set_text(f"{freq:.3f} MHz" if freq else "-")
        if icon:
            connected = snap.get("connected", False)
            icon.props(f'name={"link" if connected else "link_off"}')
            icon._props["color"] = "green" if connected else "red"
            icon.update()

    def _update_stats(self) -> None:
        """Update bridge statistics labels."""
        s = self._engine.stats
        total = self._engine.get_total_forwarded()

        if self._fwd_count:
            self._fwd_count.set_text(str(total))
        if self._fwd_a_to_b:
            self._fwd_a_to_b.set_text(str(s["forwarded_a_to_b"]))
        if self._fwd_b_to_a:
            self._fwd_b_to_a.set_text(str(s["forwarded_b_to_a"]))
        if self._dupes_blocked:
            self._dupes_blocked.set_text(str(s["duplicates_blocked"]))
        if self._last_fwd:
            self._last_fwd.set_text(s["last_forward_time"] or "-")
        if self._uptime:
            secs = s["uptime_seconds"]
            h, rem = divmod(secs, 3600)
            m, sec = divmod(rem, 60)
            self._uptime.set_text(f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s")
