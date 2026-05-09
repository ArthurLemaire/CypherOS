"""The link to the phone: which device is connected, and request/response over its socket.

A device is any WebSocket client that announced itself::

    → {"kind": "device", "name": "Pixel 7", "platform": "android", "gui": true,
       "apps": [{"id": "com.tencent.mm", "name": "微信"}], "screen": {"width": 1080, "height": 2400}}

From then on the server may ask it things; every request carries an id and gets exactly
one answer::

    ← {"kind": "device_request", "id": "r1", "op": "screen", "params": {}}
    → {"kind": "device_result", "id": "r1", "ok": true, "result": {...}}

Operations: ``screen`` (the current screen, see :mod:`nanomuse.phone.screen`) and ``act``
(one action, see :mod:`nanomuse.tools.phone`). The device is a single user's own phone:
when more than one is connected, the most recent one that can do GUI work is *the* phone.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanomuse.logger import logger
from nanomuse.phone.screen import Screen

Sender = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Device:
    id: str
    name: str = "phone"
    platform: str = "unknown"  # android | mobilegym | ...
    gui: bool = False
    apps: list[dict[str, str]] = field(default_factory=list)  # [{"id": ..., "name": ...}]
    width: int = 0
    height: int = 0
    connected_at: float = field(default_factory=time.time)
    send: Sender | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "gui": self.gui,
            "apps": len(self.apps),
            "width": self.width,
            "height": self.height,
        }

    def app_list(self, limit: int = 60) -> str:
        """``微信 (wechat), 支付宝 (alipay), …`` — what the model may name in ``open_app``."""
        items = []
        for app in self.apps[:limit]:
            app_id, name = app.get("id", ""), app.get("name", "")
            items.append(
                f"{name} ({app_id})" if name and app_id and name != app_id else name or app_id
            )
        return ", ".join(i for i in items if i)


class DeviceError(RuntimeError):
    """The phone could not do what was asked (or is not there)."""


class PhoneLink:
    def __init__(self, timeout_s: float = 20.0, shots_dir: Path | None = None):
        self.timeout_s = timeout_s
        # where screenshots go (the workspace's screenshots/ folder); None = keep none
        self.shots_dir = shots_dir
        self.devices: dict[str, Device] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # The last screen the agent saw, for risk assessment of the next action and for the
        # app's phone card.
        self.last_screen: Screen | None = None
        self.on_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------ devices
    def attach(self, conn_id: str, info: dict[str, Any], send: Sender) -> Device:
        apps = [
            {"id": str(a.get("id", "")), "name": str(a.get("name", ""))}
            for a in (info.get("apps") or [])
            if isinstance(a, dict)
        ]
        screen = info.get("screen") or {}
        device = Device(
            id=conn_id,
            name=str(info.get("name") or "phone")[:60],
            platform=str(info.get("platform") or "unknown")[:30],
            gui=bool(info.get("gui")),
            apps=apps,
            width=int(screen.get("width") or 0),
            height=int(screen.get("height") or 0),
            send=send,
        )
        self.devices[conn_id] = device
        logger.info("phone connected: {} ({}, gui={})", device.name, device.platform, device.gui)
        self._changed()
        return device

    def detach(self, conn_id: str) -> None:
        device = self.devices.pop(conn_id, None)
        if device is None:
            return
        logger.info("phone disconnected: {}", device.name)
        for req_id, fut in list(self._pending.items()):
            if req_id.startswith(conn_id + ":") and not fut.done():
                fut.set_exception(DeviceError("the phone disconnected"))
        self._changed()

    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception as exc:  # noqa: BLE001
                logger.warning("phone change listener failed: {}", exc)

    @property
    def device(self) -> Device | None:
        """The phone to operate: the most recently connected one that can do GUI work."""
        capable = [d for d in self.devices.values() if d.gui]
        if not capable:
            return None
        return max(capable, key=lambda d: d.connected_at)

    @property
    def connected(self) -> bool:
        return self.device is not None

    def status(self) -> dict[str, Any]:
        d = self.device
        return {
            "connected": d is not None,
            "device": d.to_dict() if d else None,
            "last_screen": self.last_screen.to_dict() if self.last_screen else None,
        }

    # ------------------------------------------------------------------ requests
    async def request(
        self, op: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        device = self.device
        if device is None or device.send is None:
            raise DeviceError(
                "no phone is connected. Open the nanoMuse app on the phone (with GUI operation "
                "turned on) or the MobileGym module, then try again."
            )
        req_id = f"{device.id}:{uuid.uuid4().hex[:8]}"
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await device.send(
                {"kind": "device_request", "id": req_id, "op": op, "params": params or {}}
            )
            return await asyncio.wait_for(fut, timeout or self.timeout_s)
        except TimeoutError:
            raise DeviceError(
                f"the phone did not answer '{op}' within {timeout or self.timeout_s:g}s"
            ) from None
        finally:
            self._pending.pop(req_id, None)

    def resolve(self, msg: dict[str, Any]) -> bool:
        """Hand a ``device_result`` to whoever is waiting for it."""
        fut = self._pending.get(str(msg.get("id", "")))
        if fut is None or fut.done():
            return False
        if msg.get("ok", True) and "error" not in msg:
            result = msg.get("result")
            fut.set_result(result if isinstance(result, dict) else {})
        else:
            fut.set_exception(DeviceError(str(msg.get("error") or "the phone reported an error")))
        return True

    # ------------------------------------------------------------------ high level
    async def screen(self) -> Screen:
        raw = await self.request("screen")
        screen = Screen.from_device(raw, device=self.device, shots_dir=self.shots_dir)
        self.last_screen = screen
        return screen

    async def act(self, params: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        return await self.request("act", params, timeout=timeout)


__all__ = ["Device", "DeviceError", "PhoneLink", "Sender"]
