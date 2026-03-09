"""
Bridge status dashboard — NiceGUI page with DOMCA theme.

Thin orchestrator that owns the layout, injects the DOMCA theme,
and runs a periodic update timer that refreshes all panels.
Visually consistent with the meshcore_gui dashboard.
"""

from nicegui import ui

from meshcore_gui.core.shared_data import SharedData
from meshcore_gui import config as gui_config

from meshcore_bridge.bridge_engine import BridgeEngine
from meshcore_bridge.config import BridgeConfig
from meshcore_bridge.gui.panels.status_panel import StatusPanel
from meshcore_bridge.gui.panels.log_panel import LogPanel


# ── DOMCA Theme (identical to meshcore_gui/gui/dashboard.py) ─────────
# Subset of the DOMCA theme CSS needed for the bridge dashboard.

_DOMCA_HEAD = '''
<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
/* ── DOMCA theme variables (dark) ── */
body.body--dark {
  --bg: #0A1628;
  --title: #48CAE4;  --subtitle: #48CAE4;
}
/* ── DOMCA theme variables (light) ── */
body.body--light {
  --bg: #FFFFFF;
  --title: #0077B6;  --subtitle: #0077B6;
}

/* ── DOMCA page background ── */
body.body--dark  { background: #0A1628 !important; }
body.body--light { background: #f4f8fb !important; }
body.body--dark .q-page  { background: #0A1628 !important; }
body.body--light .q-page { background: #f4f8fb !important; }

/* ── DOMCA header ── */
body.body--dark .q-header  { background: #0d1f35 !important; }
body.body--light .q-header { background: #0077B6 !important; }

/* ── DOMCA cards — dark mode readable ── */
body.body--dark .q-card {
  background: #112240 !important;
  color: #e0f0f8 !important;
  border: 1px solid rgba(0,119,182,0.15) !important;
}
body.body--dark .q-card .text-gray-600 { color: #48CAE4 !important; }
body.body--dark .q-card .text-xs       { color: #c0dce8 !important; }
body.body--dark .q-card .text-sm       { color: #d0e8f2 !important; }

/* ── Dark mode: fields ── */
body.body--dark .q-field__control { background: #0c1a2e !important; color: #e0f0f8 !important; }
body.body--dark .q-field__native  { color: #e0f0f8 !important; }

/* ── Bridge-specific ── */
.bridge-header-text {
  font-family: 'JetBrains Mono', monospace;
  color: white;
}
</style>
'''


class BridgeDashboard:
    """Bridge status dashboard page.

    Provides a NiceGUI-based status view showing both device
    connections, bridge statistics and the forwarded message log.
    """

    def __init__(
        self,
        shared_a: SharedData,
        shared_b: SharedData,
        engine: BridgeEngine,
        config: BridgeConfig,
    ) -> None:
        self._shared_a = shared_a
        self._shared_b = shared_b
        self._engine = engine
        self._cfg = config

        # Panels (created in render)
        self._status: StatusPanel | None = None
        self._log: LogPanel | None = None

        # Header status label
        self._header_status = None

    def render(self) -> None:
        """Build the complete bridge dashboard layout and start the timer."""

        # Create panel instances
        self._status = StatusPanel(
            self._shared_a, self._shared_b, self._engine, self._cfg,
        )
        self._log = LogPanel(self._engine)

        # Inject DOMCA theme
        ui.add_head_html(_DOMCA_HEAD)

        # Default to dark mode
        dark = ui.dark_mode(True)

        # ── Header ────────────────────────────────────────────────
        with ui.header().classes("items-center px-4 py-2 shadow-md"):
            ui.icon("swap_horiz").classes("text-white text-2xl")
            ui.label(
                f"MeshCore Bridge v1.0.0"
            ).classes("text-lg font-bold ml-2 bridge-header-text")

            ui.label(
                f"({self._cfg.device_a.label} ↔ {self._cfg.device_b.label})"
            ).classes("text-xs ml-2 bridge-header-text").style("opacity: 0.65")

            ui.space()

            self._header_status = ui.label("Starting...").classes(
                "text-sm opacity-70 bridge-header-text"
            )

            ui.button(
                icon="brightness_6",
                on_click=lambda: dark.toggle(),
            ).props("flat round dense color=white").tooltip("Toggle dark / light")

        # ── Main Content ──────────────────────────────────────────
        with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):

            # Config summary
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2 mb-2"):
                    ui.icon("settings", color="primary").classes("text-lg")
                    ui.label("Bridge Configuration").classes(
                        "text-sm font-bold"
                    ).style("font-family: 'JetBrains Mono', monospace")

                with ui.row().classes("gap-4 flex-wrap"):
                    for lbl, val in [
                        ("Channel", f"#{self._cfg.channel_name}"),
                        ("Channel idx A", str(self._cfg.channel_idx_a)),
                        ("Channel idx B", str(self._cfg.channel_idx_b)),
                        ("Poll interval", f"{self._cfg.poll_interval_ms}ms"),
                        ("Prefix", "ON" if self._cfg.forward_prefix else "OFF"),
                        ("Loop cache", str(self._cfg.max_forwarded_cache)),
                    ]:
                        with ui.column().classes("gap-0"):
                            ui.label(lbl).classes("text-xs opacity-50")
                            ui.label(val).classes("text-xs font-bold").style(
                                "font-family: 'JetBrains Mono', monospace"
                            )

            # Status panel
            self._status.render()

            # Log panel
            self._log.render()

        # ── Update timer (500ms, same as meshcore_gui) ────────────
        ui.timer(0.5, self._on_timer)

    def _on_timer(self) -> None:
        """Periodic UI update callback."""
        # Update header status
        snap_a = self._shared_a.get_snapshot()
        snap_b = self._shared_b.get_snapshot()
        conn_a = snap_a.get("connected", False)
        conn_b = snap_b.get("connected", False)
        total = self._engine.get_total_forwarded()

        if conn_a and conn_b:
            status = f"✅ Both connected — {total} forwarded"
        elif conn_a:
            status = f"⚠️ Device B disconnected — {total} forwarded"
        elif conn_b:
            status = f"⚠️ Device A disconnected — {total} forwarded"
        else:
            status = "❌ Both devices disconnected"

        if self._header_status:
            self._header_status.set_text(status)

        # Update panels
        if self._status:
            self._status.update()
        if self._log:
            self._log.update()
