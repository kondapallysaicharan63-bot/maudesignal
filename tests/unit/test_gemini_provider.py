"""Unit tests for GeminiProvider — mocks the google-genai SDK."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from maudesignal.extraction.llm_providers.base import LLMMessage, LLMResponse
from maudesignal.extraction.llm_providers.gemini_provider import (
    GeminiProvider,
    GeminiProviderError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msgs(*texts: str) -> list[LLMMessage]:
    return [LLMMessage(role="user", content=t) for t in texts]


def _fake_response(text: str, input_tokens: int = 10, output_tokens: int = 20) -> MagicMock:
    """Build a minimal mock of a Gemini generate_content response."""
    candidate = MagicMock()
    resp = MagicMock()
    resp.candidates = [candidate]
    resp.text = text
    usage = SimpleNamespace(prompt_token_count=input_tokens, candidates_token_count=output_tokens)
    resp.usage_metadata = usage
    return resp


def _make_provider(model: str = "gemini-2.5-flash") -> tuple[GeminiProvider, MagicMock]:
    """Return (provider, mock_client) with genai SDK fully stubbed out."""
    mock_genai = MagicMock()
    mock_types = MagicMock()

    # types.Content and types.Part.from_text are called during complete()
    mock_types.Content.return_value = MagicMock()
    mock_types.Part.from_text.return_value = MagicMock()
    mock_types.GenerateContentConfig.return_value = MagicMock()
    mock_types.ThinkingConfig.return_value = MagicMock()

    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    modules = {
        "google": MagicMock(),
        "google.genai": mock_genai,
        "google.genai.types": mock_types,
    }
    with (
        patch.dict("sys.modules", modules),
        patch("maudesignal.extraction.llm_providers.gemini_provider.os") as mock_os,
    ):
        mock_os.environ.get.return_value = "AIza-fake-key"
        provider = GeminiProvider(api_key="AIza-fake-key", model=model)
        provider._client = mock_client
        provider._types = mock_types

    return provider, mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGeminiProviderInit:
    def test_missing_key_raises(self) -> None:
        mock_genai = MagicMock()
        mock_types = MagicMock()
        mock_genai.Client.return_value = MagicMock()
        modules = {
            "google": MagicMock(),
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        }
        with (
            patch.dict("sys.modules", modules),
            patch("maudesignal.extraction.llm_providers.gemini_provider.os") as mock_os,
        ):
            mock_os.environ.get.return_value = ""
            with pytest.raises(GeminiProviderError, match="GEMINI_API_KEY"):
                GeminiProvider(api_key=None)

    def test_provider_name_is_gemini(self) -> None:
        provider, _ = _make_provider()
        assert provider.provider_name == "gemini"

    def test_model_property(self) -> None:
        provider, _ = _make_provider(model="gemini-2.0-flash")
        assert provider.model == "gemini-2.0-flash"


class TestGeminiProviderComplete:
    def test_returns_llm_response(self) -> None:
        provider, mock_client = _make_provider()
        mock_client.models.generate_content.return_value = _fake_response('{"result": "ok"}')

        resp = provider.complete(system_prompt="You extract JSON.", messages=_msgs("test input"))

        assert isinstance(resp, LLMResponse)
        assert resp.text == '{"result": "ok"}'
        assert resp.provider == "gemini"
        assert resp.model == "gemini-2.5-flash"

    def test_token_counts_from_usage_metadata(self) -> None:
        provider, mock_client = _make_provider()
        mock_client.models.generate_content.return_value = _fake_response(
            "output", input_tokens=42, output_tokens=17
        )

        resp = provider.complete(system_prompt="sp", messages=_msgs("hi"))
        assert resp.input_tokens == 42
        assert resp.output_tokens == 17

    def test_no_candidates_raises(self) -> None:
        provider, mock_client = _make_provider()
        bad_resp = MagicMock()
        bad_resp.candidates = []
        bad_resp.text = None
        mock_client.models.generate_content.return_value = bad_resp

        with pytest.raises(GeminiProviderError, match="no candidates"):
            provider.complete(system_prompt="sp", messages=_msgs("hi"))

    def test_assistant_role_mapped_to_model(self) -> None:
        """Gemini uses 'model' not 'assistant' as the AI turn role."""
        provider, mock_client = _make_provider()
        mock_client.models.generate_content.return_value = _fake_response("{}")

        messages = [
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
        ]
        provider.complete(system_prompt="sp", messages=messages)

        # Check that Content was called with role="model" for the assistant turn.
        calls = provider._types.Content.call_args_list
        assert any("model" in str(c) for c in calls)

    def test_system_prompt_passed_as_system_instruction(self) -> None:
        provider, mock_client = _make_provider()
        mock_client.models.generate_content.return_value = _fake_response("{}")

        provider.complete(system_prompt="Extract JSON carefully.", messages=_msgs("data"))

        config_call = provider._types.GenerateContentConfig.call_args
        assert config_call is not None
        assert "Extract JSON carefully." in str(config_call)

    def test_temperature_zero_by_default(self) -> None:
        provider, mock_client = _make_provider()
        mock_client.models.generate_content.return_value = _fake_response("{}")

        provider.complete(system_prompt="sp", messages=_msgs("hi"))

        config_call = provider._types.GenerateContentConfig.call_args
        # temperature=0.0 must be passed
        assert "temperature=0.0" in str(config_call) or config_call.kwargs.get("temperature") == 0.0


class TestGeminiCostEstimate:
    def test_free_tier_returns_zero(self) -> None:
        provider, _ = _make_provider(model="gemini-2.5-flash")
        assert provider.estimate_cost_usd(input_tokens=100_000, output_tokens=50_000) == 0.0

    def test_unknown_model_defaults_to_zero(self) -> None:
        provider, _ = _make_provider(model="gemini-99-ultra")
        assert provider.estimate_cost_usd(1000, 1000) == 0.0


class TestGeminiViaFactory:
    def test_get_provider_gemini(self) -> None:
        """Factory returns GeminiProvider when llm_provider='gemini'."""
        from pathlib import Path

        from maudesignal.config import Config
        from maudesignal.extraction.llm_providers import get_provider

        mock_genai = MagicMock()
        mock_types = MagicMock()
        mock_genai.Client.return_value = MagicMock()
        modules = {
            "google": MagicMock(),
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        }

        config = Config(
            llm_provider="gemini",
            groq_api_key=None,
            groq_model="llama-3.3-70b-versatile",
            anthropic_api_key=None,
            claude_model_extraction="claude-sonnet-4-6",
            claude_model_reasoning="claude-opus-4-7",
            openai_api_key=None,
            openai_model="gpt-4o-mini",
            gemini_api_key="AIza-fake-key",
            gemini_model="gemini-2.5-flash",
            provider_fallback_order="gemini",
            openfda_api_key=None,
            db_path=Path("/tmp/test.db"),
            log_level="INFO",
            cost_ceiling_usd=150.0,
            project_root=Path("/tmp"),
        )

        with patch.dict("sys.modules", modules):
            provider = get_provider(config)

        assert provider.provider_name == "gemini"
