"""Research mode (connector/research.py and its live routes). Offline: fake transport."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector import research  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.callcap import (  # noqa: E402
    MAX_CALL_HOLD_USD,
    CallLedger,
    CallRefusedError,
    enforced_cap,
)
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.legal_pages import render_privacy  # noqa: E402
from maudesignal.connector.store import verify_chain  # noqa: E402
from tests.unit.test_connector_live import Env  # noqa: E402

EXACT_LABEL = "Web research — not FDA records, not verified by the gate"
INSTR = "test instructions"
DAY = date(2026, 10, 30)
HOLD = research.hold_usd(research.DEFAULT_SEARCH_FEE_USD)


def ok_reply(
    n_sources: int = 2,
    *,
    searches: int = 2,
    input_tokens: int = 10_000,
    output_tokens: int = 1_000,
) -> dict[str, Any]:
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
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


#: A reply past every limit the hold assumes: 3 searches, 20k input, output at the cap.
OVERSHOOT = ok_reply(searches=3, input_tokens=20_000, output_tokens=3_000)
OVERSHOOT_USD = 20_000 * 1.25e-6 + 3_000 * 4.25e-6 + 3 * 0.05  # 0.18775 > HOLD


class FakeTransport:
    """Scripted Responses API: returns (status, body) in order, keeps every body sent."""

    def __init__(self, *replies: tuple[int, Any] | Exception, default: Any = None) -> None:
        self.replies = list(replies)
        self.default = default if default is not None else ok_reply()
        self.sent: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def post(self, body: dict[str, Any]) -> tuple[int, Any]:
        with self._lock:
            self.sent.append(body)
            reply = self.replies.pop(0) if self.replies else (200, self.default)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeFetcher:
    """GDELT stand-in."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.articles = [
            {"url": "https://news.example.com/g1", "title": "GDELT one", "seendate": "x"},
            {
                "url": "https://news.example.com/g2",
                "title": "GDELT two",
                "seendate": "20261021T120000Z",
            },
        ]
        self.urls: list[str] = []

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        self.urls.append(url)
        return self.status, json.dumps({"articles": self.articles})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    research.reset_rejected()
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    for name in (
        research.RESEARCH_ENV,
        research.SEARCH_FEE_ENV,
        research.PER_DAY_ENV,
        research.HOLD_CAP_ENV,
        research.SAVE_PER_DAY_ENV,
        research.DAY_USD_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def ledger(cap: float = 2.9) -> tuple[CallLedger, MemoryStore]:
    store = MemoryStore()
    return CallLedger(store, cap_usd=cap, today=lambda: DAY), store


def run(led: CallLedger | None, t: FakeTransport | None, **kw: Any) -> dict[str, Any]:
    return research.run_research(
        "CT scanner problems", None, transport=t, ledger=led, instructions=INSTR, **kw
    )


# --- settings, skill, request ------------------------------------------------------------


def test_flag_default_off_and_values() -> None:
    assert research.research_enabled({}) is False
    assert research.research_enabled({"MAUDESIGNAL_RESEARCH": "0"}) is False
    for v in ("1", "true", "ON"):
        assert research.research_enabled({"MAUDESIGNAL_RESEARCH": v}) is True


def test_fee_and_hold() -> None:
    assert research.search_fee_usd({}) == 0.05
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "0.02"}) == 0.02
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "-1"}) == 0.05
    assert research.search_fee_usd({research.SEARCH_FEE_ENV: "abc"}) == 0.05
    assert research.RESEARCH_INPUT_TOKENS == 15_000
    # 15,000 x 1.25/M + 3,000 x 4.25/M + max(2, 2) x 0.05
    assert pytest.approx(0.01875 + 0.01275 + 0.10) == HOLD
    assert pytest.approx(0.1315) == HOLD
    assert HOLD > MAX_CALL_HOLD_USD  # why research has its own per-call limit
    assert research.hold_cap_usd({}) == 0.14
    assert research.hold_cap_usd({research.HOLD_CAP_ENV: "0.5"}) == 0.14  # never above 0.14
    assert research.hold_cap_usd({research.HOLD_CAP_ENV: "0.13"}) == 0.13
    assert HOLD <= research.hold_cap_usd({})
    assert research.per_day({}) == 5
    assert research.research_day_usd({}) == 0.30
    assert research.research_day_usd({research.DAY_USD_ENV: "0.4"}) == 0.4
    # a ceiling of $0.50, and a non-finite value is rejected (default)
    assert research.MAX_DAY_USD == 0.50
    for bad in ("5", "1.5", "0.51"):
        assert research.research_day_usd({research.DAY_USD_ENV: bad}) == 0.50
    for bad in ("inf", "-inf", "nan"):
        assert research.research_day_usd({research.DAY_USD_ENV: bad}) == 0.30
    assert research.clamp_day_usd(float("inf")) == 0.30 and research.clamp_day_usd(9.0) == 0.50
    assert research.clamp_day_usd(-1.0) == 0.0
    assert research.research_day_usd({research.DAY_USD_ENV: "-1"}) == 0.30


