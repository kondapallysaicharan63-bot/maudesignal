"""The live ask keeps to its time budget and never throws away work it already has.

Regression for the live LLZ question "compare reports from Aug 25 to Aug 31, 2026 with the 4
weeks before, and what kinds of problems were reported?" (2026-11-02..04): model round 1
took ~9 s, model round 2 (after the tool results) died at the flat 25 s per-call timeout, and
the visitor saw "I have no verified answer to that question right now" (or a bare 504).

A fake provider plays Muse Spark on the backend's fake clock with set latencies, honours the
timeout each call is given (like the SDK: the call fails once it is reached) and records the
timeouts. No network, no model key, no real Meta API call.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector.ask import AgentFactory  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.errors import LiveTimeoutError  # noqa: E402
from maudesignal.connector.live import (  # noqa: E402
    CALL_TIMEOUT_S,
    DeadlineClient,
    LiveConfig,
    _DeadlineFirst,
    call_timeout_s,
)
from maudesignal.copilot import tools as copilot_tools  # noqa: E402
from maudesignal.copilot.agent import (  # noqa: E402
    END_MARGIN_S,
    MIN_REPAIR_S,
    CopilotAgent,
    RunStep,
    failure_kind,
)
from maudesignal.copilot.spend import SpendGuard  # noqa: E402
from maudesignal.copilot.tool_answer import sentences_from_tools, span_words  # noqa: E402
from tests.unit.test_connector import BAD, GOOD  # noqa: E402
from tests.unit.test_connector_live import ORIGIN, PATH_ASK, Env  # noqa: E402

BUDGET_S = 40.0
QUESTION = (
    "For LLZ, compare reports from Aug 25 to Aug 31, 2026 with the 4 weeks before, and what "
    "kinds of problems were reported?"
)
WEEK = {"product_code": "LLZ", "date_from": "20260825", "date_to": "20260831"}
BEFORE = {"product_code": "LLZ", "date_from": "20260728", "date_to": "20260824"}
GOOD_ANSWER = json.dumps({"sentences": [{"text": "LLZ had 33 reports from August 25 to "
                          "August 31, 2026.", "claims": [GOOD]}]})  # fmt: skip
MIXED_ANSWER = json.dumps(
    {
        "sentences": [
            {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [GOOD]},
            {"text": "LLZ had 99 reports from August 25 to August 31, 2026.", "claims": [BAD]},
        ]
    }
)
BAD_ANSWER = json.dumps(
    {"sentences": [{"text": "LLZ had 99 reports from August 25 to August 31, 2026.",
                    "claims": [BAD]}]}
)  # fmt: skip


@pytest.fixture(autouse=True)
def _per_instance_cap_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")


class APITimeoutError(Exception):
    """Same name as the SDK's timeout error (recognised by name, no SDK import)."""


def tool_round(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {"tool_calls": [(f"c{i}", name, json.dumps(args)) for i, (name, args) in
                           enumerate(calls)]}  # fmt: skip


def answer(content: str) -> dict[str, Any]:
    return {"content": content}


class TimedSpark:
    """Fake Muse Spark: each scripted reply takes ``latency_s`` of the fake clock.

    A call whose latency is above the timeout it was given advances the clock by that
    timeout and raises ``APITimeoutError``, as the real client does.
    """

    def __init__(self, env: Env, script: list[tuple[float, dict[str, Any]]]) -> None:
        self.env, self.script = env, list(script)
        self.timeouts: list[float | None] = []
        self.started_at: list[float] = []
        self.left_at_start: list[float] = []
        self.requests: list[dict[str, Any]] = []
        self._timeout: float | None = None
        self.deadline = 0.0

    @property
    def chat(self) -> Any:
        return SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, *, timeout: float, max_retries: int) -> TimedSpark:
        assert max_retries == 0
        self._timeout = timeout
        return self

    def create(self, **kwargs: Any) -> Any:
        clock = self.env.clock
        self.requests.append(kwargs)
        self.timeouts.append(self._timeout)
        self.started_at.append(clock.mono)
        self.left_at_start.append(self.deadline - clock.mono)
        assert kwargs["temperature"] == 0.0
        latency, reply = self.script.pop(0)
        if self._timeout is not None and latency > self._timeout:
            clock.advance(self._timeout)
            raise APITimeoutError("Request timed out.")
        clock.advance(latency)
        tool_calls = [
            SimpleNamespace(id=i, function=SimpleNamespace(name=n, arguments=a))
            for i, n, a in reply.get("tool_calls", [])
        ]
        msg = SimpleNamespace(content=reply.get("content", ""), tool_calls=tool_calls or None)
        return SimpleNamespace(
            model="muse-spark-1.3",
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=300),
        )


