"""Tests for the multi-key ProviderPool fallback layer."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from maudesignal.extraction.llm_providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)
from maudesignal.extraction.llm_providers.provider_pool import (
    PoolConfigError,
    PoolExhaustedError,
    ProviderPool,
    _is_rate_limit_error,
    _mask_key,
    _Slot,
)


class _FakeProvider(LLMProvider):
    """In-memory provider for pool tests. Programmable failure modes."""

    def __init__(self, name: str = "fake", model: str = "fake-model") -> None:
        self._name = name
        self._model = model
        self.calls = 0
        self.behavior: list[str | Exception] = []  # FIFO of either response text or exception

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls += 1
        if not self.behavior:
            return LLMResponse(
                text="ok",
                model=self._model,
                input_tokens=1,
                output_tokens=1,
                provider=self._name,
            )
        next_action = self.behavior.pop(0)
        if isinstance(next_action, Exception):
            raise next_action
        return LLMResponse(
            text=next_action,
            model=self._model,
            input_tokens=1,
            output_tokens=1,
            provider=self._name,
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


def _slot(token: str, fake: _FakeProvider) -> _Slot:
    s = _Slot(
        token=token,
        provider_name=fake.provider_name,
        api_key=f"key_{token}",
        model=fake.model,
    )
    s._instance = fake
    return s


def _msgs() -> list[LLMMessage]:
    return [LLMMessage(role="user", content="hi")]


def test_first_slot_succeeds_no_rotation() -> None:
    a, b = _FakeProvider("a"), _FakeProvider("b")
    pool = ProviderPool([_slot("a", a), _slot("b", b)])
    pool.complete(system_prompt="sp", messages=_msgs())
    assert a.calls == 1 and b.calls == 0


def test_rotates_on_rate_limit_then_succeeds() -> None:
    a, b = _FakeProvider("a"), _FakeProvider("b")
    a.behavior = [RuntimeError("HTTP 429 quota exceeded")]
    pool = ProviderPool([_slot("a", a), _slot("b", b)])
    resp = pool.complete(system_prompt="sp", messages=_msgs())
    assert resp.provider == "b"
    assert a.calls == 1 and b.calls == 1
    # Slot a is now in backoff.
    assert pool._slots[0].in_backoff is True


def test_skips_already_exhausted_slot() -> None:
    a, b, c = _FakeProvider("a"), _FakeProvider("b"), _FakeProvider("c")
    sa, sb, sc = _slot("a", a), _slot("b", b), _slot("c", c)
    sa.exhausted_at = time.monotonic()  # put slot a in backoff
    pool = ProviderPool([sa, sb, sc])
    pool.complete(system_prompt="sp", messages=_msgs())
    assert a.calls == 0 and b.calls == 1 and c.calls == 0


def test_all_slots_exhausted_raises() -> None:
    a, b = _FakeProvider("a"), _FakeProvider("b")
    a.behavior = [RuntimeError("rate limit")]
    b.behavior = [RuntimeError("RESOURCE_EXHAUSTED")]
    pool = ProviderPool([_slot("a", a), _slot("b", b)])
    with (
        patch("maudesignal.extraction.llm_providers.provider_pool.time.sleep"),
        pytest.raises(PoolExhaustedError),
    ):
        pool.complete(system_prompt="sp", messages=_msgs())


def test_non_rate_limit_error_is_reraised_immediately() -> None:
    a, b = _FakeProvider("a"), _FakeProvider("b")
    a.behavior = [ValueError("schema mismatch")]
    pool = ProviderPool([_slot("a", a), _slot("b", b)])
    with pytest.raises(ValueError, match="schema mismatch"):
        pool.complete(system_prompt="sp", messages=_msgs())
    assert b.calls == 0
    assert pool._slots[0].in_backoff is False  # not marked exhausted on non-quota error


def test_is_rate_limit_error_detection() -> None:
    assert _is_rate_limit_error(RuntimeError("HTTP 429"))
    assert _is_rate_limit_error(RuntimeError("rate_limit hit"))
    assert _is_rate_limit_error(RuntimeError("RESOURCE_EXHAUSTED"))
    assert _is_rate_limit_error(RuntimeError("Quota exceeded"))
    assert not _is_rate_limit_error(RuntimeError("invalid api key"))
    assert not _is_rate_limit_error(ValueError("bad json"))


def test_mask_key_does_not_leak() -> None:
    masked = _mask_key("AIzaSyA1234567890XYZ")
    assert "1234567890" not in masked
    assert masked.startswith("AIza")
    assert masked.endswith("0XYZ")
    assert _mask_key("") == "<empty>"
    assert _mask_key("short") == "****"


def test_from_env_skips_missing_keys() -> None:
    env = {
        "PROVIDER_FALLBACK_ORDER": "gemini,gemini2,groq",
        "GEMINI_API_KEY": "AIzaXYZ" + "x" * 30,
        # GEMINI_API_KEY_2 missing
        "GROQ_API_KEY": "gsk_" + "x" * 50,
    }
    with patch.dict("os.environ", env, clear=True):
        pool = ProviderPool.from_env()
    tokens = [s.token for s in pool._slots]
    assert tokens == ["gemini", "groq"]  # gemini2 dropped, others kept in order


def test_from_env_rejects_unknown_token() -> None:
    env = {"PROVIDER_FALLBACK_ORDER": "gemini,bogus_provider", "GEMINI_API_KEY": "x" * 30}
    with (
        patch.dict("os.environ", env, clear=True),
        pytest.raises(PoolConfigError, match="Unknown token"),
    ):
        ProviderPool.from_env()


def test_from_env_no_usable_slots_raises() -> None:
    env = {"PROVIDER_FALLBACK_ORDER": "gemini,gemini2"}
    with (
        patch.dict("os.environ", env, clear=True),
        pytest.raises(PoolConfigError, match="No usable slots"),
    ):
        ProviderPool.from_env()
