"""Shared-state tests for the Muse connector (HACKATHON-BUILT): Upstash path with a mocked REST
client, in-memory path, audit hash chain. No network, no real Redis.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from maudesignal.connector.store import (
    GENESIS,
    ConnectorState,
    SharedRateLimiter,
    UpstashClient,
    UpstashError,
    UpstashLedger,
    shared_store_configured,
    verify_chain,
)
from maudesignal.copilot.audit_export import verify_entries

URL = "https://example-test.upstash.io"
TOKEN = "AXtest-token-NOT-A-REAL-SECRET-0123456789"


class FakeRedis:
    """Just enough of Redis behind the Upstash REST shape (POST a JSON command)."""

    def __init__(self) -> None:
        self.kv: dict[str, Any] = {}
        self.lists: dict[str, list[str]] = {}
        self.calls: list[list[str]] = []
        self.auth_headers: list[str] = []
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auth_headers.append(request.headers.get("authorization", ""))
        if self.fail:
            return httpx.Response(500, json={"error": "boom " + TOKEN})
        cmd = json.loads(request.content)
        self.calls.append(cmd)
        return httpx.Response(200, json={"result": self.run(cmd)})

    def run(self, cmd: list[str]) -> Any:  # noqa: C901 - a command table
        op, args = cmd[0].upper(), cmd[1:]
        if op == "GET":
            return self.kv.get(args[0])
        if op == "SET":
            if "NX" in args and args[0] in self.kv:
                return None
            self.kv[args[0]] = args[1]
            return "OK"
        if op in {"INCR", "INCRBY"}:
            n = int(self.kv.get(args[0], 0)) + (int(args[1]) if op == "INCRBY" else 1)
            self.kv[args[0]] = str(n)
            return n
        if op == "INCRBYFLOAT":
            v = float(self.kv.get(args[0], 0)) + float(args[1])
            self.kv[args[0]] = repr(v)
            return repr(v)
        if op == "EXPIRE":
            return 1
        if op == "RPUSH":
            self.lists.setdefault(args[0], []).append(args[1])
            return len(self.lists[args[0]])
        if op == "LINDEX":
            rows = self.lists.get(args[0], [])
            return rows[int(args[1])] if rows else None
        if op == "LRANGE":
            rows = self.lists.get(args[0], [])
            start, stop = int(args[1]), int(args[2])
            return rows[start:] if stop == -1 else rows[start : stop + 1]
        if op == "LTRIM":
            rows = self.lists.get(args[0], [])
            self.lists[args[0]] = rows[int(args[1]) :]
            return "OK"
        if op == "EVAL":  # release the lock if the token matches
            key, token = args[2], args[3]
            if self.kv.get(key) == token:
                del self.kv[key]
                return 1
            return 0
        raise AssertionError(f"unexpected command {cmd[0]}")


def make_state(fake: FakeRedis, **kw: Any) -> ConnectorState:
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return ConnectorState(UpstashClient(URL, TOKEN, http=http), **kw)


def test_env_selects_the_backend() -> None:
    assert not shared_store_configured({})
    assert not shared_store_configured({"UPSTASH_REDIS_REST_URL": URL})
    assert not shared_store_configured(
        {"UPSTASH_REDIS_REST_URL": "http://insecure.example", "UPSTASH_REDIS_REST_TOKEN": TOKEN}
    )
    env = {"UPSTASH_REDIS_REST_URL": URL, "UPSTASH_REDIS_REST_TOKEN": TOKEN}
    assert shared_store_configured(env)
    assert ConnectorState.from_env(env).backend == "upstash_redis"
    assert ConnectorState.from_env({}).backend == "in_memory_per_instance"
    assert not ConnectorState.from_env({}).shared


def test_token_only_in_authorization_header_and_not_in_errors() -> None:
    fake = FakeRedis()
    state = make_state(fake)
    state.cache_set("k", "v", 60)
    assert state.cache_get("k") == "v"
    assert set(fake.auth_headers) == {f"Bearer {TOKEN}"}
    assert all(TOKEN not in json.dumps(c) for c in fake.calls)
    fake.fail = True
    client = UpstashClient(
        URL, TOKEN, http=httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    with pytest.raises(UpstashError) as exc:
        client.command("GET", "x")
    assert TOKEN not in str(exc.value) and "500" in str(exc.value)


def test_shared_rate_limiter_counts_in_redis_and_blocks() -> None:
    fake = FakeRedis()
    clock = [1000.0]
    lim = make_state(fake, wall=lambda: clock[0]).rate_limiter("tools", 3, 60)
    assert isinstance(lim, SharedRateLimiter)
    assert [lim.check("k")[0] for _ in range(4)] == [True, True, True, False]
    allowed, remaining, retry = lim.check("k")
    assert (allowed, remaining) == (False, 0) and 1 <= retry <= 60
    assert lim.blocked("k")[0] is True
    clock[0] += 61  # next window: a fresh counter
    assert lim.check("k") == (True, 2, 0)
    # a second server instance sees the same counters
    other = make_state(fake, wall=lambda: clock[0]).rate_limiter("tools", 3, 60)
    assert other.check("k") == (True, 1, 0)
    assert any(c[0] == "INCR" for c in fake.calls)


def test_rate_limiter_falls_back_to_memory_when_redis_is_down() -> None:
    fake = FakeRedis()
    fake.fail = True
    lim = make_state(fake).rate_limiter("tools", 2, 60)
    assert [lim.check("k")[0] for _ in range(3)] == [True, True, False]


def test_spend_ledger_is_shared_and_raises_when_redis_is_down() -> None:
    fake = FakeRedis()
    day = date(2026, 10, 29)
    a = UpstashLedger(make_state(fake)._client, "abc", today=lambda: day)  # type: ignore[arg-type]
    b = UpstashLedger(make_state(fake)._client, "abc", today=lambda: day)  # type: ignore[arg-type]
    assert a.spent_today() == 0.0
    assert a.add(0.25, 1) == 0.25
    assert b.add(0.5, 2) == 0.75
    assert a.spent_today() == 0.75
    other_day = UpstashLedger(make_state(fake)._client, "abc", today=lambda: date(2026, 10, 30))  # type: ignore[arg-type]
    assert other_day.spent_today() == 0.0
    fake.fail = True
    with pytest.raises(UpstashError):  # fail closed: no cap check means no live spend
        a.spent_today()


def test_cache_expires_in_memory_and_shared() -> None:
    clock = [0.0]
    mem = ConnectorState(wall=lambda: clock[0])
    mem.cache_set("a", "1", 10)
    assert mem.cache_get("a") == "1"
    clock[0] = 11
    assert mem.cache_get("a") is None
    fake = FakeRedis()
    shared = make_state(fake)
    shared.cache_set("a", "1", 10)
    assert shared.cache_get("a") == "1"
    assert ["SET", "maudesignal:connector:cache:a", "1", "EX", "10"] in fake.calls


def _append(state: ConnectorState, n: int) -> None:
    for i in range(n):
        state.audit_append(
            actor="connector:key:deadbeef",
            action="tool:recalls",
            entity_id="recalls",
            payload={"i": i},
        )


@pytest.mark.parametrize("shared", [False, True])
def test_audit_chain_is_hash_linked_and_verifies(shared: bool) -> None:
    fake = FakeRedis()
    state = make_state(fake) if shared else ConnectorState()
    _append(state, 5)
    rows = state.audit_recent(50)
    assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0]["prev_hash"] == GENESIS
    assert all(rows[i]["prev_hash"] == rows[i - 1]["entry_hash"] for i in range(1, 5))
    assert verify_chain(rows) == (True, None)
    assert verify_entries(rows) == (True, None)  # the copilot/audit_export verifier agrees
    assert verify_chain(rows[2:]) == (True, None)  # a tail verifies against its own prev_hash
    if shared:
        assert any(c[0] == "SET" and "NX" in c for c in fake.calls)  # the append took the lock
        assert not any(k.endswith("audit:lock") for k in fake.kv)  # and released it


def test_tampering_is_detected() -> None:
    state = ConnectorState()
    _append(state, 4)
    rows = state.audit_recent(10)
    rows[1]["payload_json"] = json.dumps({"i": 999})
    assert verify_chain(rows) == (False, 2)
    rows = state.audit_recent(10)
    rows[2]["prev_hash"] = "0" * 64
    assert verify_chain(rows)[0] is False


def test_audit_recent_limit_is_capped_and_oldest_first() -> None:
    state = ConnectorState()
    _append(state, 3)
    assert len(state.audit_recent(2)) == 2
    assert state.audit_recent(2)[-1]["seq"] == 3
    assert len(state.audit_recent(10_000)) == 3


def test_audit_append_raises_when_redis_is_down() -> None:
    fake = FakeRedis()
    state = make_state(fake)
    fake.fail = True
    with pytest.raises(UpstashError):
        _append(state, 1)


def test_audit_timestamps_are_naive_utc_like_the_database() -> None:
    state = ConnectorState(now=lambda: datetime(2026, 10, 29, 12, 0, tzinfo=UTC))
    _append(state, 1)
    assert state.audit_recent(1)[0]["ts"] == "2026-10-29T12:00:00"


class _FailIncrByFloat(FakeRedis):
    """Fails INCRBYFLOAT the first ``n`` times, then behaves."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self.remaining = n

    def handler(self, request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)[0].upper() == "INCRBYFLOAT" and self.remaining > 0:
            self.remaining -= 1
            return httpx.Response(500, json={"error": "boom " + TOKEN})
        return super().handler(request)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def critical(self, event: str, **kw: Any) -> None:
        self.events.append(("critical", event, kw))

    def warning(self, event: str, **kw: Any) -> None:
        self.events.append(("warning", event, kw))


