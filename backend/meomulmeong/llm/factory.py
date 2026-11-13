"""설정(LLM 모드)에 맞는 공급자를 만들어요. 템플릿 모드는 None."""

from __future__ import annotations

from ..settings import Settings
from .base import LLMError, LLMProvider


def make_llm(settings: Settings, mode: str | None = None) -> LLMProvider | None:
    mode = mode or settings.llm_mode
    if mode == "template":
        return None
    if mode == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(settings.ollama_host, settings.ollama_model, settings.ollama_timeout)
    if mode == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_model)
    raise LLMError(f"알 수 없는 LLM 모드예요: {mode}")