def timed_env(
    tmp_path: Path, script: list[tuple[float, dict[str, Any]]], budget_s: float = BUDGET_S
) -> tuple[Env, TimedSpark]:
    """The live route with the production client layers around the fake provider."""
    env = Env(tmp_path, config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_budget_s=budget_s))
    spark = TimedSpark(env, script)

    def agent_factory(deadline: float, clock: Any) -> AgentFactory:
        spark.deadline = deadline

        def factory(d: ConnectorData, guard: SpendGuard) -> CopilotAgent:
            inner = DeadlineClient(spark, deadline, clock)
            return CopilotAgent(
                _DeadlineFirst(guard.wrap(inner), deadline, clock), d.tool_context()
            )

        return factory

    env.backends.agent_factory = agent_factory
    return env, spark


def post(env: Env, question: str = QUESTION) -> Any:
    return env.client.post(PATH_ASK, json={"question": question}, headers={"Origin": ORIGIN})


def elapsed(env: Env) -> float:
    return env.clock.mono - 1000.0  # the fake clock starts at 1000 (tests.unit.test_connector_live)


def spoken(body: dict[str, Any]) -> list[str]:
    return [s["text"] for s in body["answer"]["speakable"] if s["links"]]


# --- per-call timeout -------------------------------------------------------------------


def test_per_call_timeout_shrinks_with_the_time_left() -> None:
    assert call_timeout_s(40.0) == CALL_TIMEOUT_S
    assert call_timeout_s(20.0) == pytest.approx(20.0 - END_MARGIN_S)
    assert call_timeout_s(5.0) == pytest.approx(5.0 - END_MARGIN_S)
    assert call_timeout_s(1.5) == 1.0  # never zero or negative
    assert all(
        call_timeout_s(a) >= call_timeout_s(b) for a, b in [(40, 30), (30, 20), (20, 10), (10, 4)]
    )


def test_each_call_gets_at_most_the_time_left_minus_the_margin(tmp_path: Path) -> None:
    env, spark = timed_env(
        tmp_path,
        [(9.0, tool_round(("product_summary", WEEK), ("product_summary", BEFORE))),
         (10.0, answer(MIXED_ANSWER)),
         (7.0, answer(GOOD_ANSWER))],  # fmt: skip
    )
    r = post(env)
    assert r.status_code == 200, r.text
    assert len(spark.timeouts) == 3
    for timeout, left in zip(spark.timeouts, spark.left_at_start, strict=True):
        assert timeout is not None and timeout <= max(1.0, left - END_MARGIN_S) + 1e-9
    assert spark.timeouts[0] == CALL_TIMEOUT_S  # 40 s left: the cap
    assert spark.timeouts[1] == CALL_TIMEOUT_S  # 31 s left: still the cap
    # the repair turn starts with 21 s left: the time left minus the margin, below the cap
    assert spark.timeouts[2] == pytest.approx(BUDGET_S - 19.0 - END_MARGIN_S)


# --- the reported failure ---------------------------------------------------------------


