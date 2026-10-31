"""Chat tiers on the real routes (HACKATHON-BUILT): POST /v1/live/ask, REST ask and MCP ask.

No network and no model key: Muse Spark is a scripted fake that records every request. Checks:
each tier declares itself and its cost; tiers 1 to 3 make no model call, reserve nothing in the
per-call spend ledger and use none of the visitor's daily live questions; tier 4 still does all
of that exactly as before, with the cheaper settings (compact Skill prompt, low reasoning
effort, two tool rounds); the cache answers the same question at $0 for six hours.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import (  # noqa: E402
    LEAN_MAX_TOKENS,
    LEAN_MAX_TOKENS_COMPARE,
    apply_lean,
    is_comparison,
)
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from maudesignal.copilot.agent import CopilotAgent, split_prompts  # noqa: E402
from tests.unit.test_call_ledger import FakeBlobStore, count  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_live import ORIGIN, Env  # noqa: E402
from tests.unit.test_connector_safety import LLZ_33, OneAnswerClient, live_rt  # noqa: E402


@pytest.fixture(autouse=True)
def _per_instance_cap_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")


OPEN = "Which kinds of problems do the LLZ reports describe?"
H = {"X-API-Key": KEY}


def env(tmp_path: Path, **kw: Any) -> Env:
    kw.setdefault("config", LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_per_day=2))
    kw.setdefault("store", FakeBlobStore())  # the private store that holds the spend ledger
    return Env(tmp_path, tiers=True, **kw)


def ledger_files(e: Env) -> int:
    """Entries in the per-call spend ledger (callcap) of this app."""
    return count(e.store)


# --- website chat ------------------------------------------------------------------------------


@pytest.mark.parametrize("q", ["hi", "namaste", "నమస్కారం", "kaise ho", "thanks", "who are you?"])
def test_greeting_is_canned_free_and_uses_no_limit(tmp_path: Path, q: str) -> None:
    e = env(tmp_path)
    before = ledger_files(e)
    for _ in range(3):  # more than the daily limit of 2
        r = e.ask(q)
        assert r.status_code == 200, r.text
        b = r.json()
        assert (b["tier"], b["mode"], b["cost_usd"]) == ("canned", "canned", 0.0)
        assert b["badge"] == "No FDA facts in this message"
        assert len(b["suggestions"]) == 4
        assert b["limits"]["remaining_today"] == 2  # not used
        assert b["trace"] and all(s["model"] is None for s in b["trace"])
        assert b["answer"]["withheld"] == []
    assert e.spark.requests == [] and ledger_files(e) == before
    assert forbidden_in(json.dumps(b)) == []


def test_medical_advice_request_gets_the_fixed_reply(tmp_path: Path) -> None:
    b = env(tmp_path).ask("Should I stop using my insulin pump?").json()
    assert b["tier"] == "canned"
    assert b["answer"]["speakable"][0]["text"] == (
        "I can't give medical advice — please ask a clinician."
    )


def test_direct_lookup_is_gated_linked_free_and_uses_no_limit(tmp_path: Path) -> None:
    e = env(tmp_path)
    for _ in range(3):
        b = e.ask("What changed this week for LLZ?").json()
        assert (b["tier"], b["mode"], b["cost_usd"]) == ("direct", "direct", 0.0)
        assert b["badge"] == "Direct FDA lookup — no AI"
        assert b["limits"]["remaining_today"] == 2
    first = b["answer"]["speakable"][0]
    assert "33 reports received" in first["text"] and "8.75" in first["text"]
    assert first["links"] and all(lk["url"].startswith("https://") for lk in first["links"])
    assert [s["step"] for s in b["trace"]] == [
        "Direct lookup: what_changed_this_week",
        "Claim gate",
    ]
    assert e.spark.requests == []


def test_did_you_mean_and_open_page(tmp_path: Path) -> None:
    b = env(tmp_path).ask("what changed for LLX").json()
    assert b["tier"] == "direct" and b["did_you_mean"] == ["LLZ"]
    assert b["open"] == {"view": "check-device", "code": "LLX"}
    assert b["suggestions"] == ["What changed this week for LLZ?"]


def test_open_question_reaches_muse_spark_with_lean_settings(tmp_path: Path) -> None:
    e = env(tmp_path)
    r = e.ask(OPEN)
    b = r.json()
    assert b["tier"] == "live" and b["mode"] == "live"
    assert b["limits"]["remaining_today"] == 1  # one daily live question used
    assert e.spark.requests, "the model was called"
    req = e.spark.requests[0]
    assert req["reasoning_effort"] == "low"
    assert req["max_tokens"] == LEAN_MAX_TOKENS
    assert req["temperature"] == 0.0
    system = req["messages"][0]["content"]
    _full, compact = split_prompts(
        (Path(__file__).resolve().parents[2] / "skills/safety-copilot/SKILL.md").read_text()
    )
    assert system == compact and len(system) < 2500
    assert isinstance(b["cost_usd"], float) and b["cost_usd"] > 0
    assert ledger_files(e) >= 1  # the per-call ledger was used for the model call


def test_comparison_uses_medium_effort(tmp_path: Path) -> None:
    e = env(tmp_path)
    e.ask("Compare LLZ and QIH this week")
    assert e.spark.requests[0]["reasoning_effort"] == "medium"
    assert e.spark.requests[0]["max_tokens"] == LEAN_MAX_TOKENS_COMPARE
    assert is_comparison("LLZ vs QIH") and not is_comparison("Why did LLZ increase?")


def test_same_question_within_six_hours_is_cached_free_and_uses_no_limit(tmp_path: Path) -> None:
    e = env(tmp_path)
    first = e.ask(OPEN).json()
    calls = len(e.spark.requests)
    ledger = ledger_files(e)
    again = e.ask("which kinds of problems do the LLZ reports describe").json()
    assert (again["tier"], again["cost_usd"], again["badge"]) == (
        "cache",
        0.0,
        "Answered earlier today",
    )
    assert again["answer"] == first["answer"]
    assert again["limits"]["remaining_today"] == 1  # still one left: the hit used none
    assert len(e.spark.requests) == calls and ledger_files(e) == ledger
    e.clock.now += timedelta(hours=6, minutes=5)  # later the same day: the entry is too old
    later = e.ask(OPEN).json()
    assert later["tier"] == "live" and len(e.spark.requests) > calls


def test_recorded_answers_are_not_cached(tmp_path: Path) -> None:
    e = env(tmp_path, live=False)
    assert e.ask(OPEN).json()["mode"] == "recorded"
    assert e.ask(OPEN).json()["tier"] == "live"  # asked again: still not a cache hit


def test_follow_up_with_history_goes_to_muse_spark(tmp_path: Path) -> None:
    e = env(tmp_path)
    hist = [{"question": "What changed this week for LLZ?", "answer": "LLZ had 33 reports."}]
    b = e.ask("Which were not filed by the manufacturer?", history=hist).json()
    assert b["tier"] == "live" and e.spark.requests


def test_daily_limit_still_applies_to_tier_four_only(tmp_path: Path) -> None:
    e = env(tmp_path)
    assert e.ask("Why did LLZ reports increase?").status_code == 200
    assert e.ask("Why did QIH reports stay flat?").status_code == 200
    assert e.ask("Why did MYN reports stay flat?").status_code == 429
    assert e.ask("hello").status_code == 200  # tiers 1 and 2 still answer
    assert e.ask("Recalls for QIH").json()["tier"] == "direct"


def test_patient_data_is_refused_before_any_tier(tmp_path: Path) -> None:
    r = env(tmp_path).ask("hi, Mrs. Jane Smith age 67 had a problem")
    assert r.status_code == 422


def test_tiers_can_be_switched_off(tmp_path: Path) -> None:
    e = Env(tmp_path)  # tiers off: every question goes to Muse Spark as before
    assert e.ask("What changed this week for LLZ?").json()["tier"] == "live"
    assert e.spark.requests


# --- connector ask (REST and MCP) ------------------------------------------------------


def connector(tmp_path: Path, client: Any, *, tiers: bool = True) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(100),
        data=ConnectorData(work_dir=tmp_path / "w"),
        ask_runtime=live_rt(tmp_path, client),
        live_checker=fake_check,
        state=ConnectorState(),
        feedback_store=MemoryStore(),
        web_origins=(ORIGIN,),
        chat_tiers=tiers,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


class Counting(OneAnswerClient):
    def __init__(self, sentences: list[dict[str, Any]]) -> None:
        super().__init__(sentences)
        self.calls = 0
        inner = self.chat.completions.create

        def create(**kw: Any) -> Any:
            self.calls += 1
            return inner(**kw)

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


LIVE_SENTENCES = [
    {"text": "Here is what I found.", "claims": []},
    {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [LLZ_33]},
]


def test_rest_ask_tiers(tmp_path: Path) -> None:
    model = Counting(LIVE_SENTENCES)
    c = connector(tmp_path, model)
    hello = c.post("/v1/tools/ask", json={"question": "hello"}, headers=H).json()
    assert (hello["tier"], hello["cost_usd"], hello["provenance"]["kind"]) == (
        "canned",
        0.0,
        "canned_reply",
    )
    direct = c.post("/v1/tools/ask", json={"question": "Recalls for QIH"}, headers=H).json()
    assert direct["tier"] == "direct" and direct["facts"] and direct["cost_usd"] == 0.0
    assert model.calls == 0
    live = c.post("/v1/tools/ask", json={"question": OPEN}, headers=H).json()
    assert live["tier"] == "live" and live["provenance"]["kind"] == "live_model"
    assert model.calls > 0 and live["cost_usd"] > 0
    # the connective "Here is what I found." is neither spoken nor listed as held back
    assert "Here is what I found" not in live["speakable"] and live["withheld"] == []
    calls = model.calls
    cached = c.post("/v1/tools/ask", json={"question": OPEN}, headers=H).json()
    assert cached["tier"] == "cache" and cached["cost_usd"] == 0.0 and model.calls == calls
    assert cached["speakable"] == live["speakable"]


def test_mcp_ask_declares_its_tier(tmp_path: Path) -> None:
    c = connector(tmp_path, Counting(LIVE_SENTENCES))
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ask", "arguments": {"question": "Who filed MYN reports?"}},
    }
    out = c.post("/mcp", json=body, headers=H).json()["result"]
    assert out["isError"] is False
    assert out["structuredContent"]["tier"] == "direct"
    assert out["structuredContent"]["badge"] == "Direct FDA lookup — no AI"


# --- lean agent settings ---------------------------------------------------------------


class ToolThenAnswer:
    """Calls a tool every round it is offered tools; answers when asked without tools."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.requests.append(kw)
        if kw.get("tools"):
            call = SimpleNamespace(
                id=f"c{len(self.requests)}",
                function=SimpleNamespace(name="search_reports", arguments='{"product_code":"LLZ"}'),
            )
            msg = SimpleNamespace(content="", tool_calls=[call])
        else:
            text = json.dumps({"sentences": [{"text": "LLZ had 34 reports.", "claims": []}]})
            msg = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def test_lean_agent_two_tool_rounds_cut_tool_results_and_repairs_without_tools(
    tmp_path: Path,
) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = ToolThenAnswer()
    agent = CopilotAgent(client, d.tool_context())
    apply_lean(agent, "Why did LLZ increase?")
    res = agent.ask("Why did LLZ increase?")
    with_tools = [r for r in client.requests if r.get("tools")]
    assert len(with_tools) == 2  # at most two tool rounds
    tool_msgs = [m for m in client.requests[-1]["messages"] if m["role"] == "tool"]
    assert tool_msgs and all(len(m["content"]) <= 6000 + 60 for m in tool_msgs)
    # the untagged "34 reports" was blocked, so one repair ran, and it offered no tools
    assert res.repaired
    assert not client.requests[-1].get("tools")
    assert all(r["reasoning_effort"] == "low" for r in client.requests)


def test_no_repair_when_nothing_was_blocked(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = OneAnswerClient([{"text": "A person reviews this.", "claims": []}])
    agent = CopilotAgent(client, d.tool_context())
    apply_lean(agent, "anything")
    assert agent.ask("anything").repaired is False


def test_full_prompt_for_other_callers_has_no_compact_block() -> None:
    text = (Path(__file__).resolve().parents[2] / "skills/safety-copilot/SKILL.md").read_text()
    full, compact = split_prompts(text)
    assert compact and compact not in full and "live-compact-prompt" not in full
    assert "## Hard rules" in full and len(compact) < len(full) / 3
    assert split_prompts("no markers") == ("no markers", None)
