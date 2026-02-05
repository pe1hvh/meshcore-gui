"""
BLE communication worker for MeshCore GUI.

Runs in a separate thread with its own asyncio event loop.  Connects to
the MeshCore device, subscribes to events, and processes commands sent
from the GUI via the SharedData command queue.

Single-source architecture
~~~~~~~~~~~~~~~~~~~~~~~~~~
When a LoRa packet arrives the companion firmware pushes two events:

1. ``RX_LOG_DATA`` — the *raw* LoRa frame with header, path hashes
   and encrypted payload.
2. ``CHANNEL_MSG_RECV`` — the *decrypted* message text but **no** path
   hashes (only the hop count ``path_len``).

This module uses ``meshcoredecoder`` to fully decode the raw packet
from (1): message_hash, path_hashes, sender name, message text and
channel index are all extracted from that **single frame**.

The ``CHANNEL_MSG_RECV`` event (2) serves only as a fallback for
packets that could not be decrypted from the raw frame (e.g. missing
channel key).

Deduplication is done via ``message_hash``: if the same hash has
already been processed from RX_LOG_DATA, the CHANNEL_MSG_RECV event
is silently dropped.

There is **no temporal correlation**, no ring buffer, no archive, and
no sanity-margin heuristics.
"""

import asyncio
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

from meshcore import MeshCore, EventType

from meshcore_gui.config import (
    BOT_CHANNEL, BOT_COOLDOWN_SECONDS, BOT_KEYWORDS, BOT_NAME,
    CHANNELS_CONFIG, debug_print,
)
from meshcore_gui.packet_parser import PacketDecoder, PayloadType
from meshcore_gui.protocols import SharedDataWriter


# Maximum number of message_hashes kept for deduplication.
# Oldest entries are evicted first.  200 is generous for the
# typical message rate of a mesh network.
_SEEN_HASHES_MAX = 200


