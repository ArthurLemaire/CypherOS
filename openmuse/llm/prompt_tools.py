"""Prompt-based tool calling for models/endpoints without native function calling.

Tools are described in the system prompt; the model emits::

    <tool_call>
    {"name": "web_search", "arguments": {"query": "..."}}
    </tool_call>

Tool results are fed back as user messages wrapped in ``<tool_result>`` blocks.
The adapter wraps any :class:`BaseLLM` and presents the same interface, so the
agent loop does not care which mode is active.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openmuse.llm.base import BaseLLM, DeltaCallback
from openmuse.schema import Function, LLMResponse, Message, Role, ToolCall

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_OPEN_TAG = "<tool_call>"

PROTOCOL = """
# Tool calling protocol

You can use tools. To call one, output a block **exactly** like this (you may emit several blocks in one reply):

<tool_call>
{{"name": "<tool_name>", "arguments": {{<json arguments>}}}}
</tool_call>

Rules:
- `arguments` must be a JSON object matching the tool's parameter schema.
- After emitting tool calls, STOP and wait. Results come back inside <tool_result> blocks.
- Never invent tool results. Never wrap a tool call in markdown code fences.
- When the task is complete, reply normally without any <tool_call> block.

# Available tools

{tools}
""".strip()


def render_tools(tools: list[dict[str, Any]]) -> str:
    lines = []
    for t in tools:
        fn = t.get("function", t)
        schema = json.dumps(fn.get("parameters", {}), ensure_ascii=False)
        lines.append(
            f"- **{fn['name']}**: {fn.get('description', '').strip()}\n  parameters: {schema}"
        )
    return "\n".join(lines)


def parse_tool_calls(text: str | None) -> tuple[str | None, list[ToolCall]]:
    """Split model output into (visible_text, tool_calls)."""
    if not text:
        return text, []
    calls: list[ToolCall] = []
    for raw in _TOOL_CALL_RE.findall(text):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "name" not in data:
            continue
        args = data.get("arguments", {})
        if not isinstance(args, dict):
            args = {"value": args}
        calls.append(
            ToolCall(
                function=Function(
                    name=str(data["name"]), arguments=json.dumps(args, ensure_ascii=False)
                )
            )
        )
    visible = _TOOL_CALL_RE.sub("", text)
    # An unterminated block (model cut off) is dropped from the visible text.
    if _OPEN_TAG in visible:
        visible = visible.split(_OPEN_TAG, 1)[0]
    visible = visible.strip()
    return (visible or None), calls


def convert_messages(messages: list[Message], tools: list[dict[str, Any]]) -> list[Message]:
    """Rewrite a tool-aware conversation into plain user/assistant/system turns."""
    out: list[Message] = []
    protocol = PROTOCOL.format(tools=render_tools(tools))
    injected = False
    for m in messages:
        if m.role == Role.SYSTEM:
            if not injected:
                out.append(Message.system(f"{m.content or ''}\n\n{protocol}".strip()))
                injected = True
            else:
                out.append(m)
        elif m.role == Role.ASSISTANT:
            parts = [m.content] if m.content else []
            for tc in m.tool_calls or []:
                payload = {"name": tc.function.name, "arguments": tc.arguments}
                parts.append(
                    f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
                )
            out.append(Message.assistant(content="\n".join(parts) or ""))
        elif m.role == Role.TOOL:
            block = f'<tool_result name="{m.name or ""}">\n{m.content or ""}\n</tool_result>'
            # Merge consecutive tool results into one user message.
            if out and out[-1].role == Role.USER and out[-1].meta.get("tool_results"):
                out[-1].content = f"{out[-1].content}\n{block}"
            else:
                msg = Message.user(block)
                msg.meta["tool_results"] = True
                out.append(msg)
        else:
            out.append(m)
    if not injected:
        out.insert(0, Message.system(protocol))
    return out


class _StopAtToolCall:
    """Forward streamed text to the UI until a <tool_call> tag shows up."""

    def __init__(self, on_delta: DeltaCallback | None):
        self.on_delta = on_delta
        self.buf = ""
        self.stopped = False

    def __call__(self, text: str) -> None:
        if self.stopped or not self.on_delta:
            return
        self.buf += text
        idx = self.buf.find(_OPEN_TAG)
        if idx != -1:
            self.on_delta(self.buf[:idx])
            self.stopped = True
            return
        # Hold back a possible partial tag prefix.
        hold = 0
        for k in range(len(_OPEN_TAG) - 1, 0, -1):
            if self.buf.endswith(_OPEN_TAG[:k]):
                hold = k
                break
        emit, self.buf = self.buf[: len(self.buf) - hold], self.buf[len(self.buf) - hold :]
        if emit:
            self.on_delta(emit)

    def flush(self) -> None:
        if not self.stopped and self.on_delta and self.buf:
            self.on_delta(self.buf)
        self.buf = ""


class PromptToolAdapter(BaseLLM):
    name = "prompt_tools"
    supports_native_tools = False

    def __init__(self, inner: BaseLLM):
        self.inner = inner

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        if not tools:
            return await self.inner.ask(messages, None, on_delta=on_delta)
        converted = convert_messages(messages, tools)
        stopper = _StopAtToolCall(on_delta)
        resp = await self.inner.ask(converted, None, on_delta=stopper if on_delta else None)
        stopper.flush()
        visible, calls = parse_tool_calls(resp.content)
        resp.content = visible
        resp.tool_calls = calls
        resp.finish_reason = "tool_calls" if calls else resp.finish_reason
        return resp

    async def close(self) -> None:
        await self.inner.close()


__all__ = ["PromptToolAdapter", "convert_messages", "parse_tool_calls", "render_tools"]
