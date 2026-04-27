"""Gemini (Google) provider for SafeSignal.

Implements the LLMProvider interface using Google's google-genai SDK
(the successor to google-generativeai, which is deprecated). Default
model is ``gemini-2.5-flash`` — Gemini's free tier is generous
(~1,500 requests/day at the time of writing), making it the second free
option alongside Groq for the SafeSignal project budget.

We treat Gemini as $0.00 cost for budgeting purposes while on the free
tier. The pricing table at top of file exists so the in-app cost ceiling
has a non-zero number to track if the project ever migrates to paid.

Note: Gemini's API uses ``system_instruction`` (passed via
``GenerateContentConfig``) rather than a system role in the message
list. We translate from our normalized LLMMessage shape inside
``complete()``.

Docs: https://ai.google.dev/gemini-api/docs
Migration guide: https://ai.google.dev/gemini-api/docs/migrate
Get a free key: https://aistudio.google.com/apikey
"""

from __future__ import annotations

import os

from safesignal.common.exceptions import SafeSignalError
from safesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)


class GeminiProviderError(SafeSignalError):
    """Raised when Gemini API calls fail."""


# Gemini free tier — $0.00 for budgeting purposes. If migrating to paid,
# update from https://ai.google.dev/pricing.
_GEMINI_PRICING_USD_PER_MTOK = {
    "gemini-2.5-flash": {"input": 0.0, "output": 0.0},
    "gemini-2.5-flash-lite": {"input": 0.0, "output": 0.0},
    "gemini-2.5-pro": {"input": 0.0, "output": 0.0},
    "gemini-2.0-flash": {"input": 0.0, "output": 0.0},
    "gemini-2.0-flash-lite": {"input": 0.0, "output": 0.0},
}


class GeminiProvider(LLMProvider):
    """LLMProvider backed by Google's Gemini API.

    Reads ``GEMINI_API_KEY`` from the environment if no key is passed
    explicitly. The SafeSignal Config layer normally supplies the key,
    but environment fallback is supported for ad-hoc CLI use.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
    ) -> None:
        """Create a Gemini provider.

        Args:
            api_key: Gemini API key. If None, falls back to the
                ``GEMINI_API_KEY`` environment variable.
            model: Model identifier. Default is ``gemini-2.5-flash`` —
                fast, cheap, and free-tier eligible.
        """
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover
            raise GeminiProviderError(
                "google-genai package not installed. "
                "Run: pip install google-genai"
            ) from exc

        resolved_key = api_key if api_key else os.environ.get("GEMINI_API_KEY", "")
        if not resolved_key:
            raise GeminiProviderError(
                "Gemini API key is empty. Set GEMINI_API_KEY in the "
                "environment or pass api_key explicitly. Get a free key "
                "at https://aistudio.google.com/apikey"
            )

        self._client = genai.Client(api_key=resolved_key)
        self._types = genai_types
        self._model = model

    @property
    def provider_name(self) -> str:
        """Short provider name used in logs and audit trail."""
        return "gemini"

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
        """Call Gemini's generate_content endpoint.

        Gemini takes ``system_instruction`` separately from the message
        list (unlike OpenAI/Groq which inline it as a system role). We
        also ask for JSON output via ``response_mime_type`` to match the
        structured-output behavior of the other providers.
        """
        types = self._types
        gemini_contents: list[object] = []
        for msg in messages:
            # Gemini uses "user" / "model" rather than "user" / "assistant".
            role = "model" if msg.role == "assistant" else "user"
            gemini_contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg.content)],
                )
            )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:  # pragma: no cover - network errors
            raise GeminiProviderError(f"Gemini API call failed: {exc}") from exc

        if not response.candidates:
            raise GeminiProviderError("Gemini returned no candidates")

        content = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        return LLMResponse(
            text=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=self.provider_name,
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Gemini free tier — returns $0.0 for budgeting purposes.

        If Gemini ever leaves the free tier, update the pricing table at
        the top of this file.
        """
        pricing = _GEMINI_PRICING_USD_PER_MTOK.get(
            self._model, {"input": 0.0, "output": 0.0}
        )
        return (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
