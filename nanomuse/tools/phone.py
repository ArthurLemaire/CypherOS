"""Operating the phone: ``phone_screen``, ``phone_act`` and ``phone_task``.

These exist only while GUI operation is turned on (``[gui] enabled``, the switch in the app)
— that is the user's choice, made once, not the model's. They talk to whatever phone is
connected through :class:`~nanomuse.phone.PhoneLink`: the Android app's accessibility
service, or the MobileGym module. The phone is seen through screenshots only and operated
by coordinates, so the same three tools work on any app, on the real phone and in the demo.

Risk: looking at the screen is safe but exposes private data (what is on someone's phone
is theirs), so it taints the session like reading mail does. Acting is *moderate* — tapping
around is reversible — until what the finger is on says payment, transfer, send, delete,
order: then the call is *sensitive* with a warning, which means the Sentinel asks every time
and no standing approval covers it (``gui.sensitive_words``). Since no element tree names
what is under the finger, every tap carries a ``label`` — the words of the button or field
as read from the screenshot — and that is what is assessed and logged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict

from nanomuse.config import GUISettings
from nanomuse.phone.link import STOP_MARKER, DeviceError, DeviceStopped, PhoneLink
from nanomuse.phone.screen import Screen
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment

if TYPE_CHECKING:
    from nanomuse.phone.operator import PhoneOperator

ACTIONS = (
    "tap",
    "long_press",
    "double_tap",
    "swipe",
    "type",
    "enter",
    "back",
    "home",
    "recents",
    "open_app",
    "wait",
)
DIRECTIONS = ("up", "down", "left", "right")
POINTED = ("tap", "long_press", "double_tap")


def _screen_result(screen: Screen, prefix: str = "") -> ToolResult:
    text = (prefix + "\n\n" if prefix else "") + screen.render()
    if not screen.image_path:
        text += "\n(no screenshot came back; the phone may be locked or showing a protected screen)"
    return ToolResult(output=text, images=[screen.image_path] if screen.image_path else None)


class PhoneScreen(BaseTool):
    """Read the phone's screen."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_screen"
    description: str = (
        "Look at the phone's current screen: a screenshot, plus which app is open, the screen "
        "size in pixels and whether the keyboard is up. Coordinates for `phone_act` are pixels "
        "of that screen, (0,0) top-left. Call it again after the screen changed. For a whole job "
        "on the phone, prefer `phone_task`."
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    link: PhoneLink

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            screen = await self.link.screen()
        except DeviceStopped as exc:
            return ToolResult.fail(f"{exc} ({STOP_MARKER})")
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        return _screen_result(screen)


class PhoneAct(BaseTool):
    """One action on the phone, then the screen as it looks afterwards."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_act"
    description: str = (
        "Do one thing on the phone and get the screen after it. Actions: `tap`, `long_press`, "
        "`double_tap` at `x`/`y` (pixels of the last screenshot), with `label` — the words of "
        "what is under the finger, as shown on the screen; `swipe` from `x`/`y` to `x2`/`y2`, or "
        "`direction` up|down|left|right (`up` moves the finger up, so the content scrolls down); "
        "`type` (`text` into the focused field — tap the field first; `clear` empties it first; "
        "`submit` presses enter); `enter`, `back`, `home`, `recents`; `open_app` (`app` name or "
        "id); `wait` (`seconds`). One action per call — look at the result before the next. "
        "Never type passwords, card numbers or one-time codes: ask the user to do that step."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "x": {"type": "number", "description": "pixels from the left of the screenshot"},
            "y": {"type": "number", "description": "pixels from the top of the screenshot"},
            "x2": {"type": "number", "description": "swipe: where the finger ends"},
            "y2": {"type": "number"},
            "label": {
                "type": "string",
                "description": "what is under the finger, in the words the screen shows",
            },
            "direction": {"type": "string", "enum": list(DIRECTIONS)},
            "distance": {
                "type": "number",
                "description": "swipe by direction: length as a fraction of the screen (0.5)",
            },
            "text": {"type": "string"},
            "clear": {"type": "boolean", "description": "type: empty the field first"},
            "submit": {"type": "boolean", "description": "type: press enter afterwards"},
            "app": {"type": "string", "description": "open_app: the app's name or id"},
            "seconds": {"type": "number", "description": "wait / long_press: how long (max 10)"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    link: PhoneLink
    gui: GUISettings

    # ------------------------------------------------------------------ risk
    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = str(args.get("action") or "")
        screen = self.link.last_screen
        app = (screen.app if screen else "") or None
        where = f" in {screen.title}" if screen else ""
        label = str(args.get("label") or "").strip()
        shown = f' "{label[:60]}"' if label else ""
        at = (
            f" at ({_num(args.get('x'))},{_num(args.get('y'))})"
            if args.get("x") is not None and args.get("y") is not None
            else ""
        )
        if action in POINTED:
            summary = f"phone_act: {action}{shown}{at}{where}"
        elif action == "type":
            text = str(args.get("text") or "")
            summary = (
                f'phone_act: type "{text[:40]}"'
                + (f" into{shown}" if label else "")
                + (" and press enter" if args.get("submit") else "")
                + where
            )
        elif action == "swipe":
            how = args.get("direction") or (
                f"({_num(args.get('x'))},{_num(args.get('y'))})→({_num(args.get('x2'))},{_num(args.get('y2'))})"
                if args.get("x2") is not None
                else ""
            )
            summary = f"phone_act: swipe {how}{where}".rstrip()
        elif action == "open_app":
            summary = f"phone_act: open {args.get('app') or '?'}"
        else:
            summary = f"phone_act: {action}{shown}{where}"

        words = list(self.gui.sensitive_words)
        risk, warnings, egress = RiskLevel.MODERATE, [], False
        hit: list[str] = []
        if action in (*POINTED, "enter") and label and not self._is_app_name(label):
            hit = [w for w in words if w.lower() in label.lower()]
        if action in POINTED and not label:
            warnings.append("a tap with no `label`: nothing says what is under the finger")
        if action == "type" and args.get("submit"):
            # the send button only shows once there is text, so nothing yet says whether this
            # is a search box or a chat: submitting blind is a step the user gets to see
            risk, egress = RiskLevel.SENSITIVE, True
            warnings.append(
                "this types and submits in one step — the text goes out (a message, a search, an "
                "order) before anyone sees the screen"
            )
        if hit:
            risk, egress = RiskLevel.SENSITIVE, True
            warnings.append(
                f"this step touches {', '.join(repr(w) for w in hit[:3])} — paying, transferring, "
                "sending or deleting is not undone by pressing back"
            )
        return CallAssessment(
            risk=risk,
            reads_private_data=True,
            egress=egress,
            egress_target=app,
            target=app,
            summary=summary,
            warnings=warnings,
        )

    def _is_app_name(self, label: str) -> bool:
        """An icon or tab that is just an app's name (支付宝, 微信) is never a payment step."""
        device = self.link.device
        low = label.strip().lower()
        if not low or device is None:
            return False
        return any(low in (a.get("name", "").lower(), a.get("id", "").lower()) for a in device.apps)

    # ------------------------------------------------------------------ run
    async def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "")
        if action not in ACTIONS:
            return ToolResult.fail(f"unknown action '{action}'. One of: {', '.join(ACTIONS)}")
        params: dict[str, Any] = {"action": action}
        label = str(kwargs.get("label") or "").strip()
        if label:
            params["label"] = label[:120]
        screen = self.link.last_screen

        if action in POINTED or (action == "swipe" and kwargs.get("direction") is None):
            point = _point(kwargs, "x", "y")
            if point is None:
                return ToolResult.fail(
                    f"`{action}` needs `x` and `y` (pixels of the last screenshot)"
                    + (" or a `direction`" if action == "swipe" else "")
                )
            if screen is not None and not _inside(point, screen):
                return ToolResult.fail(
                    f"({point[0]:g},{point[1]:g}) is outside the {screen.width}×{screen.height} screen"
                )
            params["x"], params["y"] = point
        if action in POINTED and not label:
            return ToolResult.fail(
                f"`{action}` needs `label`: the words of what is under the finger, as the screen "
                "shows them (the Sentinel and the audit log go by it)"
            )
        if action == "swipe":
            if kwargs.get("direction") is not None:
                direction = str(kwargs.get("direction"))
                if direction not in DIRECTIONS:
                    return ToolResult.fail(f"`direction` must be one of {', '.join(DIRECTIONS)}")
                distance = float(kwargs.get("distance") or 0.5)
                params.update(direction=direction, distance=max(0.1, min(0.9, distance)))
                start = _point(kwargs, "x", "y")
                if start is not None:
                    params["x"], params["y"] = start
            else:
                end = _point(kwargs, "x2", "y2")
                if end is None:
                    return ToolResult.fail(
                        "`swipe` needs `x2`/`y2` (where the finger ends) or a `direction`"
                    )
                params["x2"], params["y2"] = end
        if action == "type":
            text = kwargs.get("text")
            if text is None:
                return ToolResult.fail("`type` needs `text`")
            params.update(
                text=str(text)[:2000],
                clear=bool(kwargs.get("clear")),
                submit=bool(kwargs.get("submit")),
            )
            focus = _point(kwargs, "x", "y")
            if focus is not None:
                params["x"], params["y"] = focus
        if action == "open_app":
            app = str(kwargs.get("app") or "").strip()
            if not app:
                return ToolResult.fail("`open_app` needs `app`")
            params["app"] = self._resolve_app(app)
        if action in ("wait", "long_press"):
            default = 1.0 if action == "wait" else 0.8
            params["seconds"] = max(0.2, min(10.0, float(kwargs.get("seconds") or default)))
        try:
            raw = await self.link.act(
                params, timeout=self.gui.device_timeout_s + params.get("seconds", 0)
            )
        except DeviceStopped as exc:
            return ToolResult.fail(f"{exc} ({STOP_MARKER})")
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        note = str(raw.get("note") or "")
        done = "Done" + (f": {note}" if note else "")
        try:
            if isinstance(raw.get("screen"), dict):
                after = Screen.from_device(
                    raw["screen"], device=self.link.device, shots_dir=self.link.shots_dir
                )
                self.link.last_screen = after
            else:
                after = await self.link.screen()
        except DeviceError as exc:
            # the action itself ran; only the look afterwards failed
            return ToolResult(output=f"{done}. The screen could not be read afterwards: {exc}")
        return _screen_result(after, done + ". Screen now:")

    def _resolve_app(self, wanted: str) -> str:
        """An app named the way the user says it → the id the device knows."""
        device = self.link.device
        if device is None:
            return wanted
        low = wanted.lower()
        for app in device.apps:
            if low in (app.get("id", "").lower(), app.get("name", "").lower()):
                return app.get("id") or wanted
        for app in device.apps:
            name = app.get("name", "").lower()
            if low and (low in name or name in low):
                return app.get("id") or wanted
        return wanted


