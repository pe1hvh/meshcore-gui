"""
Ed25519 JWT authentication token for LetsMesh MQTT broker.

Generates tokens compatible with the ``@michaelhart/meshcore-decoder``
``createAuthToken()`` reference implementation.  Uses PyNaCl for
Ed25519 signing — no Node.js dependency.

Token format::

    base64url(header) . base64url(payload) . base64url(signature)

Where signature = Ed25519.sign(header_b64 + "." + payload_b64, private_key)

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import base64
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Token lifetime defaults
DEFAULT_TOKEN_LIFETIME_S = 3600  # 1 hour
TOKEN_REFRESH_MARGIN_S = 300     # Refresh 5 minutes before expiry


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding (JWT standard).

    Args:
        data: Raw bytes to encode.

    Returns:
        Base64url-encoded string without ``=`` padding.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration.

    Args:
        s: Base64url-encoded string.

    Returns:
        Decoded bytes.
    """
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_auth_token(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int = DEFAULT_TOKEN_LIFETIME_S,
) -> str:
    """Create a LetsMesh-compatible Ed25519 JWT authentication token.

    Mirrors ``@michaelhart/meshcore-decoder`` ``createAuthToken()``
    to produce tokens accepted by mqtt-eu-v1.letsmesh.net.

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64-char hex device Ed25519 private key (seed).
        audience:        Broker hostname (e.g. ``mqtt-eu-v1.letsmesh.net``).
        lifetime_s:      Token validity in seconds (default 3600).

    Returns:
        JWT-style token string: ``header.payload.signature``

    Raises:
        ValueError: If key format is invalid.
        ImportError: If PyNaCl is not installed.
    """
    try:
        from nacl.signing import SigningKey
    except ImportError:
        raise ImportError(
            "PyNaCl is required for MQTT authentication. "
            "Install with: pip install PyNaCl"
        )

    # Validate key lengths
    if len(public_key_hex) != 64:
        raise ValueError(
            f"Public key must be 64 hex chars, got {len(public_key_hex)}"
        )
    if len(private_key_hex) != 64:
        raise ValueError(
            f"Private key must be 64 hex chars, got {len(private_key_hex)}"
        )

    # Parse keys
    try:
        private_key_bytes = bytes.fromhex(private_key_hex)
        signing_key = SigningKey(private_key_bytes)
    except Exception as exc:
        raise ValueError(f"Invalid private key: {exc}") from exc

    # Build header (matches meshcore-decoder format)
    header = {"alg": "EdDSA", "typ": "JWT"}

    # Build payload
    now = int(time.time())
    payload = {
        "publicKey": public_key_hex.upper(),
        "aud": audience,
        "iat": now,
        "exp": now + lifetime_s,
    }

    # Encode parts
    header_b64 = _base64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )

    # Sign: Ed25519(header_b64 + "." + payload_b64)
    message = f"{header_b64}.{payload_b64}".encode("utf-8")
    signed = signing_key.sign(message)
    # signed.signature is the 64-byte Ed25519 signature
    signature_b64 = _base64url_encode(signed.signature)

    token = f"{header_b64}.{payload_b64}.{signature_b64}"
    return token


class TokenManager:
    """Manages JWT token lifecycle with automatic refresh.

    Generates tokens on demand and refreshes them before expiry.
    Thread-safe for use from paho-mqtt callbacks.

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64-char hex device Ed25519 private key (seed).
        lifetime_s:      Token validity in seconds.
    """

    def __init__(
        self,
        public_key_hex: str,
        private_key_hex: str,
        lifetime_s: int = DEFAULT_TOKEN_LIFETIME_S,
    ) -> None:
        self._public_key = public_key_hex
        self._private_key = private_key_hex
        self._lifetime_s = lifetime_s
        self._current_token: Optional[str] = None
        self._token_expiry: float = 0.0

    @property
    def username(self) -> str:
        """MQTT username: ``v1_{PUBLIC_KEY}``."""
        return f"v1_{self._public_key.upper()}"

    def get_token(self, audience: str) -> str:
        """Get a valid token, refreshing if necessary.

        Args:
            audience: Broker hostname for the ``aud`` claim.

        Returns:
            Valid JWT token string.
        """
        now = time.time()
        if (
            self._current_token is None
            or now >= self._token_expiry - TOKEN_REFRESH_MARGIN_S
        ):
            self._current_token = create_auth_token(
                self._public_key,
                self._private_key,
                audience,
                self._lifetime_s,
            )
            self._token_expiry = now + self._lifetime_s
            logger.debug(
                "Generated new auth token for %s (expires in %ds)",
                audience,
                self._lifetime_s,
            )
        return self._current_token

    def invalidate(self) -> None:
        """Force token regeneration on next ``get_token()`` call."""
        self._current_token = None
        self._token_expiry = 0.0
