"""
Observer-specific configuration.

Loads settings from a YAML configuration file and provides typed
access to all observer parameters.  Falls back to sensible defaults
when keys are missing.

Dependencies:
    pyyaml (6.x)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

# Default config file location (next to meshcore_observer.py)
DEFAULT_CONFIG_PATH: Path = Path(__file__).parent.parent / "observer_config.yaml"

# Device identity file written by meshcore_gui (auto-detected)
DEFAULT_DEVICE_IDENTITY_PATH: Path = Path.home() / ".meshcore-gui" / "device_identity.json"

# Valid key lengths (hex chars)
VALID_PUBLIC_KEY_LENGTH = 64        # 32-byte Ed25519 public key
VALID_PRIVATE_KEY_LENGTHS = (64, 128)  # 32-byte seed or 64-byte expanded


# ── Key validation helper ────────────────────────────────────────────


def _is_valid_key(hex_str: str, allowed_lengths: tuple) -> bool:
    """Check if *hex_str* is valid hex with one of the allowed lengths."""
    if not hex_str or len(hex_str) not in allowed_lengths:
        return False
    try:
        bytes.fromhex(hex_str)
        return True
    except ValueError:
        return False


# ── MQTT Broker Configuration ────────────────────────────────────────


@dataclass
class MqttBrokerConfig:
    """Configuration for a single MQTT broker endpoint."""

    name: str = "letsmesh-eu"
    server: str = "mqtt-eu-v1.letsmesh.net"
    port: int = 443
    transport: str = "websockets"
    tls: bool = True
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "MqttBrokerConfig":
        return cls(
            name=str(data.get("name", "letsmesh-eu")),
            server=str(data.get("server", "mqtt-eu-v1.letsmesh.net")),
            port=int(data.get("port", 443)),
            transport=str(data.get("transport", "websockets")),
            tls=bool(data.get("tls", True)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class MqttConfig:
    """MQTT uplink configuration.

    Attributes:
        enabled:               Master MQTT enable switch (default OFF).
        iata:                  3-letter IATA airport code for topic path.
        brokers:               List of broker endpoints.
        device_identity_file:  Path to meshcore_gui device identity JSON.
        private_key:           Ed25519 private key (hex) — from config.
        private_key_file:      Path to file containing private key.
        public_key:            Device public key (hex) — for topics/auth.
        device_name:           Device display name for ``origin`` field.
        upload_packet_types:   Packet type filter (empty = all).
        status_interval_s:     Seconds between status republish.
        reconnect_delay_s:     Seconds between reconnect attempts.
        max_reconnect_retries: Max reconnect retries (0 = infinite).
        token_lifetime_s:      JWT token validity in seconds.
        dry_run:               Log payloads but do not publish.
    """

    enabled: bool = False
    iata: str = "AMS"
    brokers: List[MqttBrokerConfig] = field(default_factory=list)
    device_identity_file: str = ""
    private_key: str = ""
    private_key_file: str = ""
    public_key: str = ""
    device_name: str = ""
    upload_packet_types: List[int] = field(default_factory=list)
    status_interval_s: int = 300
    reconnect_delay_s: int = 10
    max_reconnect_retries: int = 0
    token_lifetime_s: int = 3600
    dry_run: bool = False

    # Cached identity data (not serialised)
    _identity_cache: Optional[dict] = field(
        default=None, repr=False, compare=False,
    )

    @classmethod
    def from_dict(cls, data: dict) -> "MqttConfig":
        brokers_raw = data.get("brokers", [])
        brokers = [MqttBrokerConfig.from_dict(b) for b in brokers_raw]

        return cls(
            enabled=bool(data.get("enabled", False)),
            iata=str(data.get("iata", "AMS")),
            brokers=brokers,
            device_identity_file=str(data.get("device_identity_file", "")),
            private_key=str(data.get("private_key", "")),
            private_key_file=str(data.get("private_key_file", "")),
            public_key=str(data.get("public_key", "")),
            device_name=str(data.get("device_name", "")),
            upload_packet_types=list(data.get("upload_packet_types", [])),
            status_interval_s=int(data.get("status_interval_s", 300)),
            reconnect_delay_s=int(data.get("reconnect_delay_s", 10)),
            max_reconnect_retries=int(data.get("max_reconnect_retries", 0)),
            token_lifetime_s=int(data.get("token_lifetime_s", 3600)),
            dry_run=bool(data.get("dry_run", False)),
        )

    # ── Device identity loading ──────────────────────────────────────

    def _load_device_identity(self) -> Optional[dict]:
        """Load device identity JSON written by meshcore_gui.

        Checks (in order):
            1. ``device_identity_file`` from config (explicit path)
            2. Default path ``~/.meshcore-gui/device_identity.json``

        Accepts private keys in both 64-char (legacy seed) and 128-char
        (orlp expanded) formats.

        Returns:
            Dict with ``public_key`` and ``private_key``, or None.
        """
        if self._identity_cache is not None:
            return self._identity_cache

        paths_to_try = []
        if self.device_identity_file:
            paths_to_try.append(Path(self.device_identity_file).expanduser())
        paths_to_try.append(DEFAULT_DEVICE_IDENTITY_PATH)

        for id_path in paths_to_try:
            if not id_path.exists():
                continue
            try:
                data = json.loads(id_path.read_text(encoding="utf-8"))
                pub = data.get("public_key", "")
                priv = data.get("private_key", "")

                if (_is_valid_key(pub, (VALID_PUBLIC_KEY_LENGTH,))
                        and _is_valid_key(priv, VALID_PRIVATE_KEY_LENGTHS)):
                    logger.info(
                        "Loaded device identity from %s "
                        "(key=%s..., priv=%d chars)",
                        id_path, pub[:12], len(priv),
                    )
                    self._identity_cache = data
                    return data

                logger.warning(
                    "Device identity file %s has invalid key lengths "
                    "(pub=%d, priv=%d)",
                    id_path, len(pub), len(priv),
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Cannot read device identity file %s: %s",
                    id_path, exc,
                )

        self._identity_cache = {}  # Mark as tried (empty = not found)
        return None

    # ── Key resolution (Single Responsibility) ───────────────────────

    def resolve_private_key(self) -> str:
        """Resolve the private key.

        Priority:
            1. ``MESHCORE_PRIVATE_KEY`` environment variable
            2. Device identity file (auto from meshcore_gui)
            3. ``private_key_file`` config path
            4. ``private_key`` config value

        Returns:
            Hex private key string (64 or 128 chars), or empty string.
        """
        # Priority 1: environment variable
        env_key = os.environ.get("MESHCORE_PRIVATE_KEY", "").strip()
        if env_key:
            logger.debug("Using private key from MESHCORE_PRIVATE_KEY env var")
            return env_key

        # Priority 2: device identity file (written by meshcore_gui)
        identity = self._load_device_identity()
        if identity and identity.get("private_key"):
            logger.debug("Using private key from device identity file")
            return identity["private_key"]

        # Priority 3: key file
        if self.private_key_file:
            key_path = Path(self.private_key_file).expanduser()
            if key_path.exists():
                try:
                    key_data = key_path.read_text(encoding="utf-8").strip()
                    if key_data:
                        logger.debug("Using private key from file: %s", key_path)
                        return key_data
                except OSError as exc:
                    logger.error("Cannot read private key file %s: %s", key_path, exc)
            else:
                logger.warning("Private key file not found: %s", key_path)

        # Priority 4: inline config value
        if self.private_key:
            logger.warning(
                "Using private key from plain-text config — "
                "consider using private_key_file or MESHCORE_PRIVATE_KEY env var instead"
            )
            return self.private_key

        return ""

    def resolve_public_key(self) -> str:
        """Resolve the public key.

        Priority:
            1. ``MESHCORE_PUBLIC_KEY`` environment variable
            2. Device identity file (auto from meshcore_gui)
            3. ``public_key`` config value

        Returns:
            64-char hex public key string, or empty string.
        """
        env_key = os.environ.get("MESHCORE_PUBLIC_KEY", "").strip()
        if env_key:
            return env_key

        identity = self._load_device_identity()
        if identity and identity.get("public_key"):
            logger.debug("Using public key from device identity file")
            return identity["public_key"]

        if self.public_key:
            return self.public_key

        return ""

    def resolve_device_name(self) -> str:
        """Resolve the device display name.

        Returns:
            Device name string, or ``"MeshCore Observer"`` as default.
        """
        if self.device_name:
            return self.device_name

        identity = self._load_device_identity()
        if identity and identity.get("device_name"):
            return identity["device_name"]

        return "MeshCore Observer"

    # ── Validation ───────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """Validate MQTT configuration and return list of errors."""
        errors: List[str] = []

        if not self.enabled:
            return errors

        # IATA code
        if not self.iata or len(self.iata) != 3 or not self.iata.isalpha():
            errors.append(
                f"IATA code must be exactly 3 letters, got: '{self.iata}'"
            )

        # Public key
        pub = self.resolve_public_key()
        if not pub:
            errors.append("Public key is required for MQTT authentication")
        elif not _is_valid_key(pub, (VALID_PUBLIC_KEY_LENGTH,)):
            errors.append(
                f"Public key must be 64 hex chars, got {len(pub)}"
            )

        # Private key — accepts both 64 (seed) and 128 (expanded)
        priv = self.resolve_private_key()
        if not priv:
            errors.append(
                "Private key is required for MQTT authentication "
                "(set via config, file, or MESHCORE_PRIVATE_KEY env var)"
            )
        elif not _is_valid_key(priv, VALID_PRIVATE_KEY_LENGTHS):
            errors.append(
                f"Private key must be 64 or 128 hex chars, got {len(priv)}"
            )

        # At least one enabled broker
        enabled_brokers = [b for b in self.brokers if b.enabled]
        if not enabled_brokers:
            errors.append("At least one broker must be enabled")

        return errors


# ── Main Observer Configuration ──────────────────────────────────────


@dataclass
class ObserverConfig:
    """Complete observer daemon configuration."""

    archive_dir: str = str(Path.home() / ".meshcore-gui" / "archive")
    poll_interval_s: float = 2.0
    max_messages_display: int = 100
    max_rxlog_display: int = 50
    gui_port: int = 9093
    gui_title: str = "MeshCore Observer"
    debug: bool = False
    config_path: str = ""
    mqtt: MqttConfig = field(default_factory=MqttConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "ObserverConfig":
        """Load configuration from a YAML file.

        Missing keys fall back to dataclass defaults.
        """
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        observer_section = raw.get("observer", {})
        gui_section = raw.get("gui", {})
        mqtt_section = raw.get("mqtt", {})

        archive_raw = observer_section.get(
            "archive_dir",
            str(Path.home() / ".meshcore-gui" / "archive"),
        )
        archive_dir = str(Path(archive_raw).expanduser().resolve())

        mqtt_cfg = MqttConfig.from_dict(mqtt_section) if mqtt_section else MqttConfig()

        return cls(
            archive_dir=archive_dir,
            poll_interval_s=float(observer_section.get("poll_interval_s", 2.0)),
            max_messages_display=int(observer_section.get("max_messages_display", 100)),
            max_rxlog_display=int(observer_section.get("max_rxlog_display", 50)),
            gui_port=int(gui_section.get("port", 9093)),
            gui_title=str(gui_section.get("title", "MeshCore Observer")),
            mqtt=mqtt_cfg,
        )
