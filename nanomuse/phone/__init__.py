"""The phone as a device the agent can operate: screens in, actions out.

Meta's Muse leans on services with APIs. Most of what a person in China does on a phone
has no API — 12306, WeChat, Alipay, Meituan — so nanoMuse can also work those apps the way
the person would: look at the screen, tap, type, swipe. Two things provide that screen:

* the Android app, through an accessibility service (the real phone), and
* the MobileGym module (a simulated phone in a browser tab, for the showcase and tests).

Both speak the same small protocol over the server's WebSocket (:mod:`nanomuse.phone.link`).
The agent sees a :class:`~nanomuse.phone.screen.Screen` — a screenshot, which app, how big,
keyboard or not; no accessibility tree, because a real phone cannot be relied on to have one
— and acts by coordinates through the ``phone_*`` tools (:mod:`nanomuse.tools.phone`).
Multi-step work on the screen runs in :class:`~nanomuse.phone.operator.PhoneOperator`, a
loop with its own model speaking the Qwen-VL ``mobile_use`` dialect, with every action still
passing through the Sentinel and every run leaving a trace (:mod:`nanomuse.phone.trace`).
"""

from nanomuse.phone.link import Device, PhoneLink
from nanomuse.phone.screen import Screen

__all__ = ["Device", "PhoneLink", "Screen"]
