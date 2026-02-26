#!/usr/bin/env python3
"""
MeshCore Bridge — Entry Point
==============================

Parses command-line arguments, loads YAML configuration, creates two
SharedData/Worker pairs (one per device), initialises the BridgeEngine,
registers the NiceGUI dashboard page and starts the server.

Usage:
    python meshcore_bridge.py
    python meshcore_bridge.py --config=bridge_config.yaml
    python meshcore_bridge.py --port=9092
    python meshcore_bridge.py --debug-on

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

from nicegui import app, ui

# Allow overriding DEBUG before anything imports it
import meshcore_gui.config as gui_config

try:
    from meshcore import MeshCore, EventType  # noqa: F401
except ImportError:
    print("ERROR: meshcore library not found")
    print("Install with: pip install meshcore")
    sys.exit(1)

from meshcore_gui.ble.worker import create_worker
from meshcore_gui.core.shared_data import SharedData

from meshcore_bridge.config import BridgeConfig, DEFAULT_CONFIG_PATH
from meshcore_bridge.bridge_engine import BridgeEngine
from meshcore_bridge.gui.dashboard import BridgeDashboard


# Global instances (needed by NiceGUI page decorators)
_dashboard: BridgeDashboard | None = None


@ui.page('/')
def _page_dashboard():
    """NiceGUI page handler — bridge dashboard."""
    if _dashboard:
        _dashboard.render()


def _print_usage():
    """Show usage information."""
    print("MeshCore Bridge — Cross-Frequency Message Bridge Daemon")
    print("=" * 58)
    print()
    print("Usage: python meshcore_bridge.py [OPTIONS]")
    print()
    print("Options:")
    print("  --config=PATH     Path to bridge_config.yaml (default: ./bridge_config.yaml)")
    print("  --port=PORT       Override GUI port from config (default: 9092)")
    print("  --debug-on        Enable verbose debug logging")
    print("  --help            Show this help message")
    print()
    print("Configuration:")
    print("  All settings are defined in bridge_config.yaml.")
    print("  See BRIDGE.md for full documentation.")
    print()
    print("Examples:")
    print("  python meshcore_bridge.py")
    print("  python meshcore_bridge.py --config=/etc/meshcore/bridge_config.yaml")
    print("  python meshcore_bridge.py --port=9092 --debug-on")


def _parse_flags(argv):
    """Parse CLI arguments into a flag dict.

    Handles ``--flag=value`` and boolean ``--flag``.
    """
    flags = {}
    for a in argv:
        if '=' in a and a.startswith('--'):
            key, value = a.split('=', 1)
            flags[key] = value
        elif a.startswith('--'):
            flags[a] = True
    return flags


def _bridge_poll_loop(engine: BridgeEngine, interval_ms: int):
    """Background thread that runs the bridge polling loop.

    Args:
        engine:      BridgeEngine instance.
        interval_ms: Polling interval in milliseconds.
    """
    interval_s = interval_ms / 1000.0
    while True:
        try:
            engine.poll_and_forward()
        except Exception as e:
            gui_config.debug_print(f"Bridge poll error: {e}")
        time.sleep(interval_s)


def main():
    """Main entry point.

    Loads configuration, creates dual workers, starts the bridge
    engine and the NiceGUI dashboard.
    """
    global _dashboard

    flags = _parse_flags(sys.argv[1:])

    if '--help' in flags:
        _print_usage()
        sys.exit(0)

    # ── Load configuration ──
    config_path = Path(flags.get('--config', str(DEFAULT_CONFIG_PATH)))

    if config_path.exists():
        print(f"Loading config from: {config_path}")
        cfg = BridgeConfig.from_yaml(config_path)
    else:
        print(f"Config not found at {config_path}, using defaults.")
        print(f"Run with --help for usage information.")
        cfg = BridgeConfig()

    # ── CLI overrides ──
    if '--debug-on' in flags:
        cfg.debug = True
        gui_config.DEBUG = True

    if '--port' in flags:
        try:
            cfg.gui_port = int(flags['--port'])
        except ValueError:
            print(f"ERROR: Invalid port: {flags['--port']}")
            sys.exit(1)

    cfg.config_path = str(config_path)

    # ── Startup banner ──
    print("=" * 58)
    print("MeshCore Bridge — Cross-Frequency Message Bridge Daemon")
    print("=" * 58)
    print(f"Config:       {config_path}")
    print(f"Device A:     {cfg.device_a.port} ({cfg.device_a.label})")
    print(f"Device B:     {cfg.device_b.port} ({cfg.device_b.label})")
    print(f"Channel:      #{cfg.channel_name} (A:idx={cfg.channel_idx_a}, B:idx={cfg.channel_idx_b})")
    print(f"Poll interval:{cfg.poll_interval_ms}ms")
    print(f"GUI port:     {cfg.gui_port}")
    print(f"Forward prefix: {'ON' if cfg.forward_prefix else 'OFF'}")
    print(f"Debug mode:   {'ON' if cfg.debug else 'OFF'}")
    print("=" * 58)

    # ── Create dual SharedData instances ──
    shared_a = SharedData(f"bridge_a_{cfg.device_a.port.replace('/', '_')}")
    shared_b = SharedData(f"bridge_b_{cfg.device_b.port.replace('/', '_')}")

    # ── Create BridgeEngine ──
    engine = BridgeEngine(shared_a, shared_b, cfg)

    # ── Create workers (one per device) ──
    gui_config.SERIAL_BAUDRATE = cfg.device_a.baud
    worker_a = create_worker(
        cfg.device_a.port,
        shared_a,
        baudrate=cfg.device_a.baud,
    )

    gui_config.SERIAL_BAUDRATE = cfg.device_b.baud
    worker_b = create_worker(
        cfg.device_b.port,
        shared_b,
        baudrate=cfg.device_b.baud,
    )

    # ── Start workers ──
    print(f"Starting worker A ({cfg.device_a.port})...")
    worker_a.start()

    print(f"Starting worker B ({cfg.device_b.port})...")
    worker_b.start()

    # ── Start bridge polling thread ──
    print(f"Starting bridge engine (poll every {cfg.poll_interval_ms}ms)...")
    poll_thread = threading.Thread(
        target=_bridge_poll_loop,
        args=(engine, cfg.poll_interval_ms),
        daemon=True,
    )
    poll_thread.start()

    # ── Create dashboard ──
    _dashboard = BridgeDashboard(shared_a, shared_b, engine, cfg)

    # ── Start NiceGUI server (blocks) ──
    print(f"Starting GUI on port {cfg.gui_port}...")
    ui.run(
        show=False,
        host='0.0.0.0',
        title=cfg.gui_title,
        port=cfg.gui_port,
        reload=False,
        storage_secret='meshcore-bridge-secret',
    )


if __name__ == "__main__":
    main()
