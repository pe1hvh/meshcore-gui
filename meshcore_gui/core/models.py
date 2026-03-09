"""
Domain model for MeshCore GUI.

Typed dataclasses that replace untyped Dict objects throughout the
codebase.  Each class represents a core domain concept.  All classes
are immutable-friendly (frozen is not used because SharedData mutates
collections, but fields are not reassigned after construction).

Migration note
~~~~~~~~~~~~~~
``SharedData.get_snapshot()`` still returns a plain dict for backward
compatibility with the NiceGUI timer loop.  Inside that dict, however,
``messages`` and ``rx_log`` are now lists of dataclass instances.
UI code can access attributes directly (``msg.sender``) or fall back
to ``dataclasses.asdict(msg)`` if a plain dict is needed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A channel message or direct message (DM).

    Attributes:
        time:          Formatted timestamp (HH:MM:SS).
        sender:        Display name of the sender.
        text:          Message body.
        channel:       Channel index, or ``None`` for a DM.
        direction:     ``'in'`` for received, ``'out'`` for sent.
        snr:           Signal-to-noise ratio (dB), if available.
        path_len:      Hop count from the LoRa frame header.
        sender_pubkey: Full public key of the sender (hex string).
        path_hashes:   List of 2-char hex strings, one per repeater.
        path_names:    List of resolved display names for each path hash,
                       captured at receive time so the archive is self-contained.
        message_hash:  Deterministic packet identifier (hex string).
        channel_name:  Human-readable channel name (resolved at add time).
    """

    time: str
    sender: str
    text: str
    channel: Optional[int]
    direction: str
    snr: Optional[float] = None
    path_len: int = 0
    sender_pubkey: str = ""
    path_hashes: List[str] = field(default_factory=list)
    path_names: List[str] = field(default_factory=list)
    message_hash: str = ""
    channel_name: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Message":
        """Create a Message from an archive dictionary.

        Args:
            d: Dictionary as stored by MessageArchive.

        Returns:
            Message dataclass instance.
        """
        return Message(
            time=d.get("time", ""),
            sender=d.get("sender", ""),
            text=d.get("text", ""),
            channel=d.get("channel"),
            direction=d.get("direction", "in"),
            snr=d.get("snr"),
            path_len=d.get("path_len", 0),
            sender_pubkey=d.get("sender_pubkey", ""),
            path_hashes=d.get("path_hashes", []),
            path_names=d.get("path_names", []),
            message_hash=d.get("message_hash", ""),
            channel_name=d.get("channel_name", ""),
        )

    # -- Timestamp helper ------------------------------------------------

    @staticmethod
    def now_timestamp() -> str:
        """Current time formatted as ``HH:MM:SS``."""
        return datetime.now().strftime('%H:%M:%S')

    # -- Factory methods -------------------------------------------------

    @classmethod
    def incoming(
        cls,
        sender: str,
        text: str,
        channel: Optional[int],
        *,
        time: str = "",
        snr: Optional[float] = None,
        path_len: int = 0,
        sender_pubkey: str = "",
        path_hashes: Optional[List[str]] = None,
        path_names: Optional[List[str]] = None,
        message_hash: str = "",
    ) -> "Message":
        """Create an incoming message with auto-generated timestamp.

        Args:
            sender:        Display name of the sender.
            text:          Message body.
            channel:       Channel index, or ``None`` for a DM.
            time:          Optional pre-generated timestamp (default: now).
            snr:           Signal-to-noise ratio (dB).
            path_len:      Hop count from the LoRa frame header.
            sender_pubkey: Full public key of the sender (hex string).
            path_hashes:   List of 2-char hex strings per repeater.
            path_names:    Resolved display names for each path hash.
            message_hash:  Deterministic packet identifier (hex string).
        """
        return cls(
            time=time or cls.now_timestamp(),
            sender=sender,
            text=text,
            channel=channel,
            direction='in',
            snr=snr,
            path_len=path_len,
            sender_pubkey=sender_pubkey,
            path_hashes=path_hashes or [],
            path_names=path_names or [],
            message_hash=message_hash,
        )

    @classmethod
    def outgoing(
        cls,
        text: str,
        channel: Optional[int],
        *,
        sender_pubkey: str = "",
    ) -> "Message":
        """Create an outgoing message (sender ``'Me'``, auto-timestamp).

        Args:
            text:          Message body.
            channel:       Channel index, or ``None`` for a DM.
            sender_pubkey: Recipient public key (hex string).
        """
        return cls(
            time=cls.now_timestamp(),
            sender='Me',
            text=text,
            channel=channel,
            direction='out',
            sender_pubkey=sender_pubkey,
        )

    # -- Display formatting ----------------------------------------------

    def format_line(
        self,
        channel_names: Optional[Dict[int, str]] = None,
        show_channel: bool = True,
        sender_prefix: str = '',
    ) -> str:
        """Format as a single display line for the messages panel.

        Produces the same output as the original ``messages_panel.py``
        inline formatting, e.g.::

            12:34:56 ← [Public] [2h✓] PE1ABC: Hello mesh!

        When *show_channel* is ``False`` the ``[channel]`` / ``[DM]``
        tag is omitted (useful when the panel header already indicates
        the active channel).

        Args:
            channel_names: Optional ``{channel_idx: name}`` lookup.
                Falls back to ``self.channel_name``, then ``'ch<idx>'``.
            show_channel: Include ``[channel]`` / ``[DM]`` prefix.
                Defaults to ``True`` for backward compatibility.
            sender_prefix: Optional prefix placed before the sender name,
                e.g. a node-type icon from the map/contact view.

        Returns:
            Formatted single-line string.
        """
        direction = '→' if self.direction == 'out' else '←'

        ch_label = ''
        if show_channel:
            if self.channel is not None:
                if channel_names and self.channel in channel_names:
                    ch_name = channel_names[self.channel]
                elif self.channel_name:
                    ch_name = self.channel_name
                else:
                    ch_name = f'ch{self.channel}'
                ch_label = f'[{ch_name}] '
            else:
                ch_label = '[DM] '

        if self.direction == 'in' and self.path_len > 0:
            hop_tag = f'[{self.path_len}h{"✓" if self.path_hashes else ""}] '
        else:
            hop_tag = ''

        sender_display = f"{sender_prefix}{self.sender}" if self.sender else ''

        if self.sender:
            return f"{self.time} {direction} {ch_label}{hop_tag}{sender_display}: {self.text}"
        return f"{self.time} {direction} {ch_label}{hop_tag}{self.text}"


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    """A known mesh network node.

    Attributes:
        pubkey:       Full public key (hex string).
        adv_name:     Advertised display name.
        type:         Node type (0=unknown, 1=CLI, 2=REP, 3=ROOM).
        adv_lat:      Advertised latitude (0.0 if unknown).
        adv_lon:      Advertised longitude (0.0 if unknown).
        out_path:     Hex string of stored route (2 hex chars per hop).
        out_path_len: Number of hops in ``out_path``.
    """

    pubkey: str
    adv_name: str = ""
    type: int = 0
    adv_lat: float = 0.0
    adv_lon: float = 0.0
    out_path: str = ""
    out_path_len: int = 0

    @staticmethod
    def from_dict(pubkey: str, d: dict) -> "Contact":
        """Create a Contact from a meshcore contacts dict entry."""
        return Contact(
            pubkey=pubkey,
            adv_name=d.get("adv_name", ""),
            type=d.get("type", 0),
            adv_lat=d.get("adv_lat", 0.0),
            adv_lon=d.get("adv_lon", 0.0),
            out_path=d.get("out_path", ""),
            out_path_len=d.get("out_path_len", 0),
        )


