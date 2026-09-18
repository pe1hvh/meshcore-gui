"""Repeater statistics panel — read-only view of every reported field."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from nicegui import ui

from meshcore_gui.services.repeater_config_archive import RepeaterConfigArchive
from meshcore_gui.services.repeater_config_store import RepeaterConfigStore
from meshcore_gui.services.repeater_stats_archive import RepeaterStatsArchive

#: Fields the firmware reports as a duration in seconds.  Only their
#: presentation changes; the archive keeps the raw value.
DURATION_FIELDS = ("uptime", "airtime", "rx_airtime")

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

#: Labels for the settings read by the nightly configuration poller.  As
#: with the status fields, a setting that is not listed here is still
#: displayed under its raw name, so adding a command to
#: ``REPEATER_CONFIG_POLL_KEYS`` needs no change in this panel.
CONFIG_LABELS: Dict[str, str] = {
    "flood.max": "Flood max",
    "flood.max.unscoped": "Flood max unscoped",
    "flood.max.advert": "Flood max advert",
    "loop.detect": "Loop detect",
    "txdelay": "TX delay",
    "rxdelay": "RX delay",
    "int.thresh": "Interference threshold",
    "radio.rxgain": "RX gain",
    "agc.reset.interval": "AGC reset interval",
    "region": "Region",
}


class RepeaterStatsPanel:
    """One card per repeater with every field from its last status response.

    Read-only: repeaters are configured in the JSON file on disk, not from
    the GUI.  Passwords are never available here — the configuration store
    hands out :class:`RepeaterInfo` objects that have no password field.

    Values are rendered exactly as the repeater reports them.  The panel
    applies no conversion, so the unit is whatever the firmware returns.

    A per-repeater Poll now button queues a ``poll_repeater`` command for
    the worker, which runs the same login/status/logout sequence as the
    scheduled poll.  Nothing else on the panel is editable.

    Settings read by the nightly configuration poller are shown in their
    own block below the status fields, with their own age, because they
    come from a different read at a different moment.

    Args:
        config_store:   Source of the configured repeaters.
        archive:        Source of the poll results.
        put_command:    Command sink towards the worker.  When omitted the
                        Poll now button is not rendered.
        config_archive: Source of the nightly configuration readings.
                        When omitted the settings block is not rendered.
    """

    def __init__(
        self,
        config_store: RepeaterConfigStore,
        archive: RepeaterStatsArchive,
        put_command=None,
        config_archive: Optional[RepeaterConfigArchive] = None,
    ) -> None:
        self._config = config_store
        self._archive = archive
        self._put_command = put_command
        self._config_archive = config_archive
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
                (self._latest_config(info.pubkey) or {}).get('polled_at'),
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
    # Manual poll
    # ------------------------------------------------------------------

    def _on_poll_now(self, pubkey: str, name: str) -> None:
        """Queue a manual poll for one repeater.

        The command is handed to the worker thread; the result appears in
        the panel on a later update tick, once the poll has run.  A poll
        takes as long as the radio needs, so no result is awaited here.

        Args:
            pubkey: Full public key of the repeater.
            name:   Display name, used in the notification.
        """
        if self._put_command is None:
            return
        self._put_command({'action': 'poll_repeater', 'pubkey': pubkey})
        ui.notify(
            f"Polling {name or pubkey[:16]}…",
            type='info',
            position='top',
            timeout=3000,
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
            # ── Header: name, current state, manual poll ──────────
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(info.name or info.pubkey[:16]).classes(
                    'font-bold text-sm'
                )
                with ui.row().classes('items-center gap-2'):
                    ui.label(_status_text(info.enabled, latest)).classes(
                        'text-xs'
                    )
                    if self._put_command is not None:
                        ui.button(
                            'Poll now',
                            icon='refresh',
                            on_click=lambda pk=info.pubkey,
                            nm=info.name: self._on_poll_now(pk, nm),
                        ).props('flat dense no-caps size=sm')

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
            else:
                # ── Every field from the status response ──────────
                ui.separator()
                with ui.grid(columns=2).classes('w-full gap-x-6 gap-y-0'):
                    for key, value in _ordered_fields(status):
                        with ui.row().classes(
                            'w-full items-center justify-between'
                        ):
                            ui.label(FIELD_LABELS.get(key, key)).classes(
                                'text-xs text-gray-500'
                            )
                            ui.label(_display(key, value)).classes(
                                'text-xs font-mono'
                            )

            self._render_config(info)

    def _render_config(self, info) -> None:
        """Render the settings block of one repeater card.

        Draws nothing at all when no configuration archive is wired or
        the repeater has never been read, so a card looks exactly as it
        did before the nightly poller existed until the first read lands.

        Args:
            info: :class:`RepeaterInfo` for the repeater.
        """
        latest = self._latest_config(info.pubkey)
        if latest is None:
            return

        latest_ok = self._config_archive.get_latest_success(info.pubkey)
        settings = (latest_ok or {}).get('config', {})

        ui.separator()
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Settings').classes('text-xs text-gray-500 font-bold')
            ui.label(f'Read: {_age(latest_ok)}').classes(
                'text-xs text-gray-500'
            )

        if latest and not latest.get('ok'):
            ui.label(f"Last read error: {latest.get('error')}").classes(
                'text-xs'
            ).style('color: #e63946')

        if not settings:
            return

        with ui.grid(columns=2).classes('w-full gap-x-6 gap-y-0'):
            for key, value in _ordered_settings(settings):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label(CONFIG_LABELS.get(key, key)).classes(
                        'text-xs text-gray-500'
                    )
                    # Inline CSS, not a Tailwind whitespace class: there
                    # is no Tailwind compiler in NiceGUI.  A multi-line
                    # value such as the region list keeps its line breaks.
                    ui.label(str(value)).classes('text-xs font-mono').style(
                        'white-space: pre-line; text-align: right'
                    )

        missing = (latest_ok or {}).get('missing') or []
        if missing:
            ui.label(f"No reply: {', '.join(missing)}").classes(
                'text-xs text-gray-500'
            )

    def _latest_config(self, pubkey: str) -> Optional[Dict[str, Any]]:
        """Return the most recent configuration record for a repeater.

        Args:
            pubkey: Full public key of the repeater.

        Returns:
            The record, ``None`` when there is none or no configuration
            archive is wired into the panel.
        """
        if self._config_archive is None:
            return None
        return self._config_archive.get_latest(pubkey)


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


def _ordered_settings(settings: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Return settings in the order of the labels, unknown ones last.

    Args:
        settings: Configuration values from the archive.

    Returns:
        List of (key, value) pairs in display order.
    """
    known = [(k, settings[k]) for k in CONFIG_LABELS if k in settings]
    extra = [(k, v) for k, v in settings.items() if k not in CONFIG_LABELS]
    return known + extra


def _display(key: str, value: Any) -> str:
    """Return a field as display text.

    Durations are rendered as days, hours, minutes and seconds because
    a raw second count is unreadable at these magnitudes.  Every other
    field is shown exactly as reported.  The archive is unaffected — it
    always stores the raw value.

    Args:
        key:   Field name.
        value: Raw field value.

    Returns:
        Display string, or ``"-"`` when the value is None.
    """
    if value is None:
        return '-'
    if key in DURATION_FIELDS:
        return _format_duration(value)
    return str(value)


def _format_duration(seconds: Any) -> str:
    """Format a second count as ``NNd HHh MMm SSs``.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration, or the raw value as a string when it is
        not a whole number of seconds.
    """
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if total < 0:
        return str(seconds)

    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m {secs:02d}s"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


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