def test_three_dollar_guarantee_math() -> None:
    """The docstring's bound: research reserves against 3.00 - its per-call limit."""
    cap = enforced_cap(3.0)
    limit = research.hold_cap_usd({})
    r_cap = research.research_cap(cap, limit)
    assert cap == pytest.approx(2.90) and r_cap == pytest.approx(2.86)
    # a research call racing a normal call, neither seeing the other
    assert min(cap + limit, r_cap + MAX_CALL_HOLD_USD) == pytest.approx(2.96)
    # two research calls racing (despite ``exclusive``)
    assert r_cap + limit == pytest.approx(3.00)
    # a normal call racing a normal call (the base rule)
    assert cap + MAX_CALL_HOLD_USD == pytest.approx(3.00)


def test_instructions_come_from_the_skill() -> None:
    text = research.load_instructions()
    assert "web_search tool at most twice" in text and "## " not in text
    assert "{topic}" not in text  # the connector question templates are never instructions
    root = Path(__file__).resolve().parents[2] / "skills/web-research"
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "1.2.0"
    schema = json.loads((root / "schemas/output.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["summary_text"] == {"type": "null"}


def test_build_request_shape() -> None:
    body = research.build_request("CT scanners", "jak", INSTR)
    assert body["model"] == "muse-spark-1.3"
    assert body["tools"] == [{"type": "web_search"}]
    assert body["max_output_tokens"] == 3000 and body["reasoning"] == {"effort": "low"}
    assert body["max_tool_calls"] == 2
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["instructions"] == INSTR and body["input"].endswith("product code): JAK.")


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
    assert parsed.summary_text is None  # never shown


def test_parse_caps_items_and_never_invents_dates() -> None:
    parsed = research.parse_reply(ok_reply(n_sources=6, searches=2))
    assert len(parsed.items) == research.MAX_ITEMS
    assert all(i["date"] is None for i in parsed.items if "news.example.com" in i["url"])


def test_parse_forbidden_title_becomes_domain() -> None:
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
    assert parsed.summary_text is None and parsed.items[0]["title"] == "x.example.com"
    assert parsed.input_tokens is None


def test_parse_odd_payloads() -> None:
    parsed = research.parse_reply({"output": [None, "x", {"type": "message", "content": [1]}]})
    assert parsed.items == [] and parsed.summary_text is None and parsed.searches == 0


def test_clean_url() -> None:
    assert research.clean_url("https://a.example.com/x") == "https://a.example.com/x"
    for bad in ("javascript:x", "data:text/html,1", "https://", "http://a b", 5, "x" * 3000):
        assert research.clean_url(bad) is None


# --- spend: reservation, settle, kill switch -----------------------------------------------


def test_success_reserves_then_settles_actual() -> None:
    led, store = ledger()
    t = FakeTransport((200, ok_reply()))
    out = run(led, t)
    expected = 10_000 * 1.25e-6 + 1_000 * 4.25e-6 + 2 * 0.05
    assert out["status"] == "ok" and out["label"] == EXACT_LABEL
    assert out["summary_text"] is None
    assert set(out) == {"status", "label", "items", "summary_text", "cost_usd", "note"}
    assert out["cost_usd"] == pytest.approx(expected)
    assert led.total(DAY.isoformat()) == pytest.approx(expected)
    (ref,) = store.list_prefix("ledger/")
    assert ref.pathname.startswith("ledger/2026-10-30/research-")
    obj = json.loads(store.get(ref))
    assert obj["settled_ok"] is True and obj["hold_usd"] == pytest.approx(HOLD)
    assert len(t.sent) == 1 and not led.flag_set(research.KILL_FLAG)


def test_failure_keeps_the_hold_and_shows_it() -> None:
    led, _ = ledger()
    t = FakeTransport((500, {"error": {"message": "boom"}}))
    out = run(led, t)
    assert out["status"] == "unavailable" and out["items"] == []
    assert out["cost_usd"] == pytest.approx(HOLD)  # no partial cost hidden
    assert led.total(DAY.isoformat()) == pytest.approx(HOLD)
    assert len(t.sent) == 1 and research.disabled_reason() is None
    assert led.flag_set(research.KILL_FLAG)  # possibly billed: no second call today


@pytest.mark.parametrize("failure", [TimeoutError("slow"), ConnectionError("reset")])
def test_failure_after_sending_raises_the_day_flag(failure: Exception) -> None:
    led, store = ledger()
    out = run(led, FakeTransport(failure))
    assert out["status"] == "unavailable" and out["cost_usd"] == pytest.approx(HOLD)
    assert led.flag_set(research.KILL_FLAG)
    # counted at its hold (settled at the hold, no longer "in flight")
    assert led.total(DAY.isoformat()) == pytest.approx(HOLD)
    (ref,) = store.list_prefix("ledger/")
    assert json.loads(store.get(ref))["actual_usd"] == pytest.approx(HOLD)
    # the freed slot never lets a second paid call through today, even in a new process
    research.reset_rejected()
    t2 = FakeTransport()
    again = run(led, t2)
    assert t2.sent == [] and again["note"] == research.NOTE_OFF
    assert led.total(DAY.isoformat()) == pytest.approx(HOLD)


def test_refused_before_sending_raises_no_flag() -> None:
    led, _ = ledger(cap=0.01)
    run(led, FakeTransport())
    assert not led.flag_set(research.KILL_FLAG)


@pytest.mark.parametrize("param", ["max_tool_calls", "include"])
def test_rejected_param_is_never_retried(param: str) -> None:
    led, _ = ledger()
    t = FakeTransport((400, {"error": {"param": param, "message": "Unknown parameter"}}))
    fetcher = FakeFetcher()
    out = run(led, t, news_fetcher=lambda: fetcher)
    assert len(t.sent) == 1 and "max_tool_calls" in t.sent[0]  # no second request
    assert out["status"] == "news_only" and fetcher.urls
    assert out["cost_usd"] == pytest.approx(HOLD)
    assert research.disabled_reason() is not None
    # later questions skip the paid call for this process
    t2 = FakeTransport()
    later = run(led, t2, news_fetcher=lambda: FakeFetcher())
    assert t2.sent == [] and later["status"] == "news_only"
    assert run(led, t2)["note"] == research.NOTE_OFF


def test_overshoot_switches_research_off_for_process_and_day() -> None:
    led, store = ledger()
    t = FakeTransport((200, OVERSHOOT))
    out = run(led, t)
    assert out["status"] == "ok"
    assert out["cost_usd"] == pytest.approx(OVERSHOOT_USD)  # real cost still settled
    assert led.total(DAY.isoformat()) == pytest.approx(OVERSHOOT_USD)
    assert research.disabled_reason() is not None and led.flag_set(research.KILL_FLAG)
    # a new process (reset) still sees the day flag in the ledger: no call
    research.reset_rejected()
    t2 = FakeTransport()
    again = run(led, t2)
    assert t2.sent == [] and again["status"] == "unavailable" and again["note"] == research.NOTE_OFF
    # the flag lives outside the ledger prefix and never breaks the day total
    assert all(r.pathname.startswith("ledger/") for r in store.list_prefix("ledger/"))
    assert led.total(DAY.isoformat()) == pytest.approx(OVERSHOOT_USD)


@pytest.mark.parametrize(
    "reply",
    [
        ok_reply(searches=3),
        ok_reply(output_tokens=3_001),
        ok_reply(input_tokens=15_001),
    ],
)
def test_each_overshoot_kind_trips_the_switch(reply: dict[str, Any]) -> None:
    led, _ = ledger()
    run(led, FakeTransport((200, reply)))
    assert research.disabled_reason() is not None and led.flag_set(research.KILL_FLAG)


def test_cost_above_hold_alone_trips_the_day_flag() -> None:
    led, _ = ledger()
    # within every token / search limit, but a fee allowance that makes the real cost > hold
    reply = ok_reply(searches=2, input_tokens=15_000, output_tokens=3_000)
    calls: list[float] = []

    def actual(_r: Any) -> float:
        calls.append(1)
        return HOLD + 0.001

    led.metered(HOLD, lambda: reply, actual, kill_flag="research", max_hold_usd=0.14)
    assert led.flag_set("research")
    # other routes are unaffected: same settle without kill_flag raises nothing
    led2, _ = ledger()
    led2.metered(0.05, lambda: 1, lambda _r: 0.06)
    assert not led2.flag_set("research")


def test_exclusive_one_research_in_flight() -> None:
    led, _ = ledger()
    first = led.reserve(HOLD, max_hold_usd=0.14, kind="research", exclusive=True)
    with pytest.raises(CallRefusedError) as exc:
        led.reserve(HOLD, max_hold_usd=0.14, kind="research", exclusive=True)
    assert exc.value.cap == "busy"
    led.reserve(0.05)  # other calls still pass
    first.settle(0.05)
    led.reserve(HOLD, max_hold_usd=0.14, kind="research", exclusive=True)  # free again


def test_research_cap_is_lower_than_other_routes() -> None:
    led, _ = ledger(cap=enforced_cap(3.0))
    for _ in range(27):
        led.reserve(0.10)
    led.reserve(0.08)  # 2.78 held by normal calls
    with pytest.raises(CallRefusedError):  # 2.78 + 0.1315 = 2.9115 > 2.86
        led.reserve(HOLD, max_hold_usd=0.14, cap_usd=research.research_cap(led.cap_usd, 0.14))
    led.reserve(0.10)  # 2.88 <= 2.90 for a normal call


def test_cap_reached_makes_no_call() -> None:
    led, store = ledger(cap=0.01)
    t = FakeTransport()
    out = run(led, t)
    assert t.sent == [] and out["status"] == "unavailable" and out["cost_usd"] == 0.0
    assert out["note"] == research.NOTE_CAP
    assert store.list_prefix("ledger/") == []


def test_fee_too_big_for_one_call_is_refused() -> None:
    led, _ = ledger()
    t = FakeTransport()
    # 0.06 per search: 0.0315 + 0.12 = 0.1515 > the 0.14 per-call limit
    assert run(led, t, fee_per_search=0.06)["status"] == "unavailable" and t.sent == []


def test_no_key_or_no_ledger_makes_no_call() -> None:
    led, store = ledger()
    assert run(led, None)["status"] == "unavailable"
    t = FakeTransport()
    assert run(None, t)["status"] == "unavailable"
    assert t.sent == [] and store.list_prefix("ledger/") == []


@pytest.mark.parametrize("round_", range(4))
@pytest.mark.parametrize("day_cap", [None, 10.0])  # the default $0.30, and no research cap
@pytest.mark.parametrize("reply", [ok_reply(input_tokens=15_000, output_tokens=3_000), OVERSHOOT])
def test_day_total_never_passes_3_00_with_concurrent_research(
    reply: dict[str, Any], day_cap: float | None, round_: int
) -> None:
    """N concurrent research calls (overshooting or at the hold) and normal calls near the cap."""
    store = MemoryStore()
    led = CallLedger(store, cap_usd=enforced_cap(3.0), today=lambda: DAY)
    for _ in range(25):  # 2.50 already spent by normal calls
        led.reserve(0.10).settle(0.10)
    t = FakeTransport(default=reply)

    def research_call(_i: int) -> dict[str, Any]:
        return run(led, t, day_cap=day_cap)

    def normal_call(_i: int) -> None:
        try:
            led.metered(0.10, lambda: 1, lambda _r: 0.10)
        except CallRefusedError:
            pass

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(research_call, i) for i in range(20)]
        futures += [pool.submit(normal_call, i) for i in range(20)]
        outs = [f.result() for f in futures]
    total = led.total(DAY.isoformat())
    assert total <= 3.00 + 1e-9, total
    paid = [o for o in outs if isinstance(o, dict) and o["status"] == "ok"]
    assert len(t.sent) == len(paid)
    if reply is OVERSHOOT:
        assert len(paid) <= 1 and led.flag_set(research.KILL_FLAG)
    if day_cap is None:  # the research-only day cap holds under concurrency too
        assert led.kind_total(research.KILL_FLAG, DAY.isoformat()) <= 0.30 + 0.06


# --- research-only daily dollar cap --------------------------------------------------------


def test_research_day_cap_allows_two_requests_by_default() -> None:
    """$0.30: two requests (0.11675 settled each), the third (+0.1315 hold) is refused."""
    led, store = ledger()
    t = FakeTransport()
    fetcher = FakeFetcher()
    outs = [run(led, t, news_fetcher=lambda: fetcher) for _ in range(3)]
    assert [o["status"] for o in outs] == ["ok", "ok", "news_only"]
    assert len(t.sent) == 2  # no paid call for the third
    each = 10_000 * 1.25e-6 + 1_000 * 4.25e-6 + 2 * 0.05
    assert led.kind_total(research.KILL_FLAG, DAY.isoformat()) == pytest.approx(2 * each)
    assert not led.flag_set(research.KILL_FLAG)  # a budget refusal is not a kill switch
    # without the GDELT backup the note says why
    again = run(led, t)
    assert again["status"] == "unavailable" and again["note"] == research.NOTE_DAY_CAP
    assert again["cost_usd"] == 0.0 and len(t.sent) == 2
    # the refused reservations left nothing behind
    assert len(store.list_prefix("ledger/")) == 2


def test_research_day_cap_counts_holds_and_failures() -> None:
    led, _ = ledger()
    held = led.reserve(HOLD, max_hold_usd=0.14, kind=research.KILL_FLAG)  # unsettled: its hold
    assert led.kind_total(research.KILL_FLAG) == pytest.approx(HOLD)
    led.reserve(0.10)  # other kinds are not counted against the research cap
    assert led.kind_total(research.KILL_FLAG) == pytest.approx(HOLD)
    with pytest.raises(CallRefusedError) as exc:  # unsettled 0.1315 + 0.1315 > 0.20
        led.reserve(HOLD, max_hold_usd=0.14, kind=research.KILL_FLAG, kind_cap_usd=0.20)
    assert exc.value.cap == "kind_cap"
    held.settle(0.02)  # settled cheaply: 0.02 + 0.1315 <= 0.20
    led.reserve(HOLD, max_hold_usd=0.14, kind=research.KILL_FLAG, kind_cap_usd=0.20)


def test_caller_passed_day_cap_is_clamped_too() -> None:
    led, _ = ledger()
    t = FakeTransport()
    outs = [run(led, t, day_cap=float("inf")) for _ in range(3)]  # inf -> default $0.30
    assert [o["status"] for o in outs] == ["ok", "ok", "unavailable"] and len(t.sent) == 2
    led2, _ = ledger()
    t2 = FakeTransport()
    for _ in range(5):  # 99 -> $0.50: four requests at 0.11675 fit, a fifth does not
        run(led2, t2, day_cap=99.0)
    assert len(t2.sent) == 4
    assert led2.kind_total(research.KILL_FLAG, DAY.isoformat()) <= research.MAX_DAY_USD


def test_research_day_cap_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(research.DAY_USD_ENV, "0.10")  # below one hold: never a paid call
    led, _ = ledger()
    t = FakeTransport()
    out = run(led, t)
    assert t.sent == [] and out["note"] == research.NOTE_DAY_CAP


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
    fetcher2 = FakeFetcher()
    led2, _ = ledger()  # a new day ledger: the failed call above raised today's flag
    ok = run(led2, FakeTransport(), news_fetcher=lambda: fetcher2)
    assert ok["status"] == "ok" and fetcher2.urls == []


def test_gdelt_failing_too_gives_unavailable() -> None:
    out = research.run_research(
        "CT scanners", None, transport=None, ledger=None, news_fetcher=lambda: FakeFetcher(500)
    )
    assert out["status"] == "unavailable" and out["items"] == []


# --- routes ------------------------------------------------------------------------------

SAVE = "/v1/live/research/save"


def make_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, on: bool
) -> tuple[Env, FakeTransport]:
    if on:
        monkeypatch.setenv(research.RESEARCH_ENV, "1")
    env = Env(tmp_path)
    transport = FakeTransport()
    env.backends.research_transport = lambda _t: transport
    env.backends.research_fetcher = lambda: FakeFetcher()
    return env, transport


