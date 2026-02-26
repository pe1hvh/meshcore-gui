#!/usr/bin/env python3
"""
MeshCore Observer — Entry Point
=================================

Parses command-line arguments, loads YAML configuration, creates the
ArchiveWatcher, optionally starts the MQTT uplink, registers the
NiceGUI dashboard page and starts the server.

Usage:
    python meshcore_observer.py
    python meshcore_observer.py --config=observer_config.yaml
    python meshcore_observer.py --port=9093
    python meshcore_observer.py --debug-on
    python meshcore_observer.py --mqtt-dry-run

                   Author: PE1HVH
                  Version: 1.1.0
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
    print("  --mqtt-dry-run    MQTT dry run: log payloads without publishing")
    print("  --help            Show this help message")
    print()
    print("Configuration:")
    print("  All settings are defined in observer_config.yaml.")
    print()
    print("Examples:")
    print("  python meshcore_observer.py")
    print("  python meshcore_observer.py --config=/etc/meshcore/observer_config.yaml")
    print("  python meshcore_observer.py --port=9093 --debug-on")
    print("  python meshcore_observer.py --mqtt-dry-run")


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


def _create_mqtt_uplink(cfg: ObserverConfig):
    """Create and validate MQTT uplink if enabled.

    Args:
        cfg: Observer configuration.

    Returns:
        MqttUplink instance or None if disabled/invalid.
    """
    if not cfg.mqtt.enabled:
        logger.info("MQTT uplink: disabled")
        return None

    # Validate configuration
    errors = cfg.mqtt.validate()
    if errors:
        for err in errors:
            logger.error("MQTT config error: %s", err)
        logger.error("MQTT uplink disabled due to configuration errors")
        return None

    try:
        from meshcore_observer.mqtt_uplink import MqttUplink
    except ImportError as exc:
        logger.error("Cannot import MqttUplink: %s", exc)
        logger.error(
            "Install dependencies: pip install paho-mqtt PyNaCl"
        )
        return None

    uplink = MqttUplink(cfg.mqtt, debug=cfg.debug)

    mode = "DRY RUN" if cfg.mqtt.dry_run else "LIVE"
    logger.info(
        "MQTT uplink: enabled (%s) — IATA=%s, key=%s...",
        mode, cfg.mqtt.iata, cfg.mqtt.resolve_public_key()[:12],
    )

    return uplink


def main():
    """Main entry point.

    Loads configuration, creates ArchiveWatcher, optionally starts
    MQTT uplink, starts the NiceGUI dashboard.
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

    if "--mqtt-dry-run" in flags:
        cfg.mqtt.dry_run = True
        # Also enable MQTT if not already
        if not cfg.mqtt.enabled:
            cfg.mqtt.enabled = True

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
    print(f"MQTT uplink:  {'ENABLED' if cfg.mqtt.enabled else 'DISABLED'}")
    if cfg.mqtt.enabled:
        mode = "DRY RUN" if cfg.mqtt.dry_run else "LIVE"
        print(f"MQTT mode:    {mode}")
        print(f"MQTT IATA:    {cfg.mqtt.iata}")
        enabled_brokers = [b.name for b in cfg.mqtt.brokers if b.enabled]
        print(f"MQTT brokers: {', '.join(enabled_brokers) or 'none'}")
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

    # ── Create MQTT uplink (if enabled) ──
    mqtt_uplink = _create_mqtt_uplink(cfg)
    if mqtt_uplink:
        mqtt_uplink.start()

    # ── Create dashboard ──
    _dashboard = ObserverDashboard(watcher, cfg, mqtt_uplink=mqtt_uplink)

    # ── Start NiceGUI server (blocks) ──
    print(f"Starting GUI on port {cfg.gui_port}...")

    try:
        ui.run(
            show=False,
            host="0.0.0.0",
            title=cfg.gui_title,
            port=cfg.gui_port,
            reload=False,
            storage_secret="meshcore-observer-secret",
        )
    finally:
        # Graceful MQTT shutdown
        if mqtt_uplink:
            mqtt_uplink.shutdown()


if __name__ == "__main__":
    main()
