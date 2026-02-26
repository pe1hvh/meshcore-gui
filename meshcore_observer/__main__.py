#!/usr/bin/env python3
"""
MeshCore Observer — Entry Point
=================================

Parses command-line arguments, loads YAML configuration, creates the
ArchiveWatcher, registers the NiceGUI dashboard page and starts the
server.

Usage:
    python meshcore_observer.py
    python meshcore_observer.py --config=observer_config.yaml
    python meshcore_observer.py --port=9093
    python meshcore_observer.py --debug-on

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import logging
import sys
from pathlib import Path

from nicegui import ui

from meshcore_observer import __version__
from meshcore_observer.config import ObserverConfig, DEFAULT_CONFIG_PATH
from meshcore_observer.archive_watcher import ArchiveWatcher
from meshcore_observer.gui.dashboard import ObserverDashboard


logger = logging.getLogger("meshcore_observer")

# Global instance (needed by NiceGUI page decorator)
_dashboard: ObserverDashboard | None = None


@ui.page("/")
def _page_dashboard():
    """NiceGUI page handler — observer dashboard."""
    if _dashboard:
        _dashboard.render()


def _print_usage():
    """Show usage information."""
    print("MeshCore Observer — Read-Only Archive Monitor Dashboard")
    print("=" * 58)
    print()
    print("Usage: python meshcore_observer.py [OPTIONS]")
    print()
    print("Options:")
    print("  --config=PATH     Path to observer_config.yaml (default: ./observer_config.yaml)")
    print("  --port=PORT       Override GUI port from config (default: 9093)")
    print("  --debug-on        Enable verbose debug logging")
    print("  --help            Show this help message")
    print()
    print("Configuration:")
    print("  All settings are defined in observer_config.yaml.")
    print()
    print("Examples:")
    print("  python meshcore_observer.py")
    print("  python meshcore_observer.py --config=/etc/meshcore/observer_config.yaml")
    print("  python meshcore_observer.py --port=9093 --debug-on")


def _parse_flags(argv):
    """Parse CLI arguments into a flag dict.

    Handles ``--flag=value`` and boolean ``--flag``.
    """
    flags = {}
    for a in argv:
        if "=" in a and a.startswith("--"):
            key, value = a.split("=", 1)
            flags[key] = value
        elif a.startswith("--"):
            flags[a] = True
    return flags


def _setup_logging(debug: bool) -> None:
    """Configure logging for the observer process."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    """Main entry point.

    Loads configuration, creates ArchiveWatcher, starts the
    NiceGUI dashboard.
    """
    global _dashboard

    flags = _parse_flags(sys.argv[1:])

    if "--help" in flags:
        _print_usage()
        sys.exit(0)

    # ── Load configuration ──
    config_path = Path(flags.get("--config", str(DEFAULT_CONFIG_PATH)))

    if config_path.exists():
        print(f"Loading config from: {config_path}")
        cfg = ObserverConfig.from_yaml(config_path)
    else:
        print(f"Config not found at {config_path}, using defaults.")
        print("Run with --help for usage information.")
        cfg = ObserverConfig()

    # ── CLI overrides ──
    if "--debug-on" in flags:
        cfg.debug = True

    if "--port" in flags:
        try:
            cfg.gui_port = int(flags["--port"])
        except ValueError:
            print(f"ERROR: Invalid port: {flags['--port']}")
            sys.exit(1)

    cfg.config_path = str(config_path)

    # ── Setup logging ──
    _setup_logging(cfg.debug)

    # ── Startup banner ──
    print("=" * 58)
    print("MeshCore Observer — Read-Only Archive Monitor Dashboard")
    print("=" * 58)
    print(f"Version:      {__version__}")
    print(f"Config:       {config_path}")
    print(f"Archive dir:  {cfg.archive_dir}")
    print(f"Poll interval:{cfg.poll_interval_s}s")
    print(f"GUI port:     {cfg.gui_port}")
    print(f"Debug mode:   {'ON' if cfg.debug else 'OFF'}")
    print("=" * 58)

    # ── Verify archive directory ──
    archive_path = Path(cfg.archive_dir)
    if not archive_path.exists():
        logger.warning(
            "Archive directory does not exist yet: %s — "
            "will start scanning when it appears.",
            cfg.archive_dir,
        )

    # ── Create ArchiveWatcher ──
    watcher = ArchiveWatcher(cfg.archive_dir, debug=cfg.debug)

    # ── Create dashboard ──
    _dashboard = ObserverDashboard(watcher, cfg)

    # ── Start NiceGUI server (blocks) ──
    print(f"Starting GUI on port {cfg.gui_port}...")
    ui.run(
        show=False,
        host="0.0.0.0",
        title=cfg.gui_title,
        port=cfg.gui_port,
        reload=False,
        storage_secret="meshcore-observer-secret",
    )


if __name__ == "__main__":
    main()
