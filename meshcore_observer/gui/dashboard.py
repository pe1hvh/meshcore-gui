"""
Observer dashboard — NiceGUI page with DOMCA theme.

Thin orchestrator that owns the layout, injects the DOMCA theme,
and runs a periodic update timer that polls the ArchiveWatcher
and refreshes all panels.  Visually consistent with the
meshcore_gui and meshcore_bridge dashboards.
"""

from nicegui import ui

from meshcore_observer import __version__
from meshcore_observer.archive_watcher import ArchiveWatcher
from meshcore_observer.config import ObserverConfig
from meshcore_observer.gui.panels.sources_panel import SourcesPanel
from meshcore_observer.gui.panels.messages_panel import MessagesPanel
from meshcore_observer.gui.panels.rxlog_panel import RxLogPanel
from meshcore_observer.gui.panels.stats_panel import StatsPanel
from meshcore_observer.gui.panels.mqtt_panel import MqttPanel


# ── DOMCA Theme (identical to meshcore_bridge dashboard) ─────────────
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

/* ── Observer-specific ── */
.observer-header-text {
  font-family: 'JetBrains Mono', monospace;
  color: white;
}
</style>
'''


class ObserverDashboard:
    """Observer dashboard page.

    Provides a NiceGUI-based monitoring view showing aggregated
    messages, RX log entries, archive sources, statistics, and
    MQTT uplink status from all detected archive files.

    Args:
        watcher:      ArchiveWatcher for polling archive files.
        config:       ObserverConfig for display settings.
        mqtt_uplink:  MqttUplink instance (or None if MQTT disabled).
    """

    def __init__(
        self,
        watcher: ArchiveWatcher,
        config: ObserverConfig,
        mqtt_uplink=None,
    ) -> None:
        self._watcher = watcher
        self._cfg = config
        self._mqtt_uplink = mqtt_uplink

        # Panels (created in render)
        self._sources: SourcesPanel | None = None
        self._messages: MessagesPanel | None = None
        self._rxlog: RxLogPanel | None = None
        self._stats: StatsPanel | None = None
        self._mqtt: MqttPanel | None = None

        # Header status label
        self._header_status = None

    def render(self) -> None:
        """Build the complete observer dashboard layout and start the timer."""

        # Create panel instances
        self._sources = SourcesPanel(self._watcher)
        self._messages = MessagesPanel(self._cfg.max_messages_display)
        self._rxlog = RxLogPanel(self._cfg.max_rxlog_display)
        self._stats = StatsPanel(self._watcher)
        self._mqtt = MqttPanel(self._mqtt_uplink)

        # Inject DOMCA theme
        ui.add_head_html(_DOMCA_HEAD)

        # Default to dark mode
        dark = ui.dark_mode(True)

        # ── Header ────────────────────────────────────────────────
        with ui.header().classes("items-center px-4 py-2 shadow-md"):
            ui.icon("visibility").classes("text-white text-2xl")
            ui.label(
                f"MeshCore Observer v{__version__}"
            ).classes("text-lg font-bold ml-2 observer-header-text")

            ui.space()

            self._header_status = ui.label("Scanning...").classes(
                "text-sm opacity-70 observer-header-text"
            )

            ui.button(
                icon="brightness_6",
                on_click=lambda: dark.toggle(),
            ).props("flat round dense color=white").tooltip("Toggle dark / light")

        # ── Main Content ──────────────────────────────────────────
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):

            # Config summary
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2 mb-2"):
                    ui.icon("settings", color="primary").classes("text-lg")
                    ui.label("Configuration").classes(
                        "text-sm font-bold"
                    ).style("font-family: 'JetBrains Mono', monospace")

                with ui.row().classes("gap-4 flex-wrap"):
                    config_items = [
                        ("Archive dir", self._cfg.archive_dir),
                        ("Poll interval", f"{self._cfg.poll_interval_s}s"),
                        ("Max messages", str(self._cfg.max_messages_display)),
                        ("Max RX log", str(self._cfg.max_rxlog_display)),
                    ]

                    # MQTT status in config summary
                    if self._cfg.mqtt.enabled:
                        mode = "DRY RUN" if self._cfg.mqtt.dry_run else "LIVE"
                        config_items.append(("MQTT", f"{mode} ({self._cfg.mqtt.iata})"))
                    else:
                        config_items.append(("MQTT", "Disabled"))

                    for lbl, val in config_items:
                        with ui.column().classes("gap-0"):
                            ui.label(lbl).classes("text-xs opacity-50")
                            ui.label(val).classes("text-xs font-bold").style(
                                "font-family: 'JetBrains Mono', monospace"
                            )

            # Top row: Sources + Stats + MQTT
            with ui.row().classes("w-full gap-4 flex-wrap"):
                with ui.column().classes("flex-1 min-w-[300px]"):
                    self._sources.render()
                with ui.column().classes("flex-1 min-w-[280px]"):
                    self._stats.render()

            # MQTT panel (full width, only if enabled or for status)
            self._mqtt.render()

            # Messages panel (full width)
            self._messages.render()

            # RX log panel (full width)
            self._rxlog.render()

        # ── Update timer ──────────────────────────────────────────
        ui.timer(self._cfg.poll_interval_s, self._on_timer)

    def _on_timer(self) -> None:
        """Periodic UI update callback — poll watcher, publish MQTT, refresh panels."""
        result = self._watcher.poll()

        # Feed new data to panels
        if result.new_messages and self._messages:
            self._messages.add_messages(result.new_messages)
        if result.new_rxlog and self._rxlog:
            self._rxlog.add_entries(result.new_rxlog)

        # Publish new RX log entries to MQTT (if enabled)
        if result.new_rxlog and self._mqtt_uplink:
            try:
                self._mqtt_uplink.publish_entries(result.new_rxlog)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "MQTT publish error: %s", exc,
                )

        # Update header status
        stats = self._watcher.get_stats()
        n_sources = stats["active_sources"]
        n_msg = stats["total_messages_seen"]
        n_rx = stats["total_rxlog_seen"]

        if n_sources > 0:
            status = f"✅ {n_sources} source{'s' if n_sources != 1 else ''} — {n_msg} msg / {n_rx} rx"
        else:
            status = "⏳ Waiting for archive files..."

        if self._header_status:
            self._header_status.set_text(status)

        # Refresh all panels
        if self._sources:
            self._sources.update()
        if self._messages:
            self._messages.update()
        if self._rxlog:
            self._rxlog.update()
        if self._stats:
            self._stats.update()
        if self._mqtt:
            self._mqtt.update()
