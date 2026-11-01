"""Tests for F25 "Investigate a complaint" (HACKATHON-BUILT). No network, no model.

openFDA is replaced by ``StoredSource`` (the real raw openFDA records of the demo database, or
rows built here), so counts are recomputed from the records themselves and every case runs
offline.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDARateLimitError  # noqa: E402
from maudesignal.connector import investigate as inv  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.investigate_stored import StoredSource  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from maudesignal.gate.evidence import normalize_text  # noqa: E402

DB = PROJECT_ROOT / "data" / "demo" / "maudesignal_demo.db"
NOW = datetime(2026, 10, 27, 18, 0, 0, tzinfo=UTC)
DESC = "The report manager would not let users save a study, and images came up unreadable."
ORIGIN = "https://web.example"


@pytest.fixture(scope="module")
def stored() -> StoredSource:
    return StoredSource.from_db(DB)


def _event(
    key: str,
    day: str,
    text: str,
    *,
    code: str = "LLZ",
    source: str | None = "Manufacturer report",
    maker: str = "ACME MEDICAL",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "mdr_report_key": key,
        "report_number": f"RN-{key}",
        "date_received": day,
        "device": [{"device_report_product_code": code}],
        "mdr_text": [{"text_type_code": "Description of Event or Problem", "text": text}],
        "manufacturer_name": maker,
    }
    if source is not None:
        row["report_source_code"] = source
    return row


# --- keywords -------------------------------------------------------------------------------


def test_keywords_are_lowercase_content_words_in_order() -> None:
    assert inv.extract_keywords(DESC) == ["manager", "save", "study", "images", "unreadable"]


def test_keywords_drop_stop_words_numbers_short_words_and_repeats() -> None:
    got = inv.extract_keywords("The device had a problem 12345 and an ab; Freeze, freeze, FREEZE!")
    assert got == ["freeze"]


def test_keywords_are_capped_and_deterministic() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel india"
    assert inv.extract_keywords(text) == inv.extract_keywords(text)
    assert inv.extract_keywords(text) == ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    assert inv.extract_keywords("the and of a an") == []


# --- queries --------------------------------------------------------------------------------


def test_event_query_urls_name_code_window_and_keywords_and_hold_no_key() -> None:
    f = inv.EventFilter("LLZ", "20251101", "20261027", ("save", "study"))
    url = inv.event_query(f, count="date_received").url
    assert url.startswith("https://api.fda.gov/device/event.json?")
    assert "device.device_report_product_code%3ALLZ" in url
    assert "date_received%3A%5B20251101+TO+20261027%5D" in url
    assert "mdr_text.text%3A%28save+OR+study%29" in url
    assert "count=date_received" in url and "api_key" not in url


def test_source_value_with_odd_characters_is_not_put_in_a_query() -> None:
    f = inv.EventFilter("LLZ", "20251101", "20261027", sources=('x" OR 1:1 "',))
    assert "report_source_code" not in inv.event_search(f)


def test_window_is_twelve_calendar_months_ending_today() -> None:
    start, end = inv.window_for(NOW)
    assert (start.isoformat(), end.isoformat()) == ("2025-11-01", "2026-10-27")
    assert [m for m, _a, _b in inv._months(start, end)][0] == "2025-11"
    assert len(inv._months(start, end)) == 12


# --- counts recomputed against the stored records -------------------------------------------


def _narrative(row: dict[str, Any]) -> str:
    return " ".join(t["text"] for t in row["mdr_text"])


def test_counts_equal_a_recount_of_the_stored_records(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    llz = [
        r
        for r in stored.events
        if any(d.get("device_report_product_code") == "LLZ" for d in r["device"])
    ]
    words = set(ans.keywords)
    by_month: dict[str, int] = {}
    by_month_kw: dict[str, int] = {}
    for r in llz:
        month = f"{r['date_received'][:4]}-{r['date_received'][4:6]}"
        by_month[month] = by_month.get(month, 0) + 1
        if words & inv.narrative_words(_narrative(r)):
            by_month_kw[month] = by_month_kw.get(month, 0) + 1
    assert {m.month: m.code_wide for m in ans.months if m.code_wide} == by_month
    assert {m.month: m.keyword_matched for m in ans.months if m.keyword_matched} == by_month_kw
    assert ans.total_code_wide.value == len(llz) == sum(by_month.values())
    assert ans.total_keyword_matched is not None
    assert ans.total_keyword_matched.value == sum(by_month_kw.values())
    # The two counts are different numbers and are never merged.
    assert ans.total_keyword_matched.value < ans.total_code_wide.value
    assert len(ans.months) == 12 and ans.months[-1].partial is True


def test_every_number_has_an_openfda_link(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    urls = [m.code_wide_url for m in ans.months] + [m.keyword_url or "" for m in ans.months]
    urls += [ans.total_code_wide.url, ans.recalls.total.url if ans.recalls.total else ""]
    urls += [ans.clearances.total.url if ans.clearances.total else ""]
    urls += [ans.sources.buckets_url if ans.sources else ""]
    assert ans.sources and ans.sources.non_manufacturer.value == 0
    assert ans.sources.non_manufacturer.url == ""  # a zero is shown by the filer-type query
    assert all(u.startswith("https://api.fda.gov/") for u in urls)
    assert all("api_key" not in u for u in urls)


def test_no_keywords_gives_code_wide_counts_only(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", "the and of", now=NOW)
    assert ans.keywords == [] and ans.total_keyword_matched is None and ans.quotes == []
    assert all(m.keyword_matched is None for m in ans.months)
    assert ans.total_code_wide.value > 0


# --- quotes ---------------------------------------------------------------------------------


def test_quotes_are_verbatim_from_their_own_report(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    assert 1 <= len(ans.quotes) <= inv.MAX_QUOTES
    by_key = {str(r["mdr_report_key"]): r for r in stored.events}
    for q in ans.quotes:
        assert normalize_text(q.quote) in normalize_text(_narrative(by_key[q.mdr_report_key]))
        assert q.gate == "verbatim match"
        assert q.keywords_in_quote and set(q.keywords_in_quote) <= set(ans.keywords)
        assert q.url.startswith("https://api.fda.gov/device/event.json?")
        assert q.report_number
    assert len({q.mdr_report_key for q in ans.quotes}) == len(ans.quotes)


def test_quotes_are_the_same_on_every_run(stored: StoredSource) -> None:
    a = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    b = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    assert a.model_dump() == b.model_dump()


def test_a_quote_the_gate_cannot_match_is_dropped_and_counted(
    stored: StoredSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        inv,
        "_best_sentence",
        lambda text, kw: ("a sentence nobody wrote in this report", False, kw),
    )
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    assert ans.quotes == [] and ans.dropped.quote_not_verbatim > 0


def test_quotes_with_personal_details_or_forbidden_wording_are_left_out() -> None:
    src = StoredSource(
        [
            _event(
                "1", "20260701", "Freeze happened. Contact john.doe@example.com about the freeze."
            ),
            _event("2", "20260702", "The freeze was approved by the site for the freeze screen."),
            _event("3", "20260703", "The viewer would freeze when a study was opened by a nurse."),
        ]
    )
    ans = inv.run_investigation(src, "LLZ", "viewer freeze", now=NOW)
    assert [q.mdr_report_key for q in ans.quotes] == ["3"]
    assert ans.dropped.quote_personal_details == 1 and ans.dropped.quote_wording == 1
    assert all(not forbidden_in(q.quote) for q in ans.quotes)


def test_a_long_sentence_is_cut_at_a_word_and_marked() -> None:
    long_text = "The viewer would freeze " + "and keep going " * 40 + "until it was restarted."
    src = StoredSource([_event("9", "20260701", long_text)])
    ans = inv.run_investigation(src, "LLZ", "viewer freeze", now=NOW)
    (q,) = ans.quotes
    assert q.truncated and len(q.quote) <= inv.QUOTE_MAX_CHARS
    assert normalize_text(q.quote) in normalize_text(long_text)


# --- who filed (F12) ------------------------------------------------------------------------


def test_reports_not_filed_by_a_manufacturer_are_counted_and_listed() -> None:
    src = StoredSource(
        [
            _event("1", "20260701", "Screen freeze on open.", source="Manufacturer report"),
            _event("2", "20260702", "Screen freeze on open.", source="User facility report"),
            _event("3", "20260703", "Screen freeze on open.", source="Voluntary report"),
            _event("4", "20260704", "Screen freeze on open.", source=None),
            _event("5", "20260705", "Other.", code="ZZZ", source="User facility report"),
        ]
    )
    ans = inv.run_investigation(src, "LLZ", "screen freeze", now=NOW)
    s = ans.sources
    assert s is not None
    assert s.manufacturer_count == 1 and s.non_manufacturer.value == 2 and s.no_source_count == 1
    assert [r.mdr_report_key for r in s.reports] == ["3", "2"]
    assert {r.source for r in s.reports} == {"user facility", "voluntary"}
    assert "report_source_code" in s.non_manufacturer.url


def test_own_company_reports_are_stated_as_not_separable(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    assert "cannot be separated" in ans.own_maker_note
    assert ans.notice.startswith("This is evidence assembled from public FDA data")
    assert "MaudeSignal determined" not in ans.model_dump_json()


# --- recalls and 510(k)s --------------------------------------------------------------------


def test_recalls_and_clearances_come_with_links_and_totals(stored: StoredSource) -> None:
    ans = inv.run_investigation(stored, "LLZ", DESC, now=NOW)
    assert ans.recalls.total and ans.recalls.total.value == len(
        [r for r in stored.recalls if r["product_code"] == "LLZ"]
    )
    assert 1 <= len(ans.recalls.items) <= 5
    assert all(
        i.url.startswith("https://api.fda.gov/device/recall.json") for i in ans.recalls.items
    )
    assert ans.clearances.total and ans.clearances.total.value > 0
    dates = [c.decision_date or "" for c in ans.clearances.items]
    assert dates == sorted(dates, reverse=True)


# --- failure handling -----------------------------------------------------------------------


class _Down:
    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        raise OpenFDAAPIError("boom")


class _PartlyDown(StoredSource):
    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        if query.endpoint.endswith("recall.json"):
            raise OpenFDARateLimitError("429")
        return super().run(query, timeout_s=timeout_s)


def test_main_count_failure_raises() -> None:
    with pytest.raises(inv.InvestigateError):
        inv.run_investigation(_Down(), "LLZ", DESC, now=NOW)


def test_a_failed_section_is_said_not_invented(stored: StoredSource) -> None:
    src = _PartlyDown(stored.events, stored.recalls, stored.k510)
    ans = inv.run_investigation(src, "LLZ", DESC, now=NOW)
    assert ans.recalls.total is None and ans.recalls.items == [] and ans.recalls.note
    assert ans.total_code_wide.value > 0


def test_unknown_code_gets_a_spelling_note() -> None:
    ans = inv.run_investigation(StoredSource([]), "QQQ", DESC, now=NOW)
    assert ans.total_code_wide.value == 0
    assert any("classification list has no product code QQQ" in n for n in ans.notes)


# --- the real HTTP source -------------------------------------------------------------------


def test_openfda_source_sends_the_key_as_a_parameter_never_in_the_link() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "classification" in str(req.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"meta": {"results": {"total": 7}}, "results": []})

    src = inv.OpenFdaSource("SECRETKEY", transport=httpx.MockTransport(handler))
    q = inv.event_query(inv.EventFilter("LLZ", "20260101", "20260131"))
    assert src.run(q).total == 7
    assert "api_key=SECRETKEY" in str(seen[0].url) and "SECRETKEY" not in q.url
    assert src.run(inv.classification_query("LLZ")) == inv.Reply(0, ())


@pytest.mark.parametrize("status", [403, 429, 503, 418])
def test_openfda_source_names_errors_without_the_url(status: int) -> None:
    src = inv.OpenFdaSource(None, transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(OpenFDAAPIError) as e:
        src.run(inv.recall_query("LLZ"))
    assert "api.fda.gov" not in str(e.value)


# --- the route ------------------------------------------------------------------------------


def make_client(
    source: Any,
    *,
    origins: tuple[str, ...] = (ORIGIN,),
    tmp: Path | None = None,
    state: ConnectorState | None = None,
) -> TestClient:
    settings = Settings(
        state=state or ConnectorState(),
        keys=KeyStore([]),
        limiter=RateLimiter(100),
        data=ConnectorData(work_dir=tmp),
        investigate_source=lambda: source,
        web_origins=origins,
        now=lambda: NOW,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def client(stored: StoredSource, tmp_path: Path) -> TestClient:
    return make_client(stored, tmp=tmp_path)


def test_route_returns_the_investigation_without_the_description(client: TestClient) -> None:
    r = client.post("/v1/investigate", json={"product_code": "llz", "description": DESC})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["product_code"] == "LLZ" and body["keywords"][:2] == ["manager", "save"]
    assert body["total_code_wide"]["value"] > body["total_keyword_matched"]["value"] > 0
    assert body["notice"].endswith("your team does.")
    assert DESC not in r.text and "description" not in body


def test_route_needs_no_key_and_is_documented(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/investigate"]["post"]
    assert op["operationId"] == "investigate" and "security" not in op
    assert "InvestigateAnswer" in json.dumps(op["responses"]["200"])
    assert "InvestigateRequest" in json.dumps(op["requestBody"])


@pytest.mark.parametrize(
    "description",
    [
        "Patient John Smith, DOB 03/04/1961, MRN 4455667 had the freeze",
        "Mrs. Jane Smith's viewer froze",
        "the 67-year-old patient's viewer froze",
        "email me at nurse@hospital.org about the freeze",
    ],
)
def test_patient_data_is_refused_and_nothing_is_searched(
    stored: StoredSource, tmp_path: Path, description: str
) -> None:
    calls: list[inv.Query] = []

    class Spy:
        def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
            calls.append(query)
            return stored.run(query, timeout_s=timeout_s)

    c = make_client(Spy(), tmp=tmp_path)
    r = c.post("/v1/investigate", json={"product_code": "LLZ", "description": description})
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert "Nothing was answered or kept" in r.json()["message"]
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"product_code": "LL", "description": DESC},
        {"product_code": "LLZ", "description": "abc"},
        {"product_code": "LLZ", "description": "x" * 501},
        {"product_code": "LLZ"},
        {"product_code": "LLZ", "description": DESC, "extra": 1},
    ],
)
def test_invalid_input_is_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/v1/investigate", json=body).status_code == 422


def test_openfda_down_is_502_and_audited_without_text(tmp_path: Path) -> None:
    c = make_client(_Down(), tmp=tmp_path)
    r = c.post("/v1/investigate", json={"product_code": "LLZ", "description": DESC})
    assert r.status_code == 502 and r.json()["code"] == "unavailable"


def test_per_hour_limit_is_429_with_retry_after(
    stored: StoredSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_INVESTIGATE_PER_HOUR", "2")
    c = make_client(stored, tmp=tmp_path)
    body = {"product_code": "LLZ", "description": DESC}
    assert [c.post("/v1/investigate", json=body).status_code for _ in range(2)] == [200, 200]
    r = c.post("/v1/investigate", json=body)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_per_day_limit_is_429(
    stored: StoredSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_INVESTIGATE_PER_DAY", "1")
    c = make_client(stored, tmp=tmp_path)
    body = {"product_code": "LLZ", "description": DESC}
    assert c.post("/v1/investigate", json=body).status_code == 200
    r = c.post("/v1/investigate", json=body)
    assert r.status_code == 429 and "Daily limit" in r.json()["message"]


def test_cors_allows_listed_origins_only(client: TestClient) -> None:
    body = {"product_code": "LLZ", "description": DESC}
    ok = client.post("/v1/investigate", json=body, headers={"Origin": ORIGIN})
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    bad = client.post("/v1/investigate", json=body, headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers
    pre = client.options(
        "/v1/investigate", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
    )
    assert pre.status_code == 204 and "POST" in pre.headers["access-control-allow-methods"]


def test_description_is_in_no_log_audit_entry_or_stored_record(
    stored: StoredSource,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    unique = "zxqvfrobnicate wobblegizmo"
    seen: list[str] = []

    class Spy:
        def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
            seen.append(query.url)
            return stored.run(query, timeout_s=timeout_s)

    state = ConnectorState()
    c = make_client(Spy(), tmp=tmp_path, state=state)
    r = c.post(
        "/v1/investigate",
        json={"product_code": "LLZ", "description": f"The viewer {unique} when saving"},
    )
    assert r.status_code == 200
    assert any("zxqvfrobnicate" in u for u in seen)  # openFDA is asked, as it must be
    out = capsys.readouterr()
    logged = out.out + out.err + caplog.text
    assert "zxqvfrobnicate" not in logged and "wobblegizmo" not in logged
    rows = state.audit_recent(10)
    assert len(rows) == 1 and rows[0]["action"] == "tool:investigate"
    audit = json.dumps(rows)
    assert "zxqvfrobnicate" not in audit and "wobblegizmo" not in audit
    payload = json.loads(rows[0]["payload_json"])
    assert set(payload["inputs"]) == {
        "product_code",
        "description_hmac",
        "description_length",
        "keyword_count",
    }
    assert re.fullmatch(r"[0-9a-f]{64}", payload["inputs"]["description_hmac"])
    assert payload["inputs"]["description_length"].isdigit()
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.stat().st_size < 5_000_000:
            assert b"zxqvfrobnicate" not in p.read_bytes()


def test_recorded_example_fixture_is_current() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "record_investigate_example", PROJECT_ROOT / "scripts" / "record_investigate_example.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    on_disk = json.loads(mod.OUT.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(mod.build()))
    assert on_disk["answer"]["mode"] == "recorded"
    assert mod.DESCRIPTION not in json.dumps(on_disk["answer"])


# --- review fixes ---------------------------------------------------------------------------


def test_zero_not_filed_by_manufacturer_is_not_linked_to_a_query_that_returns_reports() -> None:
    src = StoredSource([_event("1", "20260701", "Screen freeze on open.")])
    ans = inv.run_investigation(src, "LLZ", "screen freeze", now=NOW)
    s = ans.sources
    assert s is not None and s.non_manufacturer.value == 0 and s.non_manufacturer.url == ""
    assert s.manufacturer_count == 1 and s.buckets_url.startswith("https://api.fda.gov/")
    assert s.reports == []


def test_filer_type_that_cannot_go_into_a_query_is_not_counted_in_the_linked_number() -> None:
    odd = "User facility report 2"  # a digit: not allowed in a query value
    src = StoredSource(
        [
            _event("1", "20260701", "Screen freeze.", source="Voluntary report"),
            _event("2", "20260702", "Screen freeze.", source=odd),
        ]
    )
    s = inv.run_investigation(src, "LLZ", "screen freeze", now=NOW).sources
    assert s is not None and s.non_manufacturer.value == 1
    assert "Voluntary" in inv.event_search(
        inv.EventFilter("LLZ", "20251101", "20261027", sources=("Voluntary report",))
    )


class _Slow(StoredSource):
    """Every call takes 'seconds' of a fake clock."""

    def __init__(self, base: StoredSource, clock: list[float], per_call: float) -> None:
        super().__init__(base.events, base.recalls, base.k510)
        self.clock, self.per_call, self.timeouts = clock, per_call, []  # type: ignore[var-annotated]

    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        self.timeouts.append(timeout_s)
        self.clock[0] += self.per_call
        return super().run(query, timeout_s=timeout_s)


def test_time_limit_skips_the_calls_not_started_and_says_so(stored: StoredSource) -> None:
    clock = [0.0]
    slow = _Slow(stored, clock, per_call=30.0)
    ans = inv.run_investigation(slow, "LLZ", DESC, now=NOW, deadline_s=40.0, clock=lambda: clock[0])
    assert ans.total_code_wide.value > 0  # the first count ran
    assert any("time limit" in n for n in ans.notes)
    assert all(t is not None and t <= inv.CALL_TIMEOUT_S for t in slow.timeouts)


def test_first_count_failing_is_the_only_hard_error() -> None:
    clock = [100.0]
    with pytest.raises(inv.InvestigateError):
        inv.run_investigation(_Down(), "LLZ", DESC, now=NOW, clock=lambda: clock[0])


def test_deadline_is_clamped() -> None:
    b = inv.Budget(500.0, clock=lambda: 0.0)
    assert b.left() == inv.MAX_DEADLINE_S


class _Limited:
    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        raise OpenFDARateLimitError("429")


def test_openfda_429_is_its_own_message(tmp_path: Path) -> None:
    c = make_client(_Limited(), tmp=tmp_path)
    r = c.post("/v1/investigate", json={"product_code": "LLZ", "description": DESC})
    assert r.status_code == 503 and r.json()["code"] == "openfda_limited"
    assert "limiting requests just now" in r.json()["message"]


@pytest.mark.parametrize(
    "text",
    ["Patient name: Bob Jones viewer froze", "patient Name = Bob viewer froze", "Pt name Bob"],
)
def test_name_labels_are_refused(client: TestClient, text: str) -> None:
    r = client.post("/v1/investigate", json={"product_code": "LLZ", "description": text})
    assert r.status_code == 422 and r.json()["code"] == "patient_data"


def test_capitalised_name_pairs_never_become_keywords() -> None:
    got = inv.extract_keywords("viewer froze for Bob Jones during saving")
    assert "bob" not in got and "jones" not in got and "viewer" in got
    assert "smith" not in inv.extract_keywords("name: Smith viewer froze")


def test_audit_hash_is_keyed(stored: StoredSource) -> None:
    from maudesignal.connector.investigate_route import audit_inputs

    a = audit_inputs("LLZ", DESC, b"one")
    b = audit_inputs("LLZ", DESC, b"two")
    assert a["description_hmac"] != b["description_hmac"]
    import hashlib

    assert (
        a["description_hmac"] != hashlib.sha256(" ".join(DESC.split()).lower().encode()).hexdigest()
    )


def test_recall_reason_is_cut_on_a_word_boundary() -> None:
    assert inv._cut("alpha beta gamma delta", 12) == "alpha beta\u2026"
    assert inv._cut("short", 12) == "short"


def test_privacy_page_mentions_the_complaint_description() -> None:
    from maudesignal.connector.legal_pages import render_privacy

    html = render_privacy(
        rate_per_min=60,
        public_per_hour=10,
        shared_store=False,
        live_on=False,
        audit_full_text=False,
        clients_on=False,
        research_on=False,
    )
    assert "up to 6 words" in html and "keyed" in html


def test_wait_is_written_in_minutes() -> None:
    from maudesignal.connector.investigate_route import _wait_text

    assert _wait_text(600) == "10 minutes"
    assert _wait_text(45) == "45 seconds"
    assert _wait_text(7200) == "2 hours"


# --- integration review ---------------------------------------------------------------------


class _Boom:
    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        raise RuntimeError("secret detail the description must never reach")


def test_an_unexpected_error_is_a_json_500_with_cors_headers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c = make_client(_Boom(), tmp=tmp_path)
    r = c.post(
        "/v1/investigate",
        json={"product_code": "LLZ", "description": DESC},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    assert r.headers["access-control-allow-origin"] == ORIGIN
    out = capsys.readouterr()
    assert "manager" not in out.out + out.err
    other = c.post(
        "/v1/investigate",
        json={"product_code": "LLZ", "description": DESC},
        headers={"Origin": "https://evil.example"},
    )
    assert "access-control-allow-origin" not in other.headers


class _Sleepy(StoredSource):
    def run(self, query: inv.Query, *, timeout_s: float | None = None) -> inv.Reply:
        import time

        time.sleep(0.6)
        return super().run(query, timeout_s=timeout_s)


def test_one_slow_openfda_call_is_cut_at_its_wall_clock_cap(
    stored: StoredSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inv, "CALL_WALL_S", 0.1)
    slow = _Sleepy(stored.events, stored.recalls, stored.k510)
    with pytest.raises(OpenFDAAPIError):
        inv.Budget(30.0).call(slow, inv.recall_query("LLZ"))
    with pytest.raises(inv.InvestigateError):
        inv.run_investigation(slow, "LLZ", DESC, now=NOW)


def test_the_whole_search_has_an_outer_time_limit_and_answers_504_with_cors(
    stored: StoredSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maudesignal.connector import investigate_route as route

    monkeypatch.setenv("MAUDESIGNAL_INVESTIGATE_DEADLINE_S", "5")
    monkeypatch.setattr(route, "GRACE_S", -4.6)  # outer limit 0.4 s
    slow = _Sleepy(stored.events, stored.recalls, stored.k510)
    c = make_client(slow, tmp=tmp_path)
    r = c.post(
        "/v1/investigate",
        json={"product_code": "LLZ", "description": DESC},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 504 and r.json()["code"] == "investigate_timeout"
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_deadline_defaults_and_clamp() -> None:
    assert inv.DEFAULT_DEADLINE_S == 30.0 and inv.MAX_DEADLINE_S == 40.0
    assert inv.Budget(500.0, clock=lambda: 0.0).left() == 40.0


def test_openapi_lists_the_upstream_limit_and_timeout_answers(client: TestClient) -> None:
    op = client.get("/openapi.json").json()["paths"]["/v1/investigate"]["post"]
    assert {"422", "429", "502", "503", "504"} <= set(op["responses"])
