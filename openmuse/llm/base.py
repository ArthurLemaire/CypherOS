"""Provider-agnostic LLM interface."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from openmuse.schema import LLMResponse, Message

DeltaCallback = Callable[[str], None]

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)

# What endpoints say when they cannot do function calling for this model:
# Ollama: "registry.ollama.ai/library/gemma3:4b does not support tools";
# vLLM: '"auto" tool choice requires --enable-auto-tool-choice ...';
# others: "tools are not supported", "function calling is not supported".
_NO_TOOLS_RE = re.compile(
    r"(does not|doesn'?t|is not|isn'?t|are not|aren'?t|not) support(ed)?\b[^.]{0,40}\b(tool|function)"
    r"|\b(tool|function)[^.]{0,40}\b(not supported|unsupported|not available)"
    r"|enable-auto-tool-choice",
    re.IGNORECASE,
)


class ToolsUnsupported(Exception):
    """The endpoint rejected the request because of the ``tools`` field.

    Providers raise this instead of the raw 400 so the prompt-mode fallback can
    take over (``tool_mode = "auto"``).
    """


def says_no_tools(message: str) -> bool:
    return bool(_NO_TOOLS_RE.search(message or ""))


class BaseLLM(ABC):
    """A chat model that may or may not support native tool calling."""

    name: str = "base"
    supports_native_tools: bool = True
    # Whether the model takes images: None until a message with pictures has been sent,
    # False once the endpoint refused image content (``llm.vision = "auto"`` then sends
    # text only, with a note in place of each picture).
    vision_available: bool | None = None

    @abstractmethod
    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a conversation and get one assistant turn back.

        ``tools`` are OpenAI-style function schemas
        (``{"type": "function", "function": {...}}``).
        ``on_delta`` receives visible text as it streams (never reasoning).
        ``max_tokens`` overrides the configured budget for this one call.
        """

    def roomier_max_tokens(self) -> int:
        """A budget for a second try when the first answer was cut off: four times the
        configured one, 16k at least — enough for a reasoning model to think and answer."""
        configured = getattr(getattr(self, "settings", None), "max_tokens", None) or 0
        return max(16384, 4 * int(configured))

    async def ask_complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        """``ask``, tried once more with room when the answer was cut off.

        A reasoning model can spend the whole ``max_tokens`` thinking and hand back an
        empty or half-written answer with ``finish_reason == "length"``. The callers
        that want a JSON list (ideas, memory tidy-up) cannot use a fragment, so the
        second try gets ``roomier_max_tokens()``.
        """
        response = await self.ask(messages, **kwargs)
        if response.finish_reason == "length":
            kwargs["max_tokens"] = self.roomier_max_tokens()
            response = await self.ask(messages, **kwargs)
        return response

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


def split_think(content: str | None) -> tuple[str | None, str | None]:
    """Extract ``<think>...</think>`` blocks from non-streamed content.

    Returns ``(visible_content, reasoning)``.
    """
    if not content:
        return content, None
    reasoning_parts = _THINK_RE.findall(content)
    if not reasoning_parts:
        # Unterminated <think> (model ran out of tokens): treat the rest as reasoning.
        if "<think>" in content:
            head, _, tail = content.partition("<think>")
            return head.strip() or None, tail.strip() or None
        return content, None
    visible = _THINK_RE.sub("", content).strip()
    return visible or None, "\n".join(p.strip() for p in reasoning_parts) or None


class ThinkStreamFilter:
    """Streams visible text while diverting ``<think>...</think>`` to ``reasoning``.

    Handles tags that are split across deltas.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self.in_think = False
        self._buf = ""
        self._reasoning: list[str] = []

    @staticmethod
    def _partial_suffix(text: str, tag: str) -> int:
        for k in range(len(tag) - 1, 0, -1):
            if text.endswith(tag[:k]):
                return k
        return 0

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        while self._buf:
            tag = self.CLOSE if self.in_think else self.OPEN
            idx = self._buf.find(tag)
            if idx == -1:
                keep = self._partial_suffix(self._buf, tag)
                chunk, self._buf = (
                    self._buf[: len(self._buf) - keep],
                    self._buf[len(self._buf) - keep :],
                )
                if self.in_think:
                    self._reasoning.append(chunk)
                else:
                    out.append(chunk)
                break
            chunk, self._buf = self._buf[:idx], self._buf[idx + len(tag) :]
            if self.in_think:
                self._reasoning.append(chunk)
            else:
                out.append(chunk)
            self.in_think = not self.in_think
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        if self.in_think:
            self._reasoning.append(rest)
            return ""
        return rest

    @property
    def reasoning(self) -> str | None:
        text = "".join(self._reasoning).strip()
        return text or None


__all__ = [
    "BaseLLM",
    "DeltaCallback",
    "ThinkStreamFilter",
    "ToolsUnsupported",
    "says_no_tools",
    "split_think",
]