# ---------------------------------------------------------------------------
# DeviceInfo
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Radio device identification and configuration.

    Attributes:
        name:             Device display name.
        public_key:       Device public key (hex string).
        radio_freq:       Radio frequency in MHz.
        radio_sf:         LoRa spreading factor.
        radio_bw:         Bandwidth in kHz.
        tx_power:         Transmit power in dBm.
        adv_lat:          Advertised latitude.
        adv_lon:          Advertised longitude.
        firmware_version: Firmware version string.
    """

    name: str = ""
    public_key: str = ""
    radio_freq: float = 0.0
    radio_sf: int = 0
    radio_bw: float = 0.0
    tx_power: int = 0
    adv_lat: float = 0.0
    adv_lon: float = 0.0
    firmware_version: str = ""


# ---------------------------------------------------------------------------
# RxLogEntry
# ---------------------------------------------------------------------------

@dataclass
class RxLogEntry:
    """A single RX log entry from the radio.

    Attributes:
        time:         Formatted timestamp (HH:MM:SS).
        snr:          Signal-to-noise ratio (dB).
        rssi:         Received signal strength (dBm).
        payload_type: Packet type identifier.
        hops:         Number of hops (path_len from frame header).
        message_hash: Optional message hash for correlation with messages.
        path_hashes:  2-char hex repeater hashes from decoded packet.
        path_names:   Resolved display names for each path hash.
    """

    time: str
    snr: float = 0.0
    rssi: float = 0.0
    payload_type: str = "?"
    hops: int = 0
    message_hash: str = ""
    path_hashes: List[str] = field(default_factory=list)
    path_names: List[str] = field(default_factory=list)
    sender: str = ""
    receiver: str = ""
    # ── Fase 1 Observer fields (raw packet metadata) ──
    raw_payload: str = ""       # Raw hex packet data
    packet_len: int = 0         # Total packet length (bytes)
    payload_len: int = 0        # Payload length (bytes)
    route_type: str = ""        # "F" (flood) or "D" (direct)
    packet_type_num: int = -1   # Numeric packet type (0-15)


# ---------------------------------------------------------------------------
# RouteNode
# ---------------------------------------------------------------------------

@dataclass
class RouteNode:
    """A node in a message route (sender, repeater or receiver).

    Attributes:
        name:   Display name (or ``'-'`` if unknown).
        lat:    Latitude (0.0 if unknown).
        lon:    Longitude (0.0 if unknown).
        type:   Node type (0=unknown, 1=CLI, 2=REP, 3=ROOM).
        pubkey: Public key or 2-char hash (hex string).
    """

    name: str
    lat: float = 0.0
    lon: float = 0.0
    type: int = 0
    pubkey: str = ""

    @property
    def has_location(self) -> bool:
        """True if the node has GPS coordinates."""
        return self.lat != 0 or self.lon != 0
