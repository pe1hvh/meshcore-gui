"""
Repeater statistics poller for MeshCore GUI.

Opens a session on a configured repeater, requests its status, records
the result and closes the session again.

Sequence per repeater
~~~~~~~~~~~~~~~~~~~~~
1. ``send_login_sync(pubkey, password)`` — sends the login request and
   waits for the ``LOGIN_SUCCESS`` event.  The library handles the
   subscribe-before-send itself; the plain ``send_login`` returns as soon
   as the frame is on the wire and says nothing about the outcome.
2. ``req_status_sync(pubkey)`` — sends a binary STATUS request and waits
   for the matching ``STATUS_RESPONSE``, returning the parsed fields.
3. ``send_logout(pubkey)`` — always, including after a failed or timed
   out status request.  A login that timed out may still have succeeded
   on the far side, so the logout is sent whenever a login was attempted.

Spreading
~~~~~~~~~
At most one repeater is polled per call, and each repeater gets its own
start offset within the interval, so two repeaters are never queried back
to back.  With two repeaters on a 15-minute interval the polls land
roughly 7.5 minutes apart.

Airtime
~~~~~~~
One status request per poll.  Every extra measurement is another full
round trip over the radio, so no repeat-and-average happens here — raw
values go to the archive and any averaging is somebody else's job.

The poller never logs, returns or stores the password.

                   Author: PE1HVH
  SPDX-License-Identifier: MIT
"""

import time
from typing import Any, Dict, Optional

from meshcore_gui.config import (
    REPEATER_LOGIN_TIMEOUT,
    REPEATER_STATUS_TIMEOUT,
    debug_print,
)
from meshcore_gui.services.repeater_config_store import (
    RepeaterConfigStore,
    RepeaterInfo,
)
from meshcore_gui.services.repeater_stats_archive import RepeaterStatsArchive


class RepeaterPoller:
    """Polls configured repeaters for their statistics.

    Args:
        config_store: Source of repeaters, intervals and passwords.
        archive:      Destination for every poll result.
    """

    def __init__(
        self,
        config_store: RepeaterConfigStore,
        archive: RepeaterStatsArchive,
    ) -> None:
        self._config = config_store
        self._archive = archive

        # Next monotonic timestamp at which each repeater is due.
        self._next_due: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def poll_due(self, mc) -> None:
        """Poll at most one repeater that is due.

        Safe to call on every main-loop tick; it returns immediately when
        nothing is due.  A failure on one repeater is recorded and does
        not affect the schedule of the other.

        Args:
            mc: Connected ``MeshCore`` instance.
        """
        if mc is None:
            return

        repeaters = self._config.get_enabled_repeaters()
        if not repeaters:
            return

        self._schedule_new(repeaters)

        now = time.monotonic()
        for info in repeaters:
            if self._next_due.get(info.pubkey, 0.0) > now:
                continue

            # Reschedule before polling, so a slow or failing poll cannot
            # cause a burst of catch-up attempts afterwards.
            self._next_due[info.pubkey] = now + info.poll_interval

            await self._poll_one(mc, info)
            return  # one repeater per tick — keeps the polls spread out

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _schedule_new(self, repeaters) -> None:
        """Assign a start offset to repeaters that have no schedule yet.

        Offsets are spread evenly across the interval so the first round
        of polls does not fire all at once after a restart.

        Args:
            repeaters: Enabled repeaters from the configuration store.
        """
        unscheduled = [r for r in repeaters if r.pubkey not in self._next_due]
        if not unscheduled:
            return

        now = time.monotonic()
        total = len(repeaters)
        already_scheduled = len(self._next_due)
        for position, info in enumerate(unscheduled):
            spacing = info.poll_interval / total if total else 0.0
            offset = spacing * (already_scheduled + position)
            self._next_due[info.pubkey] = now + offset
            debug_print(
                f"RepeaterPoller: scheduled {info.name or info.pubkey[:16]} "
                f"in {offset:.0f}s, then every {info.poll_interval:.0f}s"
            )

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_one(self, mc, info: RepeaterInfo) -> None:
        """Run one full session against a single repeater.

        Args:
            mc:   Connected ``MeshCore`` instance.
            info: Repeater to poll.
        """
        label = info.name or info.pubkey[:16]
        password = self._config.get_password(info.pubkey)

        if password is None:
            self._archive.add_measurement(
                info.pubkey, info.name, error="no_password_configured"
            )
            return

        login_attempted = False
        try:
            debug_print(f"RepeaterPoller: login → {label}")
            login_attempted = True
            login_event = await mc.commands.send_login_sync(
                info.pubkey,
                password,
                min_timeout=REPEATER_LOGIN_TIMEOUT,
            )

            if login_event is None:
                debug_print(f"RepeaterPoller: no login confirmation from {label}")
                self._archive.add_measurement(
                    info.pubkey, info.name, error="login_failed_or_timeout"
                )
                return

            debug_print(f"RepeaterPoller: status request → {label}")
            status = await mc.commands.req_status_sync(
                info.pubkey,
                min_timeout=REPEATER_STATUS_TIMEOUT,
            )

            if not status:
                self._archive.add_measurement(
                    info.pubkey, info.name, error="no_status_response"
                )
                return

            self._archive.add_measurement(
                info.pubkey, info.name, status=_clean_status(status)
            )

        except Exception as exc:  # noqa: BLE001 — one repeater must not stop the loop
            debug_print(f"RepeaterPoller: {label} failed: {exc}")
            self._archive.add_measurement(
                info.pubkey, info.name, error=f"exception: {type(exc).__name__}"
            )

        finally:
            if login_attempted:
                await self._logout(mc, info.pubkey, label)

    async def _logout(self, mc, pubkey: str, label: str) -> None:
        """Close the session, ignoring any failure.

        Args:
            mc:     Connected ``MeshCore`` instance.
            pubkey: Full public key of the repeater.
            label:  Display label used in debug output.
        """
        try:
            await mc.commands.send_logout(pubkey)
            debug_print(f"RepeaterPoller: logout → {label}")
        except Exception as exc:  # noqa: BLE001 — logout is best-effort
            debug_print(f"RepeaterPoller: logout failed for {label}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_status(status: Any) -> Dict[str, Any]:
    """Return the status payload as a plain JSON-serialisable dict.

    Values are passed through unchanged — no scaling or rounding.  Only
    types that JSON cannot represent are converted to their string form.

    Args:
        status: Payload from ``req_status_sync``.

    Returns:
        Dict suitable for the archive.
    """
    if not isinstance(status, dict):
        return {"value": str(status)}

    cleaned: Dict[str, Any] = {}
    for key, value in status.items():
        if isinstance(value, (bytes, bytearray)):
            cleaned[str(key)] = value.hex()
        elif isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[str(key)] = value
        else:
            cleaned[str(key)] = str(value)
    return cleaned
