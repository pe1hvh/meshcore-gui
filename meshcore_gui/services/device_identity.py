"""
Device identity file writer for MeshCore Observer integration.

After a successful connection, the worker calls
:func:`write_device_identity` with the device's public and private
keys.  The resulting JSON file is placed outside the git repo at::

    ~/.meshcore-gui/device_identity.json

The MeshCore Observer reads this file automatically for MQTT
authentication — no manual key setup required.

File format::

    {
        "public_key":  "64-char hex UPPERCASE (from send_appstart)",
        "private_key": "128-char hex lowercase (full orlp/ed25519 expanded key)",
        "device_name": "PE1HVH T1000e",
        "firmware_version": "1.2.3",
        "source_device": "/dev/ttyUSB1",
        "updated_at":  "2026-02-26T15:00:00+00:00"
    }

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from meshcore_gui.config import DATA_DIR, debug_print

# Fixed output path — observer looks here by default
IDENTITY_FILE: Path = DATA_DIR / "device_identity.json"


def write_device_identity(
    public_key: str,
    private_key_bytes: bytes,
    device_name: str = "",
    firmware_version: str = "",
    source_device: str = "",
) -> bool:
    """Write the device identity file for MeshCore Observer.

    Args:
        public_key:       64-char hex public key (from send_appstart).
                          This is the key shown in the GUI and registered
                          at LetsMesh.  MUST be used for MQTT username.
        private_key_bytes: 64 raw bytes from export_private_key() in
                           orlp/ed25519 expanded format.  All 64 bytes
                           are needed for createAuthToken().
        device_name:       Device display name.
        firmware_version:  Firmware version string.
        source_device:     Device path (e.g. ``/dev/ttyUSB1``).

    Returns:
        True if the file was written successfully.
    """
    try:
        # The 64 bytes from export_private_key() are in orlp/ed25519
        # *expanded* format:
        #   bytes  0..31 = clamped scalar (NOT the raw seed)
        #   bytes 32..63 = nonce prefix   (NOT the public key)
        #
        # The public key is NOT contained in these 64 bytes — it must
        # come from send_appstart() which returns the actual device
        # public key as shown in the GUI and registered at LetsMesh.
        #
        # For MQTT auth via meshcore-decoder's createAuthToken(), the
        # full 64 bytes are needed as privateKeyHex (128 hex chars).
        if len(private_key_bytes) != 64:
            debug_print(
                f"DeviceIdentity: unexpected key length "
                f"{len(private_key_bytes)}, expected 64 bytes"
            )
            return False

        # Full 64-byte private key in MeshCore/orlp format
        private_key_hex = private_key_bytes.hex()

        if not public_key or len(public_key) != 64:
            debug_print(
                f"DeviceIdentity: no valid public key from appstart "
                f"(got {public_key!r}), cannot write identity file"
            )
            return False

        identity = {
            "public_key": public_key.upper(),
            "private_key": private_key_hex.lower(),
            "device_name": device_name,
            "firmware_version": firmware_version,
            "source_device": source_device,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        IDENTITY_FILE.write_text(
            json.dumps(identity, indent=2) + "\n",
            encoding="utf-8",
        )
        # Restrictive permissions — file contains the private key
        IDENTITY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

        debug_print(
            f"DeviceIdentity: written to {IDENTITY_FILE} "
            f"(pub={public_key[:12]}... priv={private_key_hex[:12]}...)"
        )
        print(f"📝 Device identity saved → {IDENTITY_FILE}")
        return True

    except Exception as exc:
        debug_print(f"DeviceIdentity: write failed: {exc}")
        print(f"⚠️  Could not save device identity: {exc}")
        return False


def read_device_identity() -> Optional[dict]:
    """Read the device identity file.

    Returns:
        Dict with ``public_key`` and ``private_key`` (hex strings),
        or None if the file does not exist or is invalid.
    """
    if not IDENTITY_FILE.exists():
        return None

    try:
        data = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
        pub = data.get("public_key", "")
        priv = data.get("private_key", "")
        if len(pub) == 64 and len(priv) in (64, 128):
            return data
        debug_print(
            f"DeviceIdentity: invalid key lengths in {IDENTITY_FILE} "
            f"(pub={len(pub)}, priv={len(priv)})"
        )
        return None
    except (json.JSONDecodeError, OSError) as exc:
        debug_print(f"DeviceIdentity: read error: {exc}")
        return None
