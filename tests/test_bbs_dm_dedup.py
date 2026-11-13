"""Regression tests: a resent BBS DM is handled only once.

When the sender gets no ``ACK`` for a DM, its app sends the same DM again
with a higher attempt number.  The packet differs per attempt, so the
firmware delivers every attempt as its own ``CONTACT_MSG_RECV``.  All
attempts carry the same ``pubkey_prefix``, ``sender_timestamp`` and text.
Before the fix, each attempt reached ``BbsCommandHandler.handle_dm()`` and a
``!p`` was stored once per attempt.

Structure:

1. Test doubles: minimal stand-ins for the collaborators of EventHandler.
2. DualDeduplicator: the DM store on its own.
3. EventHandler: the BBS route of ``on_contact_msg``.
"""

from types import SimpleNamespace
from typing import Dict, List, Optional

from meshcore_gui.ble.events import EventHandler
from meshcore_gui.services.dedup import DualDeduplicator

# ===========================================================================
# 1. Test doubles
# ===========================================================================

SENDER_KEY = "a1b2c3d4e5f6"
"""Made-up 6-byte public key prefix (12 hex chars) of the DM sender."""

OTHER_KEY = "0f0e0d0c0b0a"
"""Made-up public key prefix of a second sender."""

POST_TEXT = "!p tst Test message"
"""A ``!p`` post command as a user would send it by DM."""


class FakeShared:
    """Stand-in for SharedDataWriter that records stored messages."""

    def __init__(self) -> None:
        """Create an empty message list."""
        self.messages: List = []
        """Every Message passed to :meth:`add_message`, in order."""

    def add_message(self, msg) -> None:
        """Record a message.

        Args:
            msg: The Message the EventHandler stores.
        """
        self.messages.append(msg)

    def get_contact_name_by_prefix(self, prefix: str) -> str:
        """Return a fixed contact name.

        Args:
            prefix: Public key prefix to look up.

        Returns:
            ``"Node-"`` followed by the first four characters of ``prefix``.
        """
        return f"Node-{prefix[:4]}"


# One method is all the EventHandler calls on a BBS handler.
class FakeBbsHandler:  # pylint: disable=too-few-public-methods
    """Stand-in for BbsCommandHandler that counts handled DMs."""

    def __init__(self) -> None:
        """Create an empty call list."""
        self.calls: List[Dict[str, str]] = []
        """Keyword arguments of every :meth:`handle_dm` call, in order."""

    def handle_dm(self, sender: str, sender_key: str, text: str) -> str:
        """Record the call and answer like a successful post.

        Args:
            sender: Display name of the sender.
            sender_key: Public key prefix of the sender.
            text: DM text.

        Returns:
            A fixed ``Posted`` reply.
        """
        self.calls.append({"sender": sender, "sender_key": sender_key, "text": text})
        return "Posted [Test]: Test message"


def make_handler():
    """Build an EventHandler wired to test doubles.

    Returns:
        Tuple ``(handler, bbs, sent, shared)``: the EventHandler, the
        FakeBbsHandler, the list of commands passed to the command sink
        and the FakeShared.
    """
    shared = FakeShared()
    bbs = FakeBbsHandler()
    sent: List[Dict] = []
    handler = EventHandler(
        shared=shared,
        decoder=None,
        dedup=DualDeduplicator(),
        bot=None,
        bbs_handler=bbs,
        command_sink=sent.append,
    )
    return handler, bbs, sent, shared


def dm_event(text: str, pubkey: str = SENDER_KEY, sender_timestamp: Optional[int] = 1700000000):
    """Build a ``CONTACT_MSG_RECV`` event as the meshcore library delivers it.

    Args:
        text: DM text.
        pubkey: ``pubkey_prefix`` of the sender.
        sender_timestamp: Sender's clock in Unix seconds; ``None`` leaves
            the field out of the payload.

    Returns:
        Object with a ``payload`` dict, like ``meshcore.events.Event``.
    """
    payload = {"type": "PRIV", "pubkey_prefix": pubkey, "path_len": 255,
               "txt_type": 0, "text": text}
    if sender_timestamp is not None:
        payload["sender_timestamp"] = sender_timestamp
    return SimpleNamespace(payload=payload)


# ===========================================================================
# 2. DualDeduplicator
# ===========================================================================

def test_dm_key_is_seen_after_mark():
    """A marked DM is seen; other sender, timestamp or text is not."""
    dedup = DualDeduplicator()
    assert not dedup.is_dm_seen(SENDER_KEY, 100, POST_TEXT)
    dedup.mark_dm(SENDER_KEY, 100, POST_TEXT)
    assert dedup.is_dm_seen(SENDER_KEY, 100, POST_TEXT)
    assert not dedup.is_dm_seen(OTHER_KEY, 100, POST_TEXT)
    assert not dedup.is_dm_seen(SENDER_KEY, 101, POST_TEXT)
    assert not dedup.is_dm_seen(SENDER_KEY, 100, POST_TEXT + "x")


def test_dm_store_is_separate_and_cleared():
    """DM keys do not collide with content keys; clear() empties them."""
    dedup = DualDeduplicator()
    dedup.mark_dm(SENDER_KEY, 100, POST_TEXT)
    assert not dedup.is_content_seen(SENDER_KEY, 100, POST_TEXT)
    dedup.clear()
    assert not dedup.is_dm_seen(SENDER_KEY, 100, POST_TEXT)


# ===========================================================================
# 3. EventHandler — BBS route
# ===========================================================================

def test_resent_bbs_dm_is_handled_once():
    """Three attempts of one DM give one BBS call and one reply."""
    handler, bbs, sent, _shared = make_handler()
    for _ in range(3):
        handler.on_contact_msg(dm_event(POST_TEXT))
    assert len(bbs.calls) == 1
    assert len(sent) == 1


def test_resent_bbs_dm_still_reaches_archive_path():
    """Every attempt still goes to add_message, which has its own dedup."""
    handler, _bbs, _sent, shared = make_handler()
    for _ in range(3):
        handler.on_contact_msg(dm_event(POST_TEXT))
    assert len(shared.messages) == 3


def test_same_text_with_new_timestamp_is_handled_again():
    """A new command with the same text (new sender clock) is handled."""
    handler, bbs, _sent, _shared = make_handler()
    handler.on_contact_msg(dm_event(POST_TEXT, sender_timestamp=100))
    handler.on_contact_msg(dm_event(POST_TEXT, sender_timestamp=101))
    assert len(bbs.calls) == 2


def test_same_dm_from_other_sender_is_handled():
    """Equal timestamp and text from another sender is a different DM."""
    handler, bbs, _sent, _shared = make_handler()
    handler.on_contact_msg(dm_event(POST_TEXT, pubkey=SENDER_KEY))
    handler.on_contact_msg(dm_event(POST_TEXT, pubkey=OTHER_KEY))
    assert len(bbs.calls) == 2


def test_dm_without_sender_timestamp_is_not_deduplicated():
    """Without ``sender_timestamp`` every DM is handled, as before."""
    handler, bbs, _sent, _shared = make_handler()
    handler.on_contact_msg(dm_event(POST_TEXT, sender_timestamp=None))
    handler.on_contact_msg(dm_event(POST_TEXT, sender_timestamp=None))
    assert len(bbs.calls) == 2
