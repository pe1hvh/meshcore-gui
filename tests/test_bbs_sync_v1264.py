"""Tests for the compressed ``!x`` reply and replaceable sync replies (v1.26.4).

Structure:

1. Fixtures and helpers: an isolated BBS, test doubles for the DM path.
2. Compressed reply: ``!x <since_id> <since_del> z`` framing, header ``X2``
   and readable prefixes.
3. Replaceable replies: ``CommandHandler._cmd_send_dm`` with ``replace``.
4. EventHandler: which BBS replies carry the ``replace`` key.

All data is invented test data.
"""

import asyncio
import base64
import zlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterator, List, Tuple

import pytest

from meshcore_gui.ble.commands import CommandHandler
from meshcore_gui.ble.events import BBS_SYNC_REPLACE_KEY, EventHandler
from meshcore_gui.services import bbs_config_store, bbs_service
from meshcore_gui.services.bbs_config_store import BbsConfigStore
from meshcore_gui.services.bbs_service import (
    SYNC_COMPRESSED_TAG,
    SYNC_LINE_MAX_BYTES,
    BbsCommandHandler,
    BbsMessage,
    BbsService,
)
from meshcore_gui.services.dedup import DualDeduplicator

KEY_A: str = "AA" * 32
"""Invented public key of a whitelisted test sender."""

SENDER_KEY: str = "a1b2c3d4e5f6"
"""Invented 6-byte public key prefix (12 hex chars) of a DM recipient."""

OTHER_KEY: str = "0f0e0d0c0b0a"
"""Invented public key prefix of a second DM recipient."""

# ===========================================================================
# 1. Fixtures and helpers
# ===========================================================================


@pytest.fixture(name="bbs")
def fixture_bbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[
        Tuple[BbsService, BbsCommandHandler]]:
    """Create a board with categories URGENT, STATUS and 30 messages.

    Args:
        tmp_path:    Per-test temporary directory from pytest.
        monkeypatch: Pytest fixture used to replace ``BBS_DIR``.

    Yields:
        Tuple of (service, command handler).
    """
    monkeypatch.setattr(bbs_service, "BBS_DIR", tmp_path)
    monkeypatch.setattr(bbs_config_store, "BBS_DIR", tmp_path)
    store = BbsConfigStore(tmp_path / "bbs_config.json")
    store.configure_board(
        channel_indices=[1], channel_names={1: "Test"},
        categories=["URGENT", "STATUS"], allowed_keys=[KEY_A],
        default_retention_days=90, category_retention_days={},
    )
    service = BbsService(tmp_path / "bbs_messages.db")
    stamp = datetime.now(timezone.utc).isoformat()
    for i in range(30):
        service.post_message(BbsMessage(
            channel=1, region="", category="STATUS" if i % 2 else "URGENT",
            sender="Tester", sender_key=KEY_A,
            text=f"Bericht {i}: dijk bij gemaal {i % 4} gecontroleerd é",
            timestamp=stamp,
        ))
    yield service, BbsCommandHandler(service, store)


def _sync(handler: BbsCommandHandler, args: str) -> str:
    """Run ``!x`` as the whitelisted sender and return the reply.

    Args:
        handler: Command handler under test.
        args:    Arguments after ``!x``.

    Returns:
        The reply text.
    """
    reply = handler.handle_dm("Tester", KEY_A, f"!x {args}".strip())
    assert reply is not None
    return reply


def _inflate(parts: List[str]) -> str:
    """Decode and inflate the first DM parts of a compressed reply.

    Args:
        parts: DM texts in send order, the first starting with ``Z1|``.

    Returns:
        The text these parts give on their own (start of the reply).
    """
    encoded = "".join(parts)[len(SYNC_COMPRESSED_TAG):]
    return zlib.decompressobj(-15).decompress(base64.b64decode(encoded)).decode(
        "utf-8", "ignore")


def _splitter() -> CommandHandler:
    """Return a CommandHandler usable for ``_split_reply`` only.

    Returns:
        CommandHandler created without running its constructor.
    """
    return CommandHandler.__new__(CommandHandler)


# ===========================================================================
# 2. Compressed reply
# ===========================================================================


