"""
Public REST API package for MeshCore GUI.

Exposes read-only JSON endpoints under /api/v1/ for consumption by
external services (e.g. the domca.nl PHP statistics pages).

Use :func:`register_routes` to wire the routes into the running
NiceGUI/FastAPI application instance.
"""

from meshcore_gui.api.routes import register_routes

__all__ = ["register_routes"]
