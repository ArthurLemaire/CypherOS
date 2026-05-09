"""The GUI operator: a step loop on the phone's screen with its own model.

The main agent hands over one concrete goal (``phone_task``). The operator looks at the
screen — a screenshot, nothing else — decides one action, does it through the Sentinel
(every tap is a ``phone_act`` call, assessed and, when it looks like paying or sending,
approved by the user), looks again, and so on, until it is done, must ask, or gives up. It
then reports back in words; the main agent goes on with the rest of the task.

The model is the one under ``[gui]`` — a model that takes images — or the main model when
none is set. It is spoken to in the ``mobile_use`` dialect of the Qwen-VL agents: a tool
schema whose coordinates live in a 999×999 space, and one ``Thought: / Action: /
<tool_call>`` reply per step. That format is what the open Qwen-VL models were trained on
for phone operation, so it is used as is rather than a JSON dialect of our own.

Attribution: the prompt, the user template and the parsers below are ported from
MemGUI-Bench (https://github.com/lgy0404/MemGUI-Bench, MIT License), files
``src/mobile_world/agents/utils/prompts/qwen3vl.py`` and
``src/mobile_world/agents/implementations/qwen3vl.py``, with the ``open`` action of the
original Qwen ``mobile_use`` tool restored and our device actions on the other end.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanomuse.config import GUISettings
from nanomuse.llm.base import BaseLLM
from nanomuse.logger import logger
from nanomuse.phone.link import DeviceError, PhoneLink
from nanomuse.phone.screen import Screen
from nanomuse.phone.trace import Trace
from nanomuse.schema import Function, Message, ToolCall, ToolResult
from nanomuse.sentinel import Sentinel
from nanomuse.tools.base import BaseTool
from nanomuse.ui import UI

# The model places points on a 999×999 screen whatever the picture's size (MemGUI-Bench's
# convention; the open Qwen-VL agents ground well in it).
SCALE_FACTOR = 999

MOBILE_USE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "mobile_use",
        "description": (
            "Use a touchscreen to interact with a mobile device, and take screenshots.\n"
            "* This is an interface to a mobile device with touchscreen. You can perform actions "
            "like clicking, typing, swiping, etc.\n"
            "* Some applications may take time to start or process actions, so you may need to "
            "wait and take successive screenshots to see the results of your actions.\n"
            "* The screen's resolution is 999x999.\n"
            "* Make sure to click any buttons, links, icons, etc with the cursor tip in the "
            "center of the element. Don't click boxes on their edges unless asked."
        ),
        "parameters": {
            "properties": {
                "action": {
                    "description": (
                        "The action to perform. The available actions are:\n"
                        "* `click`: Click the point on the screen with coordinate (x, y).\n"
                        "* `long_press`: Press the point on the screen with coordinate (x, y) for "
                        "specified seconds.\n"
                        "* `swipe`: Swipe from the starting point with coordinate (x, y) to the "
                        "end point with coordinates2 (x2, y2).\n"
                        "* `type`: Input the specified text into the activated input box.\n"
                        "* `open`: Open an app on the device by its name (in `text`).\n"
                        "* `answer`: Output the answer.\n"
                        "* `system_button`: Press the system button.\n"
                        "* `wait`: Wait specified seconds for the change to happen.\n"
                        "* `terminate`: Terminate the current task and report its completion "
                        "status.\n"
                        "* `ask_user`: Ask user for clarification."
                    ),
                    "enum": [
                        "click",
                        "long_press",
                        "swipe",
                        "type",
                        "open",
                        "answer",
                        "system_button",
                        "wait",
                        "ask_user",
                        "terminate",
                    ],
                    "type": "string",
                },
                "coordinate": {
                    "description": (
                        "(x, y): The x (pixels from the left edge) and y (pixels from the top "
                        "edge) coordinates to move the mouse to. Required only by `action=click`, "
                        "`action=long_press`, and `action=swipe`."
                    ),
                    "type": "array",
                },
                "coordinate2": {
                    "description": (
                        "(x, y): The x (pixels from the left edge) and y (pixels from the top "
                        "edge) coordinates to move the mouse to. Required only by `action=swipe`."
                    ),
                    "type": "array",
                },
                "text": {
                    "description": (
                        "Required only by `action=type`, `action=open`, `action=ask_user` and "
                        "`action=answer`."
                    ),
                    "type": "string",
                },
                "time": {
                    "description": (
                        "The seconds to wait. Required only by `action=long_press` and "
                        "`action=wait`."
                    ),
                    "type": "number",
                },
                "button": {
                    "description": (
                        "Back means returning to the previous interface, Home means returning to "
                        "the desktop, Menu means opening the application background menu, and "
                        "Enter means pressing the enter. Required only by `action=system_button`"
                    ),
                    "enum": ["Back", "Home", "Menu", "Enter"],
                    "type": "string",
                },
                "status": {
                    "description": ("The status of the task. Required only by `action=terminate`."),
                    "type": "string",
                    "enum": ["success", "failure"],
                },
            },
            "required": ["action"],
            "type": "object",
        },
    },
}

SYSTEM_PROMPT = """# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tool}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>

