"""The phone as a device the agent can operate: screens in, actions out.

Meta's Muse leans on services with APIs. Most of what a person in China does on a phone
has no API — 12306, WeChat, Alipay, Meituan — so nanoMuse can also work those apps the way
the person would: look at the screen, tap, type, swipe. Two things provide that screen:

* the Android app, through an accessibility service (the real phone), and
* the MobileGym module (a simulated phone in a browser tab, for the showcase and tests).

Both speak the same small protocol over the server's WebSocket (:mod:`nanomuse.phone.link`).
The agent sees a :class:`~nanomuse.phone.screen.Screen` — the app, the visible elements with
ids and positions, a screenshot when the device can take one — and acts through the
``phone_*`` tools (:mod:`nanomuse.tools.phone`). Multi-step work on the screen runs in
:class:`~nanomuse.phone.operator.PhoneOperator`, a loop with its own model, with every
action still passing through the Sentinel.
"""

from nanomuse.phone.link import Device, PhoneLink
from nanomuse.phone.screen import Element, Screen

__all__ = ["Device", "Element", "PhoneLink", "Screen"]
