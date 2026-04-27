"""Configuration loading for MaudeSignal.

All configuration comes from environment variables (or a local .env file).
This module is the single source of truth — no other module should call
os.environ directly.

Per NFR-07 (Doc 3 §4.3): API keys are loaded from env vars only, never
hardcoded, never logged, never committed.

MaudeSignal is provider-agnostic (Doc 5 D4): the ``LLM_PROVIDER`` env var
selects between Groq (default, free), Anthropic (Claude), OpenAI (GPT),
or Gemini (Google, free tier).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


_SUPPORTED_PROVIDERS = {"groq", "anthropic", "openai", "gemini"}


@dataclass(frozen=True)
class Config:
    """Immutable project configuration."""

    llm_provider: str

    # Groq
    groq_api_key: str | None
    groq_model: str

    # Anthropic
    anthropic_api_key: str | None
    claude_model_extraction: str
    claude_model_reasoning: str

    # OpenAI
    openai_api_key: str | None
    openai_model: str

    # Gemini (Google)
    gemini_api_key: str | None
    gemini_model: str

    # Data & ops
    openfda_api_key: str | None
    db_path: Path
    log_level: str
    cost_ceiling_usd: float
    project_root: Path

    @classmethod
    def load(cls) -> Config:
        """Load configuration from environment variables.

        Raises:
            ConfigError: If the selected provider's API key is missing.
        """
        provider = os.environ.get("LLM_PROVIDER", "groq").lower().strip()
        if provider not in _SUPPORTED_PROVIDERS:
            raise ConfigError(
                f"LLM_PROVIDER={provider!r} is not supported. "
                f"Choose one of: {sorted(_SUPPORTED_PROVIDERS)}"
            )

        groq_api_key = os.environ.get("GROQ_API_KEY", "").strip() or None
        groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
        if anthropic_api_key and anthropic_api_key.startswith("sk-ant-api03-REPLACE"):
            anthropic_api_key = None

        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None

        gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip() or None

        provider_keys = {
            "groq": groq_api_key,
            "anthropic": anthropic_api_key,
            "openai": openai_api_key,
            "gemini": gemini_api_key,
        }
        if not provider_keys[provider]:
            env_name = {
                "groq": "GROQ_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }[provider]
            signup_url = {
                "groq": "https://console.groq.com",
                "anthropic": "https://console.anthropic.com",
                "openai": "https://platform.openai.com",
                "gemini": "https://aistudio.google.com/apikey",
            }[provider]
            raise ConfigError(
                f"LLM_PROVIDER={provider} but {env_name} is missing. "
                f"Sign up at {signup_url} and add the key to .env"
            )

        openfda_api_key = os.environ.get("OPENFDA_API_KEY", "").strip() or None

        db_path_str = os.environ.get("MAUDESIGNAL_DB_PATH", "data/maudesignal.db")
        db_path = (_PROJECT_ROOT / db_path_str).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cost_ceiling = float(os.environ.get("MAUDESIGNAL_COST_CEILING_USD", "150.0"))
        except ValueError as exc:
            raise ConfigError("MAUDESIGNAL_COST_CEILING_USD must be a number") from exc

        return cls(
            llm_provider=provider,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            anthropic_api_key=anthropic_api_key,
            claude_model_extraction=os.environ.get("CLAUDE_MODEL_EXTRACTION", "claude-sonnet-4-6"),
            claude_model_reasoning=os.environ.get("CLAUDE_MODEL_REASONING", "claude-opus-4-7"),
            openai_api_key=openai_api_key,
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            gemini_api_key=gemini_api_key,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            openfda_api_key=openfda_api_key,
            db_path=db_path,
            log_level=os.environ.get("MAUDESIGNAL_LOG_LEVEL", "INFO").upper(),
            cost_ceiling_usd=cost_ceiling,
            project_root=_PROJECT_ROOT,
        )

    def masked_summary(self) -> dict[str, str]:
        """Return a safe-to-log summary of config (NFR-08)."""
        return {
            "llm_provider": self.llm_provider,
            "groq_api_key": _mask_secret(self.groq_api_key),
            "groq_model": self.groq_model,
            "anthropic_api_key": _mask_secret(self.anthropic_api_key),
            "claude_model_extraction": self.claude_model_extraction,
            "openai_api_key": _mask_secret(self.openai_api_key),
            "openai_model": self.openai_model,
            "gemini_api_key": _mask_secret(self.gemini_api_key),
            "gemini_model": self.gemini_model,
            "openfda_api_key": _mask_secret(self.openfda_api_key),
            "db_path": str(self.db_path),
            "log_level": self.log_level,
            "cost_ceiling_usd": f"${self.cost_ceiling_usd:.2f}",
        }


def _mask_secret(value: str | None) -> str:
    """Return a masked representation safe for logging (NFR-08)."""
    if not value:
        return "<not set>"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
