#!/usr/bin/env python3
"""
Manual MQTT key setup — FALLBACK ONLY.

Normally, meshcore_gui automatically writes the device identity file
to ``~/.meshcore-gui/device_identity.json`` and the observer reads
it.  This script is only needed when meshcore_gui runs on a different
machine than the observer.

Two modes:

  1. **Copy identity file** — copy ``device_identity.json`` from the
     GUI machine and this script reads it directly.
  2. **Manual entry** — paste the public key (64 hex chars, from GUI)
     and the private key (128 hex chars, from ``export_private_key``).

Usage::

    python setup_mqtt_keys.py
    python setup_mqtt_keys.py --identity /path/to/device_identity.json

                   Author: PE1HVH
                  Version: 2.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import json
import re
import shutil
import stat
import sys
from pathlib import Path

PRIVATE_KEY_FILE = Path.home() / ".meshcore-observer-key"

# Config lives in project root (parent of the meshcore_observer package)
_PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = _PROJECT_DIR / "observer_config.yaml"
TEMPLATE_FILE = _PROJECT_DIR / "observer_config.template.yaml"

VALID_PRIVATE_KEY_LENGTHS = (64, 128)  # seed or expanded


def _validate_hex(s: str, expected_lengths: tuple) -> bool:
    return (
        bool(re.fullmatch(r"[0-9a-fA-F]+", s))
        and len(s) in expected_lengths
    )


def _save_private_key(private_key_hex: str) -> None:
    """Save private key to file with restricted permissions."""
    PRIVATE_KEY_FILE.write_text(private_key_hex + "\n", encoding="utf-8")
    PRIVATE_KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"  ✅ Private key → {PRIVATE_KEY_FILE}")
    print(f"     ({len(private_key_hex)} hex chars)")


def _update_config_public_key(public_key_hex: str) -> None:
    """Write/update the public key in observer_config.yaml."""
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
            print(f"  ✅ Config aangemaakt → {CONFIG_FILE}")
            return

    content = CONFIG_FILE.read_text(encoding="utf-8")
    pattern = r'(public_key:\s*)["\']?[0-9a-fA-F]*["\']?'
    new_content, count = re.subn(
        pattern, f'\\1"{public_key_hex}"', content, count=1,
    )
    if count == 0:
        if "mqtt:" in content:
            new_content = content.replace(
                "mqtt:", f'mqtt:\n  public_key: "{public_key_hex}"', 1,
            )
        else:
            new_content = (
                content + f'\nmqtt:\n  public_key: "{public_key_hex}"\n'
            )
    CONFIG_FILE.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Public key  → {CONFIG_FILE}")


def _from_identity_file(identity_path: Path) -> None:
    """Read keys from a device_identity.json file."""
    print(f"  📄 Lezen: {identity_path}")
    data = json.loads(identity_path.read_text(encoding="utf-8"))

    pub = data.get("public_key", "")
    priv = data.get("private_key", "")

    if not _validate_hex(pub, (64,)):
        print(f"\n❌ Ongeldige public key in identity file (lengte: {len(pub)})")
        sys.exit(1)

    if not _validate_hex(priv, VALID_PRIVATE_KEY_LENGTHS):
        print(f"\n❌ Ongeldige private key in identity file (lengte: {len(priv)})")
        sys.exit(1)

    device_name = data.get("device_name", "onbekend")
    print(f"  Device:      {device_name}")
    print(f"  Public key:  {pub[:12]}...{pub[-8:]}")
    print(f"  Private key: {len(priv)} hex chars")
    print()

    _save_private_key(priv.lower())
    _update_config_public_key(pub.upper())


def _from_manual_input() -> None:
    """Interactively enter public and private keys."""
    print("  Voer de keys in die je van de GUI-machine hebt gekopieerd.")
    print()
    print("  De PUBLIC key (64 hex chars) staat in meshcore_gui onder")
    print("  device info, of in device_identity.json.")
    print()

    pub = input("  Public key (64 hex chars): ").strip().replace(" ", "")
    if not _validate_hex(pub, (64,)):
        print(f"\n❌ Verwacht 64 hex karakters, gekregen: {len(pub)}")
        sys.exit(1)

    print()
    print("  De PRIVATE key (128 hex chars) komt uit export_private_key()")
    print("  of uit device_identity.json (het 'private_key' veld).")
    print("  Legacy 64-char seeds worden ook geaccepteerd.")
    print()

    priv = input("  Private key (128 of 64 hex chars): ").strip().replace(" ", "")
    if not _validate_hex(priv, VALID_PRIVATE_KEY_LENGTHS):
        print(f"\n❌ Verwacht 64 of 128 hex karakters, gekregen: {len(priv)}")
        sys.exit(1)

    print()
    print(f"  Public key:  {pub[:12]}...{pub[-8:]}")
    print(f"  Private key: {len(priv)} hex chars")
    print()

    _save_private_key(priv.lower())
    _update_config_public_key(pub.upper())


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

    # Check for --identity flag
    identity_path = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--identity="):
            identity_path = Path(arg.split("=", 1)[1].strip()).expanduser()
        elif arg == "--identity" and i < len(sys.argv) - 1:
            identity_path = Path(sys.argv[i + 1].strip()).expanduser()

    if identity_path:
        if not identity_path.exists():
            print(f"❌ Bestand niet gevonden: {identity_path}")
            sys.exit(1)
        _from_identity_file(identity_path)
    else:
        print("  Kies een methode:")
        print("  1. Kopieer device_identity.json van de GUI machine")
        print("  2. Voer public en private key handmatig in")
        print()
        choice = input("  Keuze [1/2]: ").strip()
        print()

        if choice == "1":
            path_str = input("  Pad naar device_identity.json: ").strip()
            p = Path(path_str).expanduser()
            if not p.exists():
                print(f"\n❌ Bestand niet gevonden: {p}")
                sys.exit(1)
            _from_identity_file(p)
        else:
            _from_manual_input()

    print()
    print("  ✅ Klaar!")
    print()
    print("  Test:  python meshcore_observer.py --mqtt-dry-run --debug-on")
    print("  Live:  python meshcore_observer.py")
    print()


if __name__ == "__main__":
    main()
