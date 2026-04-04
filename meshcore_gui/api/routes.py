"""
Public REST API route definitions for MeshCore GUI.

Registers four read-only GET endpoints under ``/api/v1/`` on the
NiceGUI/FastAPI application instance:

    GET /api/v1/stats
    GET /api/v1/nodes
    GET /api/v1/messages
    GET /api/v1/channels

Call :func:`register_routes` once from ``__main__.py`` after
:class:`~meshcore_gui.core.shared_data.SharedData` is constructed and
before ``ui.run()`` is called.

All routes are async and access shared data read-only.  CORS is
configured from :data:`~meshcore_gui.config.API_CORS_ORIGINS`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from nicegui import app as _nicegui_app

import meshcore_gui.config as config
from meshcore_gui.services.public_api_service import (
    get_channels_payload,
    get_messages_payload,
    get_nodes_payload,
    get_stats_payload,
)

if TYPE_CHECKING:
    from meshcore_gui.core.shared_data import SharedData


def register_routes(shared: "SharedData") -> None:
    """Wire public API routes into the NiceGUI/FastAPI application.

    Must be called after :class:`~meshcore_gui.core.shared_data.SharedData`
    is constructed and **before** ``ui.run()`` so that FastAPI registers
    the routes on startup.

    CORS middleware is added once using the origins configured in
    :data:`~meshcore_gui.config.API_CORS_ORIGINS`.  The middleware is
    idempotent — calling this function more than once is safe (NiceGUI
    guards against duplicate middleware).

    Args:
        shared: Application shared-data instance.  Passed to service
                functions as a read-only data source.
    """
    # ── CORS ────────────────────────────────────────────────────────────
    _nicegui_app.add_middleware(
        CORSMiddleware,
        allow_origins=config.API_CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # ── Routes ──────────────────────────────────────────────────────────

    @_nicegui_app.get(
        "/api/v1/stats",
        tags=["MeshCore Public API"],
        summary="Network statistics for the last 72 hours",
        response_model=None,
    )
    async def api_stats() -> Dict[str, Any]:
        """Return aggregate statistics for the last 72 hours.

        Only public (index 0) and hashtag channels are included in message
        counts.  Node counts reflect the live contact list.

        Returns:
            JSON object with ``generated_at``, ``period_hours``,
            ``total_messages``, ``unique_senders``, ``active_clients``,
            ``active_repeaters``, ``active_room_servers``, ``avg_hops``
            and ``peak_hour``.
        """
        return get_stats_payload(shared)

    @_nicegui_app.get(
        "/api/v1/nodes",
        tags=["MeshCore Public API"],
        summary="All known mesh nodes",
        response_model=None,
    )
    async def api_nodes() -> List[Dict[str, Any]]:
        """Return all contacts from the live contact list.

        Fields not tracked by the current firmware interface (``last_seen``,
        ``battery_mv``) are returned as ``null``.

        Returns:
            JSON array of node objects with ``name``, ``pubkey_prefix``,
            ``type``, ``last_seen``, ``adv_lat``, ``adv_lon`` and
            ``battery_mv``.
        """
        return get_nodes_payload(shared)

    @_nicegui_app.get(
        "/api/v1/messages",
        tags=["MeshCore Public API"],
        summary="Paginated public and hashtag channel messages",
        response_model=None,
    )
    async def api_messages(
        limit: int = Query(default=100, ge=1, le=500, description="Maximum items to return"),
        offset: int = Query(default=0, ge=0, description="Items to skip"),
    ) -> Dict[str, Any]:
        """Return paginated messages from public and hashtag channels only.

        Private channel messages are **never** returned, regardless of
        authentication.  The filtering is enforced server-side.

        Args:
            limit:  Number of messages to return (1–500, default 100).
            offset: Number of messages to skip for pagination (default 0).

        Returns:
            JSON object with ``total``, ``limit``, ``offset`` and ``items``
            (list of message objects).
        """
        return get_messages_payload(shared, limit=limit, offset=offset)

    @_nicegui_app.get(
        "/api/v1/channels",
        tags=["MeshCore Public API"],
        summary="Channel list with privacy flag",
        response_model=None,
    )
    async def api_channels() -> List[Dict[str, Any]]:
        """Return all channels discovered from the device.

        Each entry includes an ``is_private`` flag.  Private channels appear
        in this list (so callers know they exist) but no keys or message
        content is exposed.

        Returns:
            JSON array of channel objects with ``idx``, ``name`` and
            ``is_private``.
        """
        return get_channels_payload(shared)

    config.debug_print(
        "Public API registered: /api/v1/stats, /api/v1/nodes, "
        "/api/v1/messages, /api/v1/channels"
    )
