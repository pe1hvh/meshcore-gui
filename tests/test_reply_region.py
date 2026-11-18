"""Tests: bot and BBS replies use the region of the request (v1.26.2).

A request that arrives in a known region is answered in that region: the
reply command carries ``"region": <name>``.  A request in an unknown region
(``"?xxxx"``) or without a region gets no ``"region"`` key, so the channel
default (channel reply) or the device default (DM reply) applies.  The
device default region read back from the device is corrected with the
scope key when its name does not match (firmware/library NUL issue).

Structure:

1. Test data and doubles: made-up keys, regions and stand-ins for the
   collaborators of EventHandler, CommandHandler and the worker.
2. Bot: ``MeshBot.check_and_reply`` with and without a region.
3. Channel replies: bot and BBS channel reply via ``on_rx_log`` and via the
   ``on_channel_msg`` fallback.
4. DM replies: region record in ``on_rx_log`` and lookup in the BBS branch
   of ``on_contact_msg``.
5. DM delivery: ``_cmd_send_dm`` and ``_send_dm_part`` set and reset the
   send override.
6. Device default region: ``_read_default_scope`` takes the name from the
   scope key.
"""

import asyncio
from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest
from meshcore import EventType

from meshcore_gui.ble.commands import CommandHandler, _DmDelivery
from meshcore_gui.ble.events import EventHandler
from meshcore_gui.ble.packet_decoder import DecodedPacket, PayloadType
from meshcore_gui.ble.worker import _BaseWorker
from meshcore_gui.services.bot import BotConfig, MeshBot
from meshcore_gui.services.dedup import DualDeduplicator
from meshcore_gui.services.region_service import (
    RegionService,
    normalize_region_name,
    region_key,
    transport_code,
)

# ===========================================================================
# 1. Test data and doubles
# ===========================================================================

OWN_PUBKEY = "c7" + "11" * 31
"""Made-up 32-byte public key (64 hex chars) of the bot/BBS device."""

SENDER_KEY = "a1b2c3d4e5f6"
"""Made-up public key prefix (12 hex chars) of the requesting contact."""

KNOWN_REGIONS = ["nl", "nl-ov", "test-region"]
"""Regions known on the device; ``test-region`` stands for a third region."""

