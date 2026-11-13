"""Tests for BBS retention per category and the ``!x`` sync command (v1.26.0).

Structure:

1. Fixtures: an isolated BBS directory, config store, service and handler.
2. Config: retention helpers, migration and ``configure_board``.
3. Service: purge per category, operator deletions, epoch.
4. Command handler: ``!x`` reply format and the ``!p`` id confirmation.

All data is invented test data.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

from meshcore_gui.services import bbs_config_store, bbs_service
from meshcore_gui.services.bbs_config_store import (
    DEFAULT_RETENTION_DAYS,
    KEEP_FOREVER_HOURS,
    BbsBoard,
    BbsConfigStore,
    hours_to_days,
    legacy_retention_hours,
)
from meshcore_gui.ble.commands import CommandHandler
from meshcore_gui.services.bbs_service import (
    SYNC_LINE_MAX_BYTES,
    BbsCommandHandler,
    BbsMessage,
    BbsService,
)

KEY_A: str = "AA" * 32
"""Invented public key of a whitelisted test sender."""

KEY_B: str = "BB" * 32
"""Invented public key of a sender that is not whitelisted."""


# ===========================================================================
# 1. Fixtures
# ===========================================================================

@pytest.fixture(name="bbs_dir")
def fixture_bbs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point both BBS modules at an empty temporary directory.

    Args:
        tmp_path:    Per-test temporary directory from pytest.
        monkeypatch: Pytest fixture used to replace ``BBS_DIR``.

    Returns:
        The temporary BBS directory.
    """
    monkeypatch.setattr(bbs_service, "BBS_DIR", tmp_path)
    monkeypatch.setattr(bbs_config_store, "BBS_DIR", tmp_path)
    return tmp_path


@pytest.fixture(name="env")
def fixture_env(bbs_dir: Path) -> Iterator[Tuple[BbsConfigStore, BbsService, BbsCommandHandler]]:
    """Create a configured board with categories ADDRESSES, URGENT, STATUS.

    Retention: ADDRESSES 0 (forever), STATUS 30 days, URGENT and other
    categories 90 days.  ``KEY_A`` is the only whitelisted key.

    Args:
        bbs_dir: Isolated BBS directory.

    Yields:
        Tuple of (config store, service, command handler).
    """
    store = BbsConfigStore(bbs_dir / "bbs_config.json")
    store.configure_board(
        channel_indices=[1],
        channel_names={1: "Test"},
        categories=["ADDRESSES", "URGENT", "STATUS"],
        allowed_keys=[KEY_A],
        default_retention_days=90,
        category_retention_days={"ADDRESSES": 0, "STATUS": 30},
    )
    service = BbsService(bbs_dir / "bbs_messages.db")
    yield store, service, BbsCommandHandler(service, store)


def _post(service: BbsService, category: str, age_days: float, text: str = "t") -> int:
    """Insert a message on channel 1 with a given age.

    Args:
        service:  Service to write to.
        category: Category name as stored.
        age_days: Age of the message in days.
        text:     Message body.

    Returns:
        Row id of the new message.
    """
    stamp = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return service.post_message(BbsMessage(
        channel=1, region="", category=category, sender="Tester",
        sender_key=KEY_A, text=text, timestamp=stamp,
    ))


def _sync(handler: BbsCommandHandler, args: str = "") -> List[str]:
    """Run ``!x`` as the whitelisted sender and return the reply lines.

    Args:
        handler: Command handler under test.
        args:    Arguments after ``!x``.

    Returns:
        Reply split into lines.
    """
    reply = handler.handle_dm("Tester", KEY_A, f"!x {args}".strip())
    assert reply is not None
    return reply.splitlines()


# ===========================================================================
# 2. Config
# ===========================================================================

