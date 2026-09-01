"""
Repeater configuration store for MeshCore GUI.

Persists the list of repeaters that are polled for statistics to
``~/.meshcore-gui/repeaters/<safe_dev_id>_repeaters.json``.

The filename mirrors the :class:`~meshcore_gui.services.pin_store.PinStore`
convention so configuration is always bound to a specific device.  Only
the instance that has a repeater in its own file will poll that repeater,
which keeps multiple instances (one per USB port) from querying the same
node twice.

Example path for ``/dev/ttyUSB1``::

    ~/.meshcore-gui/repeaters/_dev_ttyUSB1_repeaters.json

Password handling
~~~~~~~~~~~~~~~~~
The file contains the repeater login password and is therefore created
with mode ``0600`` inside a ``0700`` directory.  The password is
reachable through exactly one method, :meth:`RepeaterConfigStore.get_password`,
which only the poller calls.  Every other accessor returns
:class:`RepeaterInfo` objects that carry no password field at all, so the
GUI cannot render a password even by accident.

A password of ``None`` means "not configured"; an empty string is a valid
credential for a repeater that accepts a blank password.

Public key
~~~~~~~~~~
The meshcore library requires the **full 32-byte** public key for login,
status and logout requests — a prefix is rejected.  Entries with a key
that is not 64 hex characters are skipped at load time with a warning.

Thread safety
~~~~~~~~~~~~~
All public methods acquire an internal ``threading.Lock``.

                   Author: PE1HVH
  SPDX-License-Identifier: MIT
"""

import json
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from meshcore_gui.config import (
    REPEATER_POLL_INTERVAL,
    REPEATERS_DIR,
    debug_print,
)

#: Length of a full public key in hex characters (32 bytes).
PUBKEY_HEX_LENGTH = 64

#: File mode for the configuration file (owner read/write only).
FILE_MODE = 0o600

#: Directory mode for the configuration directory (owner only).
DIR_MODE = 0o700


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RepeaterInfo:
    """Non-secret view of a configured repeater.

    This is the type handed to the GUI and to any other consumer.  It
    deliberately has no password attribute.

    Attributes:
        pubkey:        Full public key (64 hex characters).
        name:          Display name.
        poll_interval: Seconds between polls for this repeater.
        enabled:       Whether this repeater is polled.
        has_password:  True when a password is configured, including an
                       empty one.  False means no credential is set.
    """

    pubkey: str
    name: str = ""
    poll_interval: float = REPEATER_POLL_INTERVAL
    enabled: bool = True
    has_password: bool = False


