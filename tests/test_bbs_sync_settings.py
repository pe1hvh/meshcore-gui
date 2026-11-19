"""Tests for the BBS sync settings per board (v1.27.0).

The parameters that tune the ``!x`` sync and the delivery of BBS replies
are board settings instead of code constants: ``sync_limit``,
``dm_max_attempts``, ``dm_flood_after``, ``dm_flood_min_wait`` and
``dm_wait_factor``.  ``!h x`` announces the four delivery values to an
app.

Structure:

1. Fixtures: an isolated BBS directory, config store, service and handler.
2. Config: defaults, validation, round trip, ``configure_board``.
3. Command handler: ``sync_limit``, ``!h x``, ``delivery_settings``.
4. Delivery: per-reply settings in ``EventHandler`` and ``CommandHandler``.

All data is invented test data.
"""

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterator, List, Tuple

import pytest

from meshcore import EventType

from meshcore_gui.ble import commands
from meshcore_gui.ble.commands import CommandHandler, _DmDelivery
from meshcore_gui.ble.events import EventHandler
from meshcore_gui.config import (
    DM_FLOOD_AFTER,
    DM_FLOOD_MIN_WAIT,
    DM_MAX_ATTEMPTS,
    DM_WAIT_FACTOR,
)
from meshcore_gui.services import bbs_config_store, bbs_service
from meshcore_gui.services.bbs_config_store import (
    DEFAULT_SYNC_LIMIT,
    SYNC_SETTINGS,
    BbsBoard,
    BbsConfigStore,
    clean_sync_setting,
)
from meshcore_gui.services.bbs_service import (
    HELP_SETTINGS_TAG,
    BbsCommandHandler,
    BbsMessage,
    BbsService,
)
from meshcore_gui.services.dedup import DualDeduplicator

KEY_A: str = "AA" * 32
"""Invented public key of the whitelisted test sender."""

SENDER_PREFIX: str = "aaaaaaaaaaaa"
"""12-hex-character prefix of :data:`KEY_A`, as in ``CONTACT_MSG_RECV``."""

# ===========================================================================
# 1. Fixtures
# ===========================================================================


@pytest.fixture(name="env")
def fixture_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[
        Tuple[BbsConfigStore, BbsService, BbsCommandHandler]]:
    """Create a board on channel 1 with category STATUS; KEY_A whitelisted.

    Args:
        tmp_path:    Per-test temporary directory from pytest.
        monkeypatch: Pytest fixture used to replace ``BBS_DIR``.

    Yields:
        Tuple of (config store, service, command handler).
    """
    monkeypatch.setattr(bbs_service, "BBS_DIR", tmp_path)
    monkeypatch.setattr(bbs_config_store, "BBS_DIR", tmp_path)
    store = BbsConfigStore(tmp_path / "bbs_config.json")
    store.configure_board(
        channel_indices=[1], channel_names={1: "Test"},
        categories=["STATUS"], allowed_keys=[KEY_A],
    )
    service = BbsService(tmp_path / "bbs_messages.db")
    yield store, service, BbsCommandHandler(service, store)


def _post(service: BbsService, text: str) -> int:
    """Insert a STATUS message on channel 1.

    Args:
        service: Service to write to.
        text:    Message body.

    Returns:
        Row id of the new message.
    """
    return service.post_message(BbsMessage(
        channel=1, region="", category="STATUS", sender="Tester",
        sender_key=KEY_A, text=text,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))


def _set(store: BbsConfigStore, **settings) -> None:
    """Save the test board again with the given sync settings.

    Args:
        store:      Config store of the fixture.
        **settings: Sync settings by name.
    """
    store.configure_board(
        channel_indices=[1], channel_names={1: "Test"},
        categories=["STATUS"], sync_settings=settings,
    )

# ===========================================================================
# 2. Config
# ===========================================================================


