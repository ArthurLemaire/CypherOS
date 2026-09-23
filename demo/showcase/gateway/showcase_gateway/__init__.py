"""The showcase gateway.

The public showcase is MobileGym (a phone in the browser) with the nanoMuse app installed.
Everything a visitor sees runs in their own tab; what the server adds is a *private nanoMuse
per visitor*: this gateway starts one container for each session, gives the phone its address
and token, relays the app's HTTP and WebSocket traffic to it, and stands between the container
and the model providers so that the demo key never leaves the server and every session has a
budget. Sessions end after a fixed time or when nobody has used them for a while.
"""

__version__ = "0.1.0"