@dataclass
class _RepeaterEntry:
    """Internal storage record, including the password.

    Never leaves this module except through :meth:`get_password`.

    Attributes:
        pubkey:        Full public key (64 hex characters).
        name:          Display name.
        password:      Login password.  ``None`` means not configured;
                       ``""`` is a valid empty credential.
        poll_interval: Seconds between polls for this repeater.
        enabled:       Whether this repeater is polled.
    """

    pubkey: str
    name: str = ""
    password: Optional[str] = None
    poll_interval: float = REPEATER_POLL_INTERVAL
    enabled: bool = True


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class RepeaterConfigStore:
    """Persistent repeater configuration for a single device.

    Args:
        device_id: Device identifier string used to derive the filename.
                   May be empty for a device-agnostic default store.
    """

    def __init__(self, device_id: str = "") -> None:
        self._lock = threading.Lock()

        safe_name = (
            device_id
            .replace("literal:", "")
            .replace(":", "_")
            .replace("/", "_")
        ) if device_id else "default"

        self._path: Path = REPEATERS_DIR / f"{safe_name}_repeaters.json"
        self._repeaters: Dict[str, _RepeaterEntry] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API — non-secret
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Return the configuration file path."""
        return self._path

    def get_repeaters(self) -> List[RepeaterInfo]:
        """Return all configured repeaters without their passwords.

        Returns:
            List of :class:`RepeaterInfo`, ordered by name then pubkey.
        """
        with self._lock:
            infos = [
                RepeaterInfo(
                    pubkey=entry.pubkey,
                    name=entry.name,
                    poll_interval=entry.poll_interval,
                    enabled=entry.enabled,
                    has_password=entry.password is not None,
                )
                for entry in self._repeaters.values()
            ]
        return sorted(infos, key=lambda i: (i.name.lower(), i.pubkey))

    def get_enabled_repeaters(self) -> List[RepeaterInfo]:
        """Return only the repeaters that are enabled for polling.

        Returns:
            List of :class:`RepeaterInfo` with ``enabled`` set.
        """
        return [info for info in self.get_repeaters() if info.enabled]

    def has_repeaters(self) -> bool:
        """Check whether any repeater is configured.

        Returns:
            True when the store holds at least one entry.
        """
        with self._lock:
            return bool(self._repeaters)

    # ------------------------------------------------------------------
    # Public API — secret
    # ------------------------------------------------------------------

    def get_password(self, pubkey: str) -> Optional[str]:
        """Return the login password for a repeater.

        Called only by :class:`~meshcore_gui.services.repeater_poller.RepeaterPoller`.

        Args:
            pubkey: Full public key (hex string).

        Returns:
            The password, which may legitimately be an empty string, or
            ``None`` when the repeater is unknown or has no password
            configured.
        """
        with self._lock:
            entry = self._repeaters.get(pubkey)
            return entry.password if entry is not None else None

    # ------------------------------------------------------------------
    # Public API — mutation
    # ------------------------------------------------------------------

    def add_repeater(
        self,
        pubkey: str,
        name: str = "",
        password: Optional[str] = None,
        poll_interval: float = REPEATER_POLL_INTERVAL,
        enabled: bool = True,
    ) -> bool:
        """Add or replace a repeater entry and persist it.

        Args:
            pubkey:        Full public key (64 hex characters).
            name:          Display name.
            password:      Login password; ``None`` for not configured,
                           ``""`` for an empty credential.
            poll_interval: Seconds between polls.
            enabled:       Whether the repeater is polled.

        Returns:
            True when the entry was stored, False when the public key is
            not a valid full key.
        """
        if not _is_full_pubkey(pubkey):
            debug_print(
                f"RepeaterConfigStore: rejected {pubkey[:16]}… — "
                f"a full {PUBKEY_HEX_LENGTH}-character public key is required"
            )
            return False

        key = pubkey.lower()
        with self._lock:
            self._repeaters[key] = _RepeaterEntry(
                pubkey=key,
                name=name,
                password=password,
                poll_interval=poll_interval,
                enabled=enabled,
            )
            self._save()
        debug_print(f"RepeaterConfigStore: stored {name or key[:16]}")
        return True

    def remove_repeater(self, pubkey: str) -> None:
        """Remove a repeater entry and persist the change.

        Args:
            pubkey: Full public key (hex string).
        """
        key = pubkey.lower()
        with self._lock:
            if key in self._repeaters:
                del self._repeaters[key]
                self._save()
                debug_print(f"RepeaterConfigStore: removed {key[:16]}")

    def set_enabled(self, pubkey: str, enabled: bool) -> None:
        """Enable or disable polling for a repeater.

        Args:
            pubkey:  Full public key (hex string).
            enabled: New enabled state.
        """
        key = pubkey.lower()
        with self._lock:
            entry = self._repeaters.get(key)
            if entry is not None:
                entry.enabled = enabled
                self._save()
                debug_print(
                    f"RepeaterConfigStore: {key[:16]} enabled={enabled}"
                )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the configuration from disk (called once at construction)."""
        if not self._path.exists():
            debug_print(
                f"RepeaterConfigStore: no file at {self._path} — "
                "repeater polling stays idle until one is configured"
            )
            return

        self._warn_on_permissions()

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            debug_print(f"RepeaterConfigStore: load error: {exc}")
            self._repeaters = {}
            return

        for pubkey, entry_dict in (data.get("repeaters") or {}).items():
            key = str(pubkey).lower()
            if not _is_full_pubkey(key):
                debug_print(
                    f"RepeaterConfigStore: skipped {key[:16]}… — "
                    f"not a full {PUBKEY_HEX_LENGTH}-character public key"
                )
                continue
            # Absent "password" → None (not configured).
            # Present and ""    → ""   (valid empty credential).
            self._repeaters[key] = _RepeaterEntry(
                pubkey=key,
                name=entry_dict.get("name", ""),
                password=entry_dict.get("password"),
                poll_interval=float(
                    entry_dict.get("poll_interval", REPEATER_POLL_INTERVAL)
                ),
                enabled=bool(entry_dict.get("enabled", True)),
            )

        debug_print(
            f"RepeaterConfigStore: loaded {len(self._repeaters)} repeaters "
            f"from {self._path.name}"
        )

    def _save(self) -> None:
        """Write the configuration to disk with restrictive permissions.

        Caller must hold the lock.  The temp file is created with mode
        0600 before it receives any content, so the password is never
        briefly world-readable.
        """
        try:
            REPEATERS_DIR.mkdir(parents=True, exist_ok=True)
            REPEATERS_DIR.chmod(DIR_MODE)

            data = {
                "version": 1,
                "repeaters": {
                    entry.pubkey: {
                        "name": entry.name,
                        "password": entry.password,
                        "poll_interval": entry.poll_interval,
                        "enabled": entry.enabled,
                    }
                    for entry in self._repeaters.values()
                },
            }

            temp_path = self._path.with_suffix(".json.tmp")
            temp_path.touch(mode=FILE_MODE, exist_ok=True)
            temp_path.chmod(FILE_MODE)
            temp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_path.replace(self._path)
            self._path.chmod(FILE_MODE)

            debug_print(
                f"RepeaterConfigStore: saved {len(self._repeaters)} "
                f"repeaters to {self._path.name}"
            )
        except OSError as exc:
            debug_print(f"RepeaterConfigStore: save error: {exc}")

    def _warn_on_permissions(self) -> None:
        """Log a warning when file or directory permissions are too wide.

        The application keeps running: refusing to start would take the
        whole GUI down over a repeater feature.  The warning is explicit
        so the condition is visible in the log.
        """
        try:
            file_mode = stat.S_IMODE(self._path.stat().st_mode)
            if file_mode & 0o077:
                print(
                    f"⚠️  {self._path} has mode {file_mode:04o} — "
                    f"expected {FILE_MODE:04o}. It contains a repeater "
                    "password; run: chmod 600 on this file."
                )
            dir_mode = stat.S_IMODE(self._path.parent.stat().st_mode)
            if dir_mode & 0o077:
                print(
                    f"⚠️  {self._path.parent} has mode {dir_mode:04o} — "
                    f"expected {DIR_MODE:04o}. Run: chmod 700 on this "
                    "directory."
                )
        except OSError as exc:
            debug_print(f"RepeaterConfigStore: permission check failed: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_full_pubkey(pubkey: str) -> bool:
    """Check whether *pubkey* is a full 32-byte key in hex form.

    Args:
        pubkey: Candidate public key string.

    Returns:
        True when the string is exactly 64 hexadecimal characters.
    """
    if not pubkey or len(pubkey) != PUBKEY_HEX_LENGTH:
        return False
    try:
        int(pubkey, 16)
    except ValueError:
        return False
    return True
