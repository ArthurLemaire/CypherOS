"""The CLI bridge: how a shell command the agent runs reaches the phone and the browser.

A skill's script or a one-liner in the sandbox cannot call a tool — it can only run
programs. Three small programs are on the ``PATH`` wherever nanoMuse's own Python is:

- ``nanomuse-device`` — the phone's capabilities (clipboard, calendar, alarms, contacts,
  location, notifications, photos), when a phone is there;
- ``nanomuse-browser`` — the agent's browser view: navigate, extract, click, type, fetch,
  screenshot;
- ``nanomuse-open URL`` — hand a page to the user in the app's browser view (it is the
  root file system's ``BROWSER`` on the phone, so "open this in your browser" from any CLI
  lands there).

They speak to the running server over ``127.0.0.1`` with a **call token**: minted by the
shell tool for the one command it starts, good for the length of that command, and bound to
the chat and the agent run the command belongs to. The server turns each request into an
ordinary tool call in that chat — the Sentinel decides, an approval card appears where the
user is looking, the audit log records it — and sends the result back. The app's own token
is never in a command's environment (``scrubbed_env`` strips every ``NANOMUSE_*``), so a
script cannot reach the API any other way.

This is the role OpenMinis gives its native offload (a patched ``execve``) — done over HTTP
instead, in Python, without touching PRoot.
"""

from nanomuse.bridge.tokens import BRIDGE_TOKEN_ENV, BRIDGE_URL_ENV, BridgeGrant, BridgeTokens

__all__ = ["BRIDGE_TOKEN_ENV", "BRIDGE_URL_ENV", "BridgeGrant", "BridgeTokens"]
