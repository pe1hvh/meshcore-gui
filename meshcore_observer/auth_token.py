"""
Ed25519 JWT authentication token for LetsMesh MQTT broker.

Generates tokens compatible with the ``@michaelhart/meshcore-decoder``
``createAuthToken()`` reference implementation.

Strategy:
    1. **Node.js** — calls meshcore-decoder directly (reference impl)
    2. **PyNaCl** — pure Python fallback if Node.js is unavailable

                   Author: PE1HVH
                  Version: 2.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import base64
import json
import logging
import os
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Token lifetime defaults
DEFAULT_TOKEN_LIFETIME_S = 3600  # 1 hour
TOKEN_REFRESH_MARGIN_S = 300     # Refresh 5 minutes before expiry

# Node.js environment — meshcore-decoder installed globally
_NODE_ENV = {
    **os.environ,
    "NODE_PATH": os.environ.get("NODE_PATH", "/usr/lib/node_modules"),
}

# Cache availability check
_node_available: Optional[bool] = None


def _check_node_available() -> bool:
    """Check if Node.js and meshcore-decoder are available."""
    global _node_available
    if _node_available is not None:
        return _node_available

    if not shutil.which("node"):
        logger.debug("Node.js not found in PATH")
        _node_available = False
        return False

    try:
        result = subprocess.run(
            ["node", "-e",
             "require('@michaelhart/meshcore-decoder').createAuthToken"],
            env=_NODE_ENV,
            capture_output=True,
            timeout=5,
        )
        _node_available = result.returncode == 0
        if _node_available:
            logger.info("Using Node.js meshcore-decoder for MQTT auth tokens")
        else:
            logger.debug(
                "meshcore-decoder not available: %s",
                result.stderr.decode().strip(),
            )
    except Exception as exc:
        logger.debug("Node.js check failed: %s", exc)
        _node_available = False

    return _node_available


def _create_token_nodejs(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int,
) -> str:
    """Create auth token via Node.js meshcore-decoder (reference impl).

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64-char hex device Ed25519 private key (seed).
        audience:        Broker hostname.
        lifetime_s:      Token validity in seconds.

    Returns:
        JWT token string.

    Raises:
        RuntimeError: If Node.js call fails.
    """
    js_code = f"""
const {{ createAuthToken }} = require('@michaelhart/meshcore-decoder');
(async () => {{
    const payload = {{
        publicKey: '{public_key_hex.upper()}',
        aud: '{audience}',
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + {lifetime_s}
    }};
    const token = await createAuthToken(payload, '{private_key_hex}{public_key_hex.lower()}', '{public_key_hex.upper()}');
    process.stdout.write(token);
}})();
"""

    result = subprocess.run(
        ["node", "-e", js_code],
        env=_NODE_ENV,
        capture_output=True,
        timeout=10,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode().strip()
        raise RuntimeError(f"Node.js token generation failed: {stderr}")

    token = result.stdout.decode().strip()
    if not token or token.count(".") != 2:
        raise RuntimeError(
            f"Node.js returned invalid token: {token[:50]}..."
        )

    return token


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding (JWT standard)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _create_token_pynacl(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int,
) -> str:
    """Create auth token via PyNaCl (fallback).

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64-char hex device Ed25519 private key (seed).
        audience:        Broker hostname.
        lifetime_s:      Token validity in seconds.

    Returns:
        JWT token string.
    """
    try:
        from nacl.signing import SigningKey
    except ImportError:
        raise ImportError(
            "Neither Node.js meshcore-decoder nor PyNaCl are available. "
            "Install one: npm install -g @michaelhart/meshcore-decoder "
            "OR pip install PyNaCl"
        )

    private_key_bytes = bytes.fromhex(private_key_hex)
    signing_key = SigningKey(private_key_bytes)

    header = {"alg": "Ed25519", "typ": "JWT"}

    now = int(time.time())
    payload = {
        "publicKey": public_key_hex.upper(),
        "aud": audience,
        "iat": now,
        "exp": now + lifetime_s,
    }

    header_b64 = _base64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )

    message = f"{header_b64}.{payload_b64}".encode("utf-8")
    signed = signing_key.sign(message)
    signature_b64 = _base64url_encode(signed.signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def create_auth_token(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int = DEFAULT_TOKEN_LIFETIME_S,
) -> str:
    """Create a LetsMesh-compatible Ed25519 JWT authentication token.

    Tries Node.js meshcore-decoder first (reference implementation),
    falls back to PyNaCl if unavailable.

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64-char hex device Ed25519 private key (seed).
        audience:        Broker hostname (e.g. ``mqtt-eu-v1.letsmesh.net``).
        lifetime_s:      Token validity in seconds (default 3600).

    Returns:
        JWT-style token string: ``header.payload.signature``

    Raises:
        ValueError: If key format is invalid.
    """
    # Validate key lengths
    if len(public_key_hex) != 64:
        raise ValueError(
            f"Public key must be 64 hex chars, got {len(public_key_hex)}"
        )
    if len(private_key_hex) != 64:
        raise ValueError(
            f"Private key must be 64 hex chars, got {len(private_key_hex)}"
        )

    # Strategy 1: Node.js meshcore-decoder (reference implementation)
    if _check_node_available():
        try:
            token = _create_token_nodejs(
                public_key_hex, private_key_hex, audience, lifetime_s,
            )
            logger.debug("Token generated via Node.js meshcore-decoder")
            return token
        except Exception as exc:
            logger.warning(
                "Node.js token generation failed, falling back to PyNaCl: %s",
                exc,
            )

    # Strategy 2: PyNaCl fallback
    token = _create_token_pynacl(
        public_key_hex, private_key_hex, audience, lifetime_s,
    )
    logger.debug("Token generated via PyNaCl (fallback)")
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