@pytest.mark.parametrize(
    ("hours", "days"),
    [(48, 2), (2160, 90), (1, 1), (25, 2), (0, DEFAULT_RETENTION_DAYS),
     ("x", DEFAULT_RETENTION_DAYS)],
)
def test_hours_to_days_rounds_up(hours: object, days: int) -> None:
    """Legacy hours become whole days, rounded up; invalid gives the default.

    Args:
        hours: Legacy ``retention_hours`` value.
        days:  Expected days.
    """
    assert hours_to_days(hours) == days


def test_legacy_hours_is_longest_period() -> None:
    """Older versions get the longest period, or 100 years for *forever*."""
    assert legacy_retention_hours(30, {"A": 90}) == 90 * 24
    assert legacy_retention_hours(90, {"A": 0}) == KEEP_FOREVER_HOURS
    assert legacy_retention_hours(0, {}) == KEEP_FOREVER_HOURS


def test_old_config_is_migrated() -> None:
    """A board dict without day fields gets its default from retention_hours."""
    board = BbsBoard.from_dict({
        "id": "bbs_board", "name": "Test", "channels": [1],
        "categories": ["URGENT"], "retention_hours": 2160,
    })
    assert board.default_retention_days == 90
    assert board.category_retention_days == {}
    assert board.retention_days_for("urgent") == 90


def test_round_trip_and_lookup() -> None:
    """Day fields survive to_dict/from_dict; lookup is case-insensitive."""
    board = BbsBoard(
        id="b", name="n", channels=[1], categories=["ADDRESSES", "STATUS"],
        default_retention_days=60, category_retention_days={"ADDRESSES": 0},
    )
    again = BbsBoard.from_dict(board.to_dict())
    assert again.retention_days_for("addresses") == 0
    assert again.retention_days_for("STATUS") == 60
    assert again.retention_days_for("UNLISTED") == 60
    assert board.to_dict()["retention_hours"] == KEEP_FOREVER_HOURS


def test_entry_of_removed_category_is_not_used() -> None:
    """An entry for a category that is no longer listed falls back to the default."""
    board = BbsBoard(
        id="b", name="n", categories=["URGENT"],
        default_retention_days=7, category_retention_days={"OLD": 0},
    )
    assert board.retention_days_for("OLD") == 7


def test_configure_board_filters_and_normalises(bbs_dir: Path) -> None:
    """Only listed categories keep an entry; keys upper case; bad values → default.

    Args:
        bbs_dir: Isolated BBS directory.
    """
    store = BbsConfigStore(bbs_dir / "bbs_config.json")
    store.configure_board(
        [1], {1: "Test"}, ["URGENT", "STATUS"],
        default_retention_days=45,
        category_retention_days={"urgent": 10, "STATUS": -3, "GONE": 5},
    )
    board = store.get_single_board()
    assert board is not None
    assert board.category_retention_days == {"URGENT": 10, "STATUS": 45}
    assert board.default_retention_days == 45


def test_configure_board_without_days_uses_hours(bbs_dir: Path) -> None:
    """Callers that only pass retention_hours keep working.

    Args:
        bbs_dir: Isolated BBS directory.
    """
    store = BbsConfigStore(bbs_dir / "bbs_config.json")
    store.configure_board([1], {1: "Test"}, ["URGENT"], retention_hours=48)
    board = store.get_single_board()
    assert board is not None and board.default_retention_days == 2


# ===========================================================================
# 3. Service
# ===========================================================================

def test_purge_per_category(env) -> None:
    """Each category uses its own period; 0 keeps forever; unlisted uses default.

    Args:
        env: Store, service and handler fixture.
    """
    store, service, _ = env
    keep = [
        _post(service, "ADDRESSES", 400),
        _post(service, "STATUS", 20),
        _post(service, "urgent", 80),
        _post(service, "OLDCAT", 50),
    ]
    gone = [
        _post(service, "STATUS", 40),
        _post(service, "URGENT", 100),
        _post(service, "OLDCAT", 100),
    ]
    board = store.get_single_board()
    assert service.purge_board(board) == len(gone)
    left = {m.id for m in service.get_all_messages([1])}
    assert left == set(keep)


