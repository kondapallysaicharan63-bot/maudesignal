"""Abstract LLM provider interface.

Every provider (Anthropic, OpenAI, Groq) implements ``LLMProvider`` so the
extraction layer can swap backends via configuration without code changes.

Design principle (Doc 5 D4): explicit, provider-agnostic interface over
opaque framework magic. We know exactly what each provider returns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMMessage:
    """A single message in a conversation.

    Mirrors the common role/content pattern shared by Anthropic, OpenAI,
    and Groq APIs. We keep it minimal to avoid vendor-specific fields.
    """

    role: str  # "user" or "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response returned by any provider.

    Attributes:
        text: The model's text output (pre-JSON-extraction).
        model: Full model identifier that produced this response.
        input_tokens: Tokens counted against the input (prompt).
        output_tokens: Tokens counted against the completion.
        provider: The provider name ("anthropic", "openai", "groq").
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    provider: str


class LLMProvider(ABC):
    """Abstract interface every LLM provider implements.

    Subclasses only need to translate between our normalized types and the
    vendor SDK. They do NOT handle retries, audit logging, or JSON
    validation — those live in the Extractor above this layer.
    """

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send messages and return a normalized response.

        Args:
            system_prompt: System-level instructions (the SKILL.md content).
            messages: Conversation turns (few-shot examples + real input).
            max_tokens: Maximum output tokens to generate.
            temperature: Sampling temperature. Default 0.0 for reproducibility.

        Returns:
            An LLMResponse with normalized fields.

        Raises:
            LLMProviderError: On transport or API errors. Upstream code
                decides whether to retry.
        """

    @abstractmethod
    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Return a conservative USD cost estimate for a completed call.

        Used only for the in-app budget ceiling (not for billing). Real
        billing comes from the provider's invoicing.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (lowercase short name)."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the current model identifier."""

    def describe(self) -> dict[str, Any]:
        """Return a dict summarizing provider + model for logging."""
        return {"provider": self.provider_name, "model": self.model}