def test_flag_off_is_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=False)
    r = env.ask(research=True)
    assert r.status_code == 422 and "research" in r.json()["message"]  # unknown field, as before
    assert transport.sent == []
    assert "research" not in env.ask().json()
    assert "research" not in env.client.get("/v1/health").json().get("features", {})
    body = {"url": "https://a.example.com", "person_action": True}
    s = env.client.post(SAVE, json=body)
    missing = env.client.post("/v1/live/no-such-route", json=body)
    assert (
        (s.status_code, s.content)
        == (missing.status_code, missing.content)
        == (
            404,
            missing.content,
        )
    )
    o = env.client.options(SAVE, headers={"Origin": "https://app.example.com"})
    o2 = env.client.options("/v1/live/no-such-route", headers={"Origin": "https://app.example.com"})
    assert (o.status_code, o.content) == (o2.status_code, o2.content)
    page = env.client.get("/privacy").text
    assert "Research mode" not in page
    assert render_privacy(rate_per_min=1, public_per_hour=1, shared_store=False, live_on=False) == (
        render_privacy(
            rate_per_min=1, public_per_hour=1, shared_store=False, live_on=False, research_on=False
        )
    )


def test_flag_on_research_beside_answer_never_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    assert env.client.get("/v1/health").json()["features"] == {
        "voice_transcribe_only": True,
        "research": True,
    }
    page = env.client.get("/privacy").text
    assert "Research mode (switched on here)" in page and "GDELT news index" in page
    plain = env.ask().json()
    assert "research" not in plain and transport.sent == []
    body = env.ask(research=True).json()
    blk = body["research"]
    assert blk["label"] == EXACT_LABEL and blk["status"] == "ok" and blk["items"]
    assert blk["summary_text"] is None
    assert set(blk) == {"status", "label", "items", "summary_text", "cost_usd", "note"}
    assert body["answer"] == plain["answer"]
    answer_text = json.dumps(body["answer"])
    assert "fda.gov/ct" not in answer_text and "news.example.com" not in answer_text
    assert "research" not in json.dumps(body["trace"]).lower()
    assert forbidden_in(json.dumps(body)) == []
    assert len(transport.sent) == 1


