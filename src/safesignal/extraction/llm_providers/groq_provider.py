"""Groq provider for SafeSignal.

Groq hosts Llama and Mixtral models via an OpenAI-compatible API.
Their **free tier** gives ~30 requests/minute and ~14,400/day — plenty for
the SafeSignal project scope.

We use ``llama-3.3-70b-versatile`` as the default model. It's Groq's
strongest reasoning model at the time of writing, and handles structured
JSON output reliably when paired with a strict SKILL.md.

Docs: https://console.groq.com/docs
"""

from __future__ import annotations

from safesignal.common.exceptions import SafeSignalError
from safesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class GroqProviderError(SafeSignalError):
    """Raised when Groq API calls fail."""


# Groq free tier is generous; we don't bill for it. These estimates exist
# only so the app-level cost ceiling has a non-zero number to track for
# observability.
_GROQ_PRICING_USD_PER_MTOK = {
    # Llama 3.3 70B Versatile
    "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},
    # Llama 3.1 8B (cheaper/faster if needed)
    "llama-3.1-8b-instant": {"input": 0.0, "output": 0.0},
    # Mixtral (still supported as of writing)
    "mixtral-8x7b-32768": {"input": 0.0, "output": 0.0},
}


class GroqProvider(LLMProvider):
    """LLMProvider backed by the Groq API."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        """Create a Groq provider.

        Args:
            api_key: Groq API key (from https://console.groq.com).
            model: Groq model identifier. Default is the 70B versatile model.
        """
        # Lazy import so the dependency is only required when this provider is used.
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise GroqProviderError(
                "groq package not installed. Run: pip install groq"
            ) from exc

        if not api_key:
            raise GroqProviderError("Groq API key is empty")

        self._client = Groq(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        """Short provider name used in logs and audit trail."""
        return "groq"

    @property
    def model(self) -> str:
        """Current model identifier."""
        return self._model

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Call Groq's chat completion endpoint."""
        # Groq uses OpenAI-compatible chat messages. Prepend the system message.
        chat_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in messages:
            chat_messages.append({"role": msg.role, "content": msg.content})

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=chat_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                # Ask for JSON explicitly — Groq supports this mode for some models.
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise GroqProviderError(f"Groq API call failed: {exc}") from exc

        if not response.choices:
            raise GroqProviderError("Groq returned no choices")

        content = response.choices[0].message.content or ""
        usage = response.usage

        return LLMResponse(
            text=content,
            model=self._model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            provider=self.provider_name,
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Groq free tier — returns $0.0 for budgeting purposes.

        If Groq ever starts charging, update the pricing table at top of file.
        """
        pricing = _GROQ_PRICING_USD_PER_MTOK.get(
            self._model, {"input": 0.0, "output": 0.0}
        )
        return (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
