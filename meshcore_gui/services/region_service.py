"""
Region (flood scope) logic for MeshCore GUI.

MeshCore restricts the reach of flood packets with *regions*, also called
*scopes*.  A sender stamps a flood packet with a 16-bit transport code
that is derived from the region key; repeaters configured for that region
forward the packet, others drop it.

Region key
~~~~~~~~~~
For a publicly known (hashtag) region the key is
``SHA-256("#" + name)[:16]`` — the same rule the firmware applies in
``TransportKeyStore::getAutoKeyFor``.  The key is computed here and handed
to the library as raw bytes, so the result does not depend on whether the
installed ``meshcore`` version prefixes the ``#`` itself.

Transport code
~~~~~~~~~~~~~~
``TransportKey::calcTransportCode`` in the firmware computes::

    HMAC-SHA256(key, payload_type || payload)[:2]   (little-endian uint16)

with ``0x0000`` and ``0xFFFF`` reserved (bumped to ``0x0001`` / ``0xFFFE``).
The region name cannot be recovered from the code; a received packet is
attributed by trying every known region, in the same way channel keys are
tried in :class:`~meshcore_gui.ble.packet_decoder.PacketDecoder`.

Per-channel default
~~~~~~~~~~~~~~~~~~~
The companion firmware has a single device-wide default scope and one
session-wide send override (``// TODO: have per-channel send_scope`` in
``companion_radio/MyMesh.cpp``).  The per-channel default is therefore an
application concept: :meth:`RegionService.resolve_send_region` decides the
region, and the command handler sets the override just for that send.
"""

import hashlib
import hmac
from typing import Callable, List, Optional

from meshcore_gui.config import debug_print

# Length of a region (transport) key in bytes.
REGION_KEY_LEN: int = 16

# Prefix used in the message line for a code that matches no known region.
UNKNOWN_REGION_PREFIX: str = "?"


def normalize_region_name(name: str) -> str:
    """Return a region name without surrounding whitespace or leading ``#``.

    Region names are stored and displayed without the hashtag; the ``#`` is
    only added when deriving the key.  Case is preserved because it is part
    of the hashed name.

    Args:
        name: Region name as typed by the user (with or without ``#``).

    Returns:
        Normalized name, or an empty string for blank input.
    """
    return (name or "").strip().lstrip("#").strip()


def region_key(name: str) -> bytes:
    """Derive the 16-byte transport key of a hashtag region.

    Args:
        name: Region name, with or without leading ``#``.

    Returns:
        ``SHA-256("#" + name)[:16]``.
    """
    tag = "#" + normalize_region_name(name)
    return hashlib.sha256(tag.encode("utf-8")).digest()[:REGION_KEY_LEN]


def transport_code(key: bytes, payload_type: int, payload: bytes) -> int:
    """Compute the transport code a region key gives a packet.

    Mirrors ``TransportKey::calcTransportCode`` in the MeshCore firmware.

    Args:
        key:          16-byte region key.
        payload_type: Numeric payload type (0-15) from the packet header.
        payload:      Packet payload bytes (after header, codes and path).

    Returns:
        Transport code as an unsigned 16-bit integer.
    """
    digest = hmac.new(
        key, bytes([payload_type & 0x0F]) + payload, hashlib.sha256,
    ).digest()
    code = int.from_bytes(digest[:2], "little")
    if code == 0x0000:
        code = 0x0001
    elif code == 0xFFFF:
        code = 0xFFFE
    return code


# Firmware limit for the default scope name: 31 bytes incl. terminator,
# the name is stored with its leading '#'.
DEFAULT_SCOPE_NAME_MAX_BYTES: int = 30


def default_scope_payload(name: str) -> bytes:
    """Build the payload of ``CMD_SET_DEFAULT_FLOOD_SCOPE`` (after the code).

    The firmware expects ``name[31] + key[16]`` to set a default scope and
    a frame without payload to clear it.  The payload is built here because
    ``meshcore`` 2.3.17 ``set_default_flood_scope()`` cannot clear (``None``
    raises, ``""`` sends an empty name the firmware rejects) and pads by
    character count instead of byte count.

    Args:
        name: Region name, with or without leading ``#``; empty clears.

    Returns:
        Payload bytes; empty for "clear".

    Raises:
        ValueError: When the name is longer than the firmware allows.
    """
    region = normalize_region_name(name)
    if not region:
        return b""
    tag = ("#" + region).encode("utf-8")
    if len(tag) > DEFAULT_SCOPE_NAME_MAX_BYTES:
        raise ValueError(
            f"region name too long ({len(tag)} bytes, max "
            f"{DEFAULT_SCOPE_NAME_MAX_BYTES} incl. '#')"
        )
    return tag + b"\0" * (31 - len(tag)) + region_key(region)


def format_unknown_region(code: int) -> str:
    """Return the display label for a code that matches no known region.

    Args:
        code: Transport code from the packet.

    Returns:
        Label such as ``"?1a2b"``.
    """
    return f"{UNKNOWN_REGION_PREFIX}{code:04x}"


class RegionService:
    """Decides send regions and attributes received transport codes.

    Args:
        known_regions:   Callable returning the currently known region
                         names (normalized, without ``#``).
        channel_region:  Callable returning the default region stored for
                         a channel name (empty string when none).
        device_default:  Callable returning the device default scope name
                         (empty string when none or unknown).
    """

    def __init__(
        self,
        known_regions: Callable[[], List[str]],
        channel_region: Callable[[str], str],
        device_default: Callable[[], str],
    ) -> None:
        self._known_regions = known_regions
        self._channel_region = channel_region
        self._device_default = device_default

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def resolve_send_region(
        self, channel_name: str, override: Optional[str] = None,
    ) -> str:
        """Return the region a channel message must be sent with.

        Args:
            channel_name: Name of the target channel.
            override:     Region chosen for this single message; ``None``
                          or empty means "use the channel default".

        Returns:
            Region name to set as send override, or an empty string when
            no override is needed (the device default then applies).
        """
        chosen = normalize_region_name(override or "")
        if chosen:
            return chosen
        return normalize_region_name(self._channel_region(channel_name or ""))

    def label_for_sent(self, send_region: str) -> str:
        """Return the region label to show on an outgoing message.

        Args:
            send_region: Result of :meth:`resolve_send_region`.

        Returns:
            The override region, or the device default when no override
            was set (empty string when that is unknown as well).
        """
        return send_region or normalize_region_name(self._device_default())

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def match_transport_code(
        self, code: Optional[int], payload_type: int, payload: bytes,
    ) -> str:
        """Attribute a received transport code to a known region.

        Args:
            code:         ``transport_codes[0]`` of the packet, or ``None``
                          for a packet without transport codes.
            payload_type: Numeric payload type of the packet.
            payload:      Packet payload bytes.

        Returns:
            Region name on a match, ``"?xxxx"`` for an unknown region and
            an empty string for an unscoped packet.
        """
        if code is None or code == 0:
            return ""
        for name in self._known_regions():
            if transport_code(region_key(name), payload_type, payload) == code:
                return name
        debug_print(f"RegionService: transport code {code:04x} matches no known region")
        return format_unknown_region(code)
