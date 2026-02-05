"""
Thread-safe shared data container for MeshCore GUI.

SharedData is the central data store shared between the BLE worker thread
and the GUI main thread.  All access goes through methods that acquire a
threading.Lock so both threads can safely read and write.

Single-source architecture
~~~~~~~~~~~~~~~~~~~~~~~~~~
Path data (repeater hashes) is embedded in each message dict at creation
time — decoded from the raw LoRa packet via ``meshcoredecoder``.  There
is no temporal archive or deferred matching.
"""

import queue
import threading
from typing import Dict, List, Optional, Tuple

from meshcore_gui.config import debug_print


class SharedData:
    """
    Thread-safe container for shared data between BLE worker and GUI.

    Attributes:
        lock: Threading lock for thread-safe access
        name: Device name
        public_key: Device public key
        radio_freq: Radio frequency in MHz
        radio_sf: Spreading factor
        radio_bw: Bandwidth in kHz
        tx_power: Transmit power in dBm
        adv_lat: Advertised latitude
        adv_lon: Advertised longitude
        firmware_version: Firmware version string
        connected: Whether device is connected
        status: Status text for UI
        contacts: Dict of contacts {key: {adv_name, type, lat, lon, …}}
        channels: List of channels [{idx, name}, …]
        messages: List of messages
        rx_log: List of RX log entries
    """

    def __init__(self) -> None:
        """Initialize SharedData with empty values and flags set to True."""
        self.lock = threading.Lock()

        # Device info
        self.name: str = ""
        self.public_key: str = ""
        self.radio_freq: float = 0.0
        self.radio_sf: int = 0
        self.radio_bw: float = 0.0
        self.tx_power: int = 0
        self.adv_lat: float = 0.0
        self.adv_lon: float = 0.0
        self.firmware_version: str = ""

        # Connection status
        self.connected: bool = False
        self.status: str = "Starting..."

        # Data collections
        self.contacts: Dict = {}
        self.channels: List[Dict] = []
        self.messages: List[Dict] = []
        self.rx_log: List[Dict] = []

        # Command queue (GUI → BLE)
        self.cmd_queue: queue.Queue = queue.Queue()

        # Update flags — initially True so first GUI render shows data
        self.device_updated: bool = True
        self.contacts_updated: bool = True
        self.channels_updated: bool = True
        self.rxlog_updated: bool = True

        # Flag to track if GUI has done first render
        self.gui_initialized: bool = False

        # BOT enabled flag (toggled from GUI)
        self.bot_enabled: bool = False

    # ------------------------------------------------------------------
    # Device info updates
    # ------------------------------------------------------------------

    def update_from_appstart(self, payload: Dict) -> None:
        """Update device info from send_appstart response."""
        with self.lock:
            self.name = payload.get('name', self.name)
            self.public_key = payload.get('public_key', self.public_key)
            self.radio_freq = payload.get('radio_freq', self.radio_freq)
            self.radio_sf = payload.get('radio_sf', self.radio_sf)
            self.radio_bw = payload.get('radio_bw', self.radio_bw)
            self.tx_power = payload.get('tx_power', self.tx_power)
            self.adv_lat = payload.get('adv_lat', self.adv_lat)
            self.adv_lon = payload.get('adv_lon', self.adv_lon)
            self.device_updated = True
            debug_print(f"Device info updated: {self.name}")

    def update_from_device_query(self, payload: Dict) -> None:
        """Update firmware version from send_device_query response."""
        with self.lock:
            self.firmware_version = payload.get('ver', self.firmware_version)
            self.device_updated = True
            debug_print(f"Firmware version: {self.firmware_version}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        """Update status text."""
        with self.lock:
            self.status = status

    def set_connected(self, connected: bool) -> None:
        """Update connection status."""
        with self.lock:
            self.connected = connected

    # ------------------------------------------------------------------
    # BOT
    # ------------------------------------------------------------------

    def set_bot_enabled(self, enabled: bool) -> None:
        """Toggle the BOT on or off."""
        with self.lock:
            self.bot_enabled = enabled
            debug_print(f"BOT {'enabled' if enabled else 'disabled'}")

    def is_bot_enabled(self) -> bool:
        """Return whether the BOT is currently enabled."""
        with self.lock:
            return self.bot_enabled

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    def put_command(self, cmd: Dict) -> None:
        """Enqueue a command for the BLE worker."""
        self.cmd_queue.put(cmd)

    def get_next_command(self) -> Optional[Dict]:
        """
        Dequeue the next command, or return None if the queue is empty.

        Returns:
            Command dictionary, or None.
        """
        try:
            return self.cmd_queue.get_nowait()
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def set_contacts(self, contacts_dict: Dict) -> None:
        """Replace the contacts dictionary."""
        with self.lock:
            self.contacts = contacts_dict.copy()
            self.contacts_updated = True
            debug_print(f"Contacts updated: {len(self.contacts)} contacts")

    def set_channels(self, channels: List[Dict]) -> None:
        """Replace the channels list."""
        with self.lock:
            self.channels = channels.copy()
            self.channels_updated = True
            debug_print(f"Channels updated: {[c['name'] for c in channels]}")

    def add_message(self, msg: Dict) -> None:
        """
        Add a message to the messages list (max 100).

        Args:
            msg: Message dict with keys: time, sender, text, channel,
                 direction, path_len, path_hashes, message_hash,
                 sender_pubkey, snr
        """
        with self.lock:
            self.messages.append(msg)
            if len(self.messages) > 100:
                self.messages.pop(0)
            debug_print(
                f"Message added: {msg.get('sender', '?')}: "
                f"{msg.get('text', '')[:30]}"
            )

    def add_rx_log(self, entry: Dict) -> None:
        """Add an RX log entry (max 50, newest first)."""
        with self.lock:
            self.rx_log.insert(0, entry)
            if len(self.rx_log) > 50:
                self.rx_log.pop()
            self.rxlog_updated = True

    # ------------------------------------------------------------------
    # Snapshot and flags
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict:
        """Create a complete snapshot of all data for the GUI."""
        with self.lock:
            return {
                'name': self.name,
                'public_key': self.public_key,
                'radio_freq': self.radio_freq,
                'radio_sf': self.radio_sf,
                'radio_bw': self.radio_bw,
                'tx_power': self.tx_power,
                'adv_lat': self.adv_lat,
                'adv_lon': self.adv_lon,
                'firmware_version': self.firmware_version,
                'connected': self.connected,
                'status': self.status,
                'contacts': self.contacts.copy(),
                'channels': self.channels.copy(),
                'messages': self.messages.copy(),
                'rx_log': self.rx_log.copy(),
                'device_updated': self.device_updated,
                'contacts_updated': self.contacts_updated,
                'channels_updated': self.channels_updated,
                'rxlog_updated': self.rxlog_updated,
                'gui_initialized': self.gui_initialized,
                'bot_enabled': self.bot_enabled,
            }

    def clear_update_flags(self) -> None:
        """Reset all update flags to False."""
        with self.lock:
            self.device_updated = False
            self.contacts_updated = False
            self.channels_updated = False
            self.rxlog_updated = False

    def mark_gui_initialized(self) -> None:
        """Mark that the GUI has completed its first render."""
        with self.lock:
            self.gui_initialized = True
            debug_print("GUI marked as initialized")

    # ------------------------------------------------------------------
    # Contact lookups
    # ------------------------------------------------------------------

    def get_contact_by_prefix(self, pubkey_prefix: str) -> Optional[Dict]:
        """
        Look up a contact by public key prefix.

        Used by route visualization to resolve pubkey prefixes (from
        messages and out_path) to full contact records.

        Returns:
            Copy of the contact dictionary, or None if not found.
        """
        if not pubkey_prefix:
            return None

        with self.lock:
            for key, contact in self.contacts.items():
                if key.startswith(pubkey_prefix) or pubkey_prefix.startswith(key):
                    return contact.copy()
        return None

    def get_contact_name_by_prefix(self, pubkey_prefix: str) -> str:
        """
        Look up a contact name by public key prefix.

        Returns:
            The contact's adv_name, or the first 8 chars of the prefix
            if not found, or empty string if prefix is empty.
        """
        if not pubkey_prefix:
            return ""

        with self.lock:
            for key, contact in self.contacts.items():
                if key.startswith(pubkey_prefix):
                    name = contact.get('adv_name', '')
                    if name:
                        return name

        return pubkey_prefix[:8]

    # ------------------------------------------------------------------
    # Contact lookup by name
    # ------------------------------------------------------------------

    def get_contact_by_name(self, name: str) -> Optional[Tuple[str, Dict]]:
        """
        Look up a contact by advertised name.

        Tries in order: exact match → case-insensitive → startswith
        (either direction, to handle truncated names).

        Returns:
            ``(pubkey, contact_dict)`` tuple, or ``None`` if no match.
        """
        if not name:
            return None

        with self.lock:
            # Strategy 1: exact match
            for key, contact in self.contacts.items():
                if contact.get('adv_name', '') == name:
                    return (key, contact.copy())

            # Strategy 2: case-insensitive
            name_lower = name.lower()
            for key, contact in self.contacts.items():
                if contact.get('adv_name', '').lower() == name_lower:
                    return (key, contact.copy())

            # Strategy 3: one name starts with the other
            for key, contact in self.contacts.items():
                adv = contact.get('adv_name', '')
                if not adv:
                    continue
                if name.startswith(adv) or adv.startswith(name):
                    return (key, contact.copy())

        return None
