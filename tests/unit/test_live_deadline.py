"""The live ask must stop at its own deadline and fail with CORS headers (no network, no model).

Regression for the "The live service could not be reached" report: a browser shows that when
it gets a reply with no CORS headers or a dropped connection. Two server-side causes are
covered here: an unhandled exception (a bare 500 built outside the CORS middleware) and a
request that runs into the hosting platform's function limit instead of stopping first.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector import live as live_module  # noqa: E402
from maudesignal.connector.ask import AgentFactory  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.errors import LiveTimeoutError  # noqa: E402
from maudesignal.connector.live import (  # noqa: E402
    ASK_BUDGET_ENV,
    DEFAULT_ASK_BUDGET_S,
    DeadlineClient,
    LiveConfig,
)
from maudesignal.copilot.agent import CopilotAgent  # noqa: E402
from maudesignal.copilot.spend import SpendGuard  # noqa: E402
from tests.unit.test_connector_live import ORIGIN, PATH_ASK, QUESTION, Env  # noqa: E402


@pytest.fixture(autouse=True)
def _per_instance_cap_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")


class SlowSpark:
    """Each model call 'takes' ``step_s`` seconds of the fake clock."""

    def __init__(self, env: Env, step_s: float) -> None:
        self.env, self.step_s = env, step_s
        self.calls = 0
        self.inner = env.spark

    @property
    def chat(self) -> Any:
        return self

    @property
    def completions(self) -> Any:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.env.clock.advance(self.step_s)
        return self.inner._create(**kwargs)


def slow_env(tmp_path: Path, step_s: float) -> tuple[Env, SlowSpark]:
    env = Env(tmp_path)
    slow = SlowSpark(env, step_s)

    def agent_factory(deadline: float, clock: Any) -> AgentFactory:
        def factory(d: ConnectorData, guard: SpendGuard) -> CopilotAgent:
            return CopilotAgent(guard.wrap(DeadlineClient(slow, deadline, clock)), d.tool_context())

        return factory

    env.backends.agent_factory = agent_factory
    return env, slow


def post(env: Env) -> Any:
    return env.client.post(PATH_ASK, json={"question": QUESTION}, headers={"Origin": ORIGIN})


def test_deadline_stop_is_a_clean_504_with_cors_and_no_further_model_call(tmp_path: Path) -> None:
    env, slow = slow_env(tmp_path, step_s=45.0)  # the first call uses up the whole budget
    r = post(env)
    assert r.status_code == 504, r.text
    body = r.json()
    assert body["code"] == "live_timeout" and body["error"]["code"] == "live_timeout"
    assert "answer" not in body and "trace" not in body  # no model text
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert slow.calls == 1, "no model call may start after the deadline"


def test_a_fast_model_is_not_affected(tmp_path: Path) -> None:
    env, _slow = slow_env(tmp_path, step_s=0.5)
    r = post(env)
    assert r.status_code == 200 and r.json()["mode"] == "live"


def test_unexpected_error_still_carries_cors_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env(tmp_path)

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("shape the response builder did not expect")

    monkeypatch.setattr(live_module, "answer_block", boom)
    r = post(env)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "shape the response" not in r.text


def test_disallowed_origin_gets_no_cors_on_a_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env(tmp_path)
    monkeypatch.setattr(live_module, "answer_block", lambda *_a, **_k: 1 / 0)
    r = env.client.post(PATH_ASK, json={"question": QUESTION})  # no Origin header
    assert r.status_code == 500 and "access-control-allow-origin" not in r.headers


def test_budget_default_is_below_the_function_limit_and_configurable() -> None:
    assert DEFAULT_ASK_BUDGET_S <= 45.0
    assert LiveConfig.from_env({}).ask_budget_s == DEFAULT_ASK_BUDGET_S
    assert LiveConfig.from_env({ASK_BUDGET_ENV: "30"}).ask_budget_s == 30.0
    assert LiveConfig.from_env({ASK_BUDGET_ENV: "500"}).ask_budget_s <= 55.0  # clamped
    assert LiveConfig.from_env({ASK_BUDGET_ENV: "x"}).ask_budget_s == DEFAULT_ASK_BUDGET_S


def test_deadline_client_raises_live_timeout_before_calling() -> None:
    called: list[int] = []

    class Completions:
        def create(self, **_k: Any) -> Any:
            called.append(1)

    class Inner:
        chat = type("C", (), {"completions": Completions()})()

    t = [0.0]
    client = DeadlineClient(Inner(), 10.0, lambda: t[0])
    t[0] = 9.0
    with pytest.raises(LiveTimeoutError):
        client.create(model="m")
    assert called == []


# --- review follow-ups ------------------------------------------------------------------


def test_budget_clamp_leaves_room_below_the_function_limit() -> None:
    vercel = json.loads((Path(__file__).resolve().parents[2] / "vercel.json").read_text("utf-8"))
    max_duration = vercel["functions"]["api/index.py"]["maxDuration"]
    assert live_module.ASK_BUDGET_MAX_S + live_module.ASK_HARD_GRACE_S + 10 < max_duration
    assert live_module.VOICE_REQUEST_BUDGET_S + 10 < max_duration
    assert (
        LiveConfig.from_env({ASK_BUDGET_ENV: "9999"}).ask_budget_s == live_module.ASK_BUDGET_MAX_S
    )


def test_a_call_that_never_starts_leaves_no_hold() -> None:
    holds: list[int] = []

    class Guarded:  # stands in for guard.wrap(...): one hold per call that reaches it
        def __init__(self) -> None:
            self.chat = type("C", (), {"completions": self})()

        def create(self, **_k: Any) -> Any:
            holds.append(1)
            return "ok"

    t = [0.0]
    client = live_module._DeadlineFirst(Guarded(), 10.0, lambda: t[0])
    assert client.chat.completions.create(model="m") == "ok" and holds == [1]
    t[0] = 8.5  # under MIN_CALL_BUDGET_S left
    with pytest.raises(LiveTimeoutError):
        client.chat.completions.create(model="m")
    assert holds == [1], "the refused call reserved nothing"


def test_inner_check_is_looser_than_the_outer_one() -> None:
    called: list[int] = []

    class Completions:
        def create(self, **_k: Any) -> Any:
            called.append(1)
            return "ok"

    class Inner:
        chat = type("C", (), {"completions": Completions()})()

    t = [0.0]
    inner = DeadlineClient(Inner(), 10.0, lambda: t[0])
    t[0] = 7.5  # left 2.5: the outer layer would refuse, the inner one must not
    assert inner.create(model="m") == "ok"


def test_a_blocked_ask_thread_still_gets_a_504_with_cors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_module, "ASK_HARD_GRACE_S", 0.1)
    env = Env(tmp_path, config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_budget_s=0.2))

    # the fake clock never moves, so the deadline check passes and the thread blocks
    env.backends.agent_factory = lambda _d, _c: (lambda _data, _guard: _Blocking())  # type: ignore[assignment,return-value]
    r = post(env)
    assert r.status_code == 504 and r.json()["code"] == "live_timeout"
    assert r.headers["access-control-allow-origin"] == ORIGIN


class _Blocking:
    """An agent whose ask() blocks the worker thread."""

    def __init__(self) -> None:
        self._client = object()
        self.context = type("X", (), {"created_capas": []})()

    def ask(self, _q: str) -> Any:
        time.sleep(1.0)


def test_public_route_500_carries_cors(tmp_path: Path) -> None:
    from maudesignal.connector.store import ConnectorState

    class BrokenState(ConnectorState):
        def cache_get(self, key: str) -> Any:
            raise RuntimeError("the cache exploded")

    env = Env(tmp_path, state=BrokenState())
    r = env.client.get("/v1/public/check_device_type?product_code=LLZ", headers={"Origin": ORIGIN})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_exc_where_names_our_frame_and_never_the_message() -> None:
    from maudesignal.connector.errors import exc_where

    try:
        DeadlineClient(object(), 0.0, lambda: 5.0).create(model="m")
    except LiveTimeoutError as exc:
        got = exc_where(exc)
    assert got["error_type"] == "LiveTimeoutError"
    assert str(got["where"]).startswith("connector/live.py:")
    assert "took too long" not in str(got)
