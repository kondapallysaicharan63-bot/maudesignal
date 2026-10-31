"""Tests for the lookup_device connector tool (HACKATHON-BUILT). No network, no model.

openFDA is replaced by a fake searcher that serves canned rows and counts, so every case
(K-number, UDI / GTIN, fuzzy name + maker, no match, openFDA down, the 3-match cap, the
always-null ``confirmed``, MCP schema, demo key, rate limit) runs offline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDAUnavailableError  # noqa: E402
from maudesignal.connector import lookup  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.errors import InvalidInputError  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.lookup import Answer, public_url  # noqa: E402
from maudesignal.connector.models import ADVISORY, LookupAnswer  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.vision.label import gtin_check_digit_ok  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
H = {"X-API-Key": KEY}
DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"


def _gtin(body13: str) -> str:
    """A GTIN-14 with a valid GS1 check digit."""
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


GTIN = _gtin("0038074000000")
assert gtin_check_digit_ok(GTIN)

ROW_802 = {
    "k_number": "K123456",
    "applicant": "Welch Allyn, Inc.",
    "device_name": "Welch Allyn 802 LTR Spot Vital Signs Monitor",
    "product_code": "DXN",
    "decision_date": "2021-03-10",
}


def row(k: str, applicant: str, name: str, code: str = "DXN", date: str = "2020-01-01") -> dict:
    return {
        "k_number": k,
        "applicant": applicant,
        "device_name": name,
        "product_code": code,
        "decision_date": date,
    }


class FakeSearcher:
    """Serves canned openFDA answers by endpoint; records every query."""

    def __init__(
        self,
        *,
        k510: list[dict[str, Any]] | None = None,
        udi: list[dict[str, Any]] | None = None,
        listing: list[dict[str, Any]] | None = None,
        recalls: int = 3,
        reports: int = 1234,
        fail: Exception | None = None,
        fail_endpoints: tuple[str, ...] = (),
    ) -> None:
        self.rows = {"510k": k510 or [], "udi": udi or [], "registrationlisting": listing or []}
        self.recalls, self.reports = recalls, reports
        self.fail, self.fail_endpoints = fail, fail_endpoints
        self.calls: list[tuple[str, str]] = []

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> Answer:
        self.calls.append((endpoint, search))
        if self.fail is not None or endpoint in self.fail_endpoints:
            raise self.fail or OpenFDAUnavailableError("openFDA server error 503")
        url = public_url(endpoint, search, limit, sort)
        if endpoint == "recall":
            return Answer(url, self.recalls, ())
        if endpoint == "event":
            return Answer(url, self.reports, ())
        if endpoint == "classification":
            return Answer(url, 1, ({"product_code": "DXN", "device_name": "Monitor, Vital Signs"},))
        rows = self.rows[endpoint]
        if endpoint == "510k" and search.startswith("k_number:"):
            k = search.split(":", 1)[1]
            rows = [r for r in rows if r["k_number"] == k]
        return Answer(url, len(rows), tuple(rows[:limit]))


def run(searcher: FakeSearcher, **kw: Any) -> LookupAnswer:
    return lookup.lookup_device(searcher=searcher, live_checker=fake_check, now=lambda: NOW, **kw)


# --- the tool --------------------------------------------------------------------------------


def test_k_number_exact_match() -> None:
    s = FakeSearcher(k510=[ROW_802, row("K999999", "Other Co", "Other thing")])
    a = run(s, k_number="k 123456")
    assert a.status == "needs_person_to_confirm"
    assert a.confirmed is None
    assert [m.k_number for m in a.matches] == ["K123456"]
    m = a.matches[0]
    assert m.exact_id == "k_number" and m.rank == 1
    assert any("K-number K123456" in t for t in m.why_matched)
    assert m.applicant == "Welch Allyn, Inc." and m.product_code == "DXN"
    assert m.decision_date == "2021-03-10"
    assert m.links[0].url.startswith("https://api.fda.gov/device/510k.json?search=k_number")
    assert a.searched_with == ["k_number"]
    # an id match stops the broader name searches
    assert all(ep != "registrationlisting" for ep, _ in s.calls)
    assert "possible match" in a.speakable and "A person confirms" in a.speakable


def test_device_type_context_for_the_top_product_code() -> None:
    a = run(FakeSearcher(k510=[ROW_802]), k_number="K123456")
    assert len(a.device_types) == 1
    dt = a.device_types[0]
    assert dt.product_code == "DXN" and dt.device_type_name == "Monitor, Vital Signs"
    # same deterministic check as check_device_type (fake_check: 5 reports vs 4 before)
    assert dt.this_week_change and dt.this_week_reports == 5
    assert dt.recent_recalls_count == 3 and dt.recent_recalls_link.startswith("https://")
    assert "recall.json" in dt.recent_recalls_link
    assert "event_date_initiated" in dt.recent_recalls_link
    assert dt.report_count == 1234 and "event.json" in dt.report_count_link
    assert "September 1, 2026" in " ".join(f.text for f in a.facts)


def test_udi_and_gtin_match() -> None:
    udi_row = {
        "public_device_record_key": "abc-123",
        "company_name": "Welch Allyn",
        "brand_name": "Spot Monitor",
        "version_or_model_number": "802",
        "identifiers": [{"id": GTIN}],
        "product_codes": [{"code": "DXN"}],
    }
    other = dict(udi_row, public_device_record_key="zzz", identifiers=[{"id": "99999999999999"}])
    printed = f"(01){GTIN}(17)261231(10)LOT77"
    for kw in ({"udi": printed}, {"gtin": GTIN}, {"gtin": GTIN.lstrip("0")}):
        a = run(FakeSearcher(udi=[udi_row, other]), **kw)
        assert a.status == "needs_person_to_confirm", kw
        top = a.matches[0]
        assert top.source == "udi" and top.record_id == "abc-123" and top.k_number is None
        assert top.exact_id == "gtin"
        assert any("GTIN" in t for t in top.why_matched)
        assert a.confirmed is None
    # the lot number never reaches a query or the answer
    s = FakeSearcher(udi=[udi_row])
    out = run(s, udi=printed).model_dump_json()
    assert "LOT77" not in out and all("LOT77" not in q for _, q in s.calls)


def test_bad_gtin_is_dropped_with_a_note_when_other_inputs_exist() -> None:
    a = run(FakeSearcher(k510=[ROW_802]), device_name="Welch Allyn 802", gtin="12345678901234")
    assert a.note and "check digit" in a.note
    assert "udi_or_gtin" not in a.searched_with
    with pytest.raises(InvalidInputError):
        run(FakeSearcher(), gtin="12345678901234")


def test_name_and_manufacturer_fuzzy_with_mismatch_reasons() -> None:
    s = FakeSearcher(
        k510=[
            ROW_802,
            row("K111111", "Acme Instruments LLC", "Spot Vital Signs 802 LTR Monitor"),
            row("K222222", "Welch Allyn, Inc.", "Thermometer 9000"),
        ]
    )
    a = run(s, device_name="Welch Allyn 802 LTR", manufacturer="Welch Allyn", model="802")
    assert a.status == "needs_person_to_confirm"
    by_k = {m.k_number: m for m in a.matches}
    assert a.matches[0].k_number == "K123456"  # maker match + model + name outranks the rest
    assert any("manufacturer name matches" in t for t in by_k["K123456"].why_matched)
    other = by_k["K111111"]
    assert any("applicant differs" in t for t in other.why_not_matched)
    assert any("model 802 appears" in t for t in other.why_matched)
    assert a.confirmed is None and all(m.exact_id is None for m in a.matches)
    text = " ".join(f.text for f in a.facts)
    assert "Did not match on" in text and "applicant differs" in text


def test_no_match_found() -> None:
    a = run(FakeSearcher(), device_name="Zorblax Quantum Widget", manufacturer="Nobody Inc")
    assert a.status == "no_match_found"
    assert a.matches == [] and a.device_types == [] and a.confirmed is None
    assert "no possible matches" in a.speakable and "A person confirms" in a.speakable
    assert a.facts and all(f.link.startswith("https://") for f in a.facts)


def test_k_number_not_on_openfda_is_a_note_not_a_guess() -> None:
    a = run(FakeSearcher(), k_number="K555555")
    assert a.status == "no_match_found" and "K555555" in (a.note or "")


def test_openfda_down_is_search_failed_with_a_note() -> None:
    a = run(
        FakeSearcher(fail=OpenFDAUnavailableError("openFDA server error 503")), k_number="K123456"
    )
    assert a.status == "search_failed" and a.confirmed is None and a.matches == []
    assert a.note and "unavailable" in a.note
    assert "could not be reached" in a.speakable and "A person confirms" in a.speakable
    assert a.provenance.kind == "live_openfda"


def test_partial_failure_still_returns_matches_and_says_so() -> None:
    s = FakeSearcher(k510=[ROW_802], fail_endpoints=("registrationlisting",))
    a = run(s, device_name="Welch Allyn 802 LTR", manufacturer="Welch Allyn")
    assert a.status == "needs_person_to_confirm"
    assert a.note and "failed" in a.note


def test_device_type_failures_do_not_hide_the_matches() -> None:
    s = FakeSearcher(k510=[ROW_802], fail_endpoints=("recall", "event", "classification"))
    a = run(s, k_number="K123456")
    dt = a.device_types[0]
    assert a.status == "needs_person_to_confirm"
    assert dt.recent_recalls_count is None and dt.report_count is None
    assert dt.note and "could not" in dt.note


def test_live_check_failure_is_a_note() -> None:
    def down(_: str) -> Any:
        raise OpenFDAAPIError("HTTP error")

    a = lookup.lookup_device(
        k_number="K123456",
        searcher=FakeSearcher(k510=[ROW_802]),
        live_checker=down,
        now=lambda: NOW,
    )
    assert a.device_types[0].this_week_change is None
    assert "could not be checked" in (a.device_types[0].note or "")


def test_at_most_three_matches() -> None:
    rows = [row(f"K10000{i}", "Welch Allyn", f"Spot Monitor model {i}") for i in range(7)]
    a = run(FakeSearcher(k510=rows), device_name="Spot Monitor", manufacturer="Welch Allyn")
    assert len(a.matches) == 3
    assert [m.rank for m in a.matches] == [1, 2, 3]
    assert len(a.device_types) <= 2


def test_product_code_only_lists_newest_510ks() -> None:
    a = run(FakeSearcher(k510=[ROW_802]), product_code="dxn")
    assert a.matches and any("product code DXN equals" in t for t in a.matches[0].why_matched)


def test_no_input_is_invalid() -> None:
    with pytest.raises(InvalidInputError):
        run(FakeSearcher())
    with pytest.raises(InvalidInputError):
        run(FakeSearcher(), device_name="   ", model="")


def test_every_fact_has_an_https_link_and_no_forbidden_term() -> None:
    a = run(FakeSearcher(k510=[ROW_802]), k_number="K123456")
    assert a.facts and all(f.link.startswith("https://api.fda.gov/") for f in a.facts)
    assert forbidden_in(json.dumps(a.model_dump())) == []
    assert a.advisory == ADVISORY


def test_forbidden_words_in_source_text_are_left_out() -> None:
    bad = row("K777777", "Acme", "Officially approved Spot Monitor")
    a = run(FakeSearcher(k510=[bad]), k_number="K777777")
    assert forbidden_in(json.dumps(a.model_dump())) == []
    assert a.matches[0].device_name and "text left out" in a.matches[0].device_name


def test_control_characters_are_stripped_and_quotes_cannot_break_a_query() -> None:
    s = FakeSearcher(k510=[ROW_802])
    run(s, device_name='Spot"\n+AND+x:y (injection)\x00', manufacturer="Welch Allyn")
    for _, q in s.calls:
        assert "\n" not in q and "\x00" not in q and '"+AND+x' not in q


def test_the_real_searcher_builds_public_urls_without_a_key() -> None:
    import httpx

    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"meta": {"results": {"total": 1}}, "results": [ROW_802]})

    s = lookup.OpenFdaSearcher("SECRETKEY", transport=httpx.MockTransport(handler))
    ans = s.query("510k", "k_number:K123456", limit=1)
    assert "SECRETKEY" in seen[0] and "SECRETKEY" not in ans.url
    assert ans.total == 1 and ans.results[0]["k_number"] == "K123456"
    down = lookup.OpenFdaSearcher(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    )
    with pytest.raises(OpenFDAUnavailableError):
        down.query("510k", "k_number:K1")
    none = lookup.OpenFdaSearcher(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, json={}))
    )
    assert none.query("510k", "k_number:K1").total == 0


# --- REST, MCP, keys, limits ------------------------------------------------------------------


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("lookup"))


def make_client(
    data: ConnectorData,
    tmp_path: Path,
    *,
    searcher: FakeSearcher | None = None,
    limit: int = 100,
    demo: str = "",
) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env(
            {
                "MAUDESIGNAL_API_KEYS": KEY,
                "MAUDESIGNAL_DEMO_KEYS": demo,
                "MAUDESIGNAL_KEY_PEPPER": "p",
            }
        ),
        limiter=RateLimiter(limit),
        demo_limiter=RateLimiter(limit),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=fake_check,
        lookup_searcher=searcher or FakeSearcher(k510=[ROW_802]),
        now=lambda: NOW,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_rest_returns_the_lookup_shape(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/lookup_device", params={"k_number": "K123456"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "lookup_device" and body["confirmed"] is None
    assert "confirmed" in body  # present and null, not omitted
    assert body["status"] == "needs_person_to_confirm"
    assert body["matches"][0]["why_matched"] and "why_not_matched" in body["matches"][0]
    assert body["device_types"][0]["product_code"] == "DXN"
    assert body["advisory"] == ADVISORY
    LookupAnswer.model_validate(body)


def test_rest_needs_a_key_and_an_input(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    assert c.get("/v1/tools/lookup_device", params={"model": "802"}).status_code == 401
    r = c.get("/v1/tools/lookup_device", headers=H)
    assert r.status_code == 422 and "at least one" in r.json()["error"]["message"]
    bad = c.get("/v1/tools/lookup_device", params={"k_number": "12345"}, headers=H)
    assert bad.status_code == 422
    long = c.get("/v1/tools/lookup_device", params={"device_name": "x" * 201}, headers=H)
    assert long.status_code == 422
    assert c.post("/v1/tools/lookup_device", headers=H).status_code == 405  # read-only


def test_rest_openfda_down_is_200_search_failed(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, searcher=FakeSearcher(fail=OpenFDAUnavailableError("503")))
    r = c.get("/v1/tools/lookup_device", params={"model": "802 LTR"}, headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "search_failed" and r.json()["confirmed"] is None


def test_demo_key_works_and_never_needs_the_model(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, demo=DEMO)
    r = c.get(
        "/v1/tools/lookup_device", params={"k_number": "K123456"}, headers={"X-API-Key": DEMO}
    )
    assert r.status_code == 200 and r.json()["status"] == "needs_person_to_confirm"
    assert r.json()["provenance"]["kind"] == "live_openfda"


def test_rate_limit_applies(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, limit=2)
    codes = [
        c.get("/v1/tools/lookup_device", params={"k_number": "K123456"}, headers=H).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_mcp_lists_and_calls_the_tool(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)

    def rpc(method: str, params: dict[str, Any] | None = None) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        return c.post("/mcp", json=body, headers=H).json()

    tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
    t = tools["lookup_device"]
    props = t["inputSchema"]["properties"]
    assert set(props) == {
        "device_name",
        "model",
        "manufacturer",
        "k_number",
        "udi",
        "gtin",
        "product_code",
    }
    assert t["inputSchema"]["required"] == [] and t["inputSchema"]["additionalProperties"] is False
    assert t["annotations"]["readOnlyHint"] is True and t["annotations"]["destructiveHint"] is False
    out = t["outputSchema"]
    assert {"status", "confirmed", "matches", "device_types"} <= set(out["properties"])
    assert tools["recalls"]["outputSchema"] != out  # the other tools keep the common schema

    args = {"device_name": "Welch Allyn 802 LTR", "manufacturer": "Welch Allyn"}
    res = rpc("tools/call", {"name": "lookup_device", "arguments": args})["result"]
    rest = c.get("/v1/tools/lookup_device", params=args, headers=H).json()
    assert res["isError"] is False
    assert res["structuredContent"] == rest
    assert res["content"] == [{"type": "text", "text": rest["speakable"]}]
    empty = rpc("tools/call", {"name": "lookup_device", "arguments": {}})["result"]
    assert empty["isError"] is True and "at least one" in empty["content"][0]["text"]
    extra = rpc("tools/call", {"name": "lookup_device", "arguments": {"x": "1"}})["result"]
    assert extra["isError"] is True
    notstr = rpc("tools/call", {"name": "lookup_device", "arguments": {"model": 5}})["result"]
    assert notstr["isError"] is True


def test_audit_entry_has_inputs_but_never_the_key(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    c.get("/v1/tools/lookup_device", params={"device_name": "Spot " + "z" * 150}, headers=H)
    rows = c.get("/v1/audit/recent", params={"limit": 5}, headers=H).json()["entries"]
    mine = [r for r in rows if r["action"] == "tool:lookup_device"]
    assert mine and KEY not in json.dumps(rows)
    inputs = json.loads(mine[-1]["payload_json"])["inputs"]
    assert len(inputs["device_name"]) == 100  # truncated in the audit log
