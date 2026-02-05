#!/usr/bin/env python3
"""
MeshCore GUI - Threaded BLE Edition
====================================

Entry point.  Parses arguments, wires up the components, registers
NiceGUI pages and starts the server.

Usage:
    python meshcore_gui.py <BLE_ADDRESS>
    python meshcore_gui.py <BLE_ADDRESS> --debug-on

                   Author: PE1HVH
                  Version: 4.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import sys

from nicegui import ui

# Allow overriding DEBUG and CHANNELS_CONFIG before anything imports them
import meshcore_gui.config as config

try:
    from meshcore import MeshCore, EventType  # noqa: F401 — availability check
except ImportError:
    print("ERROR: meshcore library not found")
    print("Install with: pip install meshcore")
    sys.exit(1)

from meshcore_gui.ble_worker import BLEWorker
from meshcore_gui.main_page import DashboardPage
from meshcore_gui.route_page import RoutePage
from meshcore_gui.shared_data import SharedData


# Global instances (needed by NiceGUI page decorators)
_shared = None
_dashboard = None
_route_page = None


@ui.page('/')
def _page_dashboard():
    """NiceGUI page handler — main dashboard."""
    if _dashboard:
        _dashboard.render()


@ui.page('/route/{msg_index}')
def _page_route(msg_index: int):
    """NiceGUI page handler — route visualization (new tab)."""
    if _route_page:
        _route_page.render(msg_index)


def main():
    """
    Main entry point.

    Parses CLI arguments, initialises all components and starts the
    NiceGUI server.
    """
    global _shared, _dashboard, _route_page

    # Parse arguments
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if not args:
        print("MeshCore GUI - Threaded BLE Edition")
        print("=" * 40)
        print("Usage: python meshcore_gui.py <BLE_ADDRESS> [--debug-on]")
        print("Example: python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF")
        print("         python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --debug-on")
        print()
        print("Options:")
        print("  --debug-on    Enable verbose debug logging")
        print()
        print("Tip: Use 'bluetoothctl scan on' to find devices")
        sys.exit(1)

    ble_address = args[0]

    # Apply --debug-on flag
    if '--debug-on' in flags:
        config.DEBUG = True

    # Startup banner
    print("=" * 50)
    print("MeshCore GUI - Threaded BLE Edition")
    print("=" * 50)
    print(f"Device:     {ble_address}")
    print(f"Debug mode: {'ON' if config.DEBUG else 'OFF'}")
    print("=" * 50)

    # Assemble components
    _shared = SharedData()
    _dashboard = DashboardPage(_shared)
    _route_page = RoutePage(_shared)

    # Start BLE worker in background thread
    worker = BLEWorker(ble_address, _shared)
    worker.start()

    # Start NiceGUI server (blocks)
    ui.run(title='MeshCore', port=8080, reload=False)


if __name__ == "__main__":
    main()
