"""Device information panel — radio name, frequency, location, firmware."""

from typing import Dict

from nicegui import ui


class DevicePanel:
    """Displays device info in the left column."""

    def __init__(self) -> None:
        self._label = None

    def render(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('📡 Device').classes('font-bold text-gray-600')
            self._label = ui.label('Connecting...').classes(
                'text-sm whitespace-pre-line'
            )

    def update(self, data: Dict) -> None:
        if not self._label:
            return

        lines = []
        if data['name']:
            lines.append(f"📡 {data['name']}")
        if data['public_key']:
            lines.append(f"🔑 {data['public_key'][:16]}...")
        if data['radio_freq']:
            lines.append(f"📻 {data['radio_freq']:.3f} MHz")
            lines.append(f"⚙️ SF{data['radio_sf']} / {data['radio_bw']} kHz")
        if data['tx_power']:
            lines.append(f"⚡ TX: {data['tx_power']} dBm")
        if data['adv_lat'] and data['adv_lon']:
            lines.append(f"📍 {data['adv_lat']:.4f}, {data['adv_lon']:.4f}")
        if data['firmware_version']:
            lines.append(f"🏷️ {data['firmware_version']}")

        self._label.text = "\n".join(lines) if lines else "Loading..."
