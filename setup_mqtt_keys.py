#!/usr/bin/env python3
"""
MeshCore Observer — MQTT Key Setup

This script configures your private and public key for the LetsMesh MQTT uplink.
It takes your MeshCore device key, derives the correct public key, stores the
private key securely, and updates observer_config.yaml.

Usage:
    python setup_mqtt_keys.py

The script will prompt for your key interactively.
"""

import os
import sys
import stat
import re

# ── Check dependencies ────────────────────────────────────────────────

try:
    from nacl.signing import SigningKey
except ImportError:
    print("Error: PyNaCl is not installed.")
    print("Run:   pip install PyNaCl")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: pyyaml is not installed.")
    print("Run:   pip install pyyaml")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────

KEYFILE = os.path.expanduser("~/.meshcore-observer-key")
CONFIG_FILE = "observer_config.yaml"

# ── Helper functions ──────────────────────────────────────────────────

def is_valid_hex(s, length):
    """Check if string is valid hex of exact length."""
    return bool(re.fullmatch(r'[0-9a-fA-F]{' + str(length) + '}', s))


def derive_public_key(private_key_hex):
    """Derive the Ed25519 public key from a 32-byte private key."""
    return SigningKey(bytes.fromhex(private_key_hex)).verify_key.encode().hex()


def find_valid_private_key(input_key):
    """
    Accept a 64-char or 128-char hex key. If 128 chars, try both halves
    as private key. Returns (private_key, public_key) or exits on failure.
    """
    input_key = input_key.strip().lower()

    # Case 1: already 64 hex chars — use directly as private key
    if is_valid_hex(input_key, 64):
        private_key = input_key
        public_key = derive_public_key(private_key)
        return private_key, public_key

    # Case 2: 128 hex chars — one half is private, other is public
    if is_valid_hex(input_key, 128):
        first_half = input_key[:64]
        second_half = input_key[64:]

        # Try first half as private key
        pk_from_first = derive_public_key(first_half)
        if pk_from_first == second_half:
            return first_half, second_half

        # Try second half as private key
        pk_from_second = derive_public_key(second_half)
        if pk_from_second == first_half:
            return second_half, first_half

        # Neither half matches the other — use first half as private key
        # and derive the public key from it (non-standard key format)
        print()
        print("  Note: Your 128-char key does not follow the standard")
        print("  [private][public] or [public][private] format.")
        print("  Using the first 64 characters as private key")
        print("  and deriving the public key from it.")
        return first_half, pk_from_first

    # Invalid input
    print()
    print(f"  Error: Expected 64 or 128 hex characters, got {len(input_key)}.")
    print("  A valid key looks like: a1b2c3d4e5f6... (only 0-9 and a-f)")
    sys.exit(1)


def save_private_key(private_key):
    """Save private key to file with restricted permissions."""
    with open(KEYFILE, 'w') as f:
        f.write(private_key + '\n')
    os.chmod(KEYFILE, stat.S_IRUSR | stat.S_IWUSR)  # 600


def update_config(public_key):
    """Update public_key in observer_config.yaml."""
    if not os.path.exists(CONFIG_FILE):
        print(f"\n  Warning: {CONFIG_FILE} not found.")
        print(f"  You need to set this manually in your config:")
        print(f'    public_key: "{public_key}"')
        return False

    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f) or {}

    if 'mqtt' not in config:
        config['mqtt'] = {}

    config['mqtt']['public_key'] = public_key
    config['mqtt']['private_key_file'] = KEYFILE

    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return True


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print()
    print("  MeshCore Observer — MQTT Key Setup")
    print("  ===================================")
    print()
    print("  This script configures your keys for the LetsMesh MQTT uplink.")
    print()
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  You need the key from your PHYSICAL MeshCore device.  │")
    print("  │  Keys from the web companion app will NOT work.        │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()
    print("  How to get it:")
    print("  • meshcore_gui → Device Info → connected device on /dev/ttyUSBx")
    print("  • Serial command: get prv.key (returns 128 hex chars)")
    print()

    input_key = input("  Paste your device key: ").strip()

    if not input_key:
        print("\n  No key entered. Exiting.")
        sys.exit(1)

    private_key, public_key = find_valid_private_key(input_key)

    print()
    print(f"  Private key: {private_key[:8]}...{private_key[-8:]}")
    print(f"  Public key:  {public_key[:8]}...{public_key[-8:]}")
    print()

    # Save private key
    save_private_key(private_key)
    print(f"  ✓ Private key saved to {KEYFILE} (permissions: 600)")

    # Update config
    if update_config(public_key):
        print(f"  ✓ Public key updated in {CONFIG_FILE}")
    
    print()
    print("  Done. Test your connection with:")
    print("    python meshcore_observer.py --mqtt-dry-run --debug-on")
    print()


if __name__ == "__main__":
    main()
