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
handled via response headers on each endpoint to avoid conflicts with
NiceGUI's frozen middleware stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from fastapi import Query
from fastapi.responses import JSONResponse
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


def _cors_response(data: Any) -> JSONResponse:
    """Wrap API data in a JSONResponse with CORS headers.

    Using response-level CORS headers avoids touching the NiceGUI
    middleware stack (which is frozen by the time routes are registered).
    """
    origins = ", ".join(config.API_CORS_ORIGINS)
    return JSONResponse(
        content=data,
        headers={
            "Access-Control-Allow-Origin": origins,
            "Access-Control-Allow-Methods": "GET",
        },
    )


def register_routes(shared: "SharedData") -> None:
    """Wire public API routes into the NiceGUI/FastAPI application.

    Must be called after :class:`~meshcore_gui.core.shared_data.SharedData`
    is constructed and **before** ``ui.run()`` so that FastAPI registers
    the routes on startup.

    CORS is handled via response headers on each endpoint rather than
    middleware, which avoids conflicts with NiceGUI's frozen middleware stack.

    Args:
        shared: Application shared-data instance.  Passed to service
                functions as a read-only data source.
    """
    # ── Routes ──────────────────────────────────────────────────────────

    @_nicegui_app.get(
        "/api/v1/stats",
        tags=["MeshCore Public API"],
        summary="Network statistics for the last 72 hours",
        response_class=JSONResponse,
    )
    async def api_stats() -> JSONResponse:
        """Return aggregate statistics for the last 72 hours.

        Only public (index 0) and hashtag channels are included in message
        counts.  Node counts reflect the live contact list.
        """
        return _cors_response(get_stats_payload(shared))

    @_nicegui_app.get(
        "/api/v1/nodes",
        tags=["MeshCore Public API"],
        summary="All known mesh nodes",
        response_class=JSONResponse,
    )
    async def api_nodes() -> JSONResponse:
        """Return all contacts from the live contact list."""
        return _cors_response(get_nodes_payload(shared))

    @_nicegui_app.get(
        "/api/v1/messages",
        tags=["MeshCore Public API"],
        summary="Paginated public and hashtag channel messages",
        response_class=JSONResponse,
    )
    async def api_messages(
        limit: int = Query(default=100, ge=1, le=500, description="Maximum items to return"),
        offset: int = Query(default=0, ge=0, description="Items to skip"),
    ) -> JSONResponse:
        """Return paginated messages from public and hashtag channels only.

        Private channel messages are **never** returned.
        """
        return _cors_response(get_messages_payload(shared, limit=limit, offset=offset))

    @_nicegui_app.get(
        "/api/v1/channels",
        tags=["MeshCore Public API"],
        summary="Channel list with privacy flag",
        response_class=JSONResponse,
    )
    async def api_channels() -> JSONResponse:
        """Return all channels discovered from the device."""
        return _cors_response(get_channels_payload(shared))

    config.debug_print(
        "Public API registered: /api/v1/stats, /api/v1/nodes, "
        "/api/v1/messages, /api/v1/channels"
    )