def test_slow_round_two_gives_a_gate_verified_partial_answer_not_no_verified_answer(
    tmp_path: Path,
) -> None:
    """The 2026-11-04 production trace: round 1 8.9 s, round 2 never returns."""
    env, spark = timed_env(
        tmp_path,
        [(8.9, tool_round(("product_summary", WEEK), ("product_summary", BEFORE),
                          ("search_reports", WEEK))),
         (60.0, answer(GOOD_ANSWER))],  # fmt: skip
    )
    r = post(env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "live"
    text = json.dumps(body["answer"])
    assert "no verified answer" not in text
    said = spoken(body)
    assert "LLZ had 33 reports received from August 25 to August 31, 2026." in said
    assert "LLZ had 35 reports received from July 28 to August 24, 2026." in said
    assert all(s["links"] for s in body["answer"]["speakable"])  # every spoken fact is linked
    # the deadline held: round 2 was given what was left minus the margin, not a flat 25 s
    assert spark.timeouts[1] == pytest.approx(min(CALL_TIMEOUT_S, BUDGET_S - 8.9 - END_MARGIN_S))
    assert elapsed(env) <= BUDGET_S - END_MARGIN_S + 1e-6
    assert len(spark.requests) == 2, "no model call after the failed round"
    # the trace says why
    first = body["trace"][0]
    assert first["status"] == "failed"
    assert "model round 1 8.9 s" in first["note"]
    assert "model round 2 timed out after 25.0 s" in first["note"]
    built = body["trace"][-1]
    assert built["step"] == "Answer built from tool results" and built["status"] == "ok"
    assert "model round 2 timed out after 25.0 s" in built["note"]


def test_gate_still_blocks_numbers_in_the_tool_result_answer(tmp_path: Path) -> None:
    """The tool-result sentences go through the same gate: a wrong count is never spoken."""
    from maudesignal.gate import verify_answer
    from maudesignal.gate.claims import CountClaim

    d = ConnectorData(work_dir=tmp_path / "w")
    ctx = d.tool_context()
    out = copilot_tools.call_tool(ctx, "product_summary", json.dumps(WEEK))
    built = sentences_from_tools([("product_summary", WEEK, out)])
    assert built and all(claims for _t, claims in built)
    forged = [
        ("LLZ had 34 reports received from August 25 to August 31, 2026.",
         [CountClaim("LLZ", 34, None, "20260825", "20260831")])
    ]  # fmt: skip
    report = verify_answer(built + forged, ctx.store)
    assert report.passed == len(built) and report.blocked == 1


def test_realistic_latencies_finish_well_inside_the_deadline(tmp_path: Path) -> None:
    """6-12 s per round: two tool rounds' worth of work, then a parsed draft (no extra call)."""
    env, spark = timed_env(
        tmp_path,
        [(8.0, tool_round(("product_summary", WEEK), ("product_summary", BEFORE))),
         (12.0, answer(MIXED_ANSWER)),  # the draft already is the answer JSON
         (9.0, answer(GOOD_ANSWER))],  # repair turn for the blocked sentence
    )  # fmt: skip
    r = post(env)
    assert r.status_code == 200 and r.json()["mode"] == "live"
    assert len(spark.requests) == 3  # round 1, round 2 (draft used), repair
    assert elapsed(env) == pytest.approx(29.0)
    assert elapsed(env) < BUDGET_S - 10


def test_repair_turn_is_skipped_when_it_cannot_finish(tmp_path: Path) -> None:
    env, spark = timed_env(
        tmp_path,
        [(12.0, tool_round(("product_summary", WEEK))),
         (21.0, answer(MIXED_ANSWER)),  # 7 s left: below MIN_REPAIR_S
         (9.0, answer(GOOD_ANSWER))],
    )  # fmt: skip
    r = post(env)
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "live"
    assert len(spark.requests) == 2, "the repair turn did not start"
    assert BUDGET_S - elapsed(env) < MIN_REPAIR_S
    assert spoken(body) == ["LLZ had 33 reports from August 25 to August 31, 2026."]
    assert len(body["answer"]["withheld"]) == 1  # the blocked sentence stays withheld
    note = body["trace"][0]["note"]
    assert "repair turn skipped: not enough time (7.0 s left)" in note


def test_failed_repair_turn_keeps_the_first_pass_gated_sentences(tmp_path: Path) -> None:
    env, spark = timed_env(
        tmp_path,
        [(6.0, tool_round(("product_summary", WEEK))),
         (6.0, answer(MIXED_ANSWER)),
         (60.0, answer(GOOD_ANSWER))],  # the repair call times out
    )  # fmt: skip
    r = post(env)
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "live"
    assert spoken(body) == ["LLZ had 33 reports from August 25 to August 31, 2026."]
    assert "repair turn timed out after" in body["trace"][0]["note"]
    assert elapsed(env) <= BUDGET_S - END_MARGIN_S + 1e-6


# --- the trace names the failed step ------------------------------------------------------


def test_round_one_timeout_without_tool_data_says_why_in_the_trace(tmp_path: Path) -> None:
    env, _spark = timed_env(tmp_path, [(60.0, answer(GOOD_ANSWER))])
    r = post(env)
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "recorded"
    note = body["trace"][0]["note"]
    assert body["trace"][0]["status"] == "failed"
    assert "Failed step: model round 1 timed out after 25.0 s" in note


def test_tool_error_is_named_in_the_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setitem(copilot_tools.TOOLS, "search_reports", broken)
    env, _spark = timed_env(
        tmp_path,
        [(5.0, tool_round(("search_reports", WEEK), ("product_summary", WEEK))),
         (5.0, answer(GOOD_ANSWER))],
    )  # fmt: skip
    body = post(env).json()
    assert body["mode"] == "live"
    tools_note = body["trace"][1]["note"]
    assert "search_reports: tool error (RuntimeError)" in tools_note
    assert "database is locked" not in json.dumps(body)  # never the exception text


def test_gate_blocked_all_is_named_and_tool_facts_are_shown(tmp_path: Path) -> None:
    env, _spark = timed_env(
        tmp_path,
        [(5.0, tool_round(("product_summary", WEEK))),
         (5.0, answer(BAD_ANSWER)),
         (5.0, answer(BAD_ANSWER))],  # the repair turn repeats the wrong number
    )  # fmt: skip
    body = post(env).json()
    assert body["mode"] == "live"
    assert "the claim gate blocked every sentence" in body["trace"][1]["note"]
    assert "LLZ had 33 reports received from August 25 to August 31, 2026." in spoken(body)
    assert "99" not in json.dumps(body["answer"])


def test_a_call_refused_at_the_deadline_is_a_504_that_says_why(tmp_path: Path) -> None:
    env = Env(tmp_path)

    class Refusing:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    def create(**_k: Any) -> Any:
        raise LiveTimeoutError("That question took too long.")

    Refusing.chat.completions.create = create

    def agent_factory(_deadline: float, _clock: Any) -> AgentFactory:
        return lambda d, guard: CopilotAgent(guard.wrap(Refusing()), d.tool_context())

    env.backends.agent_factory = agent_factory
    r = post(env)
    assert r.status_code == 504
    body = r.json()
    assert body["code"] == "live_timeout" and "answer" not in body and "trace" not in body
    assert body["why"] == "model round 1 not started: no time left"
    assert body["timeline"][0]["label"] == "model round 1"
    assert body["timeline"][0]["why"] == "not started: no time left"
    assert r.headers["access-control-allow-origin"] == ORIGIN


# --- small parts ----------------------------------------------------------------------------


def test_failure_kind_recognises_timeouts_by_type_and_never_uses_the_message() -> None:
    assert failure_kind(APITimeoutError("secret question text")) == "timeout"
    assert failure_kind(TimeoutError()) == "timeout"

    class APIStatusError(Exception):
        status_code = 500

    got = failure_kind(APIStatusError("secret question text"))
    assert got == "model error (APIStatusError, HTTP 500)" and "secret" not in got
    assert RunStep("model", "model round 2", 25300, "failed", "timeout").describe() == (
        "model round 2 timed out after 25.3 s"
    )


def test_span_words() -> None:
    assert span_words("20260825", "20260831") == "from August 25 to August 31, 2026"
    assert span_words("20251228", "20260103") == "from December 28, 2025 to January 3, 2026"
    assert span_words(None, "20260831") is None


def test_a_busy_instance_does_not_wait_past_the_point_an_answer_still_fits(tmp_path: Path) -> None:
    from maudesignal.connector.ask import AskRuntime, _acquire

    d = ConnectorData(work_dir=tmp_path / "w")
    now = [100.0]
    rt = AskRuntime(deadline=105.0, clock=lambda: now[0])  # 5 s left: not worth waiting
    assert _acquire(d, rt) is True  # free: taken at once
    assert _acquire(d, rt) is False  # held by the first ask: no wait, a clean timeout instead
    d.live_ask_lock.release()
