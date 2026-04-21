"""
Channel management service for MeshCore GUI.

Provides pure-Python helpers for:
- Generating random private channel secrets.
- Deriving deterministic hashtag-channel keys (SHA-256 of name).
- Building MeshCore-compatible QR code URLs.
- Rendering QR codes as base64-encoded PNG data URIs for inline display.

No GUI or BLE dependencies — safe to import from any layer.
"""

import base64
import io
import os
from hashlib import sha256
from typing import Dict, List
from urllib.parse import urlencode


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The globally known public-channel secret (index 0).
# Every MeshCore device ships with this key for the default "Public" channel.
# Shared here for reference only; not used by the Add Channel dialog since
# index-0 / Public is out of scope for this feature.
PUBLIC_CHANNEL_SECRET: bytes = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def generate_secret() -> bytes:
    """Generate a cryptographically secure 16-byte random channel secret.

    Returns:
        16 random bytes suitable for a new private channel.
    """
    return os.urandom(16)


def derive_hashtag_key(name: str) -> bytes:
    """Derive the deterministic key for a hashtag channel.

    MeshCore computes the channel key as the first 16 bytes of
    ``SHA-256(name.encode('utf-8'))``.  Because the ``#`` sign is part
    of the name (e.g. ``"#localmesh"``), callers must pass the full
    name including the hash symbol.

    The library's ``set_channel()`` performs this derivation itself when
    ``channel_name.startswith('#')``, so this helper is provided for
    informational display only.

    Args:
        name: Channel name including the leading ``#`` (e.g. ``"#test"``).

    Returns:
        16-byte derived key.
    """
    return sha256(name.encode("utf-8")).digest()[:16]


def secret_to_hex(secret: bytes) -> str:
    """Convert a 16-byte channel secret to a lowercase hex string (32 chars).

    Args:
        secret: 16-byte channel secret.

    Returns:
        32-character lowercase hex string.
    """
    return secret.hex()


# ---------------------------------------------------------------------------
# QR code helpers
# ---------------------------------------------------------------------------

def build_qr_url(name: str, secret: bytes) -> str:
    """Build the official MeshCore QR code URL for sharing a private channel.

    Format (per MeshCore docs)::

        meshcore://channel/add?name=<name>&secret=<32-hex>

    This URL is recognised by the official MeshCore mobile app, allowing
    recipients to join the channel by scanning the QR code.

    Args:
        name:   Channel name (without leading ``#`` for private channels).
        secret: 16-byte channel secret.

    Returns:
        URL string ready to be encoded into a QR code.
    """
    params = {"name": name, "secret": secret.hex()}
    return "meshcore://channel/add?" + urlencode(params)


def generate_qr_base64(name: str, secret: bytes) -> str:
    """Generate a QR code PNG as a base64 data URI for inline display.

    Uses the ``qrcode`` library with Pillow for image rendering.  Returns
    an empty string if either library is unavailable, allowing callers to
    degrade gracefully (hide the QR widget rather than crashing).

    Args:
        name:   Private channel name.
        secret: 16-byte channel secret.

    Returns:
        ``data:image/png;base64,...`` string, or ``""`` on import error.
    """
    try:
        import qrcode  # type: ignore[import]
        from PIL import Image  # noqa: F401 — imported for side-effect (PIL check)

        url = build_qr_url(name, secret)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img: Image.Image = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    except ImportError:
        return ""


# ---------------------------------------------------------------------------
# Sorting helpers
# ---------------------------------------------------------------------------

# Sort-mode string constants. Exposed here so both the GUI layer and the
# :class:`ChannelSortStore` can share the same vocabulary without one
# having to import the other.
CHANNEL_SORT_BY_INDEX: str = "index"
CHANNEL_SORT_BY_NAME: str = "name"


def sort_channels(channels: List[Dict], mode: str) -> List[Dict]:
    """Return a new channel list sorted according to ``mode``.

    The Public channel (``idx == 0``) is always pinned to the top of
    the returned list regardless of the requested mode. Public is the
    default broadcast slot and moving it would be confusing when the
    list is used for quick navigation.

    The input list is not mutated; each dict reference is copied across
    unchanged so the ``idx`` and ``name`` fields — and any other
    channel metadata — remain coupled.

    Args:
        channels: Channel dicts as produced by SharedData. Each dict is
            expected to contain at least an ``idx`` (int) and a
            ``name`` (str).
        mode:     Either :data:`CHANNEL_SORT_BY_INDEX` to keep the
            ascending-index order (the native MeshCore ordering) or
            :data:`CHANNEL_SORT_BY_NAME` for case-insensitive
            alphabetical order. Unknown values fall back to index mode.

    Returns:
        A new list. The Public channel (if present) is first, followed
        by the remaining channels in the order dictated by ``mode``.
    """
    if not channels:
        return []

    public = [ch for ch in channels if ch.get("idx") == 0]
    rest = [ch for ch in channels if ch.get("idx") != 0]

    if mode == CHANNEL_SORT_BY_NAME:
        rest_sorted = sorted(
            rest, key=lambda ch: (ch.get("name") or "").casefold()
        )
    else:
        # SORT_BY_INDEX (default). An explicit sort guarantees a
        # deterministic order even if the upstream list is not already
        # ordered by index.
        rest_sorted = sorted(rest, key=lambda ch: ch.get("idx", 0))

    return public + rest_sorted
