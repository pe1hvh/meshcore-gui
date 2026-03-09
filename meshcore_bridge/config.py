"""
Bridge-specific configuration.

Loads settings from a YAML configuration file and provides typed
access to all bridge parameters.  Falls back to sensible defaults
when keys are missing.

Dependencies:
    pyyaml (6.x)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# Default config file location (next to meshcore_bridge.py)
DEFAULT_CONFIG_PATH: Path = Path(__file__).parent.parent / "bridge_config.yaml"


@dataclass
class DeviceConfig:
    """Configuration for a single MeshCore device connection."""

    port: str = "/dev/ttyUSB0"
    baud: int = 115200
    label: str = ""


@dataclass
class BridgeConfig:
    """Complete bridge daemon configuration."""

    # Bridge channel settings
    channel_name: str = "bridge"
    channel_idx_a: int = 3
    channel_idx_b: int = 3
    poll_interval_ms: int = 200
    forward_prefix: bool = True
    max_forwarded_cache: int = 500

    # Device connections
    device_a: DeviceConfig = field(default_factory=lambda: DeviceConfig(
        port="/dev/ttyUSB1", label="869.525 MHz",
    ))
    device_b: DeviceConfig = field(default_factory=lambda: DeviceConfig(
        port="/dev/ttyUSB2", label="868.000 MHz",
    ))

    # GUI settings
    gui_port: int = 9092
    gui_title: str = "MeshCore Bridge"

    # Runtime flags (set from CLI, not YAML)
    debug: bool = False
    config_path: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> "BridgeConfig":
        """Load configuration from a YAML file.

        Missing keys fall back to dataclass defaults.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            Populated BridgeConfig instance.

        Raises:
            FileNotFoundError: If the config file does not exist.
            yaml.YAMLError: If the file contains invalid YAML.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        bridge_section = raw.get("bridge", {})
        device_a_section = raw.get("device_a", {})
        device_b_section = raw.get("device_b", {})
        gui_section = raw.get("gui", {})

        dev_a = DeviceConfig(
            port=device_a_section.get("port", "/dev/ttyUSB1"),
            baud=device_a_section.get("baud", 115200),
            label=device_a_section.get("label", "Device A"),
        )
        dev_b = DeviceConfig(
            port=device_b_section.get("port", "/dev/ttyUSB2"),
            baud=device_b_section.get("baud", 115200),
            label=device_b_section.get("label", "Device B"),
        )

        return cls(
            channel_name=bridge_section.get("channel_name", "bridge"),
            channel_idx_a=bridge_section.get("channel_idx_a", 3),
            channel_idx_b=bridge_section.get("channel_idx_b", 3),
            poll_interval_ms=bridge_section.get("poll_interval_ms", 200),
            forward_prefix=bridge_section.get("forward_prefix", True),
            max_forwarded_cache=bridge_section.get("max_forwarded_cache", 500),
            device_a=dev_a,
            device_b=dev_b,
            gui_port=gui_section.get("port", 9092),
            gui_title=gui_section.get("title", "MeshCore Bridge"),
        )

    def to_yaml(self, path: Path) -> None:
        """Write the current configuration to a YAML file.

        Args:
            path: Destination file path.
        """
        data = {
            "bridge": {
                "channel_name": self.channel_name,
                "channel_idx_a": self.channel_idx_a,
                "channel_idx_b": self.channel_idx_b,
                "poll_interval_ms": self.poll_interval_ms,
                "forward_prefix": self.forward_prefix,
                "max_forwarded_cache": self.max_forwarded_cache,
            },
            "device_a": {
                "port": self.device_a.port,
                "baud": self.device_a.baud,
                "label": self.device_a.label,
            },
            "device_b": {
                "port": self.device_b.port,
                "baud": self.device_b.baud,
                "label": self.device_b.label,
            },
            "gui": {
                "port": self.gui_port,
                "title": self.gui_title,
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False)
