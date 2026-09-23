"""OpenMuse: an open-source version of Meta's Muse personal agent.

The agent does the work (search, browse, files, code, email, long-running goals);
a separate Sentinel decides what may run and what leaves the machine; a credential
vault keeps secrets out of the model's sight; every action lands in an audit log.
``openmuse serve`` adds the phone app.
"""

__version__ = "0.5.0"
__all__ = ["__version__"]
