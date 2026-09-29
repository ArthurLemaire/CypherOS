"""Model-provider abstraction so planners aren't tied to one vendor."""

from __future__ import annotations

from dots.llm.base import Completion, LLM, Message, Role
from dots.llm.echo import EchoLLM

__all__ = ["Completion", "EchoLLM", "LLM", "Message", "Role"]
