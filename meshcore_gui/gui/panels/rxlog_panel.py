"""RX log panel — table of recently received packets."""

from typing import Dict, List

from nicegui import ui

from meshcore_gui.core.models import RxLogEntry


class RxLogPanel:
    """RX log table in the right column."""

    def __init__(self) -> None:
        self._table = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_path(entry: RxLogEntry) -> str:
        """Build a display path: Sender → [repeaters →] Receiver.

        Falls back gracefully when sender or receiver is unknown.
        """
        parts: list = []

        if entry.sender:
            parts.append(entry.sender)

        # Repeater names (resolved or raw hex)
        if entry.path_names:
            parts.extend(entry.path_names)

        if entry.receiver:
            parts.append(entry.receiver)

        return ' → '.join(parts) if parts else '-'

    # ------------------------------------------------------------------
    # Render / Update
    # ------------------------------------------------------------------

    def render(self) -> None:
        with ui.card().classes('w-full flex-grow'):
            ui.label('📊 RX Log').classes('font-bold text-gray-600')
            self._table = ui.table(
                columns=[
                    {'name': 'time', 'label': 'Time', 'field': 'time',
                     'align': 'left'},
                    {'name': 'snr', 'label': 'SNR', 'field': 'snr',
                     'align': 'right'},
                    {'name': 'rssi', 'label': 'RSSI', 'field': 'rssi',
                     'align': 'right'},
                    {'name': 'type', 'label': 'Type', 'field': 'type',
                     'align': 'left'},
                    {'name': 'hops', 'label': 'Hops', 'field': 'hops',
                     'align': 'right'},
                    {'name': 'path', 'label': 'Path', 'field': 'path',
                     'align': 'left',
                     'classes': 'rxlog-path-cell',
                     'headerClasses': 'rxlog-path-header'},
                ],
                rows=[],
            ).props('dense flat').classes('w-full text-xs h-40 overflow-y-auto')

            # Constrain the path column so it cannot push the table
            # wider than the parent card.
            ui.add_css('''
                .rxlog-path-cell {
                    max-width: 160px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .rxlog-path-header {
                    max-width: 160px;
                }
            ''')

    def update(self, data: Dict) -> None:
        if not self._table:
            return
        entries: List[RxLogEntry] = data['rx_log'][:20]
        rows = [
            {
                'time': e.time,
                'snr': f"{e.snr:.1f}",
                'rssi': f"{e.rssi:.0f}",
                'type': e.payload_type,
                'hops': str(e.hops),
                'path': self._build_path(e),
            }
            for e in entries
        ]
        self._table.rows = rows
        self._table.update()
