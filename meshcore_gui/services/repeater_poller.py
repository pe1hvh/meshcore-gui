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

Stale paths
~~~~~~~~~~~
Routing is not part of the login request: the frame carries the public
key and the *device* picks the route from its own contact table, where
``out_path_len == -1`` means flood.  A repeater whose stored path has
gone stale therefore never answers, while one reachable directly does.

After a login that produced no confirmation the poller calls
``reset_path()``, which drops the stored path so the next poll floods and
relearns a route from the ACK.  This mirrors what the library itself does
in ``send_msg_with_retry`` after repeated failures.  ``reset_path`` is a
device-local command and costs no airtime.

Retries
~~~~~~~
A repeater that does not answer is retried within the same poll, up to
``REPEATER_POLL_MAX_ATTEMPTS`` times with ``REPEATER_POLL_RETRY_DELAY``
seconds in between.  An attempt is the complete sequence above, logout
included: the login has to be redone because a session that never
confirmed cannot be assumed to exist.  Combined with the path reset this
means the second attempt usually goes out as a flood, which is what
recovers a repeater whose stored route went stale.

Only one record is written per poll, carrying the attempt count and the
error of the last attempt.  Recording every individual attempt would
skew the success ratio in the archive and grow the file several times
faster without adding information the count does not already give.

A missing password is not retried — that is a configuration error, not
a transient one.

This retry is a workaround, not a fix.  It masks whatever makes the
repeater unreachable rather than addressing it; the attempt count in the
archive is there to make that underlying failure rate measurable.

Cancellation
~~~~~~~~~~~~
A poll is background work with no deadline: nobody waits for the result
and a missed poll costs one data point out of ninety-six per day.  The
worker therefore runs it as a task it can cancel the moment there is
traffic to send, which has priority.  A cancelled poll writes no archive
record — the measurement is postponed, not failed — and its repeater is
made due again immediately, so it is retried as soon as the queue is
empty.  Recording a cancellation as a failure would make the repeater
look unreachable when only the timing was inconvenient.

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

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