def test_ledger_add_retries_a_failed_incrbyfloat_once() -> None:
    fake = _FailIncrByFloat(1)
    ledger = UpstashLedger(make_state(fake)._client, "abc", today=lambda: date(2026, 10, 29))  # type: ignore[arg-type]
    assert ledger.add(0.25, 1) == 0.25
    assert ledger.spent_today() == 0.25


def test_ledger_add_logs_critical_with_the_amount_when_redis_fails_after_the_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maudesignal.connector import store as store_mod

    rec = _Recorder()
    monkeypatch.setattr(store_mod, "logger", rec)
    fake = _FailIncrByFloat(2)
    ledger = UpstashLedger(make_state(fake)._client, "abc", today=lambda: date(2026, 10, 29))  # type: ignore[arg-type]
    with pytest.raises(UpstashError):
        ledger.add(0.125, 3)
    criticals = [e for e in rec.events if e[0] == "critical"]
    assert len(criticals) == 1
    _, event, kw = criticals[0]
    assert event == "connector_spend_not_recorded"
    assert kw["usd"] == 0.125 and kw["calls"] == 3 and kw["day"] == "2026-10-29"
    dumped = json.dumps(kw, default=str)
    assert TOKEN not in dumped and "abc" not in dumped


def test_per_key_ledger_has_no_hold_and_no_release() -> None:
    """The per-key total only counts real spend after a call; there is nothing to give back."""
    led = UpstashLedger(make_state(FakeRedis())._client, "abc", today=lambda: date(2026, 10, 29))  # type: ignore[arg-type]
    assert not hasattr(led, "reserve") and not hasattr(led, "release")
    led.add(0.04, 1)
    assert led.spent_today() == pytest.approx(0.04)


def test_rate_limit_bucket_and_time_left_use_one_clock_read() -> None:
    reads = iter([119.999, 120.001, 120.001])  # a second read would land in the next window
    lim = SharedRateLimiter(
        make_state(FakeRedis())._client,  # type: ignore[arg-type]
        "t",
        5,
        60,
        wall=lambda: next(reads),
    )
    key, left = lim._key("k")
    assert key.endswith(":1") and 0 < left <= 1.0
