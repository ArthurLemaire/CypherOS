"""Operating the phone: ``phone_screen``, ``phone_act`` and ``phone_task``.

These exist only while GUI operation is turned on (``[gui] enabled``, the switch in the app)
— that is the user's choice, made once, not the model's. They talk to whatever phone is
connected through :class:`~nanomuse.phone.PhoneLink`: the Android app's accessibility
service, or the MobileGym module.

Risk: looking at the screen is safe but exposes private data (what is on someone's phone
is theirs), so it taints the session like reading mail does. Acting is *moderate* — tapping
around is reversible — until the element under the finger, or the screen, says payment,
transfer, send, delete, order: then the call is *sensitive* with a warning, which means the
Sentinel asks every time and no standing approval covers it (``gui.sensitive_words``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict

from nanomuse.config import GUISettings
from nanomuse.phone.link import DeviceError, PhoneLink
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


def _screen_result(screen: Screen, prefix: str = "") -> ToolResult:
    text = (prefix + "\n\n" if prefix else "") + screen.render()
    return ToolResult(output=text, images=[screen.image_path] if screen.image_path else None)


class PhoneScreen(BaseTool):
    """Read the phone's screen."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_screen"
    description: str = (
        "Look at the phone's current screen: which app is open and the visible elements, each "
        "with an id, its text, whether it is clickable/editable and its position. Use the ids "
        "with `phone_act`. Call it again after the screen changed."
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    link: PhoneLink

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            screen = await self.link.screen()
        except DeviceError as exc:
            return ToolResult.fail(str(exc))
        return _screen_result(screen)


class PhoneAct(BaseTool):
    """One action on the phone, then the screen as it looks afterwards."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_act"
    description: str = (
        "Do one thing on the phone and get the screen after it. Actions: `tap`, `long_press`, "
        "`double_tap` (an `element` id from the last screen, or `x`/`y`); `swipe` (`direction` "
        "up|down|left|right — `up` moves the finger up, so the content scrolls down; optional "
        "`element` to swipe inside a list); `type` (`text` into `element` or the focused field; "
        "`clear` first; `submit` presses enter); `enter`, `back`, `home`, `recents`; `open_app` "
        "(`app` id or name); `wait` (`seconds`). One action per call — look at the result before "
        "the next. Never type passwords, card numbers or one-time codes: ask the user to do that "
        "step themselves."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "element": {"type": "integer", "description": "element id from the last screen"},
            "x": {"type": "number", "description": "screen x when no element id fits"},
            "y": {"type": "number"},
            "direction": {"type": "string", "enum": list(DIRECTIONS)},
            "distance": {
                "type": "number",
                "description": "swipe length as a fraction of the screen (default 0.5)",
            },
            "text": {"type": "string"},
            "clear": {"type": "boolean", "description": "type: empty the field first"},
            "submit": {"type": "boolean", "description": "type: press enter afterwards"},
            "app": {"type": "string", "description": "open_app: the app id or its name"},
            "seconds": {"type": "number", "description": "wait: how long (max 10)"},
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
        element = None
        if screen is not None and args.get("element") is not None:
            try:
                element = screen.element(int(args["element"]))
            except (TypeError, ValueError):
                element = None
        label = element.label if element else ""
        ref = (
            f"[{args.get('element')}]" + (f' "{label[:40]}"' if label else "")
            if args.get("element") is not None
            else ""
        )
        if action in ("tap", "long_press", "double_tap"):
            what = ref or (f"({args.get('x')},{args.get('y')})" if "x" in args else "?")
            summary = f"phone_act: {action} {what}{where}"
        elif action == "type":
            text = str(args.get("text") or "")
            summary = (
                f'phone_act: type "{text[:40]}"'
                + (f" into {ref}" if ref else "")
                + (" and press enter" if args.get("submit") else "")
                + where
            )
        elif action == "swipe":
            summary = f"phone_act: swipe {args.get('direction') or ''}{where}"
        elif action == "open_app":
            summary = f"phone_act: open {args.get('app') or '?'}"
        else:
            summary = f"phone_act: {action}{where}"

        words = list(self.gui.sensitive_words)
        risk, warnings, egress = RiskLevel.MODERATE, [], False
        hit: list[str] = []
        if action in ("tap", "long_press", "double_tap"):
            if element is not None:
                if not self._is_app_name(label):
                    hit = [w for w in words if w.lower() in label.lower()]
            elif screen is not None:
                # a blind tap on a screen that talks about paying: we cannot tell what is under it
                hit = screen.find_words(words)
        elif action == "enter" and screen is not None:
            hit = screen.find_words(words)
        elif action == "type" and args.get("submit"):
            # the send button only shows once there is text, so the screen we have cannot tell
            # a search box from a chat: submitting blind is a step the user gets to see
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
        screen = self.link.last_screen
        if action in ("tap", "long_press", "double_tap", "type", "swipe"):
            if kwargs.get("element") is not None:
                try:
                    element_id = int(kwargs["element"])
                except (TypeError, ValueError):
                    return ToolResult.fail("`element` must be an id from the last screen")
                element = screen.element(element_id) if screen else None
                if element is None:
                    return ToolResult.fail(
                        f"no element [{element_id}] on the last screen — call phone_screen and use "
                        "an id from it"
                    )
                x, y = element.center
                params.update(element=element_id, x=x, y=y, label=element.label[:80])
            elif kwargs.get("x") is not None and kwargs.get("y") is not None:
                params.update(x=float(kwargs["x"]), y=float(kwargs["y"]))
            elif action != "type" and action != "swipe":
                return ToolResult.fail(f"`{action}` needs an `element` id or `x`/`y`")
        if action == "swipe":
            direction = str(kwargs.get("direction") or "up")
            if direction not in DIRECTIONS:
                return ToolResult.fail(f"`direction` must be one of {', '.join(DIRECTIONS)}")
            distance = float(kwargs.get("distance") or 0.5)
            params.update(direction=direction, distance=max(0.1, min(0.9, distance)))
        if action == "type":
            text = kwargs.get("text")
            if text is None:
                return ToolResult.fail("`type` needs `text`")
            params.update(
                text=str(text)[:2000],
                clear=bool(kwargs.get("clear")),
                submit=bool(kwargs.get("submit")),
            )
        if action == "open_app":
            app = str(kwargs.get("app") or "").strip()
            if not app:
                return ToolResult.fail("`open_app` needs `app`")
            params["app"] = self._resolve_app(app)
        if action == "wait":
            params["seconds"] = max(0.2, min(10.0, float(kwargs.get("seconds") or 1.0)))
        try:
            raw = await self.link.act(
                params, timeout=self.gui.device_timeout_s + params.get("seconds", 0)
            )
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


class PhoneTask(BaseTool):
    """A whole job on the phone, run step by step by the GUI operator."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "phone_task"
    description: str = (
        "Hand a job on the phone to the GUI operator: it opens the app, reads the screen, taps, "
        "types and swipes step by step until the job is done, then reports what it found or did. "
        "Use it for anything that lives in an app rather than behind an API — buying a train "
        "ticket on 12306, checking a WeChat chat, paying a bill in Alipay, ordering on Meituan. "
        "Give one concrete `goal` with the facts it needs (names, dates, amounts) and any `context` "
        "you already have. It stops and asks before paying, transferring, sending or deleting; it "
        "never enters passwords or codes. Returns its report; the details it read are in the "
        "report, so ask for what you need."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "what to achieve on the phone, concretely"},
            "context": {
                "type": "string",
                "description": "facts that help: what was found earlier, preferences, constraints",
            },
            "app": {"type": "string", "description": "the app to start in (id or name), if known"},
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
        if outcome.status in ("failed", "blocked"):
            return ToolResult(output=text, error=None, images=images)
        return ToolResult(output=text, images=images)


__all__ = ["ACTIONS", "DIRECTIONS", "PhoneAct", "PhoneScreen", "PhoneTask"]
