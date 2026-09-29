"""A dependency-free, deterministic LLM used in tests and offline demos."""

from __future__ import annotations

from dots.llm.base import Completion, Message


class EchoLLM:
    """Returns a canned, deterministic completion.

    It summarizes the last user message instead of calling a real model, so the
    rest of the stack can be exercised with zero network and zero cost.
    """

    def __init__(self, model: str = "echo-1") -> None:
        self.model = model

    async def complete(
        self, messages: list[Message], *, temperature: float = 0.2
    ) -> Completion:
        last_user = next(
            (m.content for m in reversed(messages) if m.role.value == "user"), ""
        )
        text = f"[echo] {last_user[:280]}"
        return Completion(
            text=text,
            model=self.model,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
        )
