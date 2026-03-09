"""
Display constants for the GUI layer.

Contact type → icon/name/label mappings used by multiple panels.
"""

from typing import Any, Dict, Mapping, Optional

TYPE_ICONS: Dict[int, str] = {0: "○", 1: "📱", 2: "📡", 3: "🏠"}
TYPE_NAMES: Dict[int, str] = {0: "-", 1: "CLI", 2: "REP", 3: "ROOM"}
TYPE_LABELS: Dict[int, str] = {0: "-", 1: "Companion", 2: "Repeater", 3: "Room Server"}


def get_type_icon(contact_type: Optional[int]) -> str:
    """Return the display icon for a contact type."""
    return TYPE_ICONS.get(contact_type or 0, TYPE_ICONS[0])


def get_type_label(contact_type: Optional[int]) -> str:
    """Return the human-readable label for a contact type."""
    return TYPE_LABELS.get(contact_type or 0, TYPE_LABELS[0])


def get_type_display(contact_type: Optional[int]) -> str:
    """Return a combined icon + label string for a contact type."""
    icon = get_type_icon(contact_type)
    label = get_type_label(contact_type)
    return f"{icon} {label}" if label != '-' else icon


def resolve_contact_type(
    contacts: Mapping[str, Mapping[str, Any]],
    pubkey: str = '',
    name: str = '',
) -> int:
    """Resolve the contact type from snapshot contacts by pubkey or name."""
    if pubkey:
        pubkey_lower = pubkey.lower()
        for key, contact in contacts.items():
            key_lower = key.lower()
            if key_lower.startswith(pubkey_lower) or pubkey_lower.startswith(key_lower):
                return int(contact.get('type', 0) or 0)

    if name:
        name_lower = name.lower()
        for contact in contacts.values():
            adv_name = str(contact.get('adv_name', '') or '')
            if adv_name and adv_name.lower() == name_lower:
                return int(contact.get('type', 0) or 0)

    return 0


def resolve_contact_icon(
    contacts: Mapping[str, Mapping[str, Any]],
    pubkey: str = '',
    name: str = '',
    fallback_type: Optional[int] = None,
) -> str:
    """Resolve the display icon for a contact using the shared type mapping."""
    resolved_type = resolve_contact_type(contacts, pubkey=pubkey, name=name)
    if resolved_type == 0 and fallback_type is not None:
        resolved_type = fallback_type
    return get_type_icon(resolved_type)