# Response format

Response format for every step:
1) Thought: one concise sentence explaining the next move (no multi-step reasoning).
2) Action: a short imperative describing what to do.
3) A single <tool_call>...</tool_call> block containing only the JSON: {{"name": <function-name>, "arguments": <args-json-object>}}.

Rules:
- Output exactly in the order: Thought, Action, <tool_call>.
- Be brief: one sentence for Thought, one for Action.
- Do not output anything else outside those three parts.
- If finishing, use mobile_use with action=terminate in the tool call.
- Never type passwords, PINs, card numbers or one-time codes, and never confirm a payment, a transfer or an order on your own: use action=ask_user before that step and describe what the screen is about to do.
- Do only what the query asks: do not send, buy, delete or post anything it did not name.
- When the query asks for information, put everything you read that answers it (names, times, prices, seat numbers, order state) in action=answer, exactly as shown on the screen, before terminating.
- Write `text` for answer and ask_user in {language}.
"""

USER_TEMPLATE = """
The user query: {instruction}
Task progress (You have done the following operation on the current device): {steps}
"""


@dataclass
class Outcome:
    status: str  # done | ask | abort | blocked | failed | max_steps
    message: str = ""
    steps: int = 0
    last_screen: str = ""
    last_image: str | None = None
    actions: list[str] = field(default_factory=list)
    trace_id: str = ""

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
            lines.append("Screen when it stopped: " + self.last_screen.replace("\n", "; "))
        if self.trace_id:
            lines.append(f"Trace: {self.trace_id}")
        return "\n".join(lines)


# ------------------------------------------------------------------ parsing the reply

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Step:
    """One parsed reply: what the model thought, what it said it would do, and the call."""

    thought: str
    action: str  # the "Action:" sentence — the words the Sentinel and the trace see
    name: str  # the function called (mobile_use, normally)
    arguments: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.arguments.get("action") or "")


def parse_tagged_text(text: str) -> dict[str, Any]:
    """``Thought: … Action: … <tool_call>{…}</tool_call>`` → its three parts.

    Ported from MemGUI-Bench, made tolerant: the tags may be missing or out of order, the
    JSON may sit in a code fence or stand alone, and ``<think>`` blocks are ignored.
    """
    text = _THINK_RE.sub("", text or "").strip()
    result: dict[str, Any] = {"thinking": None, "conclusion": None, "tool_call": None}
    if not text:
        return result

    head, payload = text, ""
    m = _TOOL_CALL_RE.search(text)
    if m:
        payload = m.group(1)
        head = text[: m.start()]
    else:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            payload, head = fenced.group(1), text[: fenced.start()]
        else:
            bare = _JSON_RE.search(text)
            if bare:
                payload, head = bare.group(0), text[: bare.start()]
    if payload:
        try:
            result["tool_call"] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"tool_call is not valid JSON: {exc}") from exc

    before, tagged, rest = head.partition("Thought:")
    if not tagged:
        rest = before  # no "Thought:" — whatever precedes "Action:" is the thinking
    thinking, tagged, action = rest.partition("Action:")
    if not tagged:
        thinking, action = rest, ""
    result["thinking"] = thinking.strip() or None
    result["conclusion"] = action.strip().strip('"') or None
    return result


def parse_step(text: str | None) -> Step | None:
    """The model's reply as a :class:`Step`, or None when it is not one."""
    if not text:
        return None
    try:
        parts = parse_tagged_text(text)
    except ValueError:
        return None
    call = parts.get("tool_call")
    if not isinstance(call, dict):
        return None
    if "arguments" in call and isinstance(call["arguments"], dict):
        name = str(call.get("name") or "mobile_use")
        arguments = dict(call["arguments"])
    elif "action" in call:
        # the bare arguments object, without the {"name":..., "arguments":...} wrapper
        name, arguments = "mobile_use", dict(call)
    else:
        return None
    if name == "mobile_use" and not isinstance(arguments.get("action"), str):
        return None
    for key in ("coordinate", "coordinate2"):
        if key in arguments:
            arguments[key] = _normalise_point(arguments[key])
    # some replies fold Thought and Action into one line: the thought then names the target
    conclusion = parts.get("conclusion") or parts.get("thinking") or _describe(arguments)
    return Step(
        thought=str(parts.get("thinking") or "")[:400],
        action=str(conclusion)[:200],
        name=name,
        arguments=arguments,
    )


