"""
Repeater configuration poller for MeshCore GUI.

Reads the settings of a configured repeater once a day, preferably at
night, and records them.  Fully separate from
:class:`~meshcore_gui.services.repeater_poller.RepeaterPoller`, which
polls telemetry every fifteen minutes.

Why a separate poller
~~~~~~~~~~~~~~~~~~~~~
The settings in ``REPEATER_CONFIG_POLL_KEYS`` — flood limits, timing
parameters, radio gain, region — are configuration, not telemetry.  They
change when somebody edits them and otherwise stay identical for months.
There is no binary request that returns them, so each one costs its own
CLI round trip over the radio.  Asking for ten of them on the fifteen
minute statistics schedule would add ten round trips to every poll, for
values that did not change.  Once a day is enough, and at night it
competes with the least traffic.

Sequence per repeater
~~~~~~~~~~~~~~~~~~~~~
1. ``send_login_sync(pubkey, password)`` — same login as the statistics
   poller; the CLI is only available inside a session.
2. Per setting: ``send_cmd(pubkey, command)`` followed by waiting for the
   repeater's reply.  ``send_cmd`` returns as soon as the frame is on the
   wire and says nothing about the answer, so the reply is picked up from
   the event dispatcher.  The waiter is subscribed *before* the command
   goes out, because the reply can arrive before the send call returns.
3. ``send_logout(pubkey)`` — always, including after a failed or
   incomplete round of queries.

Replies
~~~~~~~
A repeater answers a CLI command with a direct message carrying text type
``REPEATER_CONFIG_REPLY_TXT_TYPE`` (``CLI_DATA``), which is what
distinguishes it from an ordinary DM.  The reply is free-form text: it may
echo the setting name, may prefix it with a marker, or may hold the bare
value.  Everything after the last colon is taken as the value and the
result is stored as text — no conversion to numbers, since a value such
as the region is not numeric to begin with.

A setting that goes unanswered within ``REPEATER_CONFIG_REPLY_TIMEOUT``
is listed under ``missing`` in the record and the next setting is tried.
One silent setting therefore does not cost the other nine.

Scheduling
~~~~~~~~~~
A repeater is due when it was not read today and the local clock is
inside the window that starts at ``REPEATER_CONFIG_POLL_HOUR`` and runs
for ``REPEATER_CONFIG_POLL_WINDOW_HOURS``.  A repeater that has never
been read is due immediately, so a fresh installation shows values
without waiting for the first night.  The last read moment comes from the
archive, so a restart does not trigger a new round.

A failed read also counts as read for that day.  Retrying an unreachable
repeater every ten seconds until sunrise would spend a whole night of
airtime on a repeater that is off; the next window is soon enough.

Only one repeater is handled per call, like the statistics poller, so two
repeaters are never queried back to back.

Cancellation
~~~~~~~~~~~~
Runs as a task the worker cancels the moment there is traffic to send.  A
cancelled run writes no record and is not marked as read, so it is
retried as soon as the queue is empty.  The logout still goes out, within
the bound the worker applies to the cleanup.

The poller never logs, returns or stores the password.

                   Author: PE1HVH
  SPDX-License-Identifier: MIT
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from meshcore import EventType

from meshcore_gui.config import (
    REPEATER_CONFIG_POLL_HOUR,
    REPEATER_CONFIG_POLL_KEYS,
    REPEATER_CONFIG_POLL_WINDOW_HOURS,
    REPEATER_CONFIG_REPLY_TIMEOUT,
    REPEATER_CONFIG_REPLY_TXT_TYPE,
    REPEATER_LOGIN_TIMEOUT,
    debug_print,
)
from meshcore_gui.services.repeater_config_archive import RepeaterConfigArchive
from meshcore_gui.services.repeater_config_store import (
    RepeaterConfigStore,
    RepeaterInfo,
)

#: Advertisement type of a repeater, as the firmware numbers them.
#: Passed to ``send_cmd`` so the frame is built as CLI data for a
#: repeater instead of a plain chat message.  Passing it explicitly also
#: avoids the library looking the type up in a contact dict, which is not
#: what the poller has: it works from the configured public key.
ADV_TYPE_REPEATER = 0x02

#: Number of hex characters the firmware uses as the sender prefix in an
#: incoming message: six bytes.
PUBKEY_PREFIX_CHARS = 12


class RepeaterConfigPoller:
    """Reads repeater settings once a day over the repeater CLI.

    Args:
        config_store: Source of repeaters, intervals and passwords.
        archive:      Destination for every configuration read.
    """

    def __init__(
        self,
        config_store: RepeaterConfigStore,
        archive: RepeaterConfigArchive,
    ) -> None:
        self._config = config_store
        self._archive = archive

        # Local date on which each repeater was last read.  Seeded from
        # the archive so a restart does not repeat today's round.
        self._last_read: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_due(self, mc) -> bool:
        """Read the settings of at most one repeater that is due.

        Safe to call on every main-loop tick; it returns immediately when
        nothing is due.  A failure on one repeater is recorded and does
        not affect the other.

        Args:
            mc: Connected ``MeshCore`` instance.

        Returns:
            True when a repeater was handled, False when nothing was due.

        Raises:
            asyncio.CancelledError: When the caller cancels the run.
        """
        if mc is None:
            return False

        repeaters = self._config.get_enabled_repeaters()
        if not repeaters:
            return False

        now = datetime.now()
        for info in repeaters:
            if not self._is_due(info.pubkey, now):
                continue

            label = info.name or info.pubkey[:16]
            try:
                await self._read_one(mc, info, label)
            except asyncio.CancelledError:
                # Traffic took priority.  The day is deliberately not
                # marked as read, so the round is retried once the queue
                # is empty again.
                debug_print(
                    f"RepeaterConfigPoller: read of {label} cancelled — "
                    "will retry"
                )
                raise

            # Success or failure, this repeater has had its turn today.
            self._last_read[info.pubkey] = now.date()
            return True

        return False

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _is_due(self, pubkey: str, now: datetime) -> bool:
        """Check whether a repeater should be read at this moment.

        Args:
            pubkey: Full public key of the repeater.
            now:    Current local time.

        Returns:
            True when the repeater is due.
        """
        last = self._last_read.get(pubkey)
        if last is None:
            last = self._last_read_from_archive(pubkey)
            if last is not None:
                self._last_read[pubkey] = last

        if last is None:
            # Never read: fetch at the first opportunity rather than
            # leaving the panel empty until the next night.
            return True

        if last == now.date():
            return False

        window = max(1, int(REPEATER_CONFIG_POLL_WINDOW_HOURS))
        hours = {(int(REPEATER_CONFIG_POLL_HOUR) + offset) % 24
                 for offset in range(window)}
        return now.hour in hours

    def _last_read_from_archive(self, pubkey: str):
        """Return the local date of the last archived read, if any.

        Args:
            pubkey: Full public key of the repeater.

        Returns:
            ``datetime.date`` of the last read, or ``None`` when the
            repeater has no record or its timestamp is unusable.
        """
        record = self._archive.get_latest(pubkey)
        if not record:
            return None
        try:
            return datetime.fromisoformat(
                record["polled_at"]
            ).astimezone().date()
        except (KeyError, TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def _read_one(self, mc, info: RepeaterInfo, label: str) -> None:
        """Run one complete session against a repeater.

        Logs in, queries every configured setting and always logs out
        again.  Writes exactly one archive record.

        Args:
            mc:    Connected ``MeshCore`` instance.
            info:  Repeater to read.
            label: Display label used in debug output.
        """
        password = self._config.get_password(info.pubkey)
        if password is None:
            self._archive.add_reading(
                info.pubkey,
                info.name,
                error="no_password_configured",
            )
            return

        login_attempted = False
        try:
            debug_print(f"RepeaterConfigPoller: login → {label}")
            login_attempted = True
            login_event = await mc.commands.send_login_sync(
                info.pubkey,
                password,
                min_timeout=REPEATER_LOGIN_TIMEOUT,
            )

            if login_event is None:
                debug_print(
                    f"RepeaterConfigPoller: no login confirmation from {label}"
                )
                self._archive.add_reading(
                    info.pubkey,
                    info.name,
                    error="login_failed_or_timeout",
                )
                return

            values, missing = await self._query_all(mc, info, label)

            if not values:
                self._archive.add_reading(
                    info.pubkey,
                    info.name,
                    error="no_cli_replies",
                    missing=missing,
                )
                return

            self._archive.add_reading(
                info.pubkey,
                info.name,
                config=values,
                missing=missing,
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one repeater must not stop the loop
            debug_print(f"RepeaterConfigPoller: {label} failed: {exc}")
            self._archive.add_reading(
                info.pubkey,
                info.name,
                error=f"exception: {type(exc).__name__}",
            )
        finally:
            if login_attempted:
                await self._logout(mc, info.pubkey, label)

    async def _query_all(
        self,
        mc,
        info: RepeaterInfo,
        label: str,
    ) -> Tuple[Dict[str, str], List[str]]:
        """Query every configured setting within an open session.

        Args:
            mc:    Connected ``MeshCore`` instance.
            info:  Repeater being read.
            label: Display label used in debug output.

        Returns:
            Tuple of the answered settings and the names of the settings
            that stayed silent.
        """
        values: Dict[str, str] = {}
        missing: List[str] = []

        for command in REPEATER_CONFIG_POLL_KEYS:
            name = _setting_name(command)
            reply = await self._query_one(mc, info.pubkey, command, label)

            if reply is None:
                debug_print(
                    f"RepeaterConfigPoller: no reply for '{command}' "
                    f"from {label}"
                )
                missing.append(name)
                continue

            values[name] = _parse_value(reply)

        return values, missing

    async def _query_one(
        self,
        mc,
        pubkey: str,
        command: str,
        label: str,
    ) -> Optional[str]:
        """Send one CLI command and wait for its reply.

        The waiter is created before the command is sent: the reply can
        arrive while ``send_cmd`` is still returning, and an event that
        nobody is waiting for yet is gone.

        Args:
            mc:      Connected ``MeshCore`` instance.
            pubkey:  Full public key of the repeater.
            command: CLI command to send, as configured.
            label:   Display label used in debug output.

        Returns:
            The reply text, or ``None`` on timeout or send failure.
        """
        waiter = asyncio.ensure_future(
            mc.dispatcher.wait_for_event(
                EventType.CONTACT_MSG_RECV,
                attribute_filters={
                    "pubkey_prefix": pubkey[:PUBKEY_PREFIX_CHARS].lower(),
                    "txt_type": REPEATER_CONFIG_REPLY_TXT_TYPE,
                },
                timeout=REPEATER_CONFIG_REPLY_TIMEOUT,
            )
        )
        # Give the waiter one loop iteration to register its subscription
        # before the command goes out.
        await asyncio.sleep(0)

        try:
            debug_print(f"RepeaterConfigPoller: '{command}' → {label}")
            await mc.commands.send_cmd(
                pubkey,
                command,
                dst_type=ADV_TYPE_REPEATER,
            )
            event = await waiter
        except asyncio.CancelledError:
            waiter.cancel()
            raise
        except Exception as exc:  # noqa: BLE001 — one setting must not stop the round
            waiter.cancel()
            debug_print(
                f"RepeaterConfigPoller: send of '{command}' to {label} "
                f"failed: {exc}"
            )
            return None

        if event is None:
            return None
        return str((event.payload or {}).get("text", ""))

    async def _logout(self, mc, pubkey: str, label: str) -> None:
        """Close the session, ignoring any failure.

        Args:
            mc:     Connected ``MeshCore`` instance.
            pubkey: Full public key of the repeater.
            label:  Display label used in debug output.
        """
        try:
            await mc.commands.send_logout(pubkey)
            debug_print(f"RepeaterConfigPoller: logout → {label}")
        except Exception as exc:  # noqa: BLE001 — logout is best-effort
            debug_print(f"RepeaterConfigPoller: logout failed for {label}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setting_name(command: str) -> str:
    """Return the archive key for a CLI command.

    ``"get flood.max"`` becomes ``"flood.max"``; a command without the
    ``get`` verb, such as ``"region"``, is its own name.

    Args:
        command: CLI command as configured.

    Returns:
        Name the value is stored under.
    """
    command = command.strip()
    if command.lower().startswith("get "):
        return command[4:].strip()
    return command


def _parse_value(reply: str) -> str:
    """Return the value out of a CLI reply.

    A repeater answers a ``get`` with the setting echoed in front of the
    value, separated by ``=``.  A leading prompt marker and a colon
    separator are handled too, so a firmware that formats its replies
    differently still yields a usable value.  Everything after the last
    separator is the value; a reply without one is used as-is.  The
    result stays text, because not every setting is numeric.

    Args:
        reply: Raw reply text from the repeater.

    Returns:
        The value, stripped of surrounding whitespace.
    """
    text = (reply or "").strip().lstrip(">").strip()

    # Only the first line carries the echoed setting name; a reply such
    # as the region list continues on the lines below it.  Splitting on
    # the first separator of that first line therefore keeps a multi-line
    # value whole, newlines included, and keeps a value that contains a
    # separator itself (a clock time, say) intact.
    head = text.split("\n", 1)[0]
    cuts = [head.find(separator) for separator in ("=", ":")
            if separator in head]
    if cuts:
        return text[min(cuts) + 1:].strip()
    return text
