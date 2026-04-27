"""Anthropic (Claude) provider for MaudeSignal.

Implements the LLMProvider interface using the official Anthropic SDK.
Claude was MaudeSignal's original reference provider — the SKILL.md format
was designed with Claude's prompt style in mind — but the abstraction
layer means we're no longer locked in.

Docs: https://docs.claude.com
"""

from __future__ import annotations

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class AnthropicProviderError(MaudeSignalError):
    """Raised when Anthropic API calls fail."""


# Conservative per-million-token pricing (USD). Used for the in-app budget
# ceiling. Check Anthropic's pricing page for current numbers.
_ANTHROPIC_PRICING_USD_PER_MTOK = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}


class AnthropicProvider(LLMProvider):
    """LLMProvider backed by the Anthropic Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        """Create an Anthropic provider.

        Args:
            api_key: Anthropic API key (from https://console.anthropic.com).
            model: Claude model identifier. Sonnet is the default — good
                balance of quality and cost for MaudeSignal's use case.
        """
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise AnthropicProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        if not api_key:
            raise AnthropicProviderError("Anthropic API key is empty")

        self._client = Anthropic(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        """Short provider name used in logs and audit trail."""
        return "anthropic"

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
        """Call Claude's messages endpoint."""
        # Anthropic takes system separately (not as a message in the list).
        api_messages: list[dict[str, str]] = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=api_messages,  # type: ignore[arg-type]
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise AnthropicProviderError(f"Anthropic API call failed: {exc}") from exc

        text_parts = [block.text for block in response.content if block.type == "text"]
        text = "\n".join(text_parts).strip()

        return LLMResponse(
            text=text,
            model=self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            provider=self.provider_name,
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Return a conservative USD estimate for billing observability."""
        pricing = _ANTHROPIC_PRICING_USD_PER_MTOK.get(
            self._model, {"input": 10.0, "output": 50.0}
        )
        return (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