def _normalise_point(value: Any) -> list[float]:
    """``[x, y]`` or ``[x1, y1, x2, y2]`` in the 999 space → ``[x, y]`` as fractions."""
    if isinstance(value, str):
        value = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if not isinstance(value, list | tuple):
        raise ValueError("coordinate must be a list")
    nums = [float(v) for v in value]
    if len(nums) == 4:
        nums = [(nums[0] + nums[2]) / 2, (nums[1] + nums[3]) / 2]
    if len(nums) != 2:
        raise ValueError("coordinate must have two numbers")
    return [min(1.0, max(0.0, nums[0] / SCALE_FACTOR)), min(1.0, max(0.0, nums[1] / SCALE_FACTOR))]


def _describe(arguments: dict[str, Any]) -> str:
    kind = str(arguments.get("action") or "")
    if kind in ("click", "long_press") and "coordinate" in arguments:
        x, y = arguments["coordinate"]
        return f"{kind} at ({x:.2f}, {y:.2f}) of the screen"
    if kind == "type":
        return f"type {str(arguments.get('text') or '')[:60]!r}"
    if kind == "system_button":
        return f"press {arguments.get('button') or '?'}"
    if kind == "open":
        return f"open {arguments.get('text') or '?'}"
    return kind or "?"


def to_device_action(step: Step, screen: Screen) -> dict[str, Any] | None:
    """The ``phone_act`` arguments for a ``mobile_use`` step; None for the ones that end the
    loop (answer, terminate, ask_user)."""
    a = step.arguments
    kind = step.kind
    w, h = screen.width or 1, screen.height or 1
    label = step.action

    def point(key: str) -> tuple[float, float]:
        if key not in a:
            raise ValueError(f"`{kind}` needs `{key}`")
        fx, fy = a[key]
        return round(fx * w, 1), round(fy * h, 1)

    if kind == "click":
        x, y = point("coordinate")
        return {"action": "tap", "x": x, "y": y, "label": label}
    if kind == "long_press":
        x, y = point("coordinate")
        seconds = _seconds(a.get("time"), default=1.0, cap=5.0)
        return {"action": "long_press", "x": x, "y": y, "seconds": seconds, "label": label}
    if kind == "swipe":
        x, y = point("coordinate")
        x2, y2 = point("coordinate2")
        return {"action": "swipe", "x": x, "y": y, "x2": x2, "y2": y2, "label": label}
    if kind == "type":
        return {"action": "type", "text": str(a.get("text") or ""), "label": label}
    if kind == "system_button":
        button = str(a.get("button") or "").lower()
        mapped = {"back": "back", "home": "home", "enter": "enter", "menu": "recents"}.get(button)
        if not mapped:
            raise ValueError(f"unknown system button {a.get('button')!r}")
        return {"action": mapped, "label": label}
    if kind == "wait":
        return {"action": "wait", "seconds": _seconds(a.get("time"), default=2.0, cap=10.0)}
    if kind == "open":
        app = str(a.get("text") or a.get("app") or "").strip()
        if not app:
            raise ValueError("`open` needs the app's name in `text`")
        return {"action": "open_app", "app": app, "label": label}
    if kind in ("answer", "terminate", "ask_user"):
        return None
    raise ValueError(f"unknown action {kind!r}")


