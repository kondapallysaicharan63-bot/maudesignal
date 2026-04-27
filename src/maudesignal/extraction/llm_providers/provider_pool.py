"""Multi-key provider pool with rate-limit fallback.

Cycles through a configured order of (provider, key) slots. On a
rate-limit / quota / 429 error from the underlying SDK, marks the
current slot exhausted and rotates to the next. Drop-in replacement
for any single ``LLMProvider``.

Order is configured via ``PROVIDER_FALLBACK_ORDER``, e.g.
``gemini,gemini2,gemini3,groq,groq2``. Each token resolves to an env-var
key (``GEMINI_API_KEY``, ``GEMINI_API_KEY_2``, ...).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)

_LOGGER = logging.getLogger(__name__)


class PoolExhaustedError(MaudeSignalError):
    """Raised when every slot in the pool has hit a rate limit."""


class PoolConfigError(MaudeSignalError):
    """Raised when the pool cannot be constructed (bad order, missing keys)."""


_TOKEN_TO_ENV: dict[str, tuple[str, str]] = {
    # token -> (provider_name, env_var_for_key)
    "gemini": ("gemini", "GEMINI_API_KEY"),
    "gemini2": ("gemini", "GEMINI_API_KEY_2"),
    "gemini3": ("gemini", "GEMINI_API_KEY_3"),
    "groq": ("groq", "GROQ_API_KEY"),
    "groq2": ("groq", "GROQ_API_KEY_2"),
    "openai": ("openai", "OPENAI_API_KEY"),
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
}


_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
    "resource_exhausted",
    "resource exhausted",
    "too many requests",
)


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Return True if exc looks like a rate-limit / quota error.

    Walks the exception chain so wrapped provider errors are inspected.
    """
    cur: BaseException | None = exc
    seen = 0
    while cur is not None and seen < 5:
        text = str(cur).lower()
        if any(m in text for m in _RATE_LIMIT_MARKERS):
            return True
        # SDKs sometimes attach a status_code attribute.
        status = getattr(cur, "status_code", None) or getattr(cur, "status", None)
        if status == 429:
            return True
        cur = cur.__cause__ or cur.__context__
        seen += 1
    return False


def _mask_key(key: str) -> str:
    """Return a log-safe masked form of an API key."""
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


@dataclass
class _Slot:
    token: str
    provider_name: str
    api_key: str
    model: str
    exhausted: bool = False
    _instance: LLMProvider | None = None

    def get(self) -> LLMProvider:
        if self._instance is None:
            self._instance = _build_provider(self.provider_name, self.api_key, self.model)
        return self._instance


def _build_provider(name: str, api_key: str, model: str) -> LLMProvider:
    if name == "gemini":
        from maudesignal.extraction.llm_providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=api_key, model=model)
    if name == "groq":
        from maudesignal.extraction.llm_providers.groq_provider import GroqProvider

        return GroqProvider(api_key=api_key, model=model)
    if name == "openai":
        from maudesignal.extraction.llm_providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model)
    if name == "anthropic":
        from maudesignal.extraction.llm_providers.anthropic_provider import (
            AnthropicProvider,
        )

        return AnthropicProvider(api_key=api_key, model=model)
    raise PoolConfigError(f"Unknown provider in pool: {name!r}")


def _resolve_model(provider_name: str, models: dict[str, str]) -> str:
    return models.get(provider_name, "")


class ProviderPool(LLMProvider):
    """LLMProvider that rotates across multiple keys on rate-limit errors."""

    def __init__(self, slots: list[_Slot]) -> None:
        """Initialize with an explicit ordered slot list (use from_env for env-driven)."""
        if not slots:
            raise PoolConfigError("ProviderPool requires at least one slot")
        self._slots = slots
        self._idx = 0

    @classmethod
    def from_env(
        cls,
        *,
        order: str | None = None,
        models: dict[str, str] | None = None,
    ) -> ProviderPool:
        """Build pool from PROVIDER_FALLBACK_ORDER + env-var keys."""
        order_str = order if order is not None else os.environ.get("PROVIDER_FALLBACK_ORDER", "")
        tokens = [t.strip().lower() for t in order_str.split(",") if t.strip()]
        if not tokens:
            raise PoolConfigError(
                "PROVIDER_FALLBACK_ORDER is empty. Set it to a comma-separated "
                "list like 'gemini,gemini2,groq'."
            )

        models = models or {}
        slots: list[_Slot] = []
        skipped: list[str] = []
        for token in tokens:
            if token not in _TOKEN_TO_ENV:
                raise PoolConfigError(
                    f"Unknown token in PROVIDER_FALLBACK_ORDER: {token!r}. "
                    f"Valid: {sorted(_TOKEN_TO_ENV)}"
                )
            provider_name, env_var = _TOKEN_TO_ENV[token]
            key = os.environ.get(env_var, "").strip()
            if not key:
                skipped.append(f"{token}({env_var})")
                continue
            slots.append(
                _Slot(
                    token=token,
                    provider_name=provider_name,
                    api_key=key,
                    model=_resolve_model(provider_name, models),
                )
            )

        if skipped:
            _LOGGER.warning("Pool skipping slots with missing keys: %s", skipped)
        if not slots:
            raise PoolConfigError(
                "No usable slots in pool — every PROVIDER_FALLBACK_ORDER token "
                f"is missing its env-var key. Tokens tried: {tokens}"
            )
        return cls(slots)

    @property
    def provider_name(self) -> str:
        """Return literal 'pool' so audit logs distinguish pool calls."""
        return "pool"

    @property
    def model(self) -> str:
        """Return the active slot's model identifier."""
        return self._slots[self._idx].get().model

    def describe(self) -> dict[str, object]:
        """Return a log-safe summary of the pool state (masked keys)."""
        return {
            "provider": "pool",
            "active_slot": self._slots[self._idx].token,
            "active_provider": self._slots[self._idx].provider_name,
            "active_model": self.model,
            "slots": [
                {
                    "token": s.token,
                    "provider": s.provider_name,
                    "key": _mask_key(s.api_key),
                    "exhausted": s.exhausted,
                }
                for s in self._slots
            ],
        }

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Complete via the active slot, rotating on rate-limit errors."""
        attempts = 0
        last_exc: BaseException | None = None
        while attempts < len(self._slots):
            slot = self._slots[self._idx]
            if slot.exhausted:
                self._advance()
                attempts += 1
                continue
            try:
                return slot.get().complete(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as exc:
                last_exc = exc
                if _is_rate_limit_error(exc):
                    _LOGGER.warning(
                        "Pool slot rate-limited: token=%s provider=%s key=%s — rotating",
                        slot.token,
                        slot.provider_name,
                        _mask_key(slot.api_key),
                    )
                    slot.exhausted = True
                    self._advance()
                    attempts += 1
                    continue
                raise
        raise PoolExhaustedError(
            f"All {len(self._slots)} pool slots exhausted by rate limits. "
            f"Last error: {last_exc}"
        ) from last_exc

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Delegate cost estimation to the currently active slot's provider."""
        return self._slots[self._idx].get().estimate_cost_usd(input_tokens, output_tokens)

    def _advance(self) -> None:
        self._idx = (self._idx + 1) % len(self._slots)
