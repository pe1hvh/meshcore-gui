"""
Application configuration for MeshCore GUI.

Contains only global runtime settings and the channel table.
Bot configuration lives in :mod:`meshcore_gui.services.bot`.
UI display constants live in :mod:`meshcore_gui.gui.constants`.

The ``DEBUG`` flag defaults to False and can be activated at startup
with the ``--debug-on`` command-line option.
"""

from typing import Dict, List


# ==============================================================================
# DEBUG
# ==============================================================================

DEBUG: bool = False


def debug_print(msg: str) -> None:
    """Print a debug message when ``DEBUG`` is enabled."""
    if DEBUG:
        print(f"DEBUG: {msg}")


# ==============================================================================
# CHANNELS
# ==============================================================================

# Hardcoded channels configuration.
# Determine your channels with meshcli:
#   meshcli -d <BLE_ADDRESS>
#   > get_channels
# Output: 0: Public [...], 1: #test [...], etc.
CHANNELS_CONFIG: List[Dict] = [
    {'idx': 0, 'name': 'Public'},
    {'idx': 1, 'name': '#test'},
    {'idx': 2, 'name': '#zwolle'},
    {'idx': 3, 'name': 'RahanSom'},
    {'idx': 4, 'name': '#bot'},
]


# ==============================================================================
# CACHE / REFRESH
# ==============================================================================

# Interval in seconds between periodic contact refreshes from the device.
# Contacts are merged (new/changed contacts update the cache; contacts
# only present in cache are kept so offline nodes are preserved).
CONTACT_REFRESH_SECONDS: float = 300.0  # 5 minutes
