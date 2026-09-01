"""Repeater statistics panel — read-only view of every reported field."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from nicegui import ui

from meshcore_gui.services.repeater_config_store import RepeaterConfigStore
from meshcore_gui.services.repeater_stats_archive import RepeaterStatsArchive

#: Labels for the fields the firmware currently reports.  A field that is
#: not listed here is still displayed, using its raw name — the panel
#: renders whatever the repeater sends, so a new firmware field shows up
#: without a code change.
FIELD_LABELS: Dict[str, str] = {
    "bat": "Battery",
    "uptime": "Uptime",
    "airtime": "TX airtime",
    "rx_airtime": "RX airtime",
    "tx_queue_len": "TX queue",
    "noise_floor": "Noise floor",
    "last_rssi": "Last RSSI",
    "last_snr": "Last SNR",
    "nb_recv": "Packets received",
    "nb_sent": "Packets sent",
    "sent_flood": "Sent flood",
    "sent_direct": "Sent direct",
    "recv_flood": "Received flood",
    "recv_direct": "Received direct",
    "direct_dups": "Direct duplicates",
    "flood_dups": "Flood duplicates",
    "full_evts": "Queue full events",
    "recv_errors": "Receive errors",
    "pubkey_pre": "Public key prefix",
}


class RepeaterStatsPanel:
    """One card per repeater with every field from its last status response.

    Read-only: repeaters are configured in the JSON file on disk, not from
    the GUI.  Passwords are never available here — the configuration store
    hands out :class:`RepeaterInfo` objects that have no password field.

    Values are rendered exactly as the repeater reports them.  The panel
    applies no conversion, so the unit is whatever the firmware returns.

    Args:
        config_store: Source of the configured repeaters.
        archive:      Source of the poll results.
    """

    def __init__(
        self,
        config_store: RepeaterConfigStore,
        archive: RepeaterStatsArchive,
    ) -> None:
        self._config = config_store
        self._archive = archive
        self._container = None
        self._hint = None

        # Rebuild only when something actually changed, so the 0.5 s
        # update tick does not re-create the cards continuously.
        self._fingerprint: Optional[Tuple] = None

    # ------------------------------------------------------------------
    # Render / Update
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the panel layout."""
        with ui.card().classes('w-full flex-grow'):
            ui.label('📶 Repeater Statistics').classes(
                'font-bold text-gray-600'
            )
            self._container = ui.column().classes('w-full gap-2')
            self._hint = ui.label('').classes('text-xs text-gray-500')

    def update(self, data: Optional[Dict] = None) -> None:
        """Rebuild the cards when a new poll result has arrived.

        Args:
            data: Shared-data snapshot.  Unused — this panel reads from
                  the archive cache, not from SharedData.  Accepted so
                  the call site matches the other panels.
        """
        if not self._container:
            return

        repeaters = self._config.get_repeaters()

        fingerprint = tuple(
            (
                info.pubkey,
                info.enabled,
                (self._archive.get_latest(info.pubkey) or {}).get('polled_at'),
                (self._archive.get_latest_success(info.pubkey) or {}).get('polled_at'),
            )
            for info in repeaters
        )
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint

        self._container.clear()
        with self._container:
            for info in repeaters:
                self._render_repeater(info)

        if self._hint:
            if repeaters:
                self._hint.set_text(
                    'Values as reported by the repeater, without conversion. '
                    f'Configured in {self._config.path}'
                )
            else:
                self._hint.set_text(
                    f'No repeaters configured. Add them to {self._config.path}'
                )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_repeater(self, info) -> None:
        """Render one repeater card.

        Args:
            info: :class:`RepeaterInfo` for the repeater.
        """
        latest = self._archive.get_latest(info.pubkey)
        latest_ok = self._archive.get_latest_success(info.pubkey)
        status = (latest_ok or {}).get('status', {})

        with ui.card().classes('w-full').props('flat bordered'):
            # ── Header: name and current state ────────────────────
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(info.name or info.pubkey[:16]).classes(
                    'font-bold text-sm'
                )
                ui.label(_status_text(info.enabled, latest)).classes('text-xs')

            with ui.row().classes('w-full items-center gap-4'):
                ui.label(f'Last OK: {_age(latest_ok)}').classes(
                    'text-xs text-gray-500'
                )
                ui.label(f'Last poll: {_age(latest)}').classes(
                    'text-xs text-gray-500'
                )
                ui.label(f'Interval: {int(info.poll_interval)}s').classes(
                    'text-xs text-gray-500'
                )

            if latest and not latest.get('ok'):
                ui.label(f"Last error: {latest.get('error')}").classes(
                    'text-xs'
                ).style('color: #e63946')

            if not status:
                ui.label('No successful poll yet.').classes(
                    'text-xs text-gray-500'
                )
                return

            # ── Every field from the status response ──────────────
            ui.separator()
            with ui.grid(columns=2).classes('w-full gap-x-6 gap-y-0'):
                for key, value in _ordered_fields(status):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label(FIELD_LABELS.get(key, key)).classes(
                            'text-xs text-gray-500'
                        )
                        ui.label(_display(value)).classes(
                            'text-xs font-mono'
                        )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _ordered_fields(status: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Return status fields with the known ones first, then the rest.

    Unknown fields are kept and appended, so a firmware that reports
    something new still shows it.

    Args:
        status: Raw status dict from the archive.

    Returns:
        List of (key, value) pairs in display order.
    """
    known = [(k, status[k]) for k in FIELD_LABELS if k in status]
    extra = [(k, v) for k, v in status.items() if k not in FIELD_LABELS]
    return known + extra


def _display(value: Any) -> str:
    """Return a value as display text without converting it.

    Args:
        value: Raw field value.

    Returns:
        The value as a string, or ``"-"`` when it is None.
    """
    return '-' if value is None else str(value)


def _age(record: Optional[Dict[str, Any]]) -> str:
    """Return how long ago a record was written.

    Args:
        record: Archive record, or None.

    Returns:
        Short relative time such as ``"4m ago"``, or ``"never"``.
    """
    if not record:
        return 'never'
    try:
        polled = datetime.fromisoformat(record['polled_at'])
    except (KeyError, TypeError, ValueError):
        return '-'

    seconds = (datetime.now(timezone.utc) - polled).total_seconds()
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{int(seconds // 60)}m ago'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h ago'
    return f'{int(seconds // 86400)}d ago'


def _status_text(enabled: bool, latest: Optional[Dict[str, Any]]) -> str:
    """Build the status text for a repeater card.

    Args:
        enabled: Whether polling is enabled for this repeater.
        latest:  Most recent record, successful or not.

    Returns:
        Short status description.
    """
    if not enabled:
        return '⏸ disabled'
    if not latest:
        return '⏳ waiting for first poll'
    if latest.get('ok'):
        return '✅ ok'
    return '❌ failed'
