"""Unit tests for the LLM provider abstraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.config import Config, ConfigError
from maudesignal.extraction.llm_providers import UnknownProviderError, get_provider


def _make_config(
    *,
    provider: str = "groq",
    groq_key: str | None = "gsk_fake_key_for_tests",
    anthropic_key: str | None = None,
    openai_key: str | None = None,
    gemini_key: str | None = None,
    provider_fallback_order: str = "gemini,groq",
) -> Config:
    """Construct a Config directly for tests, bypassing env loading."""
    return Config(
        llm_provider=provider,
        groq_api_key=groq_key,
        groq_model="llama-3.3-70b-versatile",
        anthropic_api_key=anthropic_key,
        claude_model_extraction="claude-sonnet-4-6",
        claude_model_reasoning="claude-opus-4-7",
        openai_api_key=openai_key,
        openai_model="gpt-4o-mini",
        gemini_api_key=gemini_key,
        gemini_model="gemini-2.5-flash",
        provider_fallback_order=provider_fallback_order,
        openfda_api_key=None,
        db_path=Path("/tmp/test.db"),
        log_level="INFO",
        cost_ceiling_usd=150.0,
        project_root=Path("/tmp"),
    )


def test_get_provider_groq_returns_groq() -> None:
    """When provider='groq' and key is set, factory returns GroqProvider."""
    config = _make_config(provider="groq", groq_key="gsk_fake")
    provider = get_provider(config)
    assert provider.provider_name == "groq"
    assert provider.model == "llama-3.3-70b-versatile"


def test_get_provider_anthropic_returns_anthropic() -> None:
    """When provider='anthropic' and key is set, factory returns AnthropicProvider."""
    config = _make_config(
        provider="anthropic",
        groq_key=None,
        anthropic_key="sk-ant-fake",
    )
    provider = get_provider(config)
    assert provider.provider_name == "anthropic"


def test_get_provider_openai_returns_openai() -> None:
    """When provider='openai' and key is set, factory returns OpenAIProvider."""
    config = _make_config(
        provider="openai",
        groq_key=None,
        openai_key="sk-fake-openai",
    )
    provider = get_provider(config)
    assert provider.provider_name == "openai"


def test_get_provider_missing_key_raises() -> None:
    """Picking a provider whose key is missing raises an actionable error."""
    config = _make_config(provider="anthropic", groq_key=None, anthropic_key=None)
    with pytest.raises(MaudeSignalError, match="ANTHROPIC_API_KEY"):
        get_provider(config)


def test_get_provider_unknown_raises() -> None:
    """Unknown provider string raises UnknownProviderError."""
    # Bypass Config's own validation to simulate misuse
    bad = _make_config()
    object.__setattr__(bad, "llm_provider", "wrong-vendor")
    with pytest.raises(UnknownProviderError):
        get_provider(bad)


def test_config_rejects_unknown_provider_at_load_time(monkeypatch) -> None:
    """Config.load() validates LLM_PROVIDER against supported values."""
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ConfigError, match="not supported"):
        Config.load()


def test_groq_cost_is_zero() -> None:
    """Groq free tier returns $0 cost estimate."""
    config = _make_config(provider="groq", groq_key="gsk_fake")
    provider = get_provider(config)
    assert provider.estimate_cost_usd(input_tokens=1000, output_tokens=500) == 0.0
