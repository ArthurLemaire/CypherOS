"""nanoMuse: an open-source version of Meta's Muse personal agent, made to work in China.

The agent does the work (search, browse, files, code, email, long-running goals, and —
when you turn it on — the apps on your phone through their screens); a separate Sentinel
decides what may run and what leaves the machine; a credential vault keeps secrets out of
the model's sight; every action lands in an audit log. ``nanomuse serve`` adds the phone app.

nanoMuse was called OpenMuse until 0.6.0. ``OPENMUSE_*`` environment variables are still
read when the ``NANOMUSE_*`` one is not set, and an existing ``~/.openmuse`` data directory
is still used (see ``nanomuse.config``).
"""

from __future__ import annotations

import os

__version__ = "0.7.0"
__all__ = ["__version__"]


def alias_legacy_env(environ: dict[str, str] | None = None) -> list[str]:
    """Make every ``OPENMUSE_*`` variable visible as ``NANOMUSE_*`` (unless that is set too).

    Runs once on import, so every reader — and every subprocess — sees the new name.
    Returns the names that were added.
    """
    env = os.environ if environ is None else environ
    added = []
    for name, value in list(env.items()):
        if name.startswith("OPENMUSE_"):
            new = "NANOMUSE_" + name[len("OPENMUSE_") :]
            if new not in env:
                env[new] = value
                added.append(new)
    return added


alias_legacy_env()