def test_compressed_reply_holds_the_x2_reply(bbs) -> None:
    """Inflated, the compressed reply is the X1 reply with an X2 header.

    Every line, the last one included, ends with a line feed.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    plain = _sync(handler, "0 0").split("\n")
    packed = _sync(handler, "0 0 z").split("\n")
    text = _inflate(packed)
    assert text.endswith("\n")
    inner = text[:-1].split("\n")
    assert inner[0] == plain[0].replace("X1|", "X2|", 1) + "|0|0"
    assert inner[1:] == plain[1:]


def test_compressed_reply_echoes_the_cursors(bbs) -> None:
    """The X2 header ends with since_id and since_del of the request.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    header = _inflate(_sync(handler, "12 0 z").split("\n")).split("\n")[0]
    assert header.startswith("X2|")
    # 18 records above id 12, capped at SYNC_LIMIT (10 since v1.26.5).
    assert header.split("|")[2] == str(min(18, BbsCommandHandler.SYNC_LIMIT))
    assert header.split("|")[-2:] == ["12", "0"]


def test_compressed_lines_are_whole_dm_parts(bbs) -> None:
    """Every line fits one DM part and the DM splitter keeps one per part.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    reply = _sync(handler, "0 0 z")
    lines = reply.split("\n")
    assert lines[0].startswith(SYNC_COMPRESSED_TAG)
    assert len(lines[0]) == len(SYNC_COMPRESSED_TAG) + 156
    assert all(len(line) == SYNC_LINE_MAX_BYTES for line in lines[1:-1])
    assert len(lines[-1]) <= SYNC_LINE_MAX_BYTES
    parts = _splitter()._split_reply(  # pylint: disable=protected-access
        reply, max_bytes=SYNC_LINE_MAX_BYTES)
    assert parts == lines


def test_compressed_reply_is_shorter(bbs) -> None:
    """The board of 30 messages takes fewer DM parts compressed.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    split = _splitter()._split_reply  # pylint: disable=protected-access
    plain = split(_sync(handler, "0 0"), max_bytes=SYNC_LINE_MAX_BYTES)
    packed = split(_sync(handler, "0 0 z"), max_bytes=SYNC_LINE_MAX_BYTES)
    assert len(packed) < len(plain)


