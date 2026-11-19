"""Regression tests: a flood DM part waits long enough for its ACK.

The companion firmware suggests a flood timeout of ``500 + 16 x airtime``
ms, independent of the number of hops.  On 18-11-2026 a reply part to a
node 4 hops away was sent as flood with a suggested timeout of 10788 ms;
``CommandHandler`` gave up after 10788 x 1.2 = 12.9 s and dropped the rest
of the reply, and the ACK of that very attempt arrived 15.7 s after
sending (``trip_time`` 15708 ms).  Since 1.26.5 a part that went out as
flood waits at least ``DM_FLOOD_MIN_WAIT`` seconds.

Structure:

1. Test doubles: a fake MeshCore and a controllable clock.
2. Deadlines: flood parts wait at least the minimum, direct parts not.
3. ACKs: a late flood ACK confirms the part; log lines show trip times.
"""

import asyncio
from collections import deque
from types import SimpleNamespace
from typing import Dict, List

import pytest

from meshcore import EventType

from meshcore_gui.ble import commands
from meshcore_gui.ble.commands import CommandHandler, _DmDelivery
from meshcore_gui.config import DM_FLOOD_MIN_WAIT

# ===========================================================================
# 1. Test doubles
# ===========================================================================

RECIPIENT = "a1b2c3d4e5f6"
"""Made-up 6-byte public key prefix (12 hex chars) of the DM recipient."""


class _FakeCommands:  # pylint: disable=too-few-public-methods
    """Stand-in for ``MeshCore.commands`` that answers every send with MSG_SENT."""

    def __init__(self, flood: bool, timeout_ms: int) -> None:
        """Set the answer of the firmware.

        Args:
            flood: True to report the DM as sent by flood (``type`` 1).
            timeout_ms: ``suggested_timeout`` to report, in milliseconds.
        """
        self.flood = flood
        """Reported send mode: True for flood, False for direct."""
        self.timeout_ms = timeout_ms
        """Reported ``suggested_timeout`` in milliseconds."""
        self.sent: List[int] = []
        """Attempt number of every ``send_msg`` call, in order."""

    async def send_msg(self, pubkey: str, text: str, timestamp: int,
                       attempt: int) -> SimpleNamespace:
        """Record the send and return a MSG_SENT event.

        Args:
            pubkey: Recipient key.
            text: Part text.
            timestamp: Sender timestamp of the part.
            attempt: Attempt number (0-based).

        Returns:
            Event with ``type``, ``expected_ack`` and ``suggested_timeout``.
        """
        del pubkey, text, timestamp
        self.sent.append(attempt)
        return SimpleNamespace(type=EventType.MSG_SENT, payload={
            "type": 1 if self.flood else 0,
            "expected_ack": bytes.fromhex(f"0102030{attempt}"),
            "suggested_timeout": self.timeout_ms,
        })


class _Clock:  # pylint: disable=too-few-public-methods
    """Replaces ``time.monotonic`` in the commands module."""

    def __init__(self) -> None:
        """Start at 1000 s."""
        self.now = 1000.0
        """Current monotonic time in seconds."""

    def monotonic(self) -> float:
        """Return the current time.

        Returns:
            :attr:`now`.
        """
        return self.now


def _handler(monkeypatch: pytest.MonkeyPatch, flood: bool,
             timeout_ms: int) -> Dict:
    """Build a CommandHandler with one queued two-part reply.

    Args:
        monkeypatch: Pytest fixture to patch the clock and ``debug_print``.
        flood: Send mode the fake firmware reports.
        timeout_ms: ``suggested_timeout`` the fake firmware reports.

    Returns:
        Dict with ``handler``, ``clock``, ``fake`` (commands double) and
        ``log`` (list of debug lines).
    """
    clock = _Clock()
    log: List[str] = []
    monkeypatch.setattr(commands.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(commands, "debug_print", log.append)
    fake = _FakeCommands(flood, timeout_ms)
    handler = CommandHandler.__new__(CommandHandler)
    # pylint: disable=protected-access  # test sets up private state directly
    handler._mc = SimpleNamespace(commands=fake)
    handler._dm_queues = {RECIPIENT: deque([_DmDelivery(
        pubkey=RECIPIENT, contact_name=RECIPIENT[:8], chunks=["one", "two"])])}
    return {"handler": handler, "clock": clock, "fake": fake, "log": log}


def _step(handler: CommandHandler) -> None:
    """Run one ``process_dm_deliveries`` step.

    Args:
        handler: Handler from :func:`_handler`.
    """
    asyncio.run(handler.process_dm_deliveries())


def _head(handler: CommandHandler) -> _DmDelivery:
    """Return the delivery at the head of the recipient's queue.

    Args:
        handler: Handler from :func:`_handler`.

    Returns:
        The first delivery to :data:`RECIPIENT`.
    """
    return handler._dm_queues[RECIPIENT][0]  # pylint: disable=protected-access

# ===========================================================================
# 2. Deadlines
# ===========================================================================


def test_flood_part_waits_at_least_the_minimum(monkeypatch) -> None:
    """Flood with a short suggested timeout waits ``DM_FLOOD_MIN_WAIT`` s.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=True, timeout_ms=10788)
    _step(env["handler"])
    assert _head(env["handler"]).deadline == pytest.approx(
        env["clock"].now + DM_FLOOD_MIN_WAIT)


def test_flood_part_keeps_a_longer_suggested_timeout(monkeypatch) -> None:
    """Flood with a suggested timeout above the minimum keeps timeout x 1.2.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=True, timeout_ms=40000)
    _step(env["handler"])
    assert _head(env["handler"]).deadline == pytest.approx(env["clock"].now + 48.0)


def test_direct_part_unchanged(monkeypatch) -> None:
    """A direct part waits suggested timeout x 1.2, as before 1.26.5.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=False, timeout_ms=10788)
    _step(env["handler"])
    assert _head(env["handler"]).deadline == pytest.approx(env["clock"].now + 12.9456)

# ===========================================================================
# 3. ACKs
# ===========================================================================


def test_late_flood_ack_confirms_the_part(monkeypatch) -> None:
    """The ACK 15.7 s after a flood send confirms the part; no resend before.

    Before 1.26.5 the part counted as not confirmed after 12.9 s.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=True, timeout_ms=10788)
    handler = env["handler"]
    _step(handler)
    env["clock"].now += 15.7
    _step(handler)
    assert env["fake"].sent == [0]
    handler.on_ack(SimpleNamespace(payload={"code": "01020300", "trip_time": 15708}))
    assert _head(handler).index == 1
    assert any("part 1/2 confirmed (trip 15708 ms)" in line for line in env["log"])


def test_sent_line_names_flood(monkeypatch) -> None:
    """The ``sent`` log line says when the part went out as flood.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=True, timeout_ms=10788)
    _step(env["handler"])
    assert any("attempt 1 sent (flood), ACK 01020300" in line for line in env["log"])


def test_unmatched_ack_is_logged(monkeypatch) -> None:
    """An ACK that confirms no waiting part is logged with its trip time.

    Args:
        monkeypatch: Pytest fixture.
    """
    env = _handler(monkeypatch, flood=False, timeout_ms=10788)
    env["handler"].on_ack(SimpleNamespace(payload={"code": "aabbccdd", "trip_time": 900}))
    assert env["log"] == ["ACK aabbccdd (trip 900 ms) matches no waiting DM part"]
