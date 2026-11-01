"""Integration-review fixes: slow research keeps the answer; the cache key has the day."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector import live as live_module  # noqa: E402
from maudesignal.connector import research  # noqa: E402
from maudesignal.connector.answer_cache import AnswerCache, cache_key  # noqa: E402
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from tests.unit.test_connector_live import Env  # noqa: E402
from tests.unit.test_research import FakeFetcher, FakeTransport  # noqa: E402


class SlowTransport(FakeTransport):
    """A research search that takes longer than the whole ask budget."""

    def post(self, body: dict[str, Any]) -> tuple[int, Any]:
        time.sleep(8.0)
        return super().post(body)


def test_slow_research_does_not_turn_a_finished_answer_into_a_504(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    monkeypatch.setenv(research.RESEARCH_ENV, "1")
    monkeypatch.setattr(live_module, "ASK_HARD_GRACE_S", 1.0)
    env = Env(tmp_path, config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_budget_s=4.0))
    transport = SlowTransport()
    env.backends.research_transport = lambda _t: transport
    env.backends.research_fetcher = lambda: FakeFetcher()
    started = time.monotonic()
    r = env.ask(research=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "live" and body["answer"]
    assert "research" not in body  # no research box, but the answer is there
    assert time.monotonic() - started < 7.5, "the answer did not wait for the slow search"


def test_cache_key_has_the_utc_day_and_old_keys_still_work() -> None:
    a = cache_key("live", "q a", "llz", "v1", "2026-11-01")
    b = cache_key("live", "q a", "llz", "v1", "2026-11-02")
    assert a != b
    assert cache_key("live", "q a", "llz", "v1") == cache_key("live", "q a", "llz", "v1", "")
    assert cache_key("live", "q a", None, "v1") != cache_key("live", "q a", None, "v2")


def test_a_cached_answer_is_not_reused_on_the_next_utc_day() -> None:
    clock = [datetime(2026, 11, 1, 23, 0, tzinfo=UTC)]
    cache = AnswerCache(ConnectorState(), "live", now=lambda: clock[0])
    assert cache.put("how many reports", "LLZ", {"answer": "x"})
    clock[0] += timedelta(minutes=30)  # same UTC day
    assert cache.get("how many reports", "LLZ") is not None
    clock[0] += timedelta(hours=1)  # 00:30 next day, still inside the 6 h TTL
    assert cache.get("how many reports", "LLZ") is None