def _seconds(value: Any, default: float, cap: float) -> float:
    try:
        seconds = float(value) if value is not None else default
    except (TypeError, ValueError):
        seconds = default
    return max(0.2, min(cap, seconds))


# ------------------------------------------------------------------ the operator


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
        traces_dir: Path | None = None,
    ):
        self.link = link
        self.settings = settings
        self.sentinel = sentinel
        self.act_tool = act_tool
        self.ui = ui
        self._make_llm = make_llm
        self._llm: BaseLLM | None = None
        self._language = language or (lambda: "the language of the query")
        self.traces_dir = traces_dir
        # how many times a reply that is not a step is asked again before giving up
        self.parse_retries = 3

    @property
    def llm(self) -> BaseLLM:
        if self._llm is None:
            self._llm = self._make_llm()
        return self._llm

    def reset_llm(self) -> None:
        self._llm = None

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            tool=json.dumps(MOBILE_USE_TOOL, ensure_ascii=False), language=self._language()
        )

    # ------------------------------------------------------------------ the loop
    async def run(self, goal: str, context: str = "", app: str = "") -> Outcome:
        outcome = Outcome(status="failed")
        instruction = goal.strip()
        if context.strip():
            instruction += f"\n(Known already: {context.strip()})"
        trace = Trace.start(self.traces_dir, goal=goal, app=app, context=context)
        outcome.trace_id = trace.id
        if self.llm.vision_available is False:
            outcome.message = (
                "the operator model does not take images; set [gui] model to one that does"
            )
            trace.end(outcome)
            return outcome

        steps: list[str] = []  # the "Action:" sentences, with results appended
        recent: list[str] = []  # the last tool calls, to notice loops
        try:
            if app:
                await self._act({"action": "open_app", "app": app, "label": f"open {app}"}, outcome)
                screen = self.link.last_screen or await self.link.screen()
            else:
                screen = await self.link.screen()
        except DeviceError as exc:
            outcome.message = str(exc)
            trace.end(outcome)
            return outcome

        refusals = 0
        for step_no in range(1, self.settings.max_steps + 1):
            outcome.steps = step_no
            outcome.last_screen = screen.render()
            outcome.last_image = screen.image_path
            if not screen.image_path:
                outcome.status = "failed"
                outcome.message = "the phone sent no screenshot; the operator cannot see the screen"
                break

            step, raw, latency_ms = await self._decide(instruction, steps, screen)
            if step is None:
                outcome.status = "failed"
                outcome.message = "the operator model did not produce usable actions"
                trace.step(step_no, screen, raw=raw, latency_ms=latency_ms, error=outcome.message)
                break
            entry = step.action.replace("\n", " ").replace('"', "")
            logger.info("phone step {}: {} — {}", step_no, step.action, step.arguments)

            if step.name != "mobile_use":
                steps.append(f"{entry}; Result: only the mobile_use function is available")
                trace.step(step_no, screen, step=step, raw=raw, latency_ms=latency_ms)
                continue

            kind = step.kind
            if kind in ("answer", "terminate", "ask_user"):
                text = str(step.arguments.get("text") or "").strip()
                if kind == "ask_user":
                    outcome.status, outcome.message = "ask", text or step.thought
                elif kind == "answer":
                    outcome.status, outcome.message = "done", text or step.thought
                else:
                    ok = str(step.arguments.get("status") or "success") == "success"
                    outcome.status = "done" if ok else "abort"
                    outcome.message = text or step.thought
                trace.step(step_no, screen, step=step, raw=raw, latency_ms=latency_ms)
                break

            try:
                params = to_device_action(step, screen)
            except ValueError as exc:
                steps.append(f"{entry}; Result: {exc}")
                trace.step(
                    step_no, screen, step=step, raw=raw, latency_ms=latency_ms, error=str(exc)
                )
                continue
            assert params is not None

            signature = json.dumps(step.arguments, sort_keys=True, ensure_ascii=False)
            recent.append(signature)
            if len(recent) >= 3 and len(set(recent[-3:])) == 1:
                steps.append(
                    f"{entry}; Note: this same action was taken three times with no visible "
                    "change — try another way, or terminate with status failure"
                )
                recent.clear()
                trace.step(step_no, screen, step=step, raw=raw, latency_ms=latency_ms, error="loop")
                continue

            result = await self._act(params, outcome)
            trace.step(
                step_no,
                screen,
                step=step,
                raw=raw,
                latency_ms=latency_ms,
                params=params,
                error=result.error,
            )
            if result.error and "Sentinel blocked" in result.error:
                refusals += 1
                steps.append(f"{entry}; Result: the owner refused this step")
                if refusals >= 2:
                    outcome.status = "blocked"
                    outcome.message = result.error
                    break
            elif result.error:
                steps.append(f"{entry}; Result: {result.error[:200]}")
            else:
                refusals = 0
                steps.append(entry)

            try:
                fresh = self.link.last_screen if not result.error else None
                screen = fresh if fresh is not None else await self.link.screen()
            except DeviceError as exc:
                outcome.message = str(exc)
                break
        else:
            outcome.status = "max_steps"
            outcome.message = f"stopped after {self.settings.max_steps} steps"

        trace.end(outcome)
        return outcome

    # ------------------------------------------------------------------ helpers
    async def _decide(
        self, instruction: str, steps: list[str], screen: Screen
    ) -> tuple[Step | None, str, int]:
        """Ask the model for the next step; a reply that is not one is asked again."""
        progress = "".join(f"Step {i}: {s}; " for i, s in enumerate(steps, start=1))
        messages = [
            Message.system(self.system_prompt()),
            Message.user(
                USER_TEMPLATE.format(instruction=instruction, steps=progress),
                images=[screen.image_path] if screen.image_path else None,
            ),
        ]
        raw = ""
        started = time.monotonic()
        for attempt in range(self.parse_retries):
            response = await self.llm.ask_complete(messages)
            raw = response.content or ""
            step = parse_step(raw)
            if step is not None:
                return step, raw, int((time.monotonic() - started) * 1000)
            logger.debug("phone step: reply was not a step (try {}): {!r}", attempt + 1, raw[:600])
            if attempt + 1 < self.parse_retries:
                messages = messages[:2] + [
                    Message.assistant(content=raw),
                    Message.user(
                        "That was not in the response format. Reply with Thought, Action and one "
                        "<tool_call> block calling mobile_use."
                    ),
                ]
        return None, raw, int((time.monotonic() - started) * 1000)

    async def _act(self, params: dict[str, Any], outcome: Outcome) -> ToolResult:
        call = ToolCall(
            function=Function(
                name=self.act_tool.name, arguments=json.dumps(params, ensure_ascii=False)
            )
        )
        summary = self.act_tool.assess(params).summary
        outcome.actions.append(summary.removeprefix("phone_act: "))
        self.ui.on_tool_call(call, summary)
        result = await self.sentinel.guard(call, self.act_tool)
        self.ui.on_tool_result(call, result)
        if result.error:
            logger.info("phone step failed: {}", result.error)
        return result


__all__ = [
    "MOBILE_USE_TOOL",
    "SCALE_FACTOR",
    "SYSTEM_PROMPT",
    "USER_TEMPLATE",
    "Outcome",
    "PhoneOperator",
    "Step",
    "parse_step",
    "parse_tagged_text",
    "to_device_action",
]
