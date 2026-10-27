"""Meta Model API provider for MaudeSignal.

HACKATHON-BUILT — created during the Meta Global AI Developer Hackathon
(Oct 26 – Nov 4, 2026). This file did not exist before the hackathon.

Implements the existing ``LLMProvider`` interface using the OpenAI-compatible
SDK pointed at the Meta Model API, so the copilot (and, optionally, the
extraction layer) can use Meta's models without changing any caller code.

Configuration (env vars only, never hardcoded, never logged):
    META_MODEL_API_KEY: API key from https://dev.meta.ai (required)
    META_MODEL_API_BASE_URL: API base URL (default: Meta Model API default)
    META_MODEL_API_MODEL: Model identifier (default: Muse Spark, see docs)

Tier rule: use the Standard tier. The Contributor tier trains on your data,
which is unacceptable for medical-device data.
"""

from __future__ import annotations

from collections.abc import Iterator

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class MetaProviderError(MaudeSignalError):
    """Raised when Meta Model API calls fail."""


class MetaProvider(LLMProvider):
    """LLMProvider backed by the Meta Model API (OpenAI-compatible)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
    ) -> None:
        """Create a Meta provider.

        Args:
            api_key: Meta Model API key (from env var, never hardcoded).
            model: Full Meta model identifier, e.g. a Muse Spark model.
            base_url: Meta Model API base URL for OpenAI-compatible calls.
        """
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise MetaProviderError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        if not api_key:
            raise MetaProviderError("Meta Model API key is empty")

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    @property
    def provider_name(self) -> str:
        """Short provider name used in logs and audit trail."""
        return "meta"

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
        """Send messages and return a normalized response."""
        chat_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in messages:
            chat_messages.append({"role": msg.role, "content": msg.content})

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=chat_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise MetaProviderError(f"Meta Model API call failed: {exc}") from exc

        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            provider=self.provider_name,
        )

    def complete_stream(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> Iterator[str]:
        """Stream a completion, yielding text deltas as they arrive.

        Used by the copilot UI so answers appear token-by-token instead of
        after the full response completes.
        """
        chat_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in messages:
            chat_messages.append({"role": msg.role, "content": msg.content})

        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=chat_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
        except Exception as exc:
            raise MetaProviderError(f"Meta Model API stream failed: {exc}") from exc

        # Local import: openai is an optional dependency (see __init__).
        # The guard also narrows the SDK's streaming union type for mypy.
        from openai.types.chat import ChatCompletionChunk

        for chunk in stream:
            if not isinstance(chunk, ChatCompletionChunk):
                continue
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Return a conservative USD cost estimate for a completed call.

        NOTE (hackathon): Meta Model API pricing is covered by the $150
        participant credit during the event, so this returns 0.0 until
        production pricing is pinned from the Meta pricing page.
        """
        _ = (input_tokens, output_tokens)
        return 0.0