def test_every_prefix_of_parts_is_readable(bbs) -> None:
    """The first k parts inflate on their own to the start of the reply.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    parts = _sync(handler, "0 0 z").split("\n")
    full = _inflate(parts)
    previous = ""
    for k in range(1, len(parts) + 1):
        text = _inflate(parts[:k])
        assert full.startswith(text)
        assert len(text) >= len(previous)
        previous = text
    assert previous == full


@pytest.mark.parametrize("args", ["z", "5 z", "0 0 Z", "0 0 z z", "0 0 x"])
def test_flag_needs_both_numbers(bbs, args: str) -> None:
    """The flag counts only as third argument; anything else is usage.

    Args:
        bbs:  Service and handler fixture.
        args: Arguments after ``!x``.
    """
    _, handler = bbs
    assert _sync(handler, args) == "Usage: !x <since_id> <since_del>"


def test_plain_reply_unchanged(bbs) -> None:
    """Without the flag the reply is the X1 reply as before.

    Args:
        bbs: Service and handler fixture.
    """
    _, handler = bbs
    assert _sync(handler, "0 0").startswith("X1|")
    assert _sync(handler, "").startswith("X1|")


# ===========================================================================
# 3. Replaceable replies
# ===========================================================================


class _FakeShared:  # pylint: disable=too-few-public-methods
    """Stand-in for SharedDataWriter that ignores stored messages."""

    def add_message(self, msg) -> None:
        """Ignore a message.

        Args:
            msg: The Message the CommandHandler stores.
        """
        del msg


def _queue_handler() -> CommandHandler:
    """Build a CommandHandler with only the DM queue state.

    Returns:
        CommandHandler created without running its constructor.
    """
    handler = CommandHandler.__new__(CommandHandler)
    # pylint: disable=protected-access  # test sets up private state directly
    handler._shared = _FakeShared()
    handler._dm_queues = {}
    return handler


def _send(handler: CommandHandler, cmd: Dict) -> None:
    """Run ``_cmd_send_dm`` for *cmd*.

    Args:
        handler: Handler from :func:`_queue_handler`.
        cmd:     ``send_dm`` command dict.
    """
    asyncio.run(handler._cmd_send_dm(cmd))  # pylint: disable=protected-access


def _texts(handler: CommandHandler, key: str) -> List[str]:
    """Return the first chunk of every queued delivery to *key*.

    Args:
        handler: Handler from :func:`_queue_handler`.
        key:     Recipient key in lower case.

    Returns:
        First chunk per delivery, in queue order.
    """
    return [d.chunks[0] for d in handler._dm_queues.get(key, [])]  # pylint: disable=protected-access


def test_new_sync_reply_replaces_older_one() -> None:
    """A second sync reply to the same node drops the first."""
    handler = _queue_handler()
    _send(handler, {"pubkey": SENDER_KEY, "text": "old", "replace": "bbs_sync"})
    _send(handler, {"pubkey": SENDER_KEY, "text": "new", "replace": "bbs_sync"})
    assert _texts(handler, SENDER_KEY) == ["new"]


def test_replace_also_drops_reply_being_delivered() -> None:
    """The queue head that waits for its ACK is dropped too; its ACK is ignored."""
    handler = _queue_handler()
    _send(handler, {"pubkey": SENDER_KEY, "text": "old", "replace": "bbs_sync"})
    head = handler._dm_queues[SENDER_KEY][0]  # pylint: disable=protected-access
    head.waiting = True
    head.acks.add("01020304")
    _send(handler, {"pubkey": SENDER_KEY, "text": "new", "replace": "bbs_sync"})
    handler.on_ack(SimpleNamespace(payload={"code": "01020304"}))
    new = handler._dm_queues[SENDER_KEY][0]  # pylint: disable=protected-access
    assert _texts(handler, SENDER_KEY) == ["new"]
    assert new.index == 0


def test_other_replies_are_kept() -> None:
    """Replies without the key, or to another node, stay in the queue."""
    handler = _queue_handler()
    _send(handler, {"pubkey": SENDER_KEY, "text": "posted"})
    _send(handler, {"pubkey": OTHER_KEY, "text": "other", "replace": "bbs_sync"})
    _send(handler, {"pubkey": SENDER_KEY, "text": "sync", "replace": "bbs_sync"})
    assert _texts(handler, SENDER_KEY) == ["posted", "sync"]
    assert _texts(handler, OTHER_KEY) == ["other"]


# ===========================================================================
# 4. EventHandler
# ===========================================================================


class _EchoBbs:  # pylint: disable=too-few-public-methods
    """Stand-in for BbsCommandHandler that answers every DM."""

    def delivery_settings(self) -> Dict:
        """Return no delivery settings, so replies use the defaults.

        Returns:
            Empty dict (``BbsCommandHandler.delivery_settings``, v1.27.0).
        """
        return {}

    def handle_dm(self, sender: str, sender_key: str, text: str) -> str:
        """Answer with a fixed text.

        Args:
            sender:     Display name of the sender.
            sender_key: Public key prefix of the sender.
            text:       DM text.

        Returns:
            ``"reply"``.
        """
        del sender, sender_key, text
        return "reply"


class _NameShared(_FakeShared):  # pylint: disable=too-few-public-methods
    """Stand-in for SharedDataWriter with a contact name lookup."""

    def get_contact_name_by_prefix(self, prefix: str) -> str:
        """Return a fixed contact name.

        Args:
            prefix: Public key prefix to look up.

        Returns:
            ``"Node"``.
        """
        del prefix
        return "Node"


@pytest.mark.parametrize(("text", "replace"), [
    ("!x 0 0", True), ("!x 0 0 z", True), ("!h", True), ("!HELP", True),
    ("!p U test", False), ("!r", False),
])
def test_sync_and_help_replies_are_replaceable(text: str, replace: bool) -> None:
    """Only replies to !x, !h and !help carry the replace key.

    Args:
        text:    BBS DM command.
        replace: Whether the reply command must carry the key.
    """
    sent: List[Dict] = []
    handler = EventHandler(
        shared=_NameShared(), decoder=None, dedup=DualDeduplicator(), bot=None,
        bbs_handler=_EchoBbs(), command_sink=sent.append,
    )
    handler.on_contact_msg(SimpleNamespace(payload={
        "type": "PRIV", "pubkey_prefix": SENDER_KEY, "path_len": 255,
        "txt_type": 0, "text": text, "sender_timestamp": 1700000000,
    }))
    dms = [c for c in sent if c["action"] == "send_dm"]
    assert len(dms) == 1
    assert (dms[0].get("replace") == BBS_SYNC_REPLACE_KEY) is replace
