#!/usr/bin/env python3
"""
Manual MQTT key setup — FALLBACK ONLY.

Normally, meshcore_gui automatically writes the device identity file
to ``~/.meshcore-gui/device_identity.json`` and the observer reads
it.  This script is only needed when meshcore_gui runs on a different
machine than the observer.

Takes the 128-char hex key from the device (obtained via serial
command ``get prv.key``) and:

  1. Determines which half is the private key (seed) and which is
     the public key.
  2. Saves the private key to ``~/.meshcore-observer-key`` (chmod 600).
  3. Writes/updates the public key in ``observer_config.yaml``.

Usage::

    python setup_mqtt_keys.py
    python setup_mqtt_keys.py --key <128-char-hex>

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import re
import shutil
import stat
import sys
from pathlib import Path

PRIVATE_KEY_FILE = Path.home() / ".meshcore-observer-key"
CONFIG_FILE = Path(__file__).parent / "observer_config.yaml"
TEMPLATE_FILE = Path(__file__).parent / "observer_config.template.yaml"


def _validate_hex(s: str, expected_len: int) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s)) and len(s) == expected_len


def _detect_key_halves(full_key_hex: str) -> tuple:
    try:
        from nacl.signing import SigningKey
    except ImportError:
        print("ERROR: PyNaCl is required.  pip install PyNaCl")
        sys.exit(1)

    first_half = full_key_hex[:64]
    second_half = full_key_hex[64:]

    for seed, pub in [(first_half, second_half), (second_half, first_half)]:
        try:
            sk = SigningKey(bytes.fromhex(seed))
            if sk.verify_key.encode().hex().lower() == pub.lower():
                return seed.lower(), pub.lower()
        except Exception:
            pass

    raise ValueError(
        "Kan private/public helft niet bepalen.  Controleer of je de "
        "volledige 128-char key hebt gekopieerd uit 'get prv.key'."
    )


def _save_private_key(private_key_hex: str) -> None:
    PRIVATE_KEY_FILE.write_text(private_key_hex + "\n", encoding="utf-8")
    PRIVATE_KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"  ✅ Private key → {PRIVATE_KEY_FILE}")


def _update_config_public_key(public_key_hex: str) -> None:
    if not CONFIG_FILE.exists():
        if TEMPLATE_FILE.exists():
            shutil.copy2(TEMPLATE_FILE, CONFIG_FILE)
            print(f"  📄 {CONFIG_FILE.name} aangemaakt vanuit template")
        else:
            CONFIG_FILE.write_text(
                "mqtt:\n"
                "  enabled: true\n"
                f'  public_key: "{public_key_hex}"\n'
                '  private_key_file: "~/.meshcore-observer-key"\n'
                '  iata: "AMS"\n'
                "  brokers:\n"
                '    - name: "letsmesh-eu"\n'
                '      server: "mqtt-eu-v1.letsmesh.net"\n'
                "      port: 443\n"
                '      transport: "websockets"\n'
                "      tls: true\n"
                "      enabled: true\n",
                encoding="utf-8",
            )
            return

    content = CONFIG_FILE.read_text(encoding="utf-8")
    pattern = r'(public_key:\s*)["\']?[0-9a-fA-F]*["\']?'
    new_content, count = re.subn(pattern, f'\\1"{public_key_hex}"', content, count=1)
    if count == 0:
        if "mqtt:" in content:
            new_content = content.replace(
                "mqtt:", f'mqtt:\n  public_key: "{public_key_hex}"', 1
            )
        else:
            new_content = content + f'\nmqtt:\n  public_key: "{public_key_hex}"\n'
    CONFIG_FILE.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Public key  → {CONFIG_FILE}")


def main():
    print()
    print("=" * 58)
    print("  MeshCore Observer — Handmatige MQTT Key Setup")
    print("=" * 58)
    print()
    print("  ℹ️  Dit script is alleen nodig als meshcore_gui op")
    print("     een andere machine draait dan de observer.")
    print("     Normaal worden keys automatisch gedeeld via")
    print("     ~/.meshcore-gui/device_identity.json")
    print()

    full_key = ""
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--key="):
            full_key = arg.split("=", 1)[1].strip()
        elif arg == "--key" and i < len(sys.argv) - 1:
            full_key = sys.argv[i + 1].strip()

    if not full_key:
        full_key = input("Plak 128-char device key: ").strip()

    full_key = full_key.replace(" ", "").replace("0x", "").replace(":", "")

    if not _validate_hex(full_key, 128):
        print(f"\n❌ Verwacht 128 hex karakters, gekregen: {len(full_key)}")
        if len(full_key) == 64:
            print("   Dit lijkt alleen de public key (64 chars).")
            print("   Je hebt de VOLLEDIGE key nodig uit 'get prv.key' (128 chars).")
        sys.exit(1)

    private_key, public_key = _detect_key_halves(full_key)
    print(f"  Private key: {private_key[:8]}...{private_key[-8:]}")
    print(f"  Public key:  {public_key[:8]}...{public_key[-8:]}")
    print()

    _save_private_key(private_key)
    _update_config_public_key(public_key)

    print()
    print("  Test:  python meshcore_observer.py --mqtt-dry-run --debug-on")
    print("  Live:  python meshcore_observer.py")
    print()


if __name__ == "__main__":
    main()
