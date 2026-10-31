"""Tier 3 of the chat (HACKATHON-BUILT): the six-hour answer cache. Offline.

Hit within six hours, miss after, the same entry for spelling variants of one question, a
different entry per product code, no question text stored, and any store error is a miss.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from maudesignal.connector.answer_cache import TTL_SECONDS, AnswerCache, cache_key
from maudesignal.connector.store import ConnectorState
from tests.unit.test_connector_store import FakeRedis, make_state

T0 = datetime(2026, 10, 31, 9, 0, 0, tzinfo=UTC)
BODY = {"answer": {"speakable": [{"text": "LLZ had 33 reports.", "links": []}]}, "mode": "live"}


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def make(state: ConnectorState | None = None) -> tuple[AnswerCache, Clock, ConnectorState]:
    clock = Clock()
    st = state or ConnectorState(wall=lambda: (clock.now - T0).total_seconds() + 1e9)
    return AnswerCache(st, "live", now=clock), clock, st


def test_hit_within_six_hours_and_miss_after() -> None:
    cache, clock, _ = make()
    assert cache.get("Why did LLZ increase?") is None
    assert cache.put("Why did LLZ increase?", None, BODY)
    clock.now = T0 + timedelta(hours=5, minutes=59)
    hit = cache.get("Why did LLZ increase?")
    assert hit is not None and hit.body == BODY and hit.stored_at_iso == "2026-10-31T09:00:00Z"
    clock.now = T0 + timedelta(hours=6, minutes=1)
    assert cache.get("Why did LLZ increase?") is None


def test_the_store_ttl_is_six_hours() -> None:
    fake = FakeRedis()
    cache, _clock, _ = make(make_state(fake))
    cache.put("q one two", None, BODY)
    sets = [c for c in fake.calls if c[0] == "SET"]
    assert sets and sets[-1][-2:] == ["EX", str(TTL_SECONDS)] and TTL_SECONDS == 6 * 3600
    assert cache.get("Q one, two!") is not None  # shared through Redis


def test_normalised_question_shares_one_entry() -> None:
    cache, _clock, _ = make()
    cache.put("Why did LLZ reports increase this week?", None, BODY)
    for variant in (
        "why did llz reports increase this week",
        "  Why did LLZ reports increase this week!!",
    ):
        assert cache.get(variant) is not None, variant
    assert cache.get("Why did QIH reports increase this week?") is None


def test_product_code_and_namespace_are_part_of_the_key() -> None:
    cache, _clock, st = make()
    cache.put("What should we look at first?", "LLZ", BODY)
    assert cache.get("What should we look at first?", "LLZ") is not None
    assert cache.get("What should we look at first?", "QIH") is None
    assert cache.get("What should we look at first?") is None
    assert AnswerCache(st, "tool").get("What should we look at first?", "LLZ") is None
    assert cache_key("live", "a b", "llz") == cache_key("live", "A B!", "LLZ")


def test_no_question_text_is_stored() -> None:
    fake = FakeRedis()
    cache, _clock, _ = make(make_state(fake))
    cache.put("Why did the Acme scanner reports increase?", None, BODY)
    dumped = json.dumps(fake.kv)
    assert "Acme" not in dumped and "scanner" not in dumped


class Broken(ConnectorState):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def cache_get(self, key: str) -> str | None:
        if self.mode == "raise":
            raise RuntimeError("store down")
        if self.mode == "garbage":
            return "{not json"
        if self.mode == "shape":
            return json.dumps({"stored_at": T0.isoformat(), "body": ["not", "a", "dict"]})
        return json.dumps({"stored_at": "yesterday", "body": BODY})

    def cache_set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise RuntimeError("store down")


def test_every_store_error_is_a_miss_never_a_failure() -> None:
    for mode in ("raise", "garbage", "shape", "bad-date"):
        cache = AnswerCache(Broken(mode), "live", now=lambda: T0)
        assert cache.get("anything at all") is None, mode
    assert AnswerCache(Broken("raise"), "live", now=lambda: T0).put("q", None, BODY) is False


def test_redis_failure_falls_back_to_memory() -> None:
    fake = FakeRedis()
    fake.fail = True
    cache, _clock, _ = make(make_state(fake))
    assert cache.put("q one", None, BODY)  # ConnectorState falls back to its memory
    hit: Any = cache.get("q one")
    assert hit is not None


def test_an_entry_from_the_future_is_ignored() -> None:
    cache, clock, _ = make()
    clock.now = T0 + timedelta(hours=1)
    cache.put("q", None, BODY)
    clock.now = T0
    assert cache.get("q") is None
