"""
Observer-specific configuration.

Loads settings from a YAML configuration file and provides typed
access to all observer parameters.  Falls back to sensible defaults
when keys are missing.

Dependencies:
    pyyaml (6.x)
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


# Default config file location (next to meshcore_observer.py)
DEFAULT_CONFIG_PATH: Path = Path(__file__).parent.parent / "observer_config.yaml"


@dataclass
class ObserverConfig:
    """Complete observer daemon configuration.

    Attributes:
        archive_dir:          Path to archive directory (glob target).
        poll_interval_s:      Seconds between archive file polls.
        max_messages_display: Maximum messages shown in dashboard.
        max_rxlog_display:    Maximum RX log entries shown in dashboard.
        gui_port:             NiceGUI dashboard TCP port.
        gui_title:            Browser tab title.
        debug:                Enable verbose debug logging.
        config_path:          Path to loaded config file (runtime only).
    """

    archive_dir: str = str(Path.home() / ".meshcore-gui" / "archive")
    poll_interval_s: float = 2.0
    max_messages_display: int = 100
    max_rxlog_display: int = 50
    gui_port: int = 9093
    gui_title: str = "MeshCore Observer"
    debug: bool = False
    config_path: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> "ObserverConfig":
        """Load configuration from a YAML file.

        Missing keys fall back to dataclass defaults.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            Populated ObserverConfig instance.

        Raises:
            FileNotFoundError: If the config file does not exist.
            yaml.YAMLError: If the file contains invalid YAML.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        observer_section = raw.get("observer", {})
        gui_section = raw.get("gui", {})

        # Resolve archive_dir: expand ~ and make absolute
        archive_raw = observer_section.get(
            "archive_dir",
            str(Path.home() / ".meshcore-gui" / "archive"),
        )
        archive_dir = str(Path(archive_raw).expanduser().resolve())

        return cls(
            archive_dir=archive_dir,
            poll_interval_s=float(observer_section.get("poll_interval_s", 2.0)),
            max_messages_display=int(observer_section.get("max_messages_display", 100)),
            max_rxlog_display=int(observer_section.get("max_rxlog_display", 50)),
            gui_port=int(gui_section.get("port", 9093)),
            gui_title=str(gui_section.get("title", "MeshCore Observer")),
        )
