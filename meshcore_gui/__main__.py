#!/usr/bin/env python3
"""
MeshCore GUI — Dual Transport Edition (Serial + BLE)
=====================================================

Entry point.  Parses arguments, auto-detects the transport mode,
wires up the components, registers NiceGUI pages and starts the server.

Usage — Serial:
    python meshcore_gui.py /dev/ttyACM0
    python meshcore_gui.py /dev/ttyACM0 --debug-on
    python meshcore_gui.py /dev/ttyACM0 --port=9090
    python meshcore_gui.py /dev/ttyACM0 --baud=115200
    python meshcore_gui.py /dev/ttyACM0 --serial-cx-dly=0.1
    python meshcore_gui.py /dev/ttyACM0 --ssl

Usage — BLE:
    python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
    python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --ble-pin 654321
    python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on

    python -m meshcore_gui <DEVICE>

                   Author: PE1HVH
                  Version: 5.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import sys

from nicegui import app, ui

# Allow overriding DEBUG before anything imports it
import meshcore_gui.config as config

try:
    from meshcore import MeshCore, EventType  # noqa: F401 — availability check
except ImportError:
    print("ERROR: meshcore library not found")
    print("Install with: pip install meshcore")
    sys.exit(1)

from meshcore_gui.ble.worker import create_worker
from meshcore_gui.core.shared_data import SharedData
from meshcore_gui.gui.dashboard import DashboardPage
from meshcore_gui.gui.route_page import RoutePage
from meshcore_gui.gui.panels.bbs_panel import BbsSettingsPage
from meshcore_gui.gui.archive_page import ArchivePage
from meshcore_gui.services.pin_store import PinStore
from meshcore_gui.services.room_password_store import RoomPasswordStore
from meshcore_gui.services.bot_config_store import BotConfigStore


# Global instances (needed by NiceGUI page decorators)
_shared = None
_dashboard = None
_route_page = None
_bbs_settings_page = None
_bbs_config_store_main = None
_archive_page = None
_pin_store = None
_room_password_store = None
_bot_config_store = None


@ui.page('/')
def _page_dashboard():
    """NiceGUI page handler — main dashboard."""
    if _shared and _pin_store and _room_password_store:
        DashboardPage(_shared, _pin_store, _room_password_store, _bot_config_store).render()


@ui.page('/route/{msg_key}')
def _page_route(msg_key: str):
    """NiceGUI page handler — route visualization."""
    if _route_page:
        _route_page.render(msg_key)


@ui.page('/bbs-settings')
def _page_bbs_settings():
    """NiceGUI page handler — BBS settings."""
    if _bbs_settings_page:
        _bbs_settings_page.render()


@ui.page('/archive')
def _page_archive():
    """NiceGUI page handler — message archive."""
    if _archive_page:
        _archive_page.render()


def _print_usage():
    """Show usage information for both serial and BLE modes."""
    print("MeshCore GUI - Dual Transport Edition (Serial + BLE)")
    print("=" * 55)
    print()
    print("Usage: python meshcore_gui.py <DEVICE> [OPTIONS]")
    print()
    print("The transport mode is auto-detected from the device argument:")
    print("  /dev/ttyACM0                  → Serial (USB)")
    print("  literal:AA:BB:CC:DD:EE:FF     → Bluetooth LE")
    print()
    print("Serial examples:")
    print("  python meshcore_gui.py /dev/ttyACM0")
    print("  python meshcore_gui.py /dev/ttyACM0 --debug-on")
    print("  python meshcore_gui.py /dev/ttyACM0 --port=9090")
    print("  python meshcore_gui.py /dev/ttyACM0 --baud=57600")
    print("  python meshcore_gui.py /dev/ttyACM0 --serial-cx-dly=0.1")
    print("  python meshcore_gui.py /dev/ttyACM0 --ssl")
    print()
    print("BLE examples:")
    print("  python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF")
    print("  python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on")
    print("  python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --ble-pin 654321")
    print("  python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --ble-pin=654321")
    print()
    print("Common options:")
    print("  --debug-on        Enable verbose debug logging")
    print("  --port=PORT       Web server port (default: 8081)")
    print("  --ssl             Enable HTTPS with auto-generated certificate")
    print()
    print("Serial options:")
    print("  --baud=BAUD       Serial baudrate (default: 115200)")
    print("  --serial-cx-dly=S Serial connection delay (default: 0.1)")
    print()
    print("BLE options:")
    print("  --ble-pin PIN     BLE pairing PIN (default: 123456)")
    print()
    print("Tips:")
    print("  Serial: ls -l /dev/serial/by-id")
    print("  BLE:    bluetoothctl scan on")


def _parse_flags(argv):
    """Parse CLI arguments into positional args and a flag dict.

    Handles ``--flag value``, ``--flag=value``, and boolean ``--flag``.
    """
    args = []
    flags = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if '=' in a and a.startswith('--'):
            key, value = a.split('=', 1)
            flags[key] = value
        elif a == '--ble-pin':
            if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                flags['--ble-pin'] = argv[i + 1]
                i += 1
            else:
                flags['--ble-pin'] = True
        elif a.startswith('--'):
            flags[a] = True
        else:
            args.append(a)
        i += 1
    return args, flags


def main():
    """Main entry point.

    Parses CLI arguments, auto-detects the transport, initialises all
    components and starts the NiceGUI server.
    """
    global _shared, _dashboard, _route_page, _bbs_settings_page, _archive_page, _pin_store, _room_password_store, _bot_config_store

    args, flags = _parse_flags(sys.argv[1:])

    if not args:
        _print_usage()
        sys.exit(1)

    device_id = args[0]
    is_ble = config.is_ble_address(device_id)
    config.TRANSPORT = "ble" if is_ble else "serial"
    config.set_log_file_for_device(device_id)

    # ── Common flags ──
    if '--debug-on' in flags:
        config.DEBUG = True
        config.MESHCORE_LIB_DEBUG = True  # sync: lib debug follows app debug

    port = int(flags.get('--port', 8081))

    # ── Serial-specific flags ──
    if not is_ble:
        if '--baud' in flags:
            try:
                config.SERIAL_BAUDRATE = int(flags['--baud'])
            except ValueError:
                print(f"ERROR: Invalid baudrate: {flags['--baud']}")
                sys.exit(1)
        if '--serial-cx-dly' in flags:
            try:
                config.SERIAL_CX_DELAY = float(flags['--serial-cx-dly'])
            except ValueError:
                print(f"ERROR: Invalid serial cx delay: {flags['--serial-cx-dly']}")
                sys.exit(1)

    # ── BLE-specific flags ──
    if is_ble:
        ble_pin = flags.get('--ble-pin')
        if ble_pin and ble_pin is not True:
            config.BLE_PIN = str(ble_pin)

    # ── SSL ──
    ssl_enabled = '--ssl' in flags
    ssl_keyfile = None
    ssl_certfile = None

    if ssl_enabled:
        import socket
        import subprocess
        from pathlib import Path
        ssl_dir = config.DATA_DIR / 'ssl'
        ssl_dir.mkdir(parents=True, exist_ok=True)
        ssl_keyfile = str(ssl_dir / 'key.pem')
        ssl_certfile = str(ssl_dir / 'cert.pem')

        if not (ssl_dir / 'cert.pem').exists():
            local_ip = '127.0.0.1'
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                pass
            san = f"DNS:localhost,IP:127.0.0.1,IP:{local_ip}"
            print(f"Generating self-signed SSL certificate (SAN: {san}) ...")
            subprocess.run([
                'openssl', 'req', '-x509',
                '-newkey', 'rsa:2048',
                '-keyout', ssl_keyfile,
                '-out', ssl_certfile,
                '-days', '3650',
                '-nodes',
                '-subj', '/CN=DOMCA MeshCore GUI',
                '-addext', f'subjectAltName={san}',
            ], check=True, capture_output=True)
            print(f"Certificate saved to {ssl_dir}/")
        else:
            print(f"Using existing certificate from {ssl_dir}/")

    # ── Startup banner ──
    transport_label = "BLE Edition" if is_ble else "Serial Edition"
    print("=" * 55)
    print(f"MeshCore GUI - {transport_label}")
    print("=" * 55)
    print(f"Device:     {device_id}")
    print(f"Transport:  {'Bluetooth LE' if is_ble else 'USB Serial'}")
    if is_ble:
        print(f"BLE PIN:    {config.BLE_PIN}")
    else:
        print(f"Baudrate:   {config.SERIAL_BAUDRATE}")
        print(f"CX delay:   {config.SERIAL_CX_DELAY}")
    print(f"Port:       {port}")
    print(f"SSL:        {'ON (https)' if ssl_enabled else 'OFF (http)'}")
    print(f"Debug mode: {'ON' if config.DEBUG else 'OFF'}")
    print("=" * 55)

    # ── Assemble components ──
    _shared = SharedData(device_id)
    _pin_store = PinStore(device_id)
    _room_password_store = RoomPasswordStore(device_id)
    _bot_config_store = BotConfigStore(device_id)
    _dashboard = DashboardPage(_shared, _pin_store, _room_password_store, _bot_config_store)
    _route_page = RoutePage(_shared)
    _archive_page = ArchivePage(_shared)
    from meshcore_gui.services.bbs_config_store import BbsConfigStore as _BCS
    _bbs_settings_page = BbsSettingsPage(_shared, _BCS())

    # ── Start worker ──
    worker = create_worker(
        device_id,
        _shared,
        baudrate=config.SERIAL_BAUDRATE,
        cx_dly=config.SERIAL_CX_DELAY,
        pin_store=_pin_store,
    )
    worker.start()

    # ── Serve static PWA assets ──
    from pathlib import Path
    static_dir = Path(__file__).parent / 'static'
    if static_dir.is_dir():
        app.add_static_files('/static', str(static_dir))

    # ── Start NiceGUI server (blocks) ──
    run_kwargs = dict(
        show=False, host='0.0.0.0', title='DOMCA MeshCore',
        port=port, reload=False, storage_secret='meshcore-gui-secret',
    )
    if ssl_enabled:
        run_kwargs['ssl_keyfile'] = ssl_keyfile
        run_kwargs['ssl_certfile'] = ssl_certfile
    ui.run(**run_kwargs)


if __name__ == "__main__":
    main()
