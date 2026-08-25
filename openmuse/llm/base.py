"""Provider-agnostic LLM interface."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from openmuse.schema import LLMResponse, Message

DeltaCallback = Callable[[str], None]

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class BaseLLM(ABC):
    """A chat model that may or may not support native tool calling."""

    name: str = "base"
    supports_native_tools: bool = True

    @abstractmethod
    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        """Send a conversation and get one assistant turn back.

        ``tools`` are OpenAI-style function schemas
        (``{"type": "function", "function": {...}}``).
        ``on_delta`` receives visible text as it streams (never reasoning).
        """

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


__all__ = ["BaseLLM", "DeltaCallback", "ThinkStreamFilter", "split_think"]
