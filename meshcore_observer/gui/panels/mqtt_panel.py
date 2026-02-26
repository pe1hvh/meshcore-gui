"""
MQTT status panel — broker connection status and publish statistics.

Displays MQTT uplink health: per-broker connection state, packet
counters, filter configuration, and any errors.  Updates in real-time
via the dashboard timer.
"""

from typing import Dict, Optional

from nicegui import ui


class MqttPanel:
    """MQTT uplink status panel.

    Args:
        mqtt_uplink: MqttUplink instance (or None if MQTT disabled).
    """

    def __init__(self, mqtt_uplink=None) -> None:
        self._uplink = mqtt_uplink

        # UI element references
        self._status_icon: Optional[ui.icon] = None
        self._status_label: Optional[ui.label] = None
        self._topic_label: Optional[ui.label] = None
        self._filter_label: Optional[ui.label] = None
        self._published_label: Optional[ui.label] = None
        self._filtered_label: Optional[ui.label] = None
        self._skipped_label: Optional[ui.label] = None
        self._brokers_container: Optional[ui.column] = None

    def render(self) -> None:
        """Build the MQTT status panel UI."""
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.icon("cell_tower", color="primary").classes("text-lg")
                ui.label("MQTT Uplink").classes(
                    "text-sm font-bold"
                ).style("font-family: 'JetBrains Mono', monospace")

                ui.space()

                self._status_icon = ui.icon("circle").classes("text-sm")
                self._status_label = ui.label("").classes("text-xs")

            if self._uplink is None:
                ui.label("MQTT is disabled in configuration.").classes(
                    "text-xs opacity-40 py-1"
                )
                return

            with ui.column().classes("gap-1 w-full"):
                # Topic info
                with ui.row().classes("items-center gap-2"):
                    ui.label("Topic:").classes("text-xs opacity-60 w-24")
                    self._topic_label = ui.label("-").classes(
                        "text-xs font-bold"
                    ).style("font-family: 'JetBrains Mono', monospace")

                # Filter info
                with ui.row().classes("items-center gap-2"):
                    ui.label("Filter:").classes("text-xs opacity-60 w-24")
                    self._filter_label = ui.label("-").classes("text-xs")

                # Counters
                with ui.row().classes("items-center gap-2"):
                    ui.label("Published:").classes("text-xs opacity-60 w-24")
                    self._published_label = ui.label("0").classes(
                        "text-xs font-bold"
                    )

                with ui.row().classes("items-center gap-2"):
                    ui.label("Filtered:").classes("text-xs opacity-60 w-24")
                    self._filtered_label = ui.label("0").classes("text-xs")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Skipped:").classes("text-xs opacity-60 w-24")
                    self._skipped_label = ui.label("0").classes("text-xs")

            ui.separator().classes("my-2")

            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon("dns", color="primary").classes("text-sm")
                ui.label("Brokers").classes("text-xs font-bold")

            self._brokers_container = ui.column().classes("gap-1 w-full")

    def update(self) -> None:
        """Refresh MQTT status from uplink instance."""
        if self._uplink is None:
            return

        status = self._uplink.get_status()

        # Global status indicator
        if self._status_icon and self._status_label:
            if status.get("dry_run"):
                self._status_icon.props("color=yellow")
                self._status_label.set_text("DRY RUN")
            elif any(b["connected"] for b in status.get("brokers", [])):
                self._status_icon.props("color=green")
                self._status_label.set_text("Connected")
            elif status.get("started"):
                self._status_icon.props("color=orange")
                self._status_label.set_text("Connecting...")
            else:
                self._status_icon.props("color=red")
                self._status_label.set_text("Disconnected")

        # Topic
        if self._topic_label:
            self._topic_label.set_text(status.get("topic_base", "-"))

        # Filter
        if self._filter_label:
            filt = status.get("upload_filter", "ALL")
            if isinstance(filt, list):
                self._filter_label.set_text(", ".join(filt))
            else:
                self._filter_label.set_text(str(filt))

        # Counters
        if self._published_label:
            self._published_label.set_text(str(status.get("total_published", 0)))
        if self._filtered_label:
            self._filtered_label.set_text(str(status.get("total_filtered", 0)))
        if self._skipped_label:
            self._skipped_label.set_text(
                f"{status.get('total_skipped_no_raw', 0)} (no raw_payload)"
            )

        # Per-broker status
        if self._brokers_container:
            self._brokers_container.clear()
            with self._brokers_container:
                brokers = status.get("brokers", [])
                if not brokers:
                    ui.label("No brokers configured.").classes(
                        "text-xs opacity-40 py-1"
                    )
                else:
                    for b in brokers:
                        with ui.row().classes("items-center gap-2 py-0.5"):
                            # Connection dot
                            color = "green" if b["connected"] else "red"
                            ui.icon("circle", color=color).classes("text-xs")

                            ui.label(b["name"]).classes(
                                "text-xs opacity-70 w-28"
                            )
                            ui.label(f"{b['packets_published']} pkts").classes(
                                "text-xs w-20"
                            )
                            ui.label(
                                b.get("last_publish_time", "-")[-8:]
                            ).classes("text-xs opacity-50 w-20")

                        # Show error if present
                        if b.get("last_error"):
                            with ui.row().classes("pl-6"):
                                ui.label(
                                    f"⚠ {b['last_error']}"
                                ).classes("text-xs text-red-400")