class BLEWorker:
    """
    BLE communication worker that runs in a separate thread.

    Attributes:
        address: BLE MAC address of the device
        shared:  SharedDataWriter for thread-safe communication
        mc:      MeshCore instance after connection
        running: Boolean to control the worker loop
    """

    def __init__(self, address: str, shared: SharedDataWriter) -> None:
        self.address = address
        self.shared = shared
        self.mc: Optional[MeshCore] = None
        self.running = True

        # Packet decoder (channel keys loaded at startup)
        self._decoder = PacketDecoder()

        # BOT: timestamp of last reply (cooldown enforcement)
        self._bot_last_reply: float = 0.0

        # Deduplication: message_hash values already processed via
        # RX_LOG_DATA decode.  When CHANNEL_MSG_RECV arrives for the
        # same packet, it is silently dropped.
        #
        # Two dedup strategies:
        # 1. message_hash (from decoded packet)
        # 2. content key (sender:channel:text) — because CHANNEL_MSG_RECV
        #    does NOT include message_hash in its payload
        self._seen_hashes: Set[str] = set()
        self._seen_hashes_order: List[str] = []
        self._seen_content: Set[str] = set()
        self._seen_content_order: List[str] = []

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker in a new daemon thread."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        debug_print("BLE worker thread started")

    def _run(self) -> None:
        """Entry point for the worker thread."""
        asyncio.run(self._async_main())

    async def _async_main(self) -> None:
        """Connect, then process commands in an infinite loop."""
        await self._connect()
        if self.mc:
            while self.running:
                await self._process_commands()
                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Connect to the BLE device and load initial data."""
        self.shared.set_status(f"🔄 Connecting to {self.address}...")

        try:
            print(f"BLE: Connecting to {self.address}...")
            self.mc = await MeshCore.create_ble(self.address)
            print("BLE: Connected!")

            await asyncio.sleep(1)

            # Subscribe to events
            self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._on_channel_msg)
            self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_contact_msg)
            self.mc.subscribe(EventType.RX_LOG_DATA, self._on_rx_log)

            await self._load_data()
            await self._load_channel_keys()
            await self.mc.start_auto_message_fetching()

            self.shared.set_connected(True)
            self.shared.set_status("✅ Connected")
            print("BLE: Ready!")

        except Exception as e:
            print(f"BLE: Connection error: {e}")
            self.shared.set_status(f"❌ {e}")

    async def _load_data(self) -> None:
        """
        Load device data with retry mechanism.

        Tries send_appstart and send_device_query each up to 5 times.
        Channels come from hardcoded config.
        """
        # send_appstart
        self.shared.set_status("🔄 Device info...")
        for i in range(5):
            debug_print(f"send_appstart attempt {i + 1}")
            r = await self.mc.commands.send_appstart()
            if r.type != EventType.ERROR:
                print(f"BLE: send_appstart OK: {r.payload.get('name')}")
                self.shared.update_from_appstart(r.payload)
                break
            await asyncio.sleep(0.3)

        # send_device_query
        for i in range(5):
            debug_print(f"send_device_query attempt {i + 1}")
            r = await self.mc.commands.send_device_query()
            if r.type != EventType.ERROR:
                print(f"BLE: send_device_query OK: {r.payload.get('ver')}")
                self.shared.update_from_device_query(r.payload)
                break
            await asyncio.sleep(0.3)

        # Channels (hardcoded — BLE get_channel is unreliable)
        self.shared.set_status("🔄 Channels...")
        self.shared.set_channels(CHANNELS_CONFIG)
        print(f"BLE: Channels loaded: {[c['name'] for c in CHANNELS_CONFIG]}")

        # Contacts
        self.shared.set_status("🔄 Contacts...")
        r = await self.mc.commands.get_contacts()
        if r.type != EventType.ERROR:
            self.shared.set_contacts(r.payload)
            print(f"BLE: Contacts loaded: {len(r.payload)} contacts")

    async def _load_channel_keys(self) -> None:
        """
        Load channel decryption keys for packet decoding.

        Strategy per channel:

        1. Try ``get_channel(idx)`` from the device (returns the
           authoritative 16-byte ``channel_secret``).
        2. If that fails, derive the key from the channel name via
           ``SHA-256(name)[:16]``.  This is correct for channels whose
           name starts with ``#`` (like ``#test``).  For other channels
           the derived key may be wrong, but decryption will simply fail
           gracefully.
        """
        self.shared.set_status("🔄 Channel keys...")

        for ch in CHANNELS_CONFIG:
            idx = ch['idx']
            name = ch['name']
            loaded = False

            # Strategy 1: get_channel from device (3 retries)
            for attempt in range(3):
                try:
                    r = await self.mc.commands.get_channel(idx)
                    if r.type != EventType.ERROR:
                        secret = r.payload.get('channel_secret')
                        if secret and isinstance(secret, bytes) and len(secret) >= 16:
                            self._decoder.add_channel_key(idx, secret[:16])
                            print(
                                f"BLE: Channel key [{idx}] '{name}' "
                                f"loaded from device"
                            )
                            loaded = True
                            break
                except Exception as exc:
                    debug_print(
                        f"get_channel({idx}) attempt {attempt + 1} "
                        f"error: {exc}"
                    )
                await asyncio.sleep(0.3)

            # Strategy 2: derive from name
            if not loaded:
                self._decoder.add_channel_key_from_name(idx, name)
                print(
                    f"BLE: Channel key [{idx}] '{name}' "
                    f"derived from name (fallback)"
                )

        print(
            f"BLE: PacketDecoder ready — "
            f"has_keys={self._decoder.has_keys}"
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _mark_seen(self, message_hash: str) -> None:
        """Record a message_hash as processed.  Evicts old entries."""
        if message_hash in self._seen_hashes:
            return
        self._seen_hashes.add(message_hash)
        self._seen_hashes_order.append(message_hash)
        while len(self._seen_hashes_order) > _SEEN_HASHES_MAX:
            oldest = self._seen_hashes_order.pop(0)
            self._seen_hashes.discard(oldest)

    def _mark_content_seen(self, sender: str, channel, text: str) -> None:
        """Record a content key as processed.  Evicts old entries."""
        key = f"{channel}:{sender}:{text}"
        if key in self._seen_content:
            return
        self._seen_content.add(key)
        self._seen_content_order.append(key)
        while len(self._seen_content_order) > _SEEN_HASHES_MAX:
            oldest = self._seen_content_order.pop(0)
            self._seen_content.discard(oldest)

    def _is_seen(self, message_hash: str) -> bool:
        """Check if a message_hash has already been processed."""
        return message_hash in self._seen_hashes

    def _is_content_seen(self, sender: str, channel, text: str) -> bool:
        """Check if a content key has already been processed."""
        key = f"{channel}:{sender}:{text}"
        return key in self._seen_content

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    async def _process_commands(self) -> None:
        """Process all commands queued by the GUI."""
        while True:
            cmd = self.shared.get_next_command()
            if cmd is None:
                break
            await self._handle_command(cmd)

    async def _handle_command(self, cmd: Dict) -> None:
        """
        Process a single command from the GUI.

        Supported actions: send_message, send_dm, send_advert, refresh.
        """
        action = cmd.get('action')

        if action == 'send_message':
            channel = cmd.get('channel', 0)
            text = cmd.get('text', '')
            is_bot = cmd.get('_bot', False)
            if text and self.mc:
                await self.mc.commands.send_chan_msg(channel, text)
                # Bot replies appear via the radio echo (RX_LOG),
                # so only add manual messages to the message list.
                if not is_bot:
                    self.shared.add_message({
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'sender': 'Me',
                        'text': text,
                        'channel': channel,
                        'direction': 'out',
                        'sender_pubkey': '',
                        'path_hashes': [],
                    })
                debug_print(
                    f"{'BOT' if is_bot else 'Sent'} message to "
                    f"channel {channel}: {text[:30]}"
                )

        elif action == 'send_advert':
            if self.mc:
                await self.mc.commands.send_advert(flood=True)
                self.shared.set_status("📢 Advert sent")
                debug_print("Advert sent")

        elif action == 'send_dm':
            pubkey = cmd.get('pubkey', '')
            text = cmd.get('text', '')
            contact_name = cmd.get('contact_name', pubkey[:8])
            if text and pubkey and self.mc:
                await self.mc.commands.send_msg(pubkey, text)
                self.shared.add_message({
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'sender': 'Me',
                    'text': text,
                    'channel': None,
                    'direction': 'out',
                    'sender_pubkey': pubkey,
                    'path_hashes': [],
                })
                debug_print(f"Sent DM to {contact_name}: {text[:30]}")

        elif action == 'refresh':
            if self.mc:
                debug_print("Refresh requested")
                await self._load_data()

    # ------------------------------------------------------------------
    # BOT — keyword-triggered auto-reply
    # ------------------------------------------------------------------

    def _bot_check_and_queue(
        self,
        sender: str,
        text: str,
        channel_idx,
        snr,
        path_len: int,
        path_hashes: Optional[List[str]] = None,
    ) -> None:
        """Queue a BOT reply if all guards pass.

        Guards:
            1. BOT is enabled (checkbox in GUI)
            2. Message is on the configured BOT_CHANNEL
            3. Sender is not the BOT itself (prevent self-reply)
            4. Sender name does not end with 'Bot' (prevent bot-to-bot loops)
            5. Cooldown period has elapsed
            6. Message text contains a recognised keyword
        """
        # Guard 1: BOT enabled?
        if not self.shared.is_bot_enabled():
            return

        # Guard 2: correct channel?
        if channel_idx != BOT_CHANNEL:
            return

        # Guard 3: skip own messages (use BOT_NAME as identifier, not device name)
        if sender == 'Me' or (text and text.startswith(BOT_NAME)):
            return

        # Guard 4: skip other bots (name ends with "Bot")
        if sender and sender.rstrip().lower().endswith('bot'):
            debug_print(f"BOT: skipping message from other bot '{sender}'")
            return

        # Guard 5: cooldown
        now = time.time()
        if now - self._bot_last_reply < BOT_COOLDOWN_SECONDS:
            debug_print("BOT: cooldown active, skipping")
            return

        # Guard 6: keyword match (case-insensitive, first match wins)
        text_lower = (text or '').lower()
        matched_template = None
        for keyword, template in BOT_KEYWORDS.items():
            if keyword in text_lower:
                matched_template = template
                break

        if matched_template is None:
            return

        # Build path string: "path(N); A>B" or "path(0)"
        path_str = self._format_path(path_len, path_hashes)

        # Build reply
        snr_str = f"{snr:.1f}" if snr is not None else "?"
        reply = matched_template.format(
            bot=BOT_NAME,
            sender=sender or "?",
            snr=snr_str,
            path=path_str,
        )

        # Update cooldown timestamp
        self._bot_last_reply = now

        # Queue as internal command — picked up by _process_commands
        self.shared.put_command({
            'action': 'send_message',
            'channel': BOT_CHANNEL,
            'text': reply,
            '_bot': True,
        })

        debug_print(f"BOT: queued reply to '{sender}': {reply}")

    def _format_path(
        self, path_len: int, path_hashes: Optional[List[str]],
    ) -> str:
        """Format path info as ``path(N); 8D>A8`` or ``path(0)``.

        Shows raw 1-byte hashes in uppercase hex.
        """
        if not path_len:
            return "path(0)"

        if not path_hashes:
            return f"path({path_len})"

        hop_names = [h.upper() for h in path_hashes if h and len(h) >= 2]

        if hop_names:
            return f"path({path_len}); {'>'.join(hop_names)}"
        return f"path({path_len})"

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    def _on_rx_log(self, event) -> None:
        """Callback for RX log data — the single source of truth.

        Decodes the raw LoRa frame via ``meshcoredecoder``.  For
        GroupText packets this yields message_hash, path_hashes,
        sender, text and channel_idx — all from **one** frame.

        The decoded message is added to SharedData directly.  The
        message_hash is recorded so that the duplicate
        ``CHANNEL_MSG_RECV`` event is suppressed.
        """
        payload = event.payload

        # Always add to the RX log display
        self.shared.add_rx_log({
            'time': datetime.now().strftime('%H:%M:%S'),
            'snr': payload.get('snr', 0),
            'rssi': payload.get('rssi', 0),
            'payload_type': payload.get('payload_type', '?'),
            'hops': payload.get('path_len', 0),
        })

        # Decode the raw packet
        payload_hex = payload.get('payload', '')
        if not payload_hex:
            return

        decoded = self._decoder.decode(payload_hex)
        if decoded is None:
            return

        # Only process decrypted GroupText packets as messages
        if (decoded.payload_type == PayloadType.GroupText
                and decoded.is_decrypted):
            # Mark as seen so CHANNEL_MSG_RECV is suppressed
            self._mark_seen(decoded.message_hash)
            self._mark_content_seen(
                decoded.sender, decoded.channel_idx, decoded.text,
            )

            # Look up sender pubkey from contact name
            sender_pubkey = ''
            if decoded.sender:
                match = self.shared.get_contact_by_name(decoded.sender)
                if match:
                    sender_pubkey, _contact = match

            # Extract SNR from the RX_LOG event
            snr = payload.get('snr')
            if snr is not None:
                try:
                    snr = float(snr)
                except (ValueError, TypeError):
                    snr = None

            self.shared.add_message({
                'time': datetime.now().strftime('%H:%M:%S'),
                'sender': decoded.sender,
                'text': decoded.text,
                'channel': decoded.channel_idx,
                'direction': 'in',
                'snr': snr,
                'path_len': decoded.path_length,
                'sender_pubkey': sender_pubkey,
                'path_hashes': decoded.path_hashes,
                'message_hash': decoded.message_hash,
            })

            debug_print(
                f"RX_LOG → message: hash={decoded.message_hash}, "
                f"sender={decoded.sender!r}, "
                f"ch={decoded.channel_idx}, "
                f"path={decoded.path_hashes}"
            )

            # BOT: check for keyword and queue reply
            self._bot_check_and_queue(
                sender=decoded.sender,
                text=decoded.text,
                channel_idx=decoded.channel_idx,
                snr=snr,
                path_len=decoded.path_length,
                path_hashes=decoded.path_hashes,
            )

    def _on_channel_msg(self, event) -> None:
        """Callback for channel messages — fallback only.

        If the same packet was already decoded from ``RX_LOG_DATA``
        (checked via ``message_hash``), this event is suppressed.

        Otherwise — e.g. when the channel key is missing or decryption
        failed — this adds the message without path data.
        """
        payload = event.payload

        debug_print(f"Channel msg payload keys: {list(payload.keys())}")
        debug_print(f"Channel msg payload: {payload}")

        # --- Check for duplicate via message_hash ---
        msg_hash = payload.get('message_hash', '')
        if msg_hash and self._is_seen(msg_hash):
            debug_print(
                f"Channel msg suppressed (hash match): "
                f"hash={msg_hash}"
            )
            return

        # --- Extract sender name from text field ---
        # Channel text format: "SenderName: message body"
        raw_text = payload.get('text', '')
        sender = ''
        msg_text = raw_text

        if ': ' in raw_text:
            name_part, body_part = raw_text.split(': ', 1)
            sender = name_part.strip()
            msg_text = body_part
        elif raw_text:
            msg_text = raw_text

        # --- Check for duplicate via content ---
        ch_idx = payload.get('channel_idx')
        if self._is_content_seen(sender, ch_idx, msg_text):
            debug_print(
                f"Channel msg suppressed (content match): "
                f"sender={sender!r}, ch={ch_idx}, text={msg_text[:30]!r}"
            )
            return

        debug_print(
            f"Channel msg (fallback): sender={sender!r}, "
            f"text={msg_text[:40]!r}"
        )

        # --- Look up sender contact by name to obtain pubkey ---
        sender_pubkey = ''
        if sender:
            match = self.shared.get_contact_by_name(sender)
            if match:
                sender_pubkey, _contact = match

        # Extract SNR
        msg_snr = payload.get('SNR') or payload.get('snr')
        if msg_snr is not None:
            try:
                msg_snr = float(msg_snr)
            except (ValueError, TypeError):
                msg_snr = None

        self.shared.add_message({
            'time': datetime.now().strftime('%H:%M:%S'),
            'sender': sender,
            'text': msg_text,
            'channel': payload.get('channel_idx'),
            'direction': 'in',
            'snr': msg_snr,
            'path_len': payload.get('path_len', 0),
            'sender_pubkey': sender_pubkey,
            'path_hashes': [],       # No path data from companion event
            'message_hash': msg_hash,
        })

        # BOT: check for keyword and queue reply (fallback path)
        self._bot_check_and_queue(
            sender=sender,
            text=msg_text,
            channel_idx=payload.get('channel_idx'),
            snr=msg_snr,
            path_len=payload.get('path_len', 0),
        )

    def _on_contact_msg(self, event) -> None:
        """Callback for received DMs; resolves sender name via pubkey."""
        payload = event.payload
        pubkey = payload.get('pubkey_prefix', '')
        sender = ''

        debug_print(f"DM payload keys: {list(payload.keys())}")
        debug_print(f"DM payload: {payload}")

        if pubkey:
            sender = self.shared.get_contact_name_by_prefix(pubkey)

        if not sender:
            sender = pubkey[:8] if pubkey else ''

        self.shared.add_message({
            'time': datetime.now().strftime('%H:%M:%S'),
            'sender': sender,
            'text': payload.get('text', ''),
            'channel': None,
            'direction': 'in',
            'snr': payload.get('SNR') or payload.get('snr'),
            'path_len': payload.get('path_len', 0),
            'sender_pubkey': pubkey,
            'path_hashes': [],  # DMs use out_path from contact record
        })

        debug_print(
            f"DM received from {sender}: "
            f"{payload.get('text', '')[:30]}"
        )