def test_purge_default_zero_keeps_unlisted(bbs_dir: Path) -> None:
    """With a default of 0, messages in unlisted categories are kept.

    Args:
        bbs_dir: Isolated BBS directory.
    """
    service = BbsService(bbs_dir / "db.sqlite")
    msg_id = _post(service, "OLDCAT", 1000)
    board = BbsBoard(id="b", name="n", channels=[1], categories=["URGENT"],
                     default_retention_days=0)
    assert service.purge_board(board) == 0
    assert [m.id for m in service.get_all_messages([1])] == [msg_id]


def test_delete_is_recorded_purge_is_not(env) -> None:
    """Operator deletions get a sequence number; purged messages do not.

    Args:
        env: Store, service and handler fixture.
    """
    store, service, _ = env
    first = _post(service, "URGENT", 1)
    _post(service, "URGENT", 200)
    assert service.delete_message(first)
    assert not service.delete_message(first)
    service.purge_board(store.get_single_board())
    assert service.get_deletions_since(0) == ([first], 1)
    assert service.get_deletions_since(1) == ([], 1)


def test_epoch_is_stable(bbs_dir: Path) -> None:
    """The epoch is written once and survives re-opening the database.

    Args:
        bbs_dir: Isolated BBS directory.
    """
    path = bbs_dir / "db.sqlite"
    epoch = BbsService(path).get_epoch()
    assert epoch.isdigit() and int(epoch) > 0
    assert BbsService(path).get_epoch() == epoch


# ===========================================================================
# 4. Command handler
# ===========================================================================

def test_sync_header_retention_and_record(env) -> None:
    """Header, R line and record fields follow the documented format.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    msg_id = _post(service, "URGENT", 0, text="water | food\nneeded")
    lines = _sync(handler)
    assert lines[0] == f"X1|{service.get_epoch()}|1|0|0|0|2"
    assert lines[1] == "R|*:90,A:0,U:90,S:30"
    fields = lines[2].split("|", 5)
    assert fields[0] == str(msg_id)
    assert fields[2:5] == ["U", "", "Tester"]
    assert fields[5] == "water | food needed"
    assert len(lines) == 3


def test_sync_batches_and_cursor(env) -> None:
    """At most SYNC_LIMIT records, oldest first; ``more`` and since_id work.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    ids = [_post(service, "STATUS", 0, text=f"m{i}") for i in range(12)]
    lines = _sync(handler)
    header = lines[0].split("|")
    assert header[2:4] == [str(BbsCommandHandler.SYNC_LIMIT), "1"]
    got = [int(line.split("|")[0]) for line in lines[2:]]
    assert got == ids[:BbsCommandHandler.SYNC_LIMIT]
    lines = _sync(handler, str(got[-1]))
    assert lines[0].split("|")[2:4] == ["2", "0"]
    assert [int(line.split("|")[0]) for line in lines[2:]] == ids[10:]


def test_sync_long_record_uses_continuations(env) -> None:
    """A record over the byte limit continues on ``+<id>|`` lines.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    text = "é" * 150 + "x" * 40
    msg_id = _post(service, "ADDRESSES", 0, text=text)
    lines = _sync(handler)[2:]
    assert all(len(line.encode("utf-8")) <= SYNC_LINE_MAX_BYTES for line in lines)
    assert len(lines) > 1
    prefix = f"+{msg_id}|"
    assert all(line.startswith(prefix) for line in lines[1:])
    joined = lines[0] + "".join(line[len(prefix):] for line in lines[1:])
    assert joined.split("|", 5)[5] == text


def test_sync_header_counts_lines(env) -> None:
    """The last header field is the number of lines after the header.

    Covers continuation lines, ``R`` lines and ``-`` lines, so a client
    knows when a reply that spans several DMs is complete.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    _post(service, "STATUS", 0, text="é" * 200)
    for msg_id in [_post(service, "URGENT", 0) for _ in range(40)]:
        service.delete_message(msg_id)
    lines = _sync(handler)
    assert int(lines[0].split("|")[6]) == len(lines) - 1
    assert len(lines) - 1 > 3


