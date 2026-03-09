"""
Core domain layer — models, protocols and shared data store.

Re-exports the most commonly used names so consumers can write::

    from meshcore_gui.core import SharedData, Message, RxLogEntry
"""

from meshcore_gui.core.models import (  # noqa: F401
    Contact,
    DeviceInfo,
    Message,
    RouteNode,
    RxLogEntry,
)
from meshcore_gui.core.shared_data import SharedData  # noqa: F401