def test_defaults_equal_the_former_constants() -> None:
    """A board without sync keys gets the values used before v1.27.0."""
    board = BbsBoard.from_dict({"id": "b", "name": "B"})
    assert (board.sync_limit, board.dm_max_attempts, board.dm_flood_after,
            board.dm_flood_min_wait, board.dm_wait_factor) == (
        DEFAULT_SYNC_LIMIT, DM_MAX_ATTEMPTS, DM_FLOOD_AFTER,
        DM_FLOOD_MIN_WAIT, DM_WAIT_FACTOR)
    assert BbsCommandHandler.SYNC_LIMIT == DEFAULT_SYNC_LIMIT == 10


@pytest.mark.parametrize("name, value, expected", [
    ("sync_limit", 25, 25),
    ("sync_limit", "15", 15),
    ("sync_limit", 0, DEFAULT_SYNC_LIMIT),
    ("sync_limit", 51, DEFAULT_SYNC_LIMIT),
    ("sync_limit", 2.5, DEFAULT_SYNC_LIMIT),
    ("dm_max_attempts", True, DM_MAX_ATTEMPTS),
    ("dm_max_attempts", None, DM_MAX_ATTEMPTS),
    ("dm_flood_min_wait", "45", 45.0),
    ("dm_flood_min_wait", "nan", DM_FLOOD_MIN_WAIT),
    ("dm_wait_factor", 1.5, 1.5),
    ("dm_wait_factor", 0.5, DM_WAIT_FACTOR),
])
def test_clean_sync_setting(name: str, value: object, expected: float) -> None:
    """Valid values are kept, anything else falls back to the default.

    Args:
        name:     Setting name.
        value:    Value as read from the file or the panel.
        expected: Value after cleaning.
    """
    assert clean_sync_setting(name, value) == expected


def test_round_trip_through_dict() -> None:
    """``to_dict`` writes every sync setting; ``from_dict`` reads it back."""
    board = BbsBoard(id="b", name="B", sync_limit=20, dm_max_attempts=4,
                     dm_flood_after=1, dm_flood_min_wait=40.0, dm_wait_factor=1.5)
    data = board.to_dict()
    assert {key: data[key] for key in SYNC_SETTINGS} == {
        "sync_limit": 20, "dm_max_attempts": 4, "dm_flood_after": 1,
        "dm_flood_min_wait": 40.0, "dm_wait_factor": 1.5}
    again = BbsBoard.from_dict(data)
    assert {key: getattr(again, key) for key in SYNC_SETTINGS} == {
        key: getattr(board, key) for key in SYNC_SETTINGS}


def test_configure_board_keeps_sync_settings(env) -> None:
    """Saving the board without sync settings keeps the stored values.

    Args:
        env: Store, service and handler fixture.
    """
    store, _, _ = env
    _set(store, sync_limit=7, dm_max_attempts=5)
    store.configure_board(channel_indices=[1], channel_names={1: "Test"},
                          categories=["STATUS", "URGENT"])
    board = store.get_single_board()
    assert (board.sync_limit, board.dm_max_attempts) == (7, 5)
    assert board.dm_flood_after == DM_FLOOD_AFTER


def test_change_on_disk_applies_without_restart(env) -> None:
    """A value edited in the config file is used by the next request.

    Args:
        env: Store, service and handler fixture.
    """
    store, _, handler = env
    path = Path(store._path)  # pylint: disable=protected-access
    data = json.loads(path.read_text(encoding="utf-8"))
    data["boards"][0]["dm_max_attempts"] = 6
    path.write_text(json.dumps(data), encoding="utf-8")
    assert handler.delivery_settings()["max_attempts"] == 6

# ===========================================================================
# 3. Command handler
# ===========================================================================