@pytest.mark.parametrize("pad", [0, 1, 2, 3])
def test_sync_cut_never_ends_on_whitespace(env, pad: int) -> None:
    """A record cut next to spaces survives the DM sender's ``rstrip``.

    ``CommandHandler._split_reply`` strips trailing whitespace from every
    line, so the spaces at a cut must start the next ``+`` line instead.

    Args:
        env: Store, service and handler fixture.
        pad: Shift of the text, so the cut falls before, on and after spaces.
    """
    _, service, handler = env
    head = f"1|{int(datetime.now(timezone.utc).timestamp())}|S||Tester|"
    text = "x" * (SYNC_LINE_MAX_BYTES - len(head) - 2 + pad) + "  two spaces"
    _post(service, "STATUS", 0, text=text)
    reply = handler.handle_dm("Tester", KEY_A, "!x")
    # The real DM splitter is what strips the whitespace; it has no public
    # wrapper and needs no device, so it is called on a bare instance.
    chunks = CommandHandler.__new__(CommandHandler)._split_reply(  # pylint: disable=protected-access
        reply, max_bytes=SYNC_LINE_MAX_BYTES,
    )
    lines = "\n".join(chunks).splitlines()
    record = lines[2] + "".join(
        line.split("|", 1)[1] for line in lines[3:] if line.startswith("+1|")
    )
    assert record.split("|", 5)[5] == text


def test_sync_reports_deletions(env) -> None:
    """Deleted ids appear in ``-`` lines within the byte limit, with counts.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    ids = [_post(service, "URGENT", 0) for _ in range(60)]
    for msg_id in ids:
        service.delete_message(msg_id)
    lines = _sync(handler)
    header = lines[0].split("|")
    assert header[4:6] == ["60", "60"]
    minus = [line for line in lines if line.startswith("-")]
    assert len(minus) > 1
    assert all(len(line.encode("utf-8")) <= SYNC_LINE_MAX_BYTES for line in minus)
    reported = [int(i) for line in minus for i in line[1:].split(",")]
    assert reported == ids
    assert not [line for line in _sync(handler, f"{ids[-1]} 60") if line.startswith("-")]


def test_sync_unlisted_category_uses_full_name(env) -> None:
    """A message in a category that is no longer configured carries its name.

    Args:
        env: Store, service and handler fixture.
    """
    _, service, handler = env
    _post(service, "Oldcat", 0)
    assert _sync(handler)[2].split("|")[2] == "OLDCAT"


@pytest.mark.parametrize(
    "args", ["a", "1 2 3", "-1", "1 x", "\u00b2", "1 \u0663", "9223372036854775808"],
)
def test_sync_rejects_bad_arguments(env, args: str) -> None:
    """Arguments that are not up to two whole numbers give the usage line.

    Args:
        env:  Store, service and handler fixture.
        args: Invalid argument text.
    """
    _, _, handler = env
    assert _sync(handler, args) == ["Usage: !x <since_id> <since_del>"]


def test_sync_requires_whitelist(env) -> None:
    """A sender that is not whitelisted gets no reply.

    Args:
        env: Store, service and handler fixture.
    """
    _, _, handler = env
    assert handler.handle_dm("Other", KEY_B, "!x") is None


def test_post_reply_contains_id(env) -> None:
    """``!p`` and ``!bbs post`` confirm with the new message id.

    Args:
        env: Store, service and handler fixture.
    """
    _, _, handler = env
    assert handler.handle_dm("Tester", KEY_A, "!p U hello").startswith("Posted #1 [URGENT]")
    assert handler.handle_dm(
        "Tester", KEY_A, "!bbs post STATUS hi",
    ).startswith("Posted #2 [STATUS]")
