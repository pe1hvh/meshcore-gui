"""
Thread-safe shared data container for MeshCore GUI.

SharedData is the central data store shared between the worker thread
and the GUI main thread.  All access goes through methods that acquire a
threading.Lock so both threads can safely read and write.

v4.1 changes
~~~~~~~~~~~~~
- ``messages`` is now ``List[Message]`` (was ``List[Dict]``).
- ``rx_log`` is now ``List[RxLogEntry]`` (was ``List[Dict]``).
- ``DeviceInfo`` dataclass replaces loose scalar fields.
- ``get_snapshot()`` returns typed objects; UI code accesses attributes
  directly (``msg.sender``) instead of dict keys (``msg['sender']``).
"""

import queue
import threading
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from meshcore_gui.config import debug_print
from meshcore_gui.core.models import DeviceInfo, Message, RxLogEntry
from meshcore_gui.services.message_archive import MessageArchive


class SharedData:
    """
    Thread-safe container for shared data between worker and GUI.

    Implements all four Protocol interfaces defined in ``protocols.py``.
    """

    def __init__(self, device_id: Optional[str] = None) -> None:
        self.lock = threading.Lock()

        # Device info (typed)
        self.device = DeviceInfo()

        # Connection status
        self.connected: bool = False
        self.status: str = "Starting..."

        # Data collections (typed)
        self.contacts: Dict = {}
        self.channels: List[Dict] = []
        self.messages: List[Message] = []
        self.rx_log: List[RxLogEntry] = []

        # Dedup guard: fingerprints of messages already in self.messages.
        # Acts as last-line-of-defence against duplicate inserts regardless
        # of the source (archive reload, device event, reconnect).
        self._message_fingerprints: set = set()

        # Command queue (GUI → worker)
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

        # Auto-add contacts flag (synced with device)
        self.auto_add_enabled: bool = False

        # Original device name (saved when BOT is enabled, restored when disabled)
        self.original_device_name: Optional[str] = None

        # Room Server login states: pubkey → {'state': 'ok'|'fail'|'pending'|'logged_out', 'detail': str}
        self.room_login_states: Dict[str, Dict] = {}

        # Room message cache: pubkey_prefix (12 hex) → List[Message]
        # Populated from archive on first access per room, then kept in
        # sync by add_message().
        self._room_msg_cache: Dict[str, List[Message]] = {}

        # Message archive (persistent storage)
        self.archive: Optional[MessageArchive] = None
        if device_id:
            self.archive = MessageArchive(device_id)
            debug_print(f"MessageArchive initialized for {device_id}")

    # ------------------------------------------------------------------
    # Device info updates
    # ------------------------------------------------------------------

    def update_from_appstart(self, payload: Dict) -> None:
        """Update device info from send_appstart response."""
        with self.lock:
            d = self.device
            d.name = payload.get('name', d.name)
            d.public_key = payload.get('public_key', d.public_key)
            d.radio_freq = payload.get('radio_freq', d.radio_freq)
            d.radio_sf = payload.get('radio_sf', d.radio_sf)
            d.radio_bw = payload.get('radio_bw', d.radio_bw)
            d.tx_power = payload.get('tx_power', d.tx_power)
            d.adv_lat = payload.get('adv_lat', d.adv_lat)
            d.adv_lon = payload.get('adv_lon', d.adv_lon)
            self.device_updated = True
            debug_print(f"Device info updated: {d.name}")

    def update_from_device_query(self, payload: Dict) -> None:
        """Update firmware version from send_device_query response."""
        with self.lock:
            self.device.firmware_version = payload.get(
                'ver', self.device.firmware_version,
            )
            self.device_updated = True
            debug_print(f"Firmware version: {self.device.firmware_version}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        with self.lock:
            self.status = status

    def set_connected(self, connected: bool) -> None:
        with self.lock:
            self.connected = connected

    # ------------------------------------------------------------------
    # BOT
    # ------------------------------------------------------------------

    def set_bot_enabled(self, enabled: bool) -> None:
        with self.lock:
            self.bot_enabled = enabled
            debug_print(f"BOT {'enabled' if enabled else 'disabled'}")

    def is_bot_enabled(self) -> bool:
        with self.lock:
            return self.bot_enabled

    # ------------------------------------------------------------------
    # Auto-add contacts
    # ------------------------------------------------------------------

    def set_auto_add_enabled(self, enabled: bool) -> None:
        """Set auto-add contacts flag (thread-safe)."""
        with self.lock:
            self.auto_add_enabled = enabled
            debug_print(f"Auto-add {'enabled' if enabled else 'disabled'}")

    def is_auto_add_enabled(self) -> bool:
        """Get auto-add contacts flag (thread-safe)."""
        with self.lock:
            return self.auto_add_enabled

    # ------------------------------------------------------------------
    # Original device name (BOT feature)
    # ------------------------------------------------------------------

    def set_original_device_name(self, name: Optional[str]) -> None:
        """Store the original device name before BOT rename (thread-safe)."""
        with self.lock:
            self.original_device_name = name
            debug_print(f"Original device name stored: {name}")

    def get_original_device_name(self) -> Optional[str]:
        """Get the stored original device name (thread-safe)."""
        with self.lock:
            return self.original_device_name

    def get_device_name(self) -> str:
        """Get the current device name (thread-safe)."""
        with self.lock:
            return self.device.name

    # ------------------------------------------------------------------
    # Room Server login state
    # ------------------------------------------------------------------

    def set_room_login_state(
        self, pubkey_prefix: str, state: str, detail: str = "",
    ) -> None:
        """Update login state for a Room Server (thread-safe).

        Cleans up any stale entries whose first 12 hex chars match the
        new key.  This prevents duplicate keys (e.g. a 12-char prefix
        from the worker *and* a 64-char full pubkey from the command
        handler) from coexisting and causing the UI to see stale state.

        Args:
            pubkey_prefix: Room server pubkey (full or prefix hex string).
            state:         One of 'pending', 'ok', 'fail', 'logged_out'.
            detail:        Human-readable detail string.
        """
        with self.lock:
            # Remove overlapping entries (different key length, same room)
            norm = pubkey_prefix[:12]
            stale = [
                k for k in self.room_login_states
                if k != pubkey_prefix and k[:12] == norm
            ]
            for k in stale:
                debug_print(
                    f"Room login state: removing stale key {k[:12]}…"
                )
                del self.room_login_states[k]

            self.room_login_states[pubkey_prefix] = {
                'state': state,
                'detail': detail,
            }
            debug_print(
                f"Room login state: {pubkey_prefix[:12]}… → {state}"
                f"{(' (' + detail + ')') if detail else ''}"
            )

    def get_room_login_states(self) -> Dict[str, Dict]:
        """Return a copy of all room login states (thread-safe)."""
        with self.lock:
            return {k: v.copy() for k, v in self.room_login_states.items()}

    # ------------------------------------------------------------------
    # Room message cache (archive → UI)
    # ------------------------------------------------------------------

    def load_room_history(self, pubkey: str, limit: int = 50) -> None:
        """Load archived room messages into the in-memory cache.

        Called by the command handler at room login and when a room
        card is first created.  Safe to call multiple times — subsequent
        calls refresh the cache from the archive.

        Args:
            pubkey: Room server public key (full or prefix, ≥ 12 hex chars).
            limit:  Maximum number of archived messages to load.
        """
        if not self.archive:
            return

        norm = pubkey[:12]
        archived = self.archive.get_messages_by_sender_pubkey(norm, limit)

        with self.lock:
            messages = [Message.from_dict(d) for d in archived]
            self._room_msg_cache[norm] = messages
            debug_print(
                f"Room history loaded: {norm}… → {len(messages)} messages"
            )

    def get_room_messages(self, pubkey: str) -> List[Message]:
        """Return cached room messages for a given room pubkey (thread-safe).

        Args:
            pubkey: Room server public key (full or prefix, ≥ 12 hex chars).

        Returns:
            List of Message objects (oldest first), or empty list.
        """
        norm = pubkey[:12]
        with self.lock:
            return list(self._room_msg_cache.get(norm, []))

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    def put_command(self, cmd: Dict) -> None:
        self.cmd_queue.put(cmd)

    def get_next_command(self) -> Optional[Dict]:
        try:
            return self.cmd_queue.get_nowait()
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def set_contacts(self, contacts_dict: Dict) -> None:
        with self.lock:
            self.contacts = contacts_dict.copy()
            self.contacts_updated = True
            debug_print(f"Contacts updated: {len(self.contacts)} contacts")

    def set_channels(self, channels: List[Dict]) -> None:
        with self.lock:
            self.channels = channels.copy()
            self.channels_updated = True
            debug_print(f"Channels updated: {[c['name'] for c in channels]}")

    @staticmethod
    def _message_fingerprint(msg: Message) -> str:
        """Build a dedup fingerprint for a message.

        Uses message_hash when available (deterministic packet ID),
        otherwise falls back to a composite of channel, sender and text.

        Args:
            msg: Message to fingerprint.

        Returns:
            String key suitable for set membership tests.
        """
        if msg.message_hash:
            return f"h:{msg.message_hash}"
        return f"c:{msg.channel}:{msg.sender}:{msg.text}"

    def add_message(self, msg: Message) -> None:
        """Add a Message to the store (max 100).

        Skips the message if an identical fingerprint is already present,
        preventing duplicates regardless of the insertion source (archive
        reload, device event, reconnect).

        Also resolves channel_name and path_names from the current
        contacts/channels list if not already set, and appends to the
        room-message cache if the sender matches a known room, keeping
        archive and cache in sync.
        """
        with self.lock:
            # Dedup guard: skip if fingerprint already tracked
            fps = {self._message_fingerprint(msg)}
            # Also mark outgoing messages under device name to suppress echo
            if msg.direction == 'out' and msg.sender == 'Me':
                device_name = self.device.name
                if device_name:
                    fps.add(f"c:{msg.channel}:{device_name}:{msg.text}")
            if any(fp in self._message_fingerprints for fp in fps):
                debug_print(
                    f"Message skipped (duplicate fingerprint): "
                    f"{msg.sender}: {msg.text[:30]}"
                )
                return

            # Resolve channel_name if missing
            if not msg.channel_name and msg.channel is not None:
                msg.channel_name = self._resolve_channel_name(msg.channel)

            # Resolve path_names if missing but path_hashes are present
            if msg.path_hashes and not msg.path_names:
                msg.path_names = self._resolve_path_names(msg.path_hashes)

            self.messages.append(msg)
            for fp in fps:
                self._message_fingerprints.add(fp)

            if len(self.messages) > 100:
                removed = self.messages.pop(0)
                # Evict fingerprint of removed message
                removed_fps = {self._message_fingerprint(removed)}
                if removed.direction == 'out' and removed.sender == 'Me':
                    device_name = self.device.name
                    if device_name:
                        removed_fps.add(
                            f"c:{removed.channel}:{device_name}:{removed.text}"
                        )
                for fp in removed_fps:
                    self._message_fingerprints.discard(fp)

            debug_print(
                f"Message added: {msg.sender}: {msg.text[:30]}"
            )

            # Keep room message cache in sync
            if msg.sender_pubkey:
                norm = msg.sender_pubkey[:12]
                if norm in self._room_msg_cache:
                    self._room_msg_cache[norm].append(msg)
            
            # Archive message for persistent storage
            if self.archive:
                self.archive.add_message(msg)

    def _resolve_channel_name(self, channel_idx: int) -> str:
        """Resolve a channel index to its display name.

        MUST be called with self.lock held.

        Args:
            channel_idx: Numeric channel index.

        Returns:
            Channel name string, or ``'Ch <idx>'`` as fallback.
        """
        for ch in self.channels:
            ch_idx = ch.get('idx', ch.get('index', 0))
            if ch_idx == channel_idx:
                return ch.get('name', f'Ch {channel_idx}')
        return f'Ch {channel_idx}'

    def _resolve_path_names(self, path_hashes: list) -> list:
        """Resolve 2-char path hashes to display names.

        MUST be called with self.lock held.

        Safety-net for messages whose path_names were not resolved at
        receive time (e.g. older code path, or contacts not yet loaded).

        Args:
            path_hashes: List of 2-char hex strings.

        Returns:
            List of display names (same length as *path_hashes*).
        """
        names = []
        for h in path_hashes:
            if not h or len(h) < 2:
                names.append('-')
                continue
            found_name = ''
            for key, contact in self.contacts.items():
                if key.lower().startswith(h.lower()):
                    found_name = contact.get('adv_name', '')
                    break
            names.append(found_name if found_name else f'0x{h.upper()}')
        return names

    def add_rx_log(self, entry: RxLogEntry) -> None:
        """Add an RxLogEntry (max 50, newest first)."""
        with self.lock:
            self.rx_log.insert(0, entry)
            if len(self.rx_log) > 50:
                self.rx_log.pop()
            self.rxlog_updated = True
            
            # Archive entry for persistent storage
            if self.archive:
                self.archive.add_rx_log(entry)

    def load_recent_from_archive(self, limit: int = 100) -> int:
        """Load the most recent archived messages into the in-memory list.

        Intended for startup: populates ``self.messages`` from the
        persistent archive so the main page shows historical messages
        immediately, before any live device traffic arrives.

        Safe to call multiple times (idempotent): clears the existing
        message list and fingerprint set before loading, so reconnect
        cycles do not produce duplicates.

        Messages are inserted directly (not re-archived) to avoid
        duplicating data on disk.

        Args:
            limit: Maximum number of messages to load.

        Returns:
            Number of messages loaded.
        """
        if not self.archive:
            return 0

        recent, _ = self.archive.query_messages(limit=limit)
        if not recent:
            return 0

        with self.lock:
            # Clear existing messages and fingerprints to ensure
            # idempotent behaviour on repeated calls (reconnect).
            self.messages.clear()
            self._message_fingerprints.clear()

            # recent is newest-first; reverse so oldest is appended first
            for msg_dict in reversed(recent):
                msg = Message.from_dict(msg_dict)
                fp = self._message_fingerprint(msg)
                if fp not in self._message_fingerprints:
                    self.messages.append(msg)
                    self._message_fingerprints.add(fp)

            # Cap at 100 (same as add_message)
            if len(self.messages) > 100:
                self.messages = self.messages[-100:]
                # Rebuild fingerprint set from retained messages
                self._message_fingerprints = {
                    self._message_fingerprint(m) for m in self.messages
                }

            debug_print(
                f"Loaded {len(self.messages)} recent messages from archive"
            )
            return len(self.messages)

    # ------------------------------------------------------------------
    # Snapshot and flags
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict:
        """Create a complete snapshot of all data for the GUI.

        Returns a plain dict with typed objects inside.  The
        ``messages`` and ``rx_log`` values are lists of dataclass
        instances (not dicts).
        """
        with self.lock:
            return self._build_snapshot_unlocked()

    def get_snapshot_and_clear_flags(self) -> Dict:
        """Atomically snapshot all data and reset update flags.

        Combines ``get_snapshot()`` and ``clear_update_flags()`` in a
        single lock acquisition.  This eliminates the race condition
        where the worker sets a flag between the two separate calls,
        causing the GUI to miss an update (e.g. newly discovered
        channels never appearing in the menu).

        Returns:
            Same dict structure as ``get_snapshot()``.
        """
        with self.lock:
            snapshot = self._build_snapshot_unlocked()
            self.device_updated = False
            self.contacts_updated = False
            self.channels_updated = False
            self.rxlog_updated = False
            return snapshot

    def _build_snapshot_unlocked(self) -> Dict:
        """Build the snapshot dict.  MUST be called with self.lock held."""
        d = self.device
        return {
            # DeviceInfo fields (flat for backward compat)
            'name': d.name,
            'public_key': d.public_key,
            'radio_freq': d.radio_freq,
            'radio_sf': d.radio_sf,
            'radio_bw': d.radio_bw,
            'tx_power': d.tx_power,
            'adv_lat': d.adv_lat,
            'adv_lon': d.adv_lon,
            'firmware_version': d.firmware_version,
            # Status
            'connected': self.connected,
            'status': self.status,
            # Collections (typed copies)
            'contacts': self.contacts.copy(),
            'channels': self.channels.copy(),
            'messages': self.messages.copy(),
            'rx_log': self.rx_log.copy(),
            # Flags
            'device_updated': self.device_updated,
            'contacts_updated': self.contacts_updated,
            'channels_updated': self.channels_updated,
            'rxlog_updated': self.rxlog_updated,
            'gui_initialized': self.gui_initialized,
            'bot_enabled': self.bot_enabled,
            'auto_add_enabled': self.auto_add_enabled,
            # Archive (for archive viewer)
            'archive': self.archive,
            # Room login states
            'room_login_states': {
                k: v.copy()
                for k, v in self.room_login_states.items()
            },
            # Room message cache (archived + live)
            'room_messages': {
                k: list(v)
                for k, v in self._room_msg_cache.items()
            },
        }

    def clear_update_flags(self) -> None:
        with self.lock:
            self.device_updated = False
            self.contacts_updated = False
            self.channels_updated = False
            self.rxlog_updated = False

    def mark_gui_initialized(self) -> None:
        with self.lock:
            self.gui_initialized = True
            debug_print("GUI marked as initialized")

    # ------------------------------------------------------------------
    # Contact lookups
    # ------------------------------------------------------------------

    def get_contact_by_prefix(self, pubkey_prefix: str) -> Optional[Dict]:
        if not pubkey_prefix:
            return None
        with self.lock:
            for key, contact in self.contacts.items():
                if key.lower().startswith(pubkey_prefix.lower()) or pubkey_prefix.lower().startswith(key.lower()):
                    return contact.copy()
        return None

    def get_contact_name_by_prefix(self, pubkey_prefix: str) -> str:
        if not pubkey_prefix:
            return ""
        with self.lock:
            for key, contact in self.contacts.items():
                if key.lower().startswith(pubkey_prefix.lower()):
                    name = contact.get('adv_name', '')
                    if name:
                        return name
        return pubkey_prefix[:8]

    def get_contact_by_name(self, name: str) -> Optional[Tuple[str, Dict]]:
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
            # Strategy 3: prefix match
            for key, contact in self.contacts.items():
                adv = contact.get('adv_name', '')
                if not adv:
                    continue
                if name.startswith(adv) or adv.startswith(name):
                    return (key, contact.copy())
        return None

    # ------------------------------------------------------------------
    # Archive stats
    # ------------------------------------------------------------------

    def get_archive_stats(self) -> Optional[Dict]:
        """Get statistics from the message archive.
        
        Returns:
            Dict with archive stats, or None if archive not initialized.
        """
        if self.archive:
            return self.archive.get_stats()
        return None