TXT_PAYLOAD = bytes([0xC7, 0xA1, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
"""TXT_MSG payload: dest hash 0xC7 (own key), src hash 0xA1, then made-up
MAC and ciphertext bytes."""

GRP_PAYLOAD = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
"""Made-up GRP_TXT payload bytes used for the transport code."""

BOT_TEXT = "test please"
"""Channel message that matches the bot keyword ``test``."""

BBS_TEXT = "!bbs"
"""Channel message the fake BBS handler answers."""


def code_for(region: str, payload_type: PayloadType, payload: bytes) -> int:
    """Return the transport code *region* gives a packet.

    Args:
        region: Region name without ``#``.
        payload_type: Payload type of the packet.
        payload: Payload bytes of the packet.

    Returns:
        16-bit transport code as the firmware computes it.
    """
    return transport_code(region_key(region), payload_type.value, payload)


class FakeShared:
    """Stand-in for SharedDataWriter: records messages, knows no contacts."""

    def __init__(self) -> None:
        """Create empty message and RX log lists."""
        self.messages: List = []
        """Every Message passed to :meth:`add_message`, in order."""
        self.rx_log: List = []
        """Every RxLogEntry passed to :meth:`add_rx_log`, in order."""
        self.contacts: Dict[str, tuple] = {}
        """Contacts by name; empty, so no sender key is found."""

    def add_message(self, msg) -> None:
        """Record a message.

        Args:
            msg: The Message to store.
        """
        self.messages.append(msg)

    def add_rx_log(self, entry) -> None:
        """Record an RX log entry.

        Args:
            entry: The RxLogEntry to store.
        """
        self.rx_log.append(entry)

    def get_device_name(self) -> str:
        """Return a fixed device name.

        Returns:
            ``"TestNode"``.
        """
        return "TestNode"

    def get_contact_by_name(self, name: str) -> Optional[tuple]:
        """Return the contact with *name*.

        Args:
            name: Contact name to look up.

        Returns:
            ``(pubkey, contact)`` tuple, or ``None`` (always, as no
            contacts are set).
        """
        return self.contacts.get(name)

    def get_contact_name_by_prefix(self, prefix: str) -> str:
        """Return a fixed contact name.

        Args:
            prefix: Public key prefix to look up.

        Returns:
            ``"Node-"`` followed by the first four characters of ``prefix``.
        """
        return f"Node-{prefix[:4]}"


class FakeDecoder:
    """Stand-in for PacketDecoder that returns a prepared packet."""

    def __init__(self) -> None:
        """Start without a prepared packet."""
        self.packet: Optional[DecodedPacket] = None
        """Packet returned by the next :meth:`decode` call."""

    def decode(self, payload_hex: str) -> Optional[DecodedPacket]:
        """Return the prepared packet.

        Args:
            payload_hex: Raw packet hex (ignored).

        Returns:
            The prepared DecodedPacket.
        """
        del payload_hex
        return self.packet

    @staticmethod
    def get_payload_type_text(payload_type: PayloadType) -> str:
        """Return the enum name.

        Args:
            payload_type: Payload type of the packet.

        Returns:
            Name of the enum member.
        """
        return payload_type.name


class FakeBbsHandler:
    """Stand-in for BbsCommandHandler that answers every command."""

    def handle_channel_msg(self, channel_idx, sender, sender_key, text) -> Optional[str]:
        """Answer ``!bbs`` on any channel.

        Args:
            channel_idx: Channel index of the message.
            sender: Display name of the sender.
            sender_key: Public key prefix of the sender.
            text: Message text.

        Returns:
            A fixed reply for ``!bbs``, otherwise ``None``.
        """
        del channel_idx, sender, sender_key
        return "BBS menu" if text == BBS_TEXT else None

    def handle_dm(self, sender: str, sender_key: str, text: str) -> str:
        """Answer every DM command.

        Args:
            sender: Display name of the sender.
            sender_key: Public key prefix of the sender.
            text: DM text.

        Returns:
            A fixed reply.
        """
        del sender, sender_key, text
        return "BBS reply"


def make_handler(own_pubkey: str = OWN_PUBKEY):
    """Build an EventHandler with a real bot and region service.

    Args:
        own_pubkey: Public key the handler sees as its own device key.

    Returns:
        Tuple ``(handler, decoder, sent)``: the EventHandler, its
        FakeDecoder and the list of commands passed to the command sink.
    """
    sent: List[Dict] = []
    bot = MeshBot(
        config=BotConfig(channels=frozenset({0}), name="Testbot",
                         cooldown_seconds=0.0, keywords={"test": "{bot}: ok"}),
        command_sink=sent.append,
        enabled_check=lambda: True,
    )
    decoder = FakeDecoder()
    handler = EventHandler(
        shared=FakeShared(),
        decoder=decoder,
        dedup=DualDeduplicator(),
        bot=bot,
        bbs_handler=FakeBbsHandler(),
        command_sink=sent.append,
        region_service=RegionService(
            known_regions=lambda: list(KNOWN_REGIONS),
            channel_region=lambda name: "",
            device_default=lambda: "",
        ),
        own_pubkey=lambda: own_pubkey,
    )
    return handler, decoder, sent


def group_packet(text: str, code: Optional[int], channel_idx: Optional[int] = 0,
                 sender: str = "Alice") -> DecodedPacket:
    """Build a decrypted GroupText packet.

    Args:
        text: Message body.
        code: Transport code, or ``None`` for an unscoped packet.
        channel_idx: Resolved channel index, or ``None`` when unresolved.
        sender: Sender name.

    Returns:
        DecodedPacket as PacketDecoder would return it.
    """
    return DecodedPacket(
        message_hash=f"h-{text}-{code}", payload_type=PayloadType.GroupText,
        path_length=1, path_hashes=["ab"], sender=sender, text=text,
        channel_idx=channel_idx, is_decrypted=True,
        transport_code=code, payload_raw=GRP_PAYLOAD,
    )


def txt_packet(code: Optional[int], payload: bytes = TXT_PAYLOAD) -> DecodedPacket:
    """Build a TXT_MSG packet (not decrypted, as PacketDecoder returns it).

    Args:
        code: Transport code, or ``None`` for a direct or unscoped packet.
        payload: Payload bytes (dest hash, src hash, MAC, ciphertext).

    Returns:
        DecodedPacket as PacketDecoder would return it.
    """
    return DecodedPacket(
        message_hash=f"t-{code}", payload_type=PayloadType.TextMessage,
        path_length=0, transport_code=code, payload_raw=payload,
    )


def rx(handler: EventHandler, decoder: FakeDecoder, packet: DecodedPacket) -> None:
    """Feed *packet* to ``on_rx_log`` as an RX_LOG_DATA event.

    Args:
        handler: EventHandler under test.
        decoder: Its FakeDecoder.
        packet: Packet the decoder returns.
    """
    decoder.packet = packet
    handler.on_rx_log(SimpleNamespace(payload={"payload": "00", "snr": 5.0, "rssi": -90}))


def dm_event(text: str = "!r", pubkey: str = SENDER_KEY, ts: int = 1700000000):
    """Build a ``CONTACT_MSG_RECV`` event.

    Args:
        text: DM text.
        pubkey: ``pubkey_prefix`` of the sender.
        ts: Sender timestamp in Unix seconds.

    Returns:
        Object with a ``payload`` dict, like ``meshcore.events.Event``.
    """
    return SimpleNamespace(payload={
        "type": "PRIV", "pubkey_prefix": pubkey, "path_len": 255,
        "txt_type": 0, "text": text, "sender_timestamp": ts,
    })


def by_action(sent: List[Dict], action: str) -> List[Dict]:
    """Return the commands with *action*.

    Args:
        sent: Commands passed to the command sink.
        action: Action name to select.

    Returns:
        Matching commands in order.
    """
    return [cmd for cmd in sent if cmd.get("action") == action]


# ===========================================================================
# 2. Bot
# ===========================================================================

def make_bot():
    """Build a MeshBot that answers ``test`` on channel 0.

    Returns:
        Tuple ``(bot, sent)``: the bot and the list of queued commands.
    """
    sent: List[Dict] = []
    bot = MeshBot(
        config=BotConfig(channels=frozenset({0}), name="Testbot",
                         cooldown_seconds=0.0, keywords={"test": "{bot}: ok"}),
        command_sink=sent.append,
        enabled_check=lambda: True,
    )
    return bot, sent


def test_bot_without_region_argument_unchanged():
    """``check_and_reply`` without region queues exactly the old dict."""
    bot, sent = make_bot()
    bot.check_and_reply(sender="Alice", text=BOT_TEXT, channel_idx=0, snr=1.0, path_len=0)
    assert sent == [{"action": "send_message", "channel": 0,
                     "text": "Testbot: ok", "_bot": True}]


def test_bot_with_region_adds_region_key():
    """A region passed to ``check_and_reply`` ends up in the command."""
    bot, sent = make_bot()
    bot.check_and_reply(sender="Alice", text=BOT_TEXT, channel_idx=0, snr=1.0,
                        path_len=0, region="nl")
    assert sent[0]["region"] == "nl"


# ===========================================================================
# 3. Channel replies
# ===========================================================================

@pytest.mark.parametrize("region", ["nl", "nl-ov", "test-region"])
def test_rx_log_bot_and_bbs_reply_in_request_region(region):
    """Bot and BBS channel reply via on_rx_log carry the request region.

    Args:
        region: Known region the request arrives in.
    """
    handler, decoder, sent = make_handler()
    rx(handler, decoder, group_packet(BOT_TEXT, code_for(region, PayloadType.GroupText,
                                                         GRP_PAYLOAD)))
    rx(handler, decoder, group_packet(BBS_TEXT, code_for(region, PayloadType.GroupText,
                                                         GRP_PAYLOAD)))
    replies = by_action(sent, "send_message")
    assert len(replies) == 2
    assert all(cmd["region"] == region for cmd in replies)


@pytest.mark.parametrize("code", [0x1A2B, None])
def test_rx_log_unknown_or_unscoped_gives_no_region_key(code):
    """Unknown region (``?1a2b``) and unscoped request: no region key.

    Args:
        code: Transport code matching no known region, or ``None``.
    """
    handler, decoder, sent = make_handler()
    rx(handler, decoder, group_packet(BOT_TEXT, code))
    rx(handler, decoder, group_packet(BBS_TEXT, code))
    replies = by_action(sent, "send_message")
    assert len(replies) == 2
    assert all("region" not in cmd for cmd in replies)


def test_channel_msg_fallback_uses_cached_region():
    """on_channel_msg recovers the region from the RX_LOG decode."""
    handler, decoder, sent = make_handler()
    code = code_for("nl", PayloadType.GroupText, GRP_PAYLOAD)
    # Unresolved channel_idx: on_rx_log only caches, on_channel_msg replies.
    for text in (BOT_TEXT, BBS_TEXT):
        rx(handler, decoder, group_packet(text, code, channel_idx=None))
        handler.on_channel_msg(SimpleNamespace(payload={
            "channel_idx": 0, "text": f"Alice: {text}",
            "message_hash": f"h-{text}-{code}",
        }))
    replies = by_action(sent, "send_message")
    assert len(replies) == 2
    assert all(cmd["region"] == "nl" for cmd in replies)


def test_channel_msg_fallback_without_region():
    """on_channel_msg without a cached region gives no region key."""
    handler, _decoder, sent = make_handler()
    handler.on_channel_msg(SimpleNamespace(payload={
        "channel_idx": 0, "text": f"Alice: {BOT_TEXT}", "message_hash": "x1",
    }))
    replies = by_action(sent, "send_message")
    assert len(replies) == 1 and "region" not in replies[0]


# ===========================================================================
# 4. DM replies
# ===========================================================================

def test_dm_reply_in_region_of_request():
    """A scoped TXT_MSG to this device is answered in its region."""
    handler, decoder, sent = make_handler()
    rx(handler, decoder, txt_packet(code_for("nl", PayloadType.TextMessage, TXT_PAYLOAD)))
    handler.on_contact_msg(dm_event())
    dms = by_action(sent, "send_dm")
    assert len(dms) == 1 and dms[0]["region"] == "nl"


def test_later_direct_dm_overwrites_region():
    """A later unscoped TXT_MSG from the same src clears the region."""
    handler, decoder, sent = make_handler()
    rx(handler, decoder, txt_packet(code_for("nl", PayloadType.TextMessage, TXT_PAYLOAD)))
    handler.on_contact_msg(dm_event(ts=1))
    rx(handler, decoder, txt_packet(None))
    handler.on_contact_msg(dm_event(ts=2))
    dms = by_action(sent, "send_dm")
    assert dms[0]["region"] == "nl"
    assert "region" not in dms[1]


def test_dm_to_other_node_not_recorded():
    """A TXT_MSG addressed to another node does not set a region."""
    handler, decoder, sent = make_handler()
    other = bytes([0x55]) + TXT_PAYLOAD[1:]
    rx(handler, decoder, txt_packet(code_for("nl", PayloadType.TextMessage, other), other))
    handler.on_contact_msg(dm_event())
    assert "region" not in by_action(sent, "send_dm")[0]


def test_dm_unknown_region_gives_no_region_key():
    """A TXT_MSG in an unknown region gives a reply without region key."""
    handler, decoder, sent = make_handler()
    rx(handler, decoder, txt_packet(0x1A2B))
    handler.on_contact_msg(dm_event())
    assert "region" not in by_action(sent, "send_dm")[0]


def test_dm_without_own_key_not_recorded():
    """Without a known own public key nothing is recorded."""
    handler, decoder, sent = make_handler(own_pubkey="")
    rx(handler, decoder, txt_packet(code_for("nl", PayloadType.TextMessage, TXT_PAYLOAD)))
    handler.on_contact_msg(dm_event())
    assert "region" not in by_action(sent, "send_dm")[0]


# ===========================================================================
# 5. DM delivery
# ===========================================================================

class FakeCommands:
    """Stand-in for ``mc.commands`` that records the calls in order."""

    def __init__(self, send_result: str = "ok") -> None:
        """Configure how ``send_msg`` answers.

        Args:
            send_result: ``"ok"`` (MSG_SENT), ``"error"`` (ERROR) or
                ``"raise"`` (exception).
        """
        self.calls: List[tuple] = []
        """``(name, argument)`` of every call, in order."""
        self.send_result = send_result
        """How ``send_msg`` answers, see ``__init__``."""

    async def set_flood_scope(self, scope):
        """Record a scope change.

        Args:
            scope: 16-byte region key, or ``None`` for reset.

        Returns:
            An OK event.
        """
        self.calls.append(("set_flood_scope", scope))
        return SimpleNamespace(type=EventType.OK, payload={})

    async def send_msg(self, pubkey, text, timestamp=0, attempt=0):
        """Record a DM send.

        Args:
            pubkey: Recipient key.
            text: DM text.
            timestamp: Sender timestamp.
            attempt: Attempt number.

        Returns:
            MSG_SENT or ERROR event, see ``send_result``.

        Raises:
            RuntimeError: When ``send_result`` is ``"raise"``.
        """
        del pubkey, timestamp, attempt
        self.calls.append(("send_msg", text))
        if self.send_result == "raise":
            raise RuntimeError("link lost")
        if self.send_result == "error":
            return SimpleNamespace(type=EventType.ERROR, payload={})
        return SimpleNamespace(type=EventType.MSG_SENT,
                               payload={"expected_ack": b"\x01\x02\x03\x04",
                                        "suggested_timeout": 1000})


def make_cmd_handler(commands: FakeCommands) -> CommandHandler:
    """Build a CommandHandler without running its constructor.

    Args:
        commands: Fake ``mc.commands``.

    Returns:
        CommandHandler with only the attributes the DM path uses.
    """
    handler = CommandHandler.__new__(CommandHandler)
    # pylint: disable=protected-access  # test sets up private state directly
    handler._mc = SimpleNamespace(commands=commands)
    handler._shared = FakeShared()
    handler._dm_queues = {}
    return handler


def test_cmd_send_dm_keeps_region():
    """The region of a send_dm command is kept on the delivery."""
    handler = make_cmd_handler(FakeCommands())
    asyncio.run(handler._cmd_send_dm(  # pylint: disable=protected-access
        {"pubkey": SENDER_KEY, "text": "hi", "region": "nl"}))
    asyncio.run(handler._cmd_send_dm(  # pylint: disable=protected-access
        {"pubkey": "0f0e0d0c0b0a", "text": "hi"}))
    queues = handler._dm_queues  # pylint: disable=protected-access
    assert queues[SENDER_KEY][0].region == "nl"
    assert queues["0f0e0d0c0b0a"][0].region == ""


@pytest.mark.parametrize("send_result", ["ok", "error", "raise"])
def test_send_dm_part_sets_and_resets_scope(send_result):
    """With region: scope set before send_msg and reset after, always.

    Args:
        send_result: How ``send_msg`` answers (see FakeCommands).
    """
    commands = FakeCommands(send_result)
    handler = make_cmd_handler(commands)
    delivery = _DmDelivery(pubkey=SENDER_KEY, contact_name="Node", chunks=["hi"],
                           region="nl")
    if send_result == "raise":
        with pytest.raises(RuntimeError):
            asyncio.run(handler._send_dm_part(delivery))  # pylint: disable=protected-access
    else:
        asyncio.run(handler._send_dm_part(delivery))  # pylint: disable=protected-access
    assert commands.calls == [
        ("set_flood_scope", region_key("nl")),
        ("send_msg", "hi"),
        ("set_flood_scope", None),
    ]


def test_send_dm_part_without_region_no_scope_call():
    """Without region no set_flood_scope call is made."""
    commands = FakeCommands()
    handler = make_cmd_handler(commands)
    delivery = _DmDelivery(pubkey=SENDER_KEY, contact_name="Node", chunks=["hi"])
    asyncio.run(handler._send_dm_part(delivery))  # pylint: disable=protected-access
    assert commands.calls == [("send_msg", "hi")]


# ===========================================================================
# 6. Device default region
# ===========================================================================

class FakeRegionStore:
    """Stand-in for ChannelRegionStore."""

    def __init__(self, known: List[str]) -> None:
        """Create a store with *known* regions.

        Args:
            known: Known region names.
        """
        self.known = known
        """Known region names returned by :meth:`get_known_regions`."""
        self.device_default: Optional[str] = None
        """Last value passed to :meth:`set_device_default`."""

    def get_known_regions(self) -> List[str]:
        """Return the known regions.

        Returns:
            The known region names.
        """
        return list(self.known)

    def set_device_default(self, region: str) -> None:
        """Record the device default, normalized like the real store.

        Args:
            region: Region name, with or without leading ``#``.
        """
        self.device_default = normalize_region_name(region)


def read_default(payload: Dict, known: List[str]) -> FakeRegionStore:
    """Run ``_read_default_scope`` with a device answer of *payload*.

    Args:
        payload: Payload of the DEFAULT_FLOOD_SCOPE event.
        known: Known regions in the store.

    Returns:
        The store after the read.
    """
    store = FakeRegionStore(known)

    async def getter():
        """Return the prepared device answer.

        Returns:
            DEFAULT_FLOOD_SCOPE event.
        """
        return SimpleNamespace(type=EventType.DEFAULT_FLOOD_SCOPE, payload=payload)

    worker = SimpleNamespace(
        _channel_region_store=store,
        mc=SimpleNamespace(commands=SimpleNamespace(get_default_flood_scope=getter)),
        _log_prefix="TEST",
        _scope_name_for_key=_BaseWorker._scope_name_for_key,  # pylint: disable=protected-access
    )
    asyncio.run(_BaseWorker._read_default_scope(worker))  # pylint: disable=protected-access
    return store


def test_default_scope_corrupted_name_resolved_by_key():
    """``#nlov`` with the key of ``#nl`` and ``nl`` known → ``nl``."""
    store = read_default({"scope_name": "#nlov", "scope_key": region_key("nl").hex()},
                         ["nl", "nl-ov", "nlov"])
    assert store.device_default == "nl"


def test_default_scope_normal_case_unchanged():
    """``#nl`` with its own key → ``nl``."""
    store = read_default({"scope_name": "#nl", "scope_key": region_key("nl").hex()}, [])
    assert store.device_default == "nl"


def test_default_scope_no_match_keeps_name_and_warns(capsys):
    """No matching name: returned name kept, warning printed.

    Args:
        capsys: pytest fixture capturing stdout.
    """
    store = read_default({"scope_name": "#x", "scope_key": region_key("other").hex()},
                         ["nl"])
    assert store.device_default == "x"
    assert "does not match" in capsys.readouterr().out


def test_default_scope_empty_payload():
    """No default on the device → empty name as before."""
    store = read_default({}, ["nl"])
    assert store.device_default == ""
