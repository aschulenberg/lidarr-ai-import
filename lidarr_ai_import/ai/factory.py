from __future__ import annotations

from ..config import Config
from .anthropic_provider import AnthropicProvider
from .base import AIProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def build_provider(config: Config) -> AIProvider:
    cls = _PROVIDERS.get(config.ai_provider)
    if cls is None:
        raise ValueError(
            f"Unknown AI_PROVIDER '{config.ai_provider}', expected one of {list(_PROVIDERS)}"
        )
    return cls(model=config.ai_model, api_key=config.ai_api_key, base_url=config.ai_base_url)
