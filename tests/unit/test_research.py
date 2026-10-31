"""Research mode (connector/research.py and its live routes). Offline: fake transport."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector import research  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.callcap import MAX_CALL_HOLD_USD, CallLedger  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.store import verify_chain  # noqa: E402
from tests.unit.test_connector_live import Env  # noqa: E402

EXACT_LABEL = "Web research — not FDA records, not verified by the gate"
INSTR = "test instructions"
DAY = date(2026, 10, 30)


def ok_reply(n_sources: int = 2, *, searches: int = 2) -> dict[str, Any]:
    """A Responses API reply with url citations, search sources and usage."""
    calls = [
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": f"q{i}",
                "sources": [
                    {"type": "url", "url": f"https://news.example.com/{i}-{j}", "title": f"N{j}"}
                    for j in range(n_sources)
                ],
            },
        }
        for i in range(searches)
    ]
    message = {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": "FDA safety communication - https://www.fda.gov/ct - date not shown",
                "annotations": [
                    {
                        "type": "url_citation",
                        "url": "https://www.fda.gov/ct",
                        "title": "CT safety communication",
                        "start_index": 0,
                        "end_index": 20,
                    },
                    {"type": "url_citation", "url": "https://www.fda.gov/ct/", "title": "dup"},
                    {"type": "url_citation", "url": "javascript:alert(1)", "title": "bad"},
                    {"type": "url_citation", "url": "ftp://x.example.com/a", "title": "ftp"},
                    {
                        "type": "url_citation",
                        "url": "https://www.example.org/dated",
                        "title": "Dated page",
                        "published_date": "2026-09-01",
                    },
                    {"type": "file_citation", "file_id": "f1"},
                ],
            }
        ],
    }
    return {
        "status": "completed",
        "output": [{"type": "reasoning"}, *calls, message],
        "usage": {"input_tokens": 10_000, "output_tokens": 1_000},
    }


class FakeTransport:
    """Scripted Responses API: returns (status, body) in order, keeps every body sent."""

    def __init__(self, *replies: tuple[int, Any] | Exception) -> None:
        self.replies = list(replies)
        self.sent: list[dict[str, Any]] = []

    def post(self, body: dict[str, Any]) -> tuple[int, Any]:
        self.sent.append(body)
        reply = self.replies.pop(0) if self.replies else (200, ok_reply())
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeFetcher:
    """GDELT stand-in."""

    def __init__(self, status: int = 200, articles: list[dict[str, Any]] | None = None) -> None:
        self.status = status
        self.articles = (
            articles
            if articles is not None
            else [
                {
                    "url": "https://news.example.com/g1",
                    "title": "GDELT one",
                    "seendate": "20261020T1",
                },
                {
                    "url": "https://news.example.com/g2",
                    "title": "GDELT two",
                    "seendate": "20261021T120000Z",
                },
            ]
        )
        self.urls: list[str] = []

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        self.urls.append(url)
        return self.status, json.dumps({"articles": self.articles})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    research.reset_rejected()
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    for name in (research.RESEARCH_ENV, research.SEARCH_FEE_ENV, research.PER_DAY_ENV):
        monkeypatch.delenv(name, raising=False)


def ledger(cap: float = 2.9) -> tuple[CallLedger, MemoryStore]:
    store = MemoryStore()
    return CallLedger(store, cap_usd=cap, today=lambda: DAY), store


# --- settings, skill, request ------------------------------------------------------------


def test_flag_default_off_and_values() -> None:
    assert research.research_enabled({}) is False
    assert research.research_enabled({"MAUDESIGNAL_RESEARCH": "0"}) is False
    for v in ("1", "true", "ON"):
        assert research.research_enabled({"MAUDESIGNAL_RESEARCH": v}) is True


def test_fee_and_hold() -> None:
    assert research.search_fee_usd({}) == 0.01
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "0.02"}) == 0.02
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "-1"}) == 0.01
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "abc"}) == 0.01
    # 40,000 x 1.25/M + 3,000 x 4.25/M + 2 x 0.01
    assert research.hold_usd(0.01) == pytest.approx(0.05 + 0.01275 + 0.02)
    assert research.hold_usd(0.01) <= MAX_CALL_HOLD_USD
    assert research.per_day({}) == 5


def test_instructions_come_from_the_skill() -> None:
    text = research.load_instructions()
    assert "web_search tool at most twice" in text and "## " not in text
    assert "{topic}" not in text  # the connector question templates are never instructions
    assert (Path(__file__).resolve().parents[2] / "skills/web-research/VERSION").read_text(
        encoding="utf-8"
    ).strip() == "1.1.0"


def test_build_request_shape() -> None:
    body = research.build_request("CT scanners", "jak", INSTR)
    assert body["model"] == "muse-spark-1.3"
    assert body["tools"] == [{"type": "web_search"}]
    assert body["max_output_tokens"] == 3000 and body["reasoning"] == {"effort": "low"}
    assert body["max_tool_calls"] == 2
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["instructions"] == INSTR and body["input"].endswith("product code): JAK.")
    assert "max_tool_calls" not in research.build_request(
        "q", None, INSTR, frozenset({"max_tool_calls"})
    )


# --- parsing -----------------------------------------------------------------------------


def test_parse_annotations_then_sources() -> None:
    parsed = research.parse_reply(ok_reply())
    urls = [i["url"] for i in parsed.items]
    assert urls[:2] == ["https://www.fda.gov/ct", "https://www.example.org/dated"]
    assert all(u.startswith(("http://", "https://")) for u in urls)
    assert len(urls) == len(set(urls)) and len(urls) <= research.MAX_ITEMS
    assert "https://www.fda.gov/ct/" not in urls  # trailing-slash duplicate dropped
    first, dated = parsed.items[0], parsed.items[1]
    assert first == {
        "title": "CT safety communication",
        "url": "https://www.fda.gov/ct",
        "date": None,
        "source": "fda.gov",
    }
    assert dated["date"] == "2026-09-01" and dated["source"] == "example.org"
    assert parsed.items[2]["source"] == "news.example.com"
    assert parsed.searches == 2 and (parsed.input_tokens, parsed.output_tokens) == (10_000, 1_000)
    assert parsed.summary_text and parsed.summary_text.startswith("FDA safety communication")


def test_parse_caps_items_and_never_invents_dates() -> None:
    parsed = research.parse_reply(ok_reply(n_sources=6, searches=2))
    assert len(parsed.items) == research.MAX_ITEMS
    assert all(i["date"] is None for i in parsed.items if "news.example.com" in i["url"])


def test_parse_forbidden_words_are_not_shown() -> None:
    reply = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "This device is FDA-approved.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://x.example.com/a",
                                "title": "Approved!",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    parsed = research.parse_reply(reply)
    assert parsed.summary_text is None
    assert parsed.items[0]["title"] == "x.example.com"
    assert parsed.input_tokens is None


def test_parse_odd_payloads() -> None:
    parsed = research.parse_reply({"output": [None, "x", {"type": "message", "content": [1]}]})
    assert parsed.items == [] and parsed.summary_text is None and parsed.searches == 0


def test_clean_url() -> None:
    assert research.clean_url("https://a.example.com/x") == "https://a.example.com/x"
    for bad in ("javascript:x", "data:text/html,1", "https://", "http://a b", 5, "x" * 3000):
        assert research.clean_url(bad) is None


# --- spend: reservation and settle ---------------------------------------------------------


def test_success_reserves_then_settles_actual() -> None:
    led, store = ledger()
    t = FakeTransport((200, ok_reply()))
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    expected = 10_000 * 1.25e-6 + 1_000 * 4.25e-6 + 2 * 0.01
    assert out["status"] == "ok" and out["label"] == EXACT_LABEL
    assert out["cost_usd"] == pytest.approx(expected)
    assert led.total(DAY.isoformat()) == pytest.approx(expected)
    (obj,) = [json.loads(store.get(r)) for r in store.list_prefix("ledger/")]
    assert obj["settled_ok"] is True and obj["hold_usd"] == pytest.approx(research.hold_usd(0.01))
    assert len(t.sent) == 1


def test_failure_keeps_the_hold_and_shows_it() -> None:
    led, _ = ledger()
    t = FakeTransport((500, {"error": {"message": "boom"}}))
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    hold = research.hold_usd(0.01)
    assert out["status"] == "unavailable" and out["items"] == []
    assert out["cost_usd"] == pytest.approx(hold)  # no partial cost hidden
    assert led.total(DAY.isoformat()) == pytest.approx(hold)
    assert len(t.sent) == 1


def test_timeout_counts_the_hold() -> None:
    led, _ = ledger()
    t = FakeTransport(TimeoutError("slow"))
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    assert out["status"] == "unavailable"
    assert out["cost_usd"] == pytest.approx(research.hold_usd(0.01))


def test_rejected_param_retried_once_without_it() -> None:
    led, _ = ledger()
    t = FakeTransport(
        (400, {"error": {"param": "max_tool_calls", "message": "Unknown parameter"}}),
        (200, ok_reply()),
    )
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    assert out["status"] == "ok" and len(t.sent) == 2
    assert "max_tool_calls" in t.sent[0] and "max_tool_calls" not in t.sent[1]
    assert "include" in t.sent[1]
    # the 400's hold stays counted and is shown
    assert out["cost_usd"] > research.hold_usd(0.01)
    # remembered: the next request does not send it again
    t2 = FakeTransport((200, ok_reply()))
    research.run_research("CT", None, transport=t2, ledger=led, instructions=INSTR)
    assert "max_tool_calls" not in t2.sent[0]


def test_never_more_than_two_requests() -> None:
    led, _ = ledger()
    t = FakeTransport(
        (400, {"error": {"param": "include", "message": "bad include"}}),
        (400, {"error": {"param": "max_tool_calls", "message": "bad"}}),
        (200, ok_reply()),
    )
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    assert len(t.sent) == 2 and out["status"] == "unavailable"


def test_cap_reached_makes_no_call() -> None:
    led, store = ledger(cap=0.01)
    t = FakeTransport()
    out = research.run_research("CT", None, transport=t, ledger=led, instructions=INSTR)
    assert t.sent == [] and out["status"] == "unavailable" and out["cost_usd"] == 0.0
    assert out["note"] == research.NOTE_CAP
    assert store.list_prefix("ledger/") == []


def test_fee_too_big_for_one_call_is_refused() -> None:
    led, _ = ledger()
    t = FakeTransport()
    out = research.run_research(
        "CT", None, transport=t, ledger=led, fee_per_search=0.05, instructions=INSTR
    )
    assert t.sent == [] and out["status"] == "unavailable"


def test_no_key_or_no_ledger_makes_no_call() -> None:
    led, store = ledger()
    assert research.run_research("CT", None, transport=None, ledger=led)["status"] == "unavailable"
    t = FakeTransport()
    assert research.run_research("CT", None, transport=t, ledger=None)["status"] == "unavailable"
    assert t.sent == [] and store.list_prefix("ledger/") == []


# --- GDELT backup ------------------------------------------------------------------------


def test_gdelt_backup_only_when_web_search_fails() -> None:
    led, _ = ledger()
    fetcher = FakeFetcher()
    out = research.run_research(
        "Recent problems with CT scanners",
        "jak",
        transport=FakeTransport((503, "down")),
        ledger=led,
        news_fetcher=lambda: fetcher,
        instructions=INSTR,
    )
    assert out["status"] == "news_only" and out["note"] == research.NOTE_NEWS_ONLY
    assert {i["source"] for i in out["items"]} == {"GDELT news index"}
    assert out["items"][1]["date"] == "2026-10-21" and out["items"][0]["date"] is None
    assert "api.gdeltproject.org" in fetcher.urls[0] and "JAK" in fetcher.urls[0]
    assert out["summary_text"] is None
    # web search worked: GDELT is not called
    fetcher2 = FakeFetcher()
    ok = research.run_research(
        "CT",
        None,
        transport=FakeTransport(),
        ledger=led,
        news_fetcher=lambda: fetcher2,
        instructions=INSTR,
    )
    assert ok["status"] == "ok" and fetcher2.urls == []


def test_gdelt_failing_too_gives_unavailable() -> None:
    out = research.run_research(
        "CT scanners", None, transport=None, ledger=None, news_fetcher=lambda: FakeFetcher(500)
    )
    assert out["status"] == "unavailable" and out["items"] == []


# --- routes ------------------------------------------------------------------------------


def make_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, on: bool
) -> tuple[Env, FakeTransport]:
    if on:
        monkeypatch.setenv(research.RESEARCH_ENV, "1")
    env = Env(tmp_path)
    transport = FakeTransport(*[(200, ok_reply()) for _ in range(20)])
    env.backends.research_transport = lambda _t: transport
    env.backends.research_fetcher = lambda: FakeFetcher()
    return env, transport


def test_flag_off_research_absent_and_save_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=False)
    r = env.ask(research=True)
    assert r.status_code == 200 and "research" not in r.json()
    assert transport.sent == []
    assert "features" not in env.client.get("/v1/health").json()
    s = env.client.post(
        "/v1/live/research/save", json={"url": "https://a.example.com", "person_action": True}
    )
    assert s.status_code == 404


def test_flag_on_research_beside_answer_never_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    assert env.client.get("/v1/health").json()["features"] == {"research": True}
    plain = env.ask().json()
    assert "research" not in plain and transport.sent == []
    body = env.ask(research=True).json()
    blk = body["research"]
    assert blk["label"] == EXACT_LABEL and blk["status"] == "ok" and blk["items"]
    assert set(blk) == {"status", "label", "items", "summary_text", "cost_usd", "note"}
    # the gated FDA answer is unchanged and holds nothing from the web
    assert body["answer"] == plain["answer"]
    answer_text = json.dumps(body["answer"])
    assert "fda.gov/ct" not in answer_text and "news.example.com" not in answer_text
    assert "research" not in json.dumps(body["trace"]).lower()
    assert forbidden_in(json.dumps(body)) == []
    assert len(transport.sent) == 1


def test_per_visitor_research_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    blocks = [env.ask(research=True).json()["research"] for _ in range(6)]
    assert [b["status"] for b in blocks[:5]] == ["ok"] * 5
    assert blocks[5]["status"] == "unavailable" and "Daily limit of 5" in blocks[5]["note"]
    assert len(transport.sent) == 5


def test_research_flag_must_be_boolean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    assert env.ask(research="yes").status_code == 422


def test_save_validation_and_audit_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    path = "/v1/live/research/save"
    good = {
        "url": "https://www.fda.gov/ct",
        "title": "CT safety communication",
        "date": None,
        "person_action": True,
    }
    r = env.client.post(path, json=good)
    assert r.status_code == 200 and r.json()["saved"] is True
    r2 = env.client.post(path, json=good | {"ref": "abc-123", "date": "2026-09-01"})
    assert r2.status_code == 200
    entries = env.state.audit_recent(10)
    saves = [
        e | {"payload": json.loads(e["payload_json"])}
        for e in entries
        if e["action"] == "research:save"
    ]
    assert len(saves) == 2 and verify_chain(entries)[0]
    assert set(saves[0]["payload"]) == {"url", "title", "date", "saved_by", "saved_at"}
    assert saves[0]["payload"]["saved_by"] == "anonymous"
    assert saves[1]["payload"]["saved_by"] == "abc-123"
    assert saves[1]["payload"]["date"] == "2026-09-01"
    assert "question" not in json.dumps(saves)
    for bad in (
        good | {"url": "javascript:alert(1)"},
        good | {"url": "ftp://x.example.com/a"},
        good | {"url": "https://x.example.com/" + "a" * 2100},
        good | {"person_action": False},
        good | {"person_action": "true"},
        {k: v for k, v in good.items() if k != "person_action"},
        good | {"question": "what about my patient"},
        good | {"title": "t" * 400},
    ):
        assert env.client.post(path, json=bad).status_code == 422, bad
    assert env.client.post(path, content=b"[not json").status_code == 422


def test_save_is_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(research.SAVE_PER_DAY_ENV, "2")
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    body = {"url": "https://www.fda.gov/ct", "person_action": True}
    codes = [env.client.post("/v1/live/research/save", json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