def _num(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "?"


def _point(args: dict[str, Any], kx: str, ky: str) -> tuple[float, float] | None:
    if args.get(kx) is None or args.get(ky) is None:
        return None
    try:
        return float(args[kx]), float(args[ky])
    except (TypeError, ValueError):
        return None


def _inside(point: tuple[float, float], screen: Screen) -> bool:
    if not (screen.width and screen.height):
        return True
    x, y = point
    return -1 <= x <= screen.width + 1 and -1 <= y <= screen.height + 1


class PhoneTask(BaseTool):
    """A whole job on the phone, run step by step by the GUI operator."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_task"
    description: str = (
        "Hand a job on the user's phone to the GUI operator: it opens the app, looks at the "
        "screen, taps, types and swipes step by step until the job is done, then reports what it "
        "found or did. It works on any app, through the screen alone. Use it for what lives in "
        "an app and nowhere else — buying a train ticket on 12306, reading or answering a WeChat "
        "chat, paying a bill in Alipay, ordering on Meituan — and not for what another tool does "
        "exactly and instantly (search, a web page, mail, the calendar, a file): those come first, "
        "the phone is for the rest. Give one concrete `goal` with the facts it needs (names, dates, "
        "amounts, which account) and any `context` you already have; one goal per call, in order. "
        "It stops and asks before paying, transferring, sending or deleting; it never enters "
        "passwords or codes — when it asks, put the question to the user and call again with "
        "their answer in `context`. Its report holds everything it read, so ask for what you need."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "what to achieve on the phone, concretely"},
            "context": {
                "type": "string",
                "description": "facts that help: what was found earlier, preferences, constraints",
            },
            "app": {"type": "string", "description": "the app to start in (name or id), if known"},
        },
        "required": ["goal"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    reads_private_data: bool = True
    link: PhoneLink
    operator: Any  # PhoneOperator — typed loosely to keep the import graph one-way

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        goal = str(args.get("goal") or "")
        app = str(args.get("app") or "").strip() or None
        return CallAssessment(
            risk=self.risk,
            reads_private_data=True,
            target=app,
            summary=f"phone_task: {goal[:80]}" + (f" ({app})" if app else ""),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        goal = str(kwargs.get("goal") or "").strip()
        if not goal:
            return ToolResult.fail("`goal` is required")
        if not self.link.connected:
            return ToolResult.fail(
                "no phone is connected. Open the nanoMuse app on the phone (with GUI operation "
                "turned on) or the MobileGym module, then try again."
            )
        operator: PhoneOperator = self.operator
        outcome = await operator.run(
            goal, context=str(kwargs.get("context") or ""), app=str(kwargs.get("app") or "")
        )
        text = outcome.report()
        images = [outcome.last_image] if outcome.last_image else None
        return ToolResult(output=text, images=images)


__all__ = ["ACTIONS", "DIRECTIONS", "PhoneAct", "PhoneScreen", "PhoneTask"]
