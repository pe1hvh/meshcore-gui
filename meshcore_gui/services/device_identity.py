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
        "public_key":  "64-char hex",
        "private_key": "64-char hex (Ed25519 seed)",
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
        private_key_bytes: 64 raw bytes from export_private_key()
                           (first 32 = seed, last 32 = public key).
        device_name:       Device display name.
        firmware_version:  Firmware version string.
        source_device:     Device path (e.g. ``/dev/ttyUSB1``).

    Returns:
        True if the file was written successfully.
    """
    try:
        # The 64 bytes from export_private_key contain:
        #   bytes  0..31 = Ed25519 seed (private key)
        #   bytes 32..63 = Ed25519 public key
        if len(private_key_bytes) != 64:
            debug_print(
                f"DeviceIdentity: unexpected key length "
                f"{len(private_key_bytes)}, expected 64 bytes"
            )
            return False

        seed_hex = private_key_bytes[:32].hex()
        derived_pub_hex = private_key_bytes[32:].hex()

        # Sanity check: derived public key should match appstart public key
        if public_key and derived_pub_hex.lower() != public_key.lower():
            debug_print(
                f"DeviceIdentity: public key mismatch — "
                f"appstart={public_key[:16]}... vs "
                f"derived={derived_pub_hex[:16]}..."
            )
            # Use the derived public key (from the private key export)
            # as it is cryptographically linked to the seed.

        identity = {
            "public_key": derived_pub_hex.lower(),
            "private_key": seed_hex.lower(),
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
            f"(pub={derived_pub_hex[:12]}...)"
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
        if len(pub) == 64 and len(priv) == 64:
            return data
        debug_print(
            f"DeviceIdentity: invalid key lengths in {IDENTITY_FILE}"
        )
        return None
    except (json.JSONDecodeError, OSError) as exc:
        debug_print(f"DeviceIdentity: read error: {exc}")
        return None
