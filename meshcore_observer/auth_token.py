"""
Ed25519 JWT authentication token for LetsMesh MQTT broker.

Generates tokens compatible with the ``@michaelhart/meshcore-decoder``
``createAuthToken()`` reference implementation.

Private key formats supported:

- **128 hex chars** (64 bytes): Full orlp/ed25519 expanded key as stored
  in ``device_identity.json`` by ``device_identity.py``.
  Format: ``[clamped_scalar(32)][nonce_prefix(32)]``.
- **64 hex chars** (32 bytes): Legacy Ed25519 seed.  Works with PyNaCl
  fallback and with Node.js (seed + pubkey concatenation).

Strategy:
    1. **Node.js** — calls meshcore-decoder directly (reference impl)
    2. **PyNaCl** — pure Python fallback (seed-only, 64-char keys)

                   Author: PE1HVH
                  Version: 2.1.0
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
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

DEFAULT_TOKEN_LIFETIME_S = 3600  # 1 hour
TOKEN_REFRESH_MARGIN_S = 300     # Refresh 5 minutes before expiry

VALID_PRIVATE_KEY_LENGTHS = (64, 128)  # 32-byte seed or 64-byte expanded

def _resolve_node_path() -> str:
    """Resolve NODE_PATH — check common global install locations."""
    env_val = os.environ.get("NODE_PATH", "")
    if env_val:
        return env_val
    # Common locations: Debian/Ubuntu, npm global on Pi/macOS, nvm
    for candidate in (
        "/usr/lib/node_modules",
        "/usr/local/lib/node_modules",
        Path.home() / ".npm-global" / "lib" / "node_modules",
    ):
        if Path(candidate).is_dir():
            return str(candidate)
    return "/usr/lib/node_modules"  # fallback


_NODE_ENV = {**os.environ, "NODE_PATH": _resolve_node_path()}

_node_available: Optional[bool] = None


# ── Key helpers ──────────────────────────────────────────────────────


def _is_valid_hex(value: str, allowed_lengths: tuple) -> bool:
    """Check if *value* is a hex string with one of *allowed_lengths*."""
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return len(value) in allowed_lengths


def _build_nodejs_private_key(
    private_key_hex: str,
    public_key_hex: str,
) -> str:
    """Return the 128-char hex private key meshcore-decoder expects.

    - 128-char input → already complete orlp expanded key; pass through.
    - 64-char input  → legacy seed; concatenate ``seed + pubkey``.
    """
    if len(private_key_hex) == 128:
        return private_key_hex
    return private_key_hex + public_key_hex.lower()


# ── Node.js strategy ────────────────────────────────────────────────


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
    """Create auth token via Node.js meshcore-decoder.

    Handles both 64-char seeds (concatenated with pubkey) and
    128-char orlp expanded keys (passed directly).
    """
    full_priv = _build_nodejs_private_key(private_key_hex, public_key_hex)
    pub_upper = public_key_hex.upper()

    js_code = f"""
const {{ createAuthToken }} = require('@michaelhart/meshcore-decoder');
(async () => {{
    const payload = {{
        publicKey: '{pub_upper}',
        aud: '{audience}',
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + {lifetime_s}
    }};
    const token = await createAuthToken(payload, '{full_priv}', '{pub_upper}');
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


# ── PyNaCl strategy ──────────────────────────────────────────────────


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding (JWT standard)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _create_token_pynacl(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int,
) -> str:
    """Create auth token via PyNaCl (fallback, 64-char seed only).

    The orlp/ed25519 expanded format (128-char) cannot be used with
    PyNaCl because the expanded key is not a seed — it is the result
    of ``SHA-512(seed)`` with clamping applied.  PyNaCl's ``SigningKey``
    expects the original 32-byte seed.
    """
    if len(private_key_hex) == 128:
        raise ValueError(
            "PyNaCl fallback requires a 64-char Ed25519 seed. "
            "The 128-char orlp/ed25519 expanded key is only supported "
            "via Node.js meshcore-decoder. "
            "Install: npm install -g @michaelhart/meshcore-decoder"
        )

    try:
        from nacl.signing import SigningKey
    except ImportError:
        raise ImportError(
            "Neither Node.js meshcore-decoder nor PyNaCl are available. "
            "Install one: npm install -g @michaelhart/meshcore-decoder "
            "OR pip install PyNaCl"
        )

    signing_key = SigningKey(bytes.fromhex(private_key_hex))

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


# ── Public API ───────────────────────────────────────────────────────


def create_auth_token(
    public_key_hex: str,
    private_key_hex: str,
    audience: str,
    lifetime_s: int = DEFAULT_TOKEN_LIFETIME_S,
) -> str:
    """Create a LetsMesh-compatible Ed25519 JWT authentication token.

    Tries Node.js meshcore-decoder first (reference implementation),
    falls back to PyNaCl if unavailable (seed-only).

    Args:
        public_key_hex:  64-char hex device public key (from appstart).
        private_key_hex: Ed25519 private key — either 128-char hex
                         (orlp expanded, preferred) or 64-char hex (seed).
        audience:        Broker hostname (e.g. ``mqtt-eu-v1.letsmesh.net``).
        lifetime_s:      Token validity in seconds (default 3600).

    Returns:
        JWT-style token string: ``header.payload.signature``

    Raises:
        ValueError: If key format is invalid.
    """
    if not _is_valid_hex(public_key_hex, (64,)):
        raise ValueError(
            f"Public key must be 64 hex chars, got {len(public_key_hex)}"
        )
    if not _is_valid_hex(private_key_hex, VALID_PRIVATE_KEY_LENGTHS):
        raise ValueError(
            f"Private key must be 64 or 128 hex chars, "
            f"got {len(private_key_hex)}"
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

    # Strategy 2: PyNaCl fallback (seed-only)
    token = _create_token_pynacl(
        public_key_hex, private_key_hex, audience, lifetime_s,
    )
    logger.debug("Token generated via PyNaCl (fallback)")
    return token


class TokenManager:
    """Manages JWT token lifecycle with automatic refresh.

    Args:
        public_key_hex:  64-char hex device public key.
        private_key_hex: 64- or 128-char hex Ed25519 private key.
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
        """Get a valid token, refreshing if necessary."""
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
