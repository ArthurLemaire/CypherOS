"""Where this nanoMuse runs: on a computer, in a container, or on the phone itself.

On the phone the Android app (``android/``) starts ``nanomuse serve`` inside its own Linux
root file system — Alpine, unpacked from the APK, run under PRoot without root — and tells
it so through the environment:

``NANOMUSE_DEVICE``
    ``android``: this process is on the phone. Nothing else changes in the agent; the
    sandbox reports the root file system as the box (there is no bubblewrap inside PRoot),
    the CLI bridge is on (``nanomuse-device`` and friends work from a shell command), and
    the About page says which phone.
``NANOMUSE_DEVICE_MODEL``, ``NANOMUSE_DEVICE_SDK``
    ``Pixel 8``, ``34`` — for the app and for the model's context.
``NANOMUSE_HOST_URL``, ``NANOMUSE_HOST_TOKEN``
    The app's own local API on ``127.0.0.1`` (its device capabilities as an MCP server, the
    browser view): the server connects to it as the MCP server named ``device``. The token
    is a credential and, like every ``NANOMUSE_*`` variable, never reaches a shell command.

None of these are set on a computer, and everything here answers "no" then.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

DEVICE_ENV = "NANOMUSE_DEVICE"
HOST_URL_ENV = "NANOMUSE_HOST_URL"
HOST_TOKEN_ENV = "NANOMUSE_HOST_TOKEN"

#: The MCP server name the app's device capabilities are registered under, and so the
#: prefix of their tool names (``device__clipboard_read``, the ``server__tool`` form every
#: MCP tool gets): the CLI bridge counts on it.
DEVICE_SERVER = "device"
DEVICE_PREFIX = DEVICE_SERVER + "__"


@dataclass(frozen=True)
class DeviceToolPolicy:
    """What the Sentinel assumes about one of the phone's tools before any rule of the
    user's: its risk level, whether it reads private data (taint), and the Android
    permission it needs — that one is asked for on the phone, the first time."""

    risk: str  # a RiskLevel value
    private: bool = False
    permission: str = ""
    note: str = ""


#: The permission defaults for the phone's tools (§6 of the launch checklist). The app
#: implements these names (``android/…/device/DeviceTools.kt``); ``nanomuse-device <name>``
#: and the model call them as ``device__<name>``. In the default ``ask`` mode: safe and
#: moderate run, sensitive asks; reading private data taints the session so that a later
#: send to an unknown destination asks too. Reading notifications is listed so the default
#: is on record — the app does not offer it yet (P2), and when it does it is behind its own
#: switch, off by default.
DEVICE_TOOLS: dict[str, DeviceToolPolicy] = {
    "clipboard_read": DeviceToolPolicy(
        "moderate", private=True, note="only while the app is on screen (Android 10+)"
    ),
    "clipboard_write": DeviceToolPolicy("safe"),
    "notify": DeviceToolPolicy("safe", permission="POST_NOTIFICATIONS"),
    "calendars": DeviceToolPolicy("moderate", private=True, permission="READ_CALENDAR"),
    "calendar_list": DeviceToolPolicy("moderate", private=True, permission="READ_CALENDAR"),
    "calendar_create": DeviceToolPolicy("moderate", permission="WRITE_CALENDAR"),
    "calendar_update": DeviceToolPolicy("moderate", permission="WRITE_CALENDAR"),
    "calendar_delete": DeviceToolPolicy("sensitive", permission="WRITE_CALENDAR"),
    "contacts_search": DeviceToolPolicy("moderate", private=True, permission="READ_CONTACTS"),
    "location": DeviceToolPolicy("moderate", private=True, permission="ACCESS_FINE_LOCATION"),
    "alarm_set": DeviceToolPolicy(
        "moderate", note="the clock app confirms with its own notification"
    ),
    "timer_set": DeviceToolPolicy("moderate"),
    "photo_pick": DeviceToolPolicy(
        "safe",
        private=True,
        note="the user picks in the system Photo Picker; nothing else is readable",
    ),
    "notifications_read": DeviceToolPolicy(
        "sensitive", private=True, note="not offered yet (P2); its own switch, off by default"
    ),
}


@dataclass(frozen=True)
class Device:
    kind: str  # "android"
    model: str = ""
    sdk: str = ""
    host_url: str = ""
    host_token: str = ""

    @property
    def has_host(self) -> bool:
        return bool(self.host_url)

    def describe(self) -> str:
        """One line for the app and the model: ``on this phone (Pixel 8, Android 14)``."""
        parts = [self.model] if self.model else []
        if self.kind == "android" and self.sdk.isdigit():
            parts.append(f"Android {_android_version(int(self.sdk))}")
        elif self.kind == "android":
            parts.append("Android")
        inside = f" ({', '.join(parts)})" if parts else ""
        return f"on this phone{inside}"

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "kind": self.kind,
            "model": self.model,
            "sdk": self.sdk,
            "host": self.has_host,
            "description": self.describe(),
        }


def device(environ: dict[str, str] | None = None) -> Device | None:
    """The phone this runs on, or None on a computer."""
    env = os.environ if environ is None else environ
    kind = env.get(DEVICE_ENV, "").strip().lower()
    if kind != "android":
        return None
    return Device(
        kind=kind,
        model=env.get("NANOMUSE_DEVICE_MODEL", "").strip(),
        sdk=env.get("NANOMUSE_DEVICE_SDK", "").strip(),
        host_url=env.get(HOST_URL_ENV, "").strip().rstrip("/"),
        host_token=env.get(HOST_TOKEN_ENV, "").strip(),
    )


def on_device(environ: dict[str, str] | None = None) -> bool:
    return device(environ) is not None


def device_mcp_server(dev: Device) -> Any:
    """The app's capabilities as an MCP server entry, added to the configured ones: its
    tools come out as ``device__<name>`` — what ``nanomuse-device <name>`` calls — each
    with the risk and privacy defaults of :data:`DEVICE_TOOLS`; a tool the app adds that
    is not in the table gets the server's defaults (moderate, private)."""
    from nanomuse.config import MCPServerSettings, MCPToolPolicy
    from nanomuse.schema import RiskLevel

    url = f"{dev.host_url}/mcp"
    if dev.host_token:
        url += f"?token={quote(dev.host_token, safe='')}"
    return MCPServerSettings(
        name=DEVICE_SERVER,
        url=url,
        risk=RiskLevel.MODERATE,
        egress=False,
        # the phone's clipboard, calendar, contacts, photos: private by definition
        reads_private_data=True,
        tools={
            name: MCPToolPolicy(risk=RiskLevel(p.risk), reads_private_data=p.private)
            for name, p in DEVICE_TOOLS.items()
        },
    )


def _android_version(sdk: int) -> str:
    releases = {26: "8", 27: "8.1", 28: "9", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13"}
    if sdk in releases:
        return releases[sdk]
    if sdk >= 34:
        return str(14 + (sdk - 34))
    return str(sdk)


__all__ = [
    "DEVICE_ENV",
    "DEVICE_PREFIX",
    "DEVICE_SERVER",
    "DEVICE_TOOLS",
    "HOST_TOKEN_ENV",
    "HOST_URL_ENV",
    "Device",
    "DeviceToolPolicy",
    "device",
    "device_mcp_server",
    "on_device",
]
