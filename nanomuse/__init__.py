"""nanoMuse: an open-source version of Meta's Muse personal agent, made to work in China.

The agent does the work (search, browse, files, code, email, long-running goals, and —
when you turn it on — the apps on your phone through their screens); a separate Sentinel
decides what may run and what leaves the machine; a credential vault keeps secrets out of
the model's sight; every action lands in an audit log. ``nanomuse serve`` adds the phone app.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
