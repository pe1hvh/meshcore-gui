"""
Application configuration for MeshCore GUI.

Contains only global runtime settings.
Bot configuration lives in :mod:`meshcore_gui.services.bot`.
UI display constants live in :mod:`meshcore_gui.gui.constants`.

The ``DEBUG`` flag defaults to False and can be activated at startup
with the ``--debug-on`` command-line option.

Debug output is written to both stdout and a rotating log file at
``~/.meshcore-gui/logs/meshcore_gui.log``.
"""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List


# ==============================================================================
# VERSION
# ==============================================================================


VERSION: str = "1.19.0"


# ==============================================================================
# OPERATOR / LANDING PAGE
# ==============================================================================

# Operator callsign shown on the landing page SVG and drawer footer.
# Change this to your own callsign (e.g. "PE1HVH", "PE1HVH/MIT").
OPERATOR_CALLSIGN: str = "PE1HVH"

# Path to the landing page SVG file.
# The placeholder ``{callsign}`` inside the SVG is replaced at runtime
# with ``OPERATOR_CALLSIGN``.
#
# Default: the bundled DOMCA splash (static/landing_default.svg).
# To use a custom SVG, point this to your own file, e.g.:
#   LANDING_SVG_PATH = DATA_DIR / "landing.svg"
LANDING_SVG_PATH: Path = Path(__file__).parent / "static" / "landing_default.svg"


# ==============================================================================
# MAP DEFAULTS
# ==============================================================================

# Default map centre used as the initial view *before* the device reports
# its own GPS position.  Once the device advertises a valid adv_lat/adv_lon
# pair, every map will re-centre on the device's actual location.
#
# Change these values to match the location of your device / station.
# Current default: Zwolle, The Netherlands (52.5168, 6.0830).
DEFAULT_MAP_CENTER: tuple[float, float] = (52.5168, 6.0830)

# Default zoom level for all Leaflet maps (higher = more zoomed in).
DEFAULT_MAP_ZOOM: int = 9



# ==============================================================================
# DIRECTORY STRUCTURE
# ==============================================================================

# Base data directory — all persistent data lives under this root.
# Existing services (cache, pins, archive) each define their own
# sub-directory; this constant centralises the root for new consumers.
DATA_DIR: Path = Path.home() / ".meshcore-gui"

# Log directory for debug and error log files.
LOG_DIR: Path = DATA_DIR / "logs"

# Bot configuration directory — bot JSON files live here.
# File naming: _<safe_dev_id>_bot.json (e.g. _dev_ttyUSB1_bot.json).
BOT_DIR: Path = DATA_DIR / "bot"

# Log file path (rotating: max 5 MB per file, 3 backups = 20 MB total).
LOG_FILE: Path = LOG_DIR / "meshcore_gui.log"


def set_log_file_for_device(device_id: str) -> None:
    """Set the log file name based on the device identifier.

    Transforms ``F0:9E:9E:75:A3:01`` into
    ``~/.meshcore-gui/logs/F0_9E_9E_75_A3_01_meshcore_gui.log`` and
    ``/dev/ttyUSB0`` into ``~/.meshcore-gui/logs/_dev_ttyUSB0_meshcore_gui.log``.

    Must be called **before** the first ``debug_print()`` call so the
    lazy logger initialisation picks up the correct path.
    """
    global LOG_FILE
    safe_name = (
        device_id
        .replace("literal:", "")
        .replace(":", "_")
        .replace("/", "_")
    )
    LOG_FILE = LOG_DIR / f"{safe_name}_meshcore_gui.log"

# Maximum size per log file in bytes (5 MB).
LOG_MAX_BYTES: int = 5 * 1024 * 1024

# Number of rotated backup files to keep.
LOG_BACKUP_COUNT: int = 3


# ==============================================================================
# DEBUG
# ==============================================================================

DEBUG: bool = False

# Internal file logger — initialised lazily on first debug_print() call.
_file_logger: logging.Logger | None = None