def test_sync_uses_board_limit(env) -> None:
    """``!x`` returns at most ``sync_limit`` records with ``more`` = 1.

    Args:
        env: Store, service and handler fixture.
    """
    store, service, handler = env
    _set(store, sync_limit=3)
    ids = [_post(service, f"m{i}") for i in range(5)]
    lines = handler.handle_dm("Tester", KEY_A, "!x").splitlines()
    assert lines[0].split("|")[2:4] == ["3", "1"]
    assert [int(line.split("|")[0]) for line in lines[2:]] == ids[:3]


@pytest.mark.parametrize("command", ["!h x", "!help x", "!H X"])
def test_help_x_announces_settings(env, command: str) -> None:
    """``!h x`` puts the delivery settings on the third line (any case).

    Args:
        env:     Store, service and handler fixture.
        command: Help command with the ``x`` argument.
    """
    store, _, handler = env
    _set(store, dm_max_attempts=4, dm_flood_after=1, dm_flood_min_wait=45,
         dm_wait_factor=1.5)
    lines = handler.handle_dm("Tester", KEY_A, command).splitlines()
    assert lines[0] == "BBS"
    assert lines[2] == "X|a=4,f=1,w=45,k=1.5"
    assert lines[-1] == handler.handle_dm("Tester", KEY_A, "!h").splitlines()[-1]


def test_plain_help_unchanged(env) -> None:
    """``!h`` without ``x`` has no settings line.

    Args:
        env: Store, service and handler fixture.
    """
    _, _, handler = env
    reply = handler.handle_dm("Tester", KEY_A, "!h")
    assert HELP_SETTINGS_TAG not in reply
    assert reply.splitlines()[0] == "BBS"


def test_default_settings_line(env) -> None:
    """With default settings the line shows the former constants.

    Args:
        env: Store, service and handler fixture.
    """
    _, _, handler = env
    lines = handler.handle_dm("Tester", KEY_A, "!h x").splitlines()
    assert lines[2] == "X|a=3,f=2,w=30,k=1.2"


def test_delivery_settings_without_board(tmp_path: Path) -> None:
    """Without a board the ``config.py`` defaults apply.

    Args:
        tmp_path: Per-test temporary directory from pytest.
    """
    handler = BbsCommandHandler(BbsService(tmp_path / "db.sqlite"),
                                BbsConfigStore(tmp_path / "bbs_config.json"))
    assert handler.delivery_settings() == {
        "max_attempts": DM_MAX_ATTEMPTS, "flood_after": DM_FLOOD_AFTER,
        "flood_min_wait": DM_FLOOD_MIN_WAIT, "wait_factor": DM_WAIT_FACTOR}

# ===========================================================================
# 4. Delivery
# ===========================================================================


class _Shared:
    """Stand-in for SharedDataWriter: ignores messages, names every node."""

    def add_message(self, msg) -> None:
        """Ignore a message.

        Args:
            msg: Message the handler stores.
        """
        del msg

    def get_contact_name_by_prefix(self, prefix: str) -> str:
        """Return a fixed contact name.

        Args:
            prefix: Public key prefix to look up.

        Returns:
            ``"Tester"``.
        """
        del prefix
        return "Tester"


def test_bbs_reply_carries_board_settings(env) -> None:
    """The ``send_dm`` command of a BBS reply holds the board settings.

    Args:
        env: Store, service and handler fixture.
    """
    store, _, handler = env
    _set(store, dm_max_attempts=5, dm_wait_factor=2.0)
    sent: List[Dict] = []
    events = EventHandler(shared=_Shared(), decoder=None, dedup=DualDeduplicator(),
                          bot=None, bbs_handler=handler, command_sink=sent.append)
    events.on_contact_msg(SimpleNamespace(payload={
        "type": "PRIV", "pubkey_prefix": SENDER_PREFIX, "path_len": 255,
        "txt_type": 0, "text": "!h", "sender_timestamp": 1_700_000_000,
    }))
    assert len(sent) == 1
    assert sent[0]["max_attempts"] == 5
    assert sent[0]["wait_factor"] == 2.0
    assert sent[0]["flood_after"] == DM_FLOOD_AFTER