@pytest.mark.parametrize(
    "question",
    ["hello", "Is it safe to use this scanner on my mother?", "Is this medical advice?"],
)
def test_no_research_for_canned_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    r = env.ask(question, research=True)
    assert r.status_code == 200 and "research" not in r.json()
    assert transport.sent == []


def test_no_research_for_patient_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    r = env.ask("Mrs. Smith, 64 years old, had a burn from the LLZ device", research=True)
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert transport.sent == []


def test_per_visitor_research_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the dollar cap is tested on its own (its ceiling is lifted for this test only)
    monkeypatch.setattr(research, "MAX_DAY_USD", 5.0)
    monkeypatch.setenv(research.DAY_USD_ENV, "5")
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    blocks = [env.ask(research=True).json()["research"] for _ in range(6)]
    assert [b["status"] for b in blocks[:5]] == ["ok"] * 5
    assert blocks[5]["status"] == "unavailable" and "Daily limit of 5" in blocks[5]["note"]
    assert len(transport.sent) == 5


def test_route_research_day_cap_falls_back_to_news(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, transport = make_env(tmp_path, monkeypatch, on=True)
    blocks = [env.ask(research=True).json()["research"] for _ in range(3)]
    assert [b["status"] for b in blocks] == ["ok", "ok", "news_only"]
    assert len(transport.sent) == 2


def test_research_flag_must_be_boolean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    assert env.ask(research="yes").status_code == 422


def test_save_audit_entry_is_never_an_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    good = {
        "url": "https://www.fda.gov/ct?x=1#section-2",
        "title": "CT safety communication",
        "date": "",
        "person_action": True,
    }
    r = env.client.post(SAVE, json=good)
    assert r.status_code == 200 and r.json()["saved"] is True
    r2 = env.client.post(SAVE, json=good | {"ref": "Dr-Jane-Smith", "date": "2026-09"})
    assert r2.status_code == 200
    entries = env.state.audit_recent(10)
    saves = [json.loads(e["payload_json"]) for e in entries if e["action"] == "research:save"]
    assert len(saves) == 2 and verify_chain(entries)[0]
    keys = {"url", "title", "date", "saved_by", "visitor", "ref", "saved_at"}
    assert set(saves[0]) == keys and set(saves[1]) == keys
    assert {s["saved_by"] for s in saves} == {"unverified visitor"}
    assert saves[0]["url"] == "https://www.fda.gov/ct?x=1"  # fragment stripped
    assert saves[0]["date"] is None and saves[1]["date"] == "2026-09"
    assert saves[0]["ref"] is None and saves[1]["ref"] == "Dr-Jane-Smith"
    assert saves[0]["visitor"].startswith("live:") and saves[0]["visitor"] == saves[1]["visitor"]
    assert "question" not in json.dumps(saves)


@pytest.mark.parametrize(
    "change",
    [
        {"url": "javascript:alert(1)"},
        {"url": "ftp://x.example.com/a"},
        {"url": "https://x.example.com/" + "a" * 2100},
        {"url": "https://x.example.com/a?" + "q=" + "b" * 199},
        {"date": "2026-9-1"},
        {"date": "yesterday"},
        {"date": "2026-09-01T10:00"},
        {"person_action": False},
        {"person_action": "true"},
        {"question": "what about my patient"},
        {"title": "t" * 400},
    ],
)
def test_save_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    good = {"url": "https://www.fda.gov/ct", "title": "CT", "person_action": True}
    assert env.client.post(SAVE, json=good | change).status_code == 422


def test_save_patient_data_in_url_or_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    for body in (
        {"url": "https://x.example.com/a?name=Mrs.%20Smith", "person_action": True},
        {"url": "https://x.example.com/a", "title": "Mr. Jones burn", "person_action": True},
    ):
        r = env.client.post(SAVE, json=body)
        assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert env.client.post(SAVE, content=b"[not json").status_code == 422
    assert env.client.post(SAVE, json={"person_action": True}).status_code == 422


def test_save_is_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(research.SAVE_PER_DAY_ENV, "2")
    env, _ = make_env(tmp_path, monkeypatch, on=True)
    body = {"url": "https://www.fda.gov/ct", "person_action": True}
    codes = [env.client.post(SAVE, json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
