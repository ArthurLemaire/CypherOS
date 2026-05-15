"""The GUI operator: a step loop on the phone's screen with its own model.

The main agent hands over one concrete goal (``phone_task``). The operator looks at the
screen, decides one action, does it through the Sentinel — every tap is a ``phone_act``
call, assessed and, when it looks like paying or sending, approved by the user — looks
again, and so on, until it is done, must ask, or gives up. It then reports back in words;
the main agent goes on with the rest of the task (mail, files, the calendar, a page).

The model is the one under ``[gui]`` — usually a small, fast model that takes images,
which is what looking at screens wants — or the main model when none is set. It replies
with one JSON object per step; nothing else is parsed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nanomuse.config import GUISettings
from nanomuse.llm.base import BaseLLM
from nanomuse.logger import logger
from nanomuse.phone.link import DeviceError, PhoneLink
from nanomuse.phone.screen import Screen
from nanomuse.schema import Function, Message, ToolCall, ToolResult
from nanomuse.sentinel import Sentinel
from nanomuse.tools.base import BaseTool
from nanomuse.ui import UI

OPERATOR_PROMPT = """You operate a phone for its owner, one action at a time, to reach a goal that a larger assistant handed you. You are the hands and eyes on the screen; you do not chat with the owner.

## Each step
You get the current screen: the app, and its visible elements as lines `[id] role "text" {{flags}} @(x,y)`{picture}. Reply with exactly one JSON object and nothing else:

{{"thought": "what you see and why this step", "action": {{"action": "tap", "element": 12}}}}

Actions (`action` object):
- `{{"action": "tap", "element": ID}}` — also `long_press`, `double_tap`. Prefer an element id; `{{"action": "tap", "x": 100, "y": 200}}` only when nothing has an id.
- `{{"action": "type", "element": ID, "text": "…", "clear": true}}` — into a field (`input` elements); the field is tapped first. Never tap the keys of the on-screen keyboard; typing and sending are two steps: `type`, then tap the send/search button or `enter` on the next step.
- `{{"action": "swipe", "direction": "up"}}` — the finger moves up, so the content scrolls down; `down`, `left`, `right`; add `element` to swipe inside a list.
- `{{"action": "back"}}`, `{{"action": "home"}}`, `{{"action": "enter"}}`, `{{"action": "wait", "seconds": 2}}` (a page is loading).
- `{{"action": "open_app", "app": "12306"}}` — by name or id. Apps on this phone: {apps}.
- `{{"action": "done", "message": "…"}}` — the goal is reached: say what you did and everything you read that the assistant will need (names, times, prices, seat numbers, order state), precisely, from the screen.
- `{{"action": "ask", "message": "…"}}` — you need the owner: a choice only they can make, a login, a password, a verification code, a payment confirmation you were not given. Say exactly what you need.
- `{{"action": "abort", "message": "…"}}` — it cannot be done here; say what stood in the way.

## Rules
- One action per step. Read the screen you are given; do not assume what a tap did — the next screen tells you.
- Never type passwords, card numbers, PINs or one-time codes, and never approve a payment or a transfer on your own: stop with `ask` before that step and describe the screen (amount, payee, what is about to happen).
- Paying, transferring, sending a message, deleting and placing an order are not undone by pressing back. Do the step the goal asks for and no more: do not send, buy or delete anything the goal did not name, and never type trial text or press buttons "to see what happens".
- If the field shows text you did not mean to send (`value=`), clear it (`type` with `clear` and an empty `text`) rather than sending it.
- If a permission dialog, a pop-up or an ad covers the screen, close it first. If the same screen comes back three times, try another way or `abort`.
- Do not leave the app the goal needs unless a step requires it. Keep to the goal; report anything else you noticed in your `done` message rather than acting on it.
- Write `message` texts in {language}.