def _init_file_logger() -> logging.Logger:
    """Create and configure the rotating file logger (called once)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("meshcore_gui.debug")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def _caller_module() -> str:
    """Return a short module label for the calling code.

    Walks two frames up (debug_print -> caller) and extracts the
    module ``__name__``.  The common ``meshcore_gui.`` prefix is
    stripped for brevity, e.g. ``ble.worker`` instead of
    ``meshcore_gui.ble.worker``.
    """
    frame = sys._getframe(2)  # 0=_caller_module, 1=debug_print, 2=actual caller
    module = frame.f_globals.get("__name__", "<unknown>")
    if module.startswith("meshcore_gui."):
        module = module[len("meshcore_gui."):]
    return module


def _init_meshcore_logger() -> None:
    """Route meshcore library debug output to our rotating log file.

    The meshcore library uses ``logging.getLogger("meshcore")`` throughout,
    but never attaches a handler.  Without this function all library-level
    debug output (raw send/receive, event dispatching, command flow)
    is silently dropped because Python's root logger only forwards
    WARNING and above.

    Call once at startup (or lazily from ``debug_print``) so that
    ``MESHCORE_LIB_DEBUG=True`` actually produces visible output.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    mc_logger = logging.getLogger("meshcore")
    # Guard against duplicate handlers on repeated calls
    if any(isinstance(h, RotatingFileHandler) for h in mc_logger.handlers):
        return

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  LIB [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    mc_logger.addHandler(handler)

    # Also add a stdout handler so library output appears in the console
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  LIB [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    mc_logger.addHandler(stdout_handler)


def debug_print(msg: str) -> None:
    """Print a debug message when ``DEBUG`` is enabled.

    Output goes to both stdout and the rotating log file.
    The calling module name is automatically included so that
    exception context is immediately clear, e.g.::

        DEBUG [ble.worker]: send_appstart attempt 3 exception: TimeoutError
    """
    global _file_logger

    if not DEBUG:
        return

    module = _caller_module()
    formatted = f"DEBUG [{module}]: {msg}"

    # stdout (existing behaviour, now with module tag)
    print(formatted)

    # Rotating log file
    if _file_logger is None:
        _file_logger = _init_file_logger()
        # Also wire up the meshcore library logger so MESHCORE_LIB_DEBUG
        # output actually appears in the same log file + stdout.
        _init_meshcore_logger()
    _file_logger.debug(formatted)


def pp(obj: Any, indent: int = 2) -> str:
    """Pretty-format a dict, list, or other object for debug output.

    Use inside f-strings::

        debug_print(f"payload={pp(r.payload)}")

    Dicts/lists get indented JSON; everything else falls back to repr().
    """
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return repr(obj)
    return repr(obj)


def debug_data(label: str, obj: Any) -> None:
    """Print a labelled data structure with pretty indentation.

    Combines a header line with pretty-printed data below it::

        debug_data("get_contacts result", r.payload)

    Output::

        DEBUG [worker]: get_contacts result ↓
          {
            "name": "PE1HVH",
            "contacts": 629,
            ...
          }
    """
    if not DEBUG:
        return
    formatted = pp(obj)
    # Single-line values stay on the same line
    if '\n' not in formatted:
        debug_print(f"{label}: {formatted}")
    else:
        # Multi-line: indent each line for readability
        indented = '\n'.join(f"  {line}" for line in formatted.splitlines())
        debug_print(f"{label} ↓\n{indented}")


# ==============================================================================
# CHANNELS
# ==============================================================================

# Maximum number of channel slots to probe on the device.
# MeshCore supports up to 8 channels (indices 0-7).
MAX_CHANNELS: int = 100

# Enable or disable caching of the channel list to disk.
# When False (default), channels are always fetched fresh from the
# device at startup, guaranteeing the GUI always reflects the actual
# device configuration.  When True, channels are loaded from cache
# for instant GUI population and then refreshed from the device.
# Note: channel *keys* (for packet decryption) are always cached
# regardless of this setting.
CHANNEL_CACHE_ENABLED: bool = False


# ==============================================================================
# PUBLIC API
# ==============================================================================

# Enable or disable the public REST API endpoints (/api/v1/*).
# When False, no routes are registered and the API is unreachable.
API_ENABLED: bool = True

# CORS origins allowed to call the public API.
# Set to the internal IP or hostname of the domca.nl Raspberry Pi.
# Example: ["http://192.168.1.10", "https://www.domca.nl"]
# Use ["*"] only on trusted internal networks.
API_CORS_ORIGINS: list[str] = ["*"]


# ==============================================================================
# BOT DEVICE NAME
# ==============================================================================

# Fixed device name applied when the BOT checkbox is enabled.
# The original device name is saved and restored when BOT is disabled.
BOT_DEVICE_NAME: str = "ZwolsBotje"

# Default device name used as fallback when restoring from BOT mode
# and no original name was saved (e.g. after a restart).
DEVICE_NAME: str = "PE1HVH T1000e"


# ==============================================================================
# CACHE / REFRESH
# ==============================================================================

# Default timeout (seconds) for meshcore command responses.
# Increase if you see frequent 'no_event_received' errors during startup.
DEFAULT_TIMEOUT: float = 10.0

# Enable debug logging inside the meshcore library itself.
# When True, raw send/receive data and event parsing are logged.
MESHCORE_LIB_DEBUG: bool = True

# ==============================================================================
# TRANSPORT MODE  (auto-detected from CLI argument)
# ==============================================================================

# "serial" or "ble" — set at startup by main() based on the device argument.
TRANSPORT: str = "serial"


def is_ble_address(device_id: str) -> bool:
    """Detect whether *device_id* looks like a BLE MAC address.

    Heuristic:
    - Starts with ``literal:`` → BLE
    - Matches ``XX:XX:XX:XX:XX:XX`` (6 colon-separated hex pairs) → BLE
    - Everything else (``/dev/…``, ``COM…``) → Serial
    """
    if device_id.lower().startswith("literal:"):
        return True
    parts = device_id.split(":")
    if len(parts) == 6 and all(len(p) == 2 for p in parts):
        try:
            for p in parts:
                int(p, 16)
            return True
        except ValueError:
            pass
    return False
TRANSPORT: str = "serial"

# Serial connection defaults.
SERIAL_BAUDRATE: int = 115200
SERIAL_CX_DELAY: float = 0.1

# BLE connection defaults.
# BLE pairing PIN for the MeshCore device (T1000e default: 123456).
# Used by the built-in D-Bus agent to answer pairing requests
# automatically — eliminates the need for bt-agent.service.
BLE_PIN: str = "123456"

# Maximum number of reconnect attempts after a disconnect.
RECONNECT_MAX_RETRIES: int = 5

# Base delay in seconds between reconnect attempts (multiplied by
# attempt number for linear backoff: 5s, 10s, 15s, 20s, 25s).
RECONNECT_BASE_DELAY: float = 5.0

# Interval in seconds between periodic contact refreshes from the device.
# Contacts are merged (new/changed contacts update the cache; contacts
# only present in cache are kept so offline nodes are preserved).
CONTACT_REFRESH_SECONDS: float = 300.0  # 5 minutes

# ==============================================================================
# EXTERNAL LINKS (drawer menu)
# ==============================================================================

EXT_LINKS = [
    ('MeshCore',      'https://meshcore.co.uk'),
    ('Handleiding',   'https://www.pe1hvh.nl/pdf/MeshCore_Complete_Handleiding.pdf'),
    ('Netwerk kaart', 'https://meshcore.co.uk/map'),
    ('LocalMesh NL',  'https://www.localmesh.nl/'),
]
# ==============================================================================
# ARCHIVE / RETENTION
# ==============================================================================

# Retention period for archived messages (in days).
# Messages older than this are automatically removed during cleanup.
MESSAGE_RETENTION_DAYS: int = 30

# Retention period for RX log entries (in days).
# RX log entries older than this are automatically removed during cleanup.
RXLOG_RETENTION_DAYS: int = 7

# Retention period for contacts (in days).
# Contacts not seen for longer than this are removed from cache.
CONTACT_RETENTION_DAYS: int = 90


# BBS channel configuration is managed at runtime via BbsConfigStore.
# Settings are persisted to ~/.meshcore-gui/bbs/bbs_config.json
# and edited through the BBS Settings panel in the GUI.
