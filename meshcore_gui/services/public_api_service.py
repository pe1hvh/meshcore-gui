"""
Business logic for the MeshCore public REST API.

This module contains pure data-transformation functions that are called
by the API route handlers in :mod:`meshcore_gui.api.routes`.  It has
**no** GUI, BLE or NiceGUI dependencies and may be imported from any layer.

Channel-type rules (definitive — no exceptions):
    idx == 0               → Public  — always expose
    name.startswith('#')   → Hashtag — always expose
    anything else          → Private — NEVER expose or store

All functions access :class:`~meshcore_gui.core.shared_data.SharedData`
and :class:`~meshcore_gui.services.message_archive.MessageArchive` in
**read-only** mode.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from meshcore_gui.core.shared_data import SharedData
    from meshcore_gui.services.message_archive import MessageArchive


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Stats window in hours (72 h = 3 days).
STATS_PERIOD_HOURS: int = 72

#: Maximum messages fetched from the archive for stats computation.
#: Adjust upwards if the archive grows very large and peak_hour is wrong.
_STATS_FETCH_LIMIT: int = 50_000

#: Node-type integer → API string mapping.
#: Matches the MeshCore type field: 0/1 = Companion CLI, 2 = Repeater, 3 = Room Server.
_NODE_TYPE_MAP: Dict[int, str] = {
    0: "client",
    1: "client",
    2: "repeater",
    3: "room_server",
}


# ---------------------------------------------------------------------------
# Channel classification
# ---------------------------------------------------------------------------

def is_public_channel(idx: Optional[int], name: str) -> bool:
    """Return True when the channel is public (idx 0) or a hashtag channel.

    This is the single source of truth for channel-type classification used
    throughout the public API.  Private channels are excluded from all
    endpoints.

    Args:
        idx:  Channel index as stored on the device (``None`` for DMs).
        name: Channel name string (e.g. ``"Public"``, ``"#localmesh"``).

    Returns:
        ``True`` for public or hashtag channels; ``False`` for everything else.
    """
    if idx == 0:
        return True
    if name and name.startswith("#"):
        return True
    return False


def is_private_channel(idx: Optional[int], name: str) -> bool:
    """Return True when the channel is private (inverse of :func:`is_public_channel`).

    Args:
        idx:  Channel index (``None`` for DMs).
        name: Channel name string.

    Returns:
        ``True`` for private channels; ``False`` for public/hashtag.
    """
    return not is_public_channel(idx, name)


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def get_stats_payload(shared: "SharedData") -> Dict[str, Any]:
    """Build the ``GET /api/v1/stats`` response payload.

    Reads the last :data:`STATS_PERIOD_HOURS` hours of messages from the
    archive, limited to public and hashtag channels.  All statistics are
    derived from that filtered message set and from the live contact list.

    Args:
        shared: The application :class:`~meshcore_gui.core.shared_data.SharedData`
                instance (read-only).

    Returns:
        Dict matching the ``/api/v1/stats`` JSON schema.
    """
    archive = shared.archive
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=STATS_PERIOD_HOURS)

    # ── Fetch messages from archive ──────────────────────────────────────
    messages: List[Dict[str, Any]] = []
    if archive is not None:
        raw, _ = archive.query_messages(
            after=cutoff,
            limit=_STATS_FETCH_LIMIT,
            offset=0,
        )
        messages = [
            m for m in raw
            if is_public_channel(m.get("channel"), m.get("channel_name", ""))
        ]

    # ── Aggregate stats ──────────────────────────────────────────────────
    unique_senders: set = set()
    hops_values: List[int] = []
    hour_counter: Counter = Counter()

    for msg in messages:
        sender = msg.get("sender") or msg.get("sender_pubkey", "")
        if sender:
            unique_senders.add(sender)

        path_len = msg.get("path_len", 0) or 0
        if path_len > 0:
            hops_values.append(path_len)

        ts_str = msg.get("timestamp_utc", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                hour_counter[ts.hour] += 1
            except (ValueError, TypeError):
                pass

    avg_hops = round(sum(hops_values) / len(hops_values), 2) if hops_values else 0.0
    peak_hour = hour_counter.most_common(1)[0][0] if hour_counter else None

    # ── Node counts from live contact list ───────────────────────────────
    active_clients = 0
    active_repeaters = 0
    active_room_servers = 0

    with shared.lock:
        for contact in shared.contacts.values():
            node_type = int(contact.get("type", 0) or 0)
            if node_type == 2:
                active_repeaters += 1
            elif node_type == 3:
                active_room_servers += 1
            else:
                active_clients += 1

    return {
        "generated_at": now_utc.isoformat(),
        "period_hours": STATS_PERIOD_HOURS,
        "total_messages": len(messages),
        "unique_senders": len(unique_senders),
        "active_clients": active_clients,
        "active_repeaters": active_repeaters,
        "active_room_servers": active_room_servers,
        "avg_hops": avg_hops,
        "peak_hour": peak_hour,
    }


def get_nodes_payload(shared: "SharedData") -> List[Dict[str, Any]]:
    """Build the ``GET /api/v1/nodes`` response payload.

    Returns all known contacts from the live contact list.  Fields that are
    not tracked by the current codebase (``last_seen``, ``battery_mv``) are
    returned as ``null``.

    Args:
        shared: Application shared-data instance (read-only).

    Returns:
        List of node dicts matching the ``/api/v1/nodes`` JSON schema.
    """
    nodes: List[Dict[str, Any]] = []

    with shared.lock:
        for pubkey, contact in shared.contacts.items():
            raw_type = int(contact.get("type", 0) or 0)
            node_type = _NODE_TYPE_MAP.get(raw_type, "client")

            adv_lat = contact.get("adv_lat") or None
            adv_lon = contact.get("adv_lon") or None
            # Zero-coordinates mean "unknown" — normalize to null
            if adv_lat == 0.0 and adv_lon == 0.0:
                adv_lat = None
                adv_lon = None

            nodes.append({
                "name": contact.get("adv_name") or pubkey[:12],
                "pubkey_prefix": pubkey[:12],
                "type": node_type,
                "last_seen": contact.get("last_seen"),        # null if absent
                "adv_lat": adv_lat,
                "adv_lon": adv_lon,
                "battery_mv": contact.get("battery_mv"),     # null if absent
            })

    # Stable sort: repeaters first, then clients, then room servers
    _order = {"repeater": 0, "client": 1, "room_server": 2}
    nodes.sort(key=lambda n: (_order.get(n["type"], 9), n["name"]))
    return nodes


def get_messages_payload(
    shared: "SharedData",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Build the ``GET /api/v1/messages`` response payload.

    Returns paginated messages from public and hashtag channels **only**.
    Private channel messages are excluded unconditionally — no authentication
    is required precisely because the filtering is enforced server-side here.

    Args:
        shared: Application shared-data instance (read-only).
        limit:  Maximum number of messages to return (capped at 500).
        offset: Number of messages to skip (for pagination).

    Returns:
        Dict matching the ``/api/v1/messages`` JSON schema with ``total``,
        ``limit``, ``offset`` and ``items`` keys.
    """
    # Hard cap: never return more than 500 messages per call
    limit = min(max(1, limit), 500)
    offset = max(0, offset)

    archive = shared.archive
    if archive is None:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    # Fetch a large window so we can apply channel-type filtering before pagination.
    # Because query_messages returns newest-first we fetch offset+limit+buffer rows.
    fetch_limit = offset + limit + 1000  # generous buffer for filtered-out private msgs
    raw, _ = archive.query_messages(limit=fetch_limit, offset=0)

    # Filter: public + hashtag only
    public_msgs = [
        m for m in raw
        if is_public_channel(m.get("channel"), m.get("channel_name", ""))
    ]

    total = len(public_msgs)
    page = public_msgs[offset: offset + limit]

    items: List[Dict[str, Any]] = []
    for i, msg in enumerate(page):
        items.append({
            "id": offset + i + 1,                          # 1-based stable ID
            "channel_idx": msg.get("channel"),
            "channel_name": msg.get("channel_name", ""),
            "sender": msg.get("sender", ""),
            "text": msg.get("text", ""),
            "timestamp": msg.get("timestamp_utc"),
            "hops": msg.get("path_len", 0) or 0,
            "path_hashes": msg.get("path_hashes") or [],
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def get_channels_payload(shared: "SharedData") -> List[Dict[str, Any]]:
    """Build the ``GET /api/v1/channels`` response payload.

    Returns all channels discovered from the device, annotated with an
    ``is_private`` flag.  Private channels are included in this list (so
    callers know they exist) but their names are the only information
    exposed — no keys or message content is ever returned.

    Args:
        shared: Application shared-data instance (read-only).

    Returns:
        List of channel dicts matching the ``/api/v1/channels`` JSON schema.
    """
    channels: List[Dict[str, Any]] = []

    with shared.lock:
        for ch in shared.channels:
            idx = ch.get("idx")
            name = ch.get("name", "")
            channels.append({
                "idx": idx,
                "name": name,
                "is_private": is_private_channel(idx, name),
            })

    return channels
