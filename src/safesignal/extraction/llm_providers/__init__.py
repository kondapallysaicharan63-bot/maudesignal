"""LLM provider abstraction for SafeSignal.

Usage:
    from safesignal.extraction.llm_providers import get_provider
    provider = get_provider(config)
    response = provider.complete(system_prompt=..., messages=[...])

The provider returned depends on ``config.llm_provider`` ("groq",
"anthropic", "openai", or "gemini").
"""

from __future__ import annotations

from safesignal.common.exceptions import SafeSignalError
from safesignal.config import Config
from safesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class UnknownProviderError(SafeSignalError):
    """Raised when ``LLM_PROVIDER`` env var names an unsupported provider."""


def get_provider(config: Config) -> LLMProvider:
    """Return an LLMProvider instance based on configuration.

    Args:
        config: Loaded SafeSignal Config.

    Returns:
        A concrete LLMProvider subclass ready to call ``complete()``.

    Raises:
        UnknownProviderError: If ``config.llm_provider`` is not one of
            ``"groq"``, ``"anthropic"``, ``"openai"``, or ``"gemini"``.
        ConfigError: If the required API key for the chosen provider is missing.
    """
    provider = config.llm_provider.lower().strip()

    if provider == "groq":
        from safesignal.extraction.llm_providers.groq_provider import GroqProvider

        if not config.groq_api_key:
            raise SafeSignalError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com"
            )
        return GroqProvider(
            api_key=config.groq_api_key,
            model=config.groq_model,
        )

    if provider == "anthropic":
        from safesignal.extraction.llm_providers.anthropic_provider import (
            AnthropicProvider,
        )

        if not config.anthropic_api_key:
            raise SafeSignalError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. "
                "Get a key at https://console.anthropic.com"
            )
        return AnthropicProvider(
            api_key=config.anthropic_api_key,
            model=config.claude_model_extraction,
        )

    if provider == "openai":
        from safesignal.extraction.llm_providers.openai_provider import OpenAIProvider

        if not config.openai_api_key:
            raise SafeSignalError(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is not set. "
                "Get a key at https://platform.openai.com"
            )
        return OpenAIProvider(
            api_key=config.openai_api_key,
            model=config.openai_model,
        )

    if provider == "gemini":
        from safesignal.extraction.llm_providers.gemini_provider import GeminiProvider

        if not config.gemini_api_key:
            raise SafeSignalError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        return GeminiProvider(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
        )

    raise UnknownProviderError(
        f"Unknown LLM_PROVIDER: {provider!r}. "
        f"Supported: 'groq', 'anthropic', 'openai', 'gemini'."
    )


__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "UnknownProviderError",
    "get_provider",
]
