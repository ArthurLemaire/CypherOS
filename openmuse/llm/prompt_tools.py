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

from openmuse.llm.base import BaseLLM, DeltaCallback, ToolsUnsupported
from openmuse.logger import logger
from openmuse.schema import Function, LLMResponse, Message, Role, ToolCall

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
# What small models produce instead of the tags, protocol notwithstanding: Gemma
# writes ```tool_call fences, others a ```json fence holding {"name", "arguments"}.
_FENCED_RE = re.compile(r"```(?:tool_call|tool_code|json)?[ \t]*\n?\s*(\{.*?\})\s*```", re.DOTALL)
_OPEN_TAG = "<tool_call>"
_STOP_TAGS = (_OPEN_TAG, "```tool_call")

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


def _as_call(raw: str, known: set[str] | None, strict: bool) -> ToolCall | None:
    """One JSON object → a ToolCall, or None when it is not a call.

    ``strict`` is for fenced blocks, which may be a model quoting JSON for other
    reasons: those must have ``arguments`` (or ``parameters``) and, when the tool
    names are known, name one of them.
    """
    try:
        # strict=False: small models put real newlines inside JSON strings (code arguments)
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return None
    args = data.get("arguments", data.get("parameters"))
    if strict:
        if not isinstance(args, dict) or (known is not None and data["name"] not in known):
            return None
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        args = {"value": args}
    return ToolCall(
        function=Function(name=data["name"], arguments=json.dumps(args, ensure_ascii=False))
    )


def parse_tool_calls(
    text: str | None, known: set[str] | None = None
) -> tuple[str | None, list[ToolCall]]:
    """Split model output into (visible_text, tool_calls).

    ``<tool_call>`` blocks are the protocol; fenced ```tool_call / ```json blocks
    that hold ``{"name", "arguments"}`` for a known tool are accepted too, because
    that is what several small models emit however clearly the prompt says otherwise.
    """
    if not text:
        return text, []
    calls: list[ToolCall] = []
    for raw in _TOOL_CALL_RE.findall(text):
        call = _as_call(raw, known, strict=False)
        if call is not None:
            calls.append(call)
    visible = _TOOL_CALL_RE.sub("", text)
    if not calls:
        fenced = [(m, _as_call(m.group(1), known, strict=True)) for m in _FENCED_RE.finditer(text)]
        calls = [c for _, c in fenced if c is not None]
        for m, c in reversed(fenced):
            if c is not None:
                visible = visible[: m.start()] + visible[m.end() :]
    if not calls:
        # the whole reply is one bare JSON object (Llama 3.x when its template does not
        # fire), possibly after a sentence of narration on its own lines
        for i, line in enumerate(text.splitlines()):
            if line.lstrip().startswith("{"):
                tail = "\n".join(text.splitlines()[i:]).strip()
                bare = _as_call(tail, known, strict=True)
                if bare is not None:
                    calls = [bare]
                    visible = "\n".join(text.splitlines()[:i])
                break
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
        cut = [i for i in (self.buf.find(t) for t in _STOP_TAGS) if i != -1]
        if cut:
            self.on_delta(self.buf[: min(cut)])
            self.stopped = True
            return
        # Hold back a possible partial tag prefix.
        hold = 0
        for tag in _STOP_TAGS:
            for k in range(len(tag) - 1, 0, -1):
                if self.buf.endswith(tag[:k]):
                    hold = max(hold, k)
                    break
        emit, self.buf = self.buf[: len(self.buf) - hold], self.buf[len(self.buf) - hold :]
        if emit:
            self.on_delta(emit)

    def flush(self) -> None:
        if not self.stopped and self.on_delta and self.buf:
            self.on_delta(self.buf)
        self.buf = ""


class PromptToolAdapter(BaseLLM):
    """Prompt-based tools around any model.

    With ``native_first`` the inner provider's function calling is used until the
    endpoint rejects the ``tools`` field (:class:`ToolsUnsupported`); from then on
    every request goes through the prompt protocol. That is ``tool_mode = "auto"``:
    the same config works for DeepSeek and for a small Ollama model that has no
    tool template.
    """

    name = "prompt_tools"

    def __init__(self, inner: BaseLLM, *, native_first: bool = False):
        self.inner = inner
        self.native = native_first and inner.supports_native_tools

    @property
    def supports_native_tools(self) -> bool:  # type: ignore[override]
        return self.native

    @property
    def settings(self) -> Any:
        """The wrapped provider's settings (model, base_url, …)."""
        return getattr(self.inner, "settings", None)

    @property
    def vision_available(self) -> bool | None:  # type: ignore[override]
        return self.inner.vision_available

    @vision_available.setter
    def vision_available(self, value: bool | None) -> None:
        self.inner.vision_available = value

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not tools:
            return await self.inner.ask(messages, None, on_delta=on_delta, max_tokens=max_tokens)
        known = {t.get("function", t).get("name", "") for t in tools}
        if self.native:
            try:
                resp = await self.inner.ask(
                    messages, tools, tool_choice, on_delta=on_delta, max_tokens=max_tokens
                )
            except ToolsUnsupported as e:
                self.native = False
                logger.warning(
                    "the endpoint does not do native tool calling ({}); "
                    "describing tools in the prompt from now on",
                    str(e).splitlines()[0][:200],
                )
            else:
                if not resp.tool_calls and resp.content:
                    # a native-mode model that wrote the call as text (Llama 3.x does this
                    # when its template does not fire): a bare or fenced JSON object naming
                    # one of our tools is a call, not an answer
                    visible, calls = parse_tool_calls(resp.content, known)
                    if calls:
                        resp.content, resp.tool_calls = visible, calls
                        resp.finish_reason = "tool_calls"
                return resp
        converted = convert_messages(messages, tools)
        stopper = _StopAtToolCall(on_delta)
        resp = await self.inner.ask(
            converted, None, on_delta=stopper if on_delta else None, max_tokens=max_tokens
        )
        stopper.flush()
        visible, calls = parse_tool_calls(resp.content, known)
        resp.content = visible
        resp.tool_calls = calls
        resp.finish_reason = "tool_calls" if calls else resp.finish_reason
        return resp

    async def close(self) -> None:
        await self.inner.close()


__all__ = ["PromptToolAdapter", "convert_messages", "parse_tool_calls", "render_tools"]
