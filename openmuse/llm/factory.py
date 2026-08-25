"""Build the configured LLM."""

from __future__ import annotations

from openmuse.config import LLMSettings
from openmuse.llm.base import BaseLLM
from openmuse.llm.openai_chat import OpenAIChatLLM
from openmuse.llm.openai_responses import OpenAIResponsesLLM
from openmuse.llm.prompt_tools import PromptToolAdapter


def create_llm(settings: LLMSettings) -> BaseLLM:
    if settings.provider == "openai":
        llm: BaseLLM = OpenAIChatLLM(settings)
    elif settings.provider == "openai_responses":
        llm = OpenAIResponsesLLM(settings)
    else:  # pragma: no cover - guarded by pydantic Literal
        raise ValueError(f"unknown llm provider: {settings.provider}")
    if settings.tool_mode == "prompt":
        llm = PromptToolAdapter(llm)
    return llm


__all__ = ["create_llm"]
