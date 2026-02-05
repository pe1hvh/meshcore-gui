"""
Configuration and shared constants for MeshCore GUI.

Contains:
    - Debug flag and debug_print helper
    - Channel configuration
    - Contact type mappings

The DEBUG flag defaults to False and can be activated at startup
with the ``--debug-on`` command-line option.
"""

from typing import Dict, List


# ==============================================================================
# DEBUG
# ==============================================================================

DEBUG = False


def debug_print(msg: str) -> None:
    """
    Print debug message if DEBUG mode is enabled.

    Args:
        msg: The message to print
    """
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
]


# ==============================================================================
# CONTACT TYPE MAPPINGS
# ==============================================================================

TYPE_ICONS: Dict[int, str] = {0: "○", 1: "📱", 2: "📡", 3: "🏠"}
TYPE_NAMES: Dict[int, str] = {0: "-", 1: "CLI", 2: "REP", 3: "ROOM"}
TYPE_LABELS: Dict[int, str] = {0: "-", 1: "Companion", 2: "Repeater", 3: "Room Server"}


# ==============================================================================
# BOT
# ==============================================================================

# Channel index the bot listens on (must match CHANNELS_CONFIG).
BOT_CHANNEL: int = 1  # #test

# Display name prepended to every bot reply.
BOT_NAME: str = "Zwolle Bot"

# Minimum seconds between two bot replies (prevents reply-storms).
BOT_COOLDOWN_SECONDS: float = 5.0

# Keyword → reply template mapping.
# Available variables: {bot}, {sender}, {snr}, {path}
# The bot checks whether the incoming message text *contains* the keyword
# (case-insensitive).  First match wins.
BOT_KEYWORDS: Dict[str, str] = {
    'test': '{bot}: {sender}, rcvd | SNR {snr} | {path}',
    'ping': '{bot}: Pong!',
    'help': '{bot}: test, ping, help',
}