class _Commands:  # pylint: disable=too-few-public-methods
    """Stand-in for ``MeshCore.commands``: every send is a direct DM."""

    def __init__(self) -> None:
        """Start without sends."""
        self.sent: List[int] = []
        """Attempt number of every ``send_msg`` call."""

    async def send_msg(self, pubkey: str, text: str, timestamp: int,
                       attempt: int) -> SimpleNamespace:
        """Record the attempt and return a MSG_SENT event (direct, 10 s).

        Args:
            pubkey:    Recipient key.
            text:      Part text.
            timestamp: Sender timestamp.
            attempt:   Attempt number (0-based).

        Returns:
            Event with ``type`` 0, an ACK code and a 10000 ms timeout.
        """
        del pubkey, text, timestamp
        self.sent.append(attempt)
        return SimpleNamespace(type=EventType.MSG_SENT, payload={
            "type": 0, "expected_ack": b"\x01\x02\x03\x04",
            "suggested_timeout": 10000})


def test_delivery_follows_its_own_settings(monkeypatch) -> None:
    """``max_attempts`` and ``wait_factor`` from the command are used.

    One attempt with factor 2.0: the part waits 20 s, then the reply is
    given up without a second attempt.

    Args:
        monkeypatch: Pytest fixture to replace the clock and the log.
    """
    now = [100.0]
    monkeypatch.setattr(commands.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(commands, "debug_print", lambda msg: None)
    fake = _Commands()
    handler = CommandHandler.__new__(CommandHandler)
    # pylint: disable=protected-access  # test sets up private state directly
    handler._mc = SimpleNamespace(commands=fake)
    handler._shared = _Shared()
    handler._dm_queues = {}
    asyncio.run(handler._cmd_send_dm({
        "pubkey": SENDER_PREFIX, "text": "reply", "max_attempts": 1,
        "wait_factor": 2.0}))
    asyncio.run(handler.process_dm_deliveries())
    delivery: _DmDelivery = handler._dm_queues[SENDER_PREFIX][0]
    assert delivery.deadline == pytest.approx(120.0)
    now[0] = 121.0
    asyncio.run(handler.process_dm_deliveries())
    assert fake.sent == [0]
    assert handler._dm_queues[SENDER_PREFIX] == deque()


def test_other_dms_keep_defaults() -> None:
    """A ``send_dm`` without settings uses the ``config.py`` defaults."""
    handler = CommandHandler.__new__(CommandHandler)
    # pylint: disable=protected-access  # test sets up private state directly
    handler._shared = _Shared()
    handler._dm_queues = {}
    asyncio.run(handler._cmd_send_dm({"pubkey": SENDER_PREFIX, "text": "hi"}))
    delivery = handler._dm_queues[SENDER_PREFIX][0]
    assert (delivery.max_attempts, delivery.flood_after, delivery.flood_min_wait,
            delivery.wait_factor) == (DM_MAX_ATTEMPTS, DM_FLOOD_AFTER,
                                      DM_FLOOD_MIN_WAIT, DM_WAIT_FACTOR)


def test_settings_page_collect_sync() -> None:
    """The settings page accepts valid fields and refuses others."""
    # Imported here: the panel module needs NiceGUI.
    from meshcore_gui.gui.panels.bbs_panel import (  # pylint: disable=import-outside-toplevel
        BbsSettingsPage,
    )
    good = {"sync_limit": SimpleNamespace(value=15.0),
            "dm_wait_factor": SimpleNamespace(value=1.5)}
    assert BbsSettingsPage._collect_sync(good) == {  # pylint: disable=protected-access
        "sync_limit": 15, "dm_wait_factor": 1.5}
    for bad in (None, 0, 2.5, 99):
        fields = {"sync_limit": SimpleNamespace(value=bad)}
        assert BbsSettingsPage._collect_sync(fields) is None  # pylint: disable=protected-access
