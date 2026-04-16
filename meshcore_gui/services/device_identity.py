"""
Device identity file writer for MeshCore Observer integration.

After a successful connection, the worker calls
:func:`write_device_identity` with the device's public and private
keys.  The resulting JSON file is placed outside the git repo at::

    ~/.meshcore-gui/device_identity.json

The MeshCore Observer reads this file automatically for MQTT
authentication — no manual key setup required.

Multi-device file format (v2)::

    {
        "/dev/ttyUSB0": {
            "public_key":  "64-char hex UPPERCASE (from send_appstart)",
            "private_key": "128-char hex lowercase (full orlp/ed25519 expanded key)",
            "device_name": "PE1HVH T1000e",
            "firmware_version": "1.2.3",
            "source_device": "/dev/ttyUSB0",
            "updated_at":  "2026-02-26T15:00:00+00:00"
        },
        "/dev/ttyUSB1": {
            ...
        }
    }

Backward compatibility: if the file still contains the v1 flat-object
format (``"public_key"`` at the top level), it is automatically
migrated to the v2 format on the first write.

               Author: PE1HVH
              Version: 1.1.0
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


def _load_raw() -> dict:
    """Load the raw identity file and return a v2-format dict.

    Performs automatic migration when a v1 flat-object file is detected.
    Returns an empty dict if the file does not exist or is unreadable.
    """
    if not IDENTITY_FILE.exists():
        return {}

    try:
        data = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        debug_print(f"DeviceIdentity: read error: {exc}")
        return {}

    if not isinstance(data, dict):
        debug_print("DeviceIdentity: unexpected root type, resetting")
        return {}

    # v1 detection: public_key is a string directly at the root level
    if "public_key" in data and isinstance(data["public_key"], str):
        src = data.get("source_device", "unknown")
        debug_print(
            f"DeviceIdentity: v1 format detected — migrating entry "
            f"for '{src}' to v2 multi-device format"
        )
        return {src: data}

    return data


def write_device_identity(
    public_key: str,
    private_key_bytes: bytes,
    device_name: str = "",
    firmware_version: str = "",
    source_device: str = "",
) -> bool:
    """Write (or update) the device identity entry for *source_device*.

    The file stores one entry per device, keyed by ``source_device``
    (e.g. ``"/dev/ttyUSB0"``).  Entries for other devices are left
    untouched.

    Args:
        public_key:        64-char hex public key (from send_appstart).
                           Used for MQTT username at LetsMesh.
        private_key_bytes: 64 raw bytes from export_private_key() in
                           orlp/ed25519 expanded format.  All 64 bytes
                           are needed for createAuthToken().
        device_name:       Device display name.
        firmware_version:  Firmware version string.
        source_device:     Device path (e.g. ``/dev/ttyUSB1``).
                           Used as the dict key.

    Returns:
        True if the file was written successfully.
    """
    try:
        if len(private_key_bytes) != 64:
            debug_print(
                f"DeviceIdentity: unexpected key length "
                f"{len(private_key_bytes)}, expected 64 bytes"
            )
            return False

        if not public_key or len(public_key) != 64:
            debug_print(
                f"DeviceIdentity: no valid public key from appstart "
                f"(got {public_key!r}), cannot write identity file"
            )
            return False

        private_key_hex = private_key_bytes.hex()

        entry = {
            "public_key": public_key.upper(),
            "private_key": private_key_hex.lower(),
            "device_name": device_name,
            "firmware_version": firmware_version,
            "source_device": source_device,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Load existing data (handles v1 -> v2 migration transparently)
        all_identities = _load_raw()

        # Update only this device's entry; others remain unchanged
        all_identities[source_device] = entry

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        IDENTITY_FILE.write_text(
            json.dumps(all_identities, indent=2) + "\n",
            encoding="utf-8",
        )
        # Restrictive permissions — file contains private keys
        IDENTITY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

        debug_print(
            f"DeviceIdentity: written to {IDENTITY_FILE} "
            f"[{source_device}] "
            f"(pub={public_key[:12]}... priv={private_key_hex[:12]}...) "
            f"— total devices in file: {len(all_identities)}"
        )
        print(f"📝 Device identity saved → {IDENTITY_FILE} [{source_device}]")
        return True

    except Exception as exc:
        debug_print(f"DeviceIdentity: write failed: {exc}")
        print(f"⚠️  Could not save device identity: {exc}")
        return False


def read_device_identity(
    source_device: Optional[str] = None,
) -> Optional[dict]:
    """Read one or all device identity entries.

    Args:
        source_device: If given, return only the entry for that device
                       (e.g. ``"/dev/ttyUSB1"``).  If *None*, return
                       the full multi-device dict.

    Returns:
        * When *source_device* is specified: a single entry dict with
          ``public_key`` and ``private_key`` (hex strings), or *None*
          if not found / keys invalid.
        * When *source_device* is *None*: the full ``{device: entry}``
          dict (may be empty dict, never None).
    """
    all_identities = _load_raw()

    if source_device is None:
        return all_identities or {}

    entry = all_identities.get(source_device)
    if entry is None:
        debug_print(
            f"DeviceIdentity: no entry for '{source_device}' in {IDENTITY_FILE}"
        )
        return None

    pub = entry.get("public_key", "")
    priv = entry.get("private_key", "")
    if len(pub) == 64 and len(priv) in (64, 128):
        return entry

    debug_print(
        f"DeviceIdentity: invalid key lengths for '{source_device}' "
        f"(pub={len(pub)}, priv={len(priv)})"
    )
    return None
