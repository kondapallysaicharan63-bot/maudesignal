"""OpenAI (GPT) provider for MaudeSignal.

Implements the LLMProvider interface using the official OpenAI SDK.
Supports GPT-4o, GPT-4o-mini, and the o1 reasoning models.

Note: The OpenAI API (platform.openai.com) is separate from ChatGPT Plus.
ChatGPT Plus does NOT grant API credits. You must prepay for API usage
at https://platform.openai.com/settings/organization/billing.

Docs: https://platform.openai.com/docs
"""

from __future__ import annotations

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class OpenAIProviderError(MaudeSignalError):
    """Raised when OpenAI API calls fail."""


# Conservative per-million-token pricing (USD). Check OpenAI's pricing page
# at https://openai.com/api/pricing for current numbers.
_OPENAI_PRICING_USD_PER_MTOK = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o1-preview": {"input": 15.00, "output": 60.00},
}


class OpenAIProvider(LLMProvider):
    """LLMProvider backed by the OpenAI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
    ) -> None:
        """Create an OpenAI provider.

        Args:
            api_key: OpenAI API key (from platform.openai.com).
            model: Model identifier. Default is gpt-4o-mini — cheapest
                capable model for structured extraction.
        """
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise OpenAIProviderError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        if not api_key:
            raise OpenAIProviderError("OpenAI API key is empty")

        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        """Short provider name used in logs and audit trail."""
        return "openai"

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
        """Call OpenAI's chat completions endpoint."""
        chat_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in messages:
            chat_messages.append({"role": msg.role, "content": msg.content})

        # o1 models don't accept temperature / max_tokens the same way.
        extra_kwargs: dict[str, float | int] = {}
        if not self._model.startswith("o1"):
            extra_kwargs["temperature"] = temperature
            extra_kwargs["max_tokens"] = max_tokens

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=chat_messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                **extra_kwargs,  # type: ignore[arg-type]
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise OpenAIProviderError(f"OpenAI API call failed: {exc}") from exc

        if not response.choices:
            raise OpenAIProviderError("OpenAI returned no choices")

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
        """Return a conservative USD estimate for billing observability."""
        pricing = _OPENAI_PRICING_USD_PER_MTOK.get(
            self._model, {"input": 5.0, "output": 15.0}
        )
        return (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