from meshcore_gui.config import (
    REPEATER_LOGIN_TIMEOUT,
    REPEATER_POLL_MAX_ATTEMPTS,
    REPEATER_POLL_RETRY_DELAY,
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

        Cancelling the surrounding task interrupts the poll.  The
        repeater is then made due again straight away and the
        ``CancelledError`` is re-raised so the task ends as cancelled.

        Args:
            mc: Connected ``MeshCore`` instance.

        Raises:
            asyncio.CancelledError: When the caller cancels the poll.
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

            try:
                await self._poll_one(mc, info)
            except asyncio.CancelledError:
                # Traffic took priority.  Undo the reschedule so this
                # repeater is due again on the next tick instead of
                # waiting out a full interval for a measurement that was
                # never taken.
                self._next_due[info.pubkey] = time.monotonic()
                debug_print(
                    f"RepeaterPoller: poll of {info.name or info.pubkey[:16]} "
                    f"cancelled — rescheduled immediately"
                )
                raise
            return  # one repeater per tick — keeps the polls spread out

    async def poll_now(self, mc, pubkey: str) -> bool:
        """Poll one repeater immediately, on request from the GUI.

        Runs the same sequence as the scheduled poll and writes the same
        record, so a manual poll is indistinguishable from an automatic
        one in the archive.  A disabled repeater is polled too: the
        request is an explicit user action, not the schedule.

        The repeater's next scheduled poll is pushed a full interval into
        the future, so a manual poll is not immediately followed by an
        automatic one.

        Args:
            mc:     Connected ``MeshCore`` instance.
            pubkey: Full public key of the repeater to poll.

        Returns:
            True when the poll ran, False when there is no connection or
            the repeater is not configured.
        """
        if mc is None:
            debug_print("RepeaterPoller: manual poll ignored — no connection")
            return False

        info = next(
            (r for r in self._config.get_repeaters() if r.pubkey == pubkey),
            None,
        )
        if info is None:
            debug_print(f"RepeaterPoller: manual poll for unknown {pubkey[:16]}")
            return False

        self._next_due[info.pubkey] = time.monotonic() + info.poll_interval
        debug_print(
            f"RepeaterPoller: manual poll → {info.name or info.pubkey[:16]}"
        )
        await self._poll_one(mc, info)
        return True

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
        """Poll a single repeater, retrying a failed session.

        Runs :meth:`_attempt_session` until it yields a status or the
        configured attempt budget is exhausted, then writes exactly one
        archive record for the poll as a whole.

        Args:
            mc:   Connected ``MeshCore`` instance.
            info: Repeater to poll.
        """
        label = info.name or info.pubkey[:16]
        password = self._config.get_password(info.pubkey)

        if password is None:
            self._archive.add_measurement(
                info.pubkey,
                info.name,
                error="no_password_configured",
                attempts=0,
            )
            return

        # A misconfigured zero or negative budget still buys one attempt;
        # silently polling nothing at all would be harder to diagnose.
        max_attempts = max(1, int(REPEATER_POLL_MAX_ATTEMPTS))
        last_error = "no_attempt_made"

        for attempt in range(1, max_attempts + 1):
            status, last_error = await self._attempt_session(
                mc, info, password, label, attempt, max_attempts
            )

            if status is not None:
                if attempt > 1:
                    debug_print(
                        f"RepeaterPoller: {label} answered on attempt "
                        f"{attempt}/{max_attempts}"
                    )
                self._archive.add_measurement(
                    info.pubkey,
                    info.name,
                    status=status,
                    attempts=attempt,
                )
                return

            if attempt < max_attempts and REPEATER_POLL_RETRY_DELAY > 0:
                await asyncio.sleep(REPEATER_POLL_RETRY_DELAY)

        debug_print(
            f"RepeaterPoller: {label} gave up after {max_attempts} "
            f"attempt(s) — last error: {last_error}"
        )
        self._archive.add_measurement(
            info.pubkey,
            info.name,
            error=last_error,
            attempts=max_attempts,
        )

    async def _attempt_session(
        self,
        mc,
        info: RepeaterInfo,
        password: str,
        label: str,
        attempt: int,
        max_attempts: int,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Run one complete session against a repeater.

        Logs in, requests the status and always logs out again.  Writes
        nothing to the archive: the caller decides what a failed attempt
        means once the whole poll is done.

        Args:
            mc:           Connected ``MeshCore`` instance.
            info:         Repeater to poll.
            password:     Login password for this repeater.
            label:        Display label used in debug output.
            attempt:      Number of this attempt, starting at one.
            max_attempts: Attempt budget, for debug output only.

        Returns:
            Tuple of the cleaned status and an empty string on success,
            or ``None`` and a short failure reason on failure.
        """
        suffix = f" (attempt {attempt}/{max_attempts})"
        login_attempted = False

        try:
            debug_print(f"RepeaterPoller: login → {label}{suffix}")
            login_attempted = True
            login_event = await mc.commands.send_login_sync(
                info.pubkey,
                password,
                min_timeout=REPEATER_LOGIN_TIMEOUT,
            )

            if login_event is None:
                debug_print(
                    f"RepeaterPoller: no login confirmation from {label}{suffix}"
                )
                await self._reset_path(mc, info.pubkey, label)
                return None, "login_failed_or_timeout"

            debug_print(f"RepeaterPoller: status request → {label}{suffix}")
            status = await mc.commands.req_status_sync(
                info.pubkey,
                min_timeout=REPEATER_STATUS_TIMEOUT,
            )

            if not status:
                debug_print(
                    f"RepeaterPoller: no status response from {label}{suffix}"
                )
                return None, "no_status_response"

            return _clean_status(status), ""

        except Exception as exc:  # noqa: BLE001 — one repeater must not stop the loop
            debug_print(f"RepeaterPoller: {label} failed{suffix}: {exc}")
            return None, f"exception: {type(exc).__name__}"

        finally:
            if login_attempted:
                await self._logout(mc, info.pubkey, label)

    async def _reset_path(self, mc, pubkey: str, label: str) -> None:
        """Drop the stored route so the next poll floods.

        Called after a login that produced no confirmation.  The device
        forgets the path it had for this repeater; the next attempt goes
        out as a flood and relearns a route from the ACK.  A repeater
        that is already on flood is simply set to flood again.

        Args:
            mc:     Connected ``MeshCore`` instance.
            pubkey: Full public key of the repeater.
            label:  Display label used in debug output.
        """
        try:
            await mc.commands.reset_path(pubkey)
            debug_print(
                f"RepeaterPoller: path reset for {label} — "
                "next poll will flood"
            )
        except Exception as exc:  # noqa: BLE001 — recovery is best-effort
            debug_print(f"RepeaterPoller: path reset failed for {label}: {exc}")

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