## Goal
{goal}
{context}"""


@dataclass
class Outcome:
    status: str  # done | ask | abort | blocked | failed | max_steps
    message: str = ""
    steps: int = 0
    last_screen: str = ""
    last_image: str | None = None
    actions: list[str] = field(default_factory=list)

    def report(self) -> str:
        head = {
            "done": "The phone operator finished.",
            "ask": "The phone operator stopped: it needs the user.",
            "abort": "The phone operator gave up.",
            "blocked": "The phone operator was stopped by the Sentinel (an approval was refused).",
            "failed": "The phone operator could not continue.",
            "max_steps": "The phone operator ran out of steps before finishing.",
        }.get(self.status, self.status)
        lines = [f"{head} ({self.steps} step{'s' if self.steps != 1 else ''})"]
        if self.message:
            lines.append(self.message.strip())
        if self.actions:
            shown = self.actions[-8:]
            lines.append(
                "Steps taken:"
                + ("" if len(self.actions) <= 8 else f" (last {len(shown)} of {len(self.actions)})")
            )
            lines.extend(f"- {a}" for a in shown)
        if self.last_screen and self.status != "done":
            lines.append("Screen when it stopped:\n" + self.last_screen)
        return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_step(text: str | None) -> dict[str, Any] | None:
    """The model's JSON object, tolerant of code fences and prose around it."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", candidate)
    for attempt in (candidate, *(m.group(0) for m in [_JSON_RE.search(candidate)] if m)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            # {"action": "tap", ...} without the wrapper is accepted too
            if "action" in data and not isinstance(data["action"], dict):
                return {"thought": str(data.get("thought", "")), "action": data}
            action = data.get("action")
            if isinstance(action, dict) and "action" not in action:
                # {"action": {"type": "tap", ...}} — some models name the field differently
                for alias in ("type", "name", "kind", "op"):
                    if alias in action:
                        action["action"] = action.pop(alias)
                        break
            return data
    return None


class PhoneOperator:
    def __init__(
        self,
        link: PhoneLink,
        settings: GUISettings,
        sentinel: Sentinel,
        act_tool: BaseTool,
        ui: UI,
        make_llm: Callable[[], BaseLLM],
        language: Callable[[], str] | None = None,
    ):
        self.link = link
        self.settings = settings
        self.sentinel = sentinel
        self.act_tool = act_tool
        self.ui = ui
        self._make_llm = make_llm
        self._llm: BaseLLM | None = None
        self._language = language or (lambda: "the language of the goal")
        # screens older than this many steps are dropped from the model's context
        self.keep_screens = 3

    @property
    def llm(self) -> BaseLLM:
        if self._llm is None:
            self._llm = self._make_llm()
        return self._llm

    def reset_llm(self) -> None:
        self._llm = None

    # ------------------------------------------------------------------ the loop
    async def run(self, goal: str, context: str = "", app: str = "") -> Outcome:
        outcome = Outcome(status="failed")
        device = self.link.device
        apps = device.app_list() if device else ""
        takes_images = self.llm.vision_available is not False
        system = OPERATOR_PROMPT.format(
            picture=" and, when your model takes images, a screenshot" if takes_images else "",
            apps=apps or "(the device did not list its apps; use the names the owner uses)",
            language=self._language(),
            goal=goal.strip(),
            context=f"\n## What the assistant already knows\n{context.strip()}\n"
            if context.strip()
            else "",
        )
        history: list[tuple[str, Screen | None, str]] = []  # (user text, screen, assistant json)
        try:
            if app:
                await self._act({"action": "open_app", "app": app}, outcome)
            screen = await self.link.screen()
        except DeviceError as exc:
            outcome.message = str(exc)
            return outcome

        bad_replies = 0
        refusals = 0
        for step in range(1, self.settings.max_steps + 1):
            outcome.steps = step
            outcome.last_screen = screen.render()
            outcome.last_image = screen.image_path
            user_text = f"Step {step}. Screen:\n{screen.render()}"
            messages = [Message.system(system), *self._context(history, takes_images)]
            messages.append(
                Message.user(
                    user_text,
                    images=[screen.image_path] if takes_images and screen.image_path else None,
                )
            )
            response = await self.llm.ask_complete(messages)
            data = parse_step(response.content)
            if data is None or not isinstance(data.get("action"), dict):
                bad_replies += 1
                logger.debug(
                    "phone step {}: reply was not an action: {!r}",
                    step,
                    (response.content or "")[:600],
                )
                history.append((user_text, screen, response.content or ""))
                history.append(
                    (
                        "Your reply was not one JSON object with an `action`. Reply with exactly "
                        '{"thought": "...", "action": {...}}.',
                        None,
                        "",
                    )
                )
                if bad_replies >= 3:
                    outcome.status = "failed"
                    outcome.message = "the operator model did not produce usable actions"
                    return outcome
                continue
            bad_replies = 0
            action = data["action"]
            kind = str(action.get("action") or "")
            thought = str(data.get("thought") or "")[:400]
            history.append((user_text, screen, json.dumps(data, ensure_ascii=False)))
            if kind in ("done", "ask", "abort"):
                outcome.status = kind
                outcome.message = str(action.get("message") or thought)
                return outcome

            result = await self._act(action, outcome, thought)
            if result.error and "Sentinel blocked" in result.error:
                refusals += 1
                if refusals >= 2:
                    outcome.status = "blocked"
                    outcome.message = result.error
                    return outcome
            else:
                refusals = 0
            if result.error:
                history.append((f"Result: {result.error}", None, ""))
                try:
                    screen = await self.link.screen()
                except DeviceError as exc:
                    outcome.message = str(exc)
                    return outcome
                continue
            screen = self.link.last_screen or screen
            if self._looping(history):
                history.append(
                    (
                        "You have taken the same action on the same screen three times. Try "
                        "another way, or `abort` with what is in the way.",
                        None,
                        "",
                    )
                )
        outcome.status = "max_steps"
        outcome.message = f"stopped after {self.settings.max_steps} steps"
        return outcome

    # ------------------------------------------------------------------ helpers
    def _context(
        self, history: list[tuple[str, Screen | None, str]], images: bool
    ) -> list[Message]:
        """Past steps as messages; only the newest screens stay in full."""
        out: list[Message] = []
        screens_seen = sum(1 for _, s, _ in history if s is not None)
        drop = max(0, screens_seen - self.keep_screens)
        for text, screen, reply in history:
            if screen is not None:
                if drop > 0:
                    drop -= 1
                    text = text.split("\n", 1)[0] + "\n(earlier screen omitted)"
                    out.append(Message.user(text))
                else:
                    out.append(
                        Message.user(
                            text,
                            images=[screen.image_path] if images and screen.image_path else None,
                        )
                    )
            else:
                out.append(Message.user(text))
            if reply:
                out.append(Message.assistant(content=reply))
        return out

    async def _act(self, action: dict[str, Any], outcome: Outcome, thought: str = "") -> ToolResult:
        args = {k: v for k, v in action.items() if k != "thought"}
        # typing and sending are two steps: the send is assessed against the screen with the text in
        args.pop("submit", None)
        call = ToolCall(
            function=Function(
                name=self.act_tool.name, arguments=json.dumps(args, ensure_ascii=False)
            )
        )
        summary = self.act_tool.assess(args).summary
        outcome.actions.append(summary.removeprefix("phone_act: "))
        self.ui.on_tool_call(call, summary)
        result = await self.sentinel.guard(call, self.act_tool)
        self.ui.on_tool_result(call, result)
        if result.error:
            logger.info("phone step failed: {}", result.error)
        return result

    @staticmethod
    def _looping(history: list[tuple[str, Screen | None, str]]) -> bool:
        steps = [(t.split("\n", 1)[-1], r) for t, s, r in history if s is not None and r]
        if len(steps) < 3:
            return False
        return len(set(steps[-3:])) == 1


__all__ = ["OPERATOR_PROMPT", "Outcome", "PhoneOperator", "parse_step"]
