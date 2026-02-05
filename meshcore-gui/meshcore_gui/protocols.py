"""
Protocol interfaces for MeshCore GUI.

Defines the contracts between components using ``typing.Protocol``.
Each protocol captures the subset of SharedData that a specific
consumer needs, following the Interface Segregation Principle (ISP)
and the Dependency Inversion Principle (DIP).

Consumers depend on these protocols rather than on the concrete
SharedData class, which makes the contracts explicit and enables
testing with lightweight stubs.
"""

from typing import Dict, List, Optional, Protocol, runtime_checkable


# ----------------------------------------------------------------------
# Writer — used by BLEWorker
# ----------------------------------------------------------------------

@runtime_checkable
class SharedDataWriter(Protocol):
    """Write-side interface used by BLEWorker.

    BLEWorker pushes data into the shared store: device info,
    contacts, channels, messages, RX log entries and status updates.
    It also reads commands enqueued by the GUI.
    """

    def update_from_appstart(self, payload: Dict) -> None: ...
    def update_from_device_query(self, payload: Dict) -> None: ...
    def set_status(self, status: str) -> None: ...
    def set_connected(self, connected: bool) -> None: ...
    def set_contacts(self, contacts_dict: Dict) -> None: ...
    def set_channels(self, channels: List[Dict]) -> None: ...
    def add_message(self, msg: Dict) -> None: ...
    def add_rx_log(self, entry: Dict) -> None: ...
    def get_next_command(self) -> Optional[Dict]: ...
    def get_contact_name_by_prefix(self, pubkey_prefix: str) -> str: ...
    def get_contact_by_name(self, name: str) -> Optional[tuple]: ...


# ----------------------------------------------------------------------
# Reader — used by DashboardPage and RoutePage
# ----------------------------------------------------------------------

@runtime_checkable
class SharedDataReader(Protocol):
    """Read-side interface used by GUI pages.

    GUI pages read snapshots of the shared data and manage
    update flags.  They also enqueue commands for the BLE worker.
    """

    def get_snapshot(self) -> Dict: ...
    def clear_update_flags(self) -> None: ...
    def mark_gui_initialized(self) -> None: ...
    def put_command(self, cmd: Dict) -> None: ...


# ----------------------------------------------------------------------
# ContactLookup — used by RouteBuilder
# ----------------------------------------------------------------------

@runtime_checkable
class ContactLookup(Protocol):
    """Contact lookup interface used by RouteBuilder.

    RouteBuilder needs to resolve public key prefixes and names
    to contact records.  Path hashes are always available in the
    message dict (decoded from the raw packet), so no archive
    lookup is needed.
    """

    def get_contact_by_prefix(self, pubkey_prefix: str) -> Optional[Dict]: ...
    def get_contact_by_name(self, name: str) -> Optional[tuple]: ...


# ----------------------------------------------------------------------
# ReadAndLookup — used by RoutePage (needs both Reader + Lookup)
# ----------------------------------------------------------------------

@runtime_checkable
class SharedDataReadAndLookup(SharedDataReader, ContactLookup, Protocol):
    """Combined interface for RoutePage which reads snapshots and
    delegates contact lookups to RouteBuilder."""
    ...
