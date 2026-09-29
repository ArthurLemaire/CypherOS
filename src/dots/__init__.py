"""dots — an always-on, goal-driven agent runtime.

Public API:

    from dots import Dot, Goal, Runtime

Everything else is importable from its submodule (``dots.memory``,
``dots.connectors``, ``dots.tools``, ...).
"""

from __future__ import annotations

from dots.core.agent import Dot
from dots.core.event import Event, EventKind
from dots.core.runtime import Runtime
from dots.planner.goal import Goal
from dots.version import __version__

__all__ = [
    "Dot",
    "Event",
    "EventKind",
    "Goal",
    "Runtime",
    "__version__",
]
