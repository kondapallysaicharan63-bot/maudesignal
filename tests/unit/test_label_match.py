"""Label reading -> possible openFDA matches -> device-type view (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDAForbiddenError
from maudesignal.gate import EvidenceStore
from maudesignal.monitor.deterioration import build_window
from maudesignal.monitor.live_check import LiveCheck, WindowCounts, classify_counts
from maudesignal.vision import label_match as lm

Row = dict[str, Any]
Responder = Callable[[str, str], list[Row]]

HOMEDICS_LABEL: dict[str, Any] = {
    "fields": {
        "device_name": {"value": "Non-contact Infrared Body Thermometer", "legibility": "clear"},
        "manufacturer": {"value": "HoMedics USA, LLC.", "legibility": "clear"},
        "model_number": {"value": "TIE-240", "legibility": "clear"},
        "k_number": {"value": "", "legibility": "not_present"},
        "udi": {"value": "", "legibility": "not_present"},
        "gtin": {"value": "", "legibility": "not_present"},
        "lot": {"value": "LOT-SECRET-1", "legibility": "clear"},
        "serial": {"value": "SN-SECRET-9", "legibility": "clear"},
    },
    "overall_legibility": "clear",
}


def hetaida(k: str, date_: str, name: str = "Non-contact Infrared Body Thermometer") -> Row:
    return {
        "k_number": k,
        "applicant": "Hetaida Technology Co., Ltd.",
        "device_name": name,
        "product_code": "FLL",
        "decision_date": date_,
    }


HETAIDA_ROWS = [
    hetaida("K203332", "2021-02-25", "Non-contact Infrared Body Thermometer, Model HTD8808C"),
    hetaida("K200159", "2021-01-05"),
    hetaida("K171888", "2018-07-23"),
]


class FakeSearcher:
    """Answers from a function; records every call."""

    def __init__(self, responder: Responder, fail: set[str] | None = None) -> None:
        self.responder = responder
        self.fail = fail or set()
        self.calls: list[tuple[str, str]] = []

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> lm.Answer:
        self.calls.append((endpoint, search))
        if endpoint in self.fail:
            raise OpenFDAAPIError("boom")
        rows = self.responder(endpoint, search)
        return lm.Answer(
            lm.public_url(endpoint, search, limit, sort), len(rows), tuple(rows), lm.utc_now(), 1.5
        )


def default_responder(endpoint: str, search: str) -> list[Row]:
    if endpoint == "510k" and "applicant:" not in search and "product_code:" not in search:
        return HETAIDA_ROWS
    if endpoint == "510k" and "product_code:FLL" in search:
        return [HETAIDA_ROWS[0]]
    if endpoint == "classification" and "product_code:FLL" in search:
        return [
            {
                "product_code": "FLL",
                "device_name": "Thermometer, Electronic, Clinical",
                "device_class": "2",
                "regulation_number": "880.2910",
            }
        ]
    if endpoint == "recall" and "product_code:FLL" in search:
        return [
            {
                "product_res_number": "Z-0001-2026",
                "res_event_number": "99001",
                "product_code": "FLL",
                "recalling_firm": "Acme Thermo",
                "product_description": "thermometer",
                "reason_for_recall": "label error",
                "event_date_initiated": "2026-03-02",
            }
        ]
    return []


def fake_check(code: str) -> LiveCheck:
    w = build_window(date(2026, 10, 20))
    counts = WindowCounts(
        current_total=5,
        baseline_total=8,
        prior_total=120,
        current_types=(("injury", 1), ("malfunction", 4)),
        baseline_types=(("injury", 1), ("malfunction", 7)),
        prior_types=(("injury", 10), ("malfunction", 100), ("death", 10)),
    )
    lc = classify_counts(code, counts, w)
    from dataclasses import replace

    return replace(
        lc,
        queries=(
            (
                "per day",
                f"https://api.fda.gov/device/event.json?search=a{code}&count=date_received",
            ),
            ("this week", f"https://api.fda.gov/device/event.json?search=b{code}&count=x"),
            ("baseline", f"https://api.fda.gov/device/event.json?search=c{code}&count=x"),
            ("before", f"https://api.fda.gov/device/event.json?search=d{code}&limit=1"),
            ("before types", f"https://api.fda.gov/device/event.json?search=e{code}&count=x"),
        ),
    )


# --- ranking and reasons -----------------------------------------------------------------


def test_homedics_label_does_not_show_hetaida_as_maker_match() -> None:
    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(default_responder))
    assert res["matches"], "name search still returns candidates"
    for m in res["matches"]:
        assert m["owner"].startswith("Hetaida")
        assert m["manufacturer_match"] is False
        assert not any("manufacturer name matches" in w for w in m["why_matched"])
        assert (
            "applicant differs: Hetaida Technology Co., Ltd. vs HoMedics USA, LLC. on the label"
            in m["why_not_matched"]
        )
    assert res["manufacturer_match_found"] is False
    assert "No record from 'HoMedics USA, LLC.'" in res["note"]
    assert res["status"] == "needs_person_to_confirm"
    assert res["confirmed"] is None


def test_maker_matches_rank_first_even_with_fewer_name_words() -> None:
    homedics = {
        "k_number": "K990001",
        "applicant": "HoMedics, Inc.",
        "device_name": "Infrared Thermometer TIE-240",
        "product_code": "FLL",
        "decision_date": "2019-05-01",
    }

    def responder(endpoint: str, search: str) -> list[Row]:
        if endpoint == "510k" and "applicant:" in search and "TIE-240" in search:
            return [homedics]
        return default_responder(endpoint, search)

    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(responder))
    top = res["matches"][0]
    assert top["record_id"] == "K990001"
    assert top["manufacturer_match"] is True
    assert "manufacturer name matches 'HoMedics USA, LLC.'" in top["why_matched"]
    assert "model TIE-240 appears in the 510(k) device name" in top["why_matched"]
    assert any(w.startswith("device name shares ") for w in top["why_matched"])
    assert res["manufacturer_match_found"] is True
    assert [m["manufacturer_match"] for m in res["matches"]] == [True, False, False]


def test_at_most_three_matches() -> None:
    rows = [hetaida(f"K10000{i}", f"2020-01-0{i}") for i in range(1, 9)]
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(lambda e, s: rows if e == "510k" else [])
    )
    assert len(res["matches"]) == lm.MAX_MATCHES == 3


def test_k_number_is_looked_up_first_and_flagged_exact() -> None:
    label = {
        "fields": {
            "k_number": {"value": "k 203332", "legibility": "clear"},
            "manufacturer": {"value": "Hetaida Technology Co., Ltd.", "legibility": "clear"},
            "device_name": {
                "value": "Non-contact Infrared Body Thermometer",
                "legibility": "clear",
            },
        }
    }
    s = FakeSearcher(
        lambda e, q: [HETAIDA_ROWS[0]] if e == "510k" and "k_number:K203332" in q else []
    )
    res = lm.match_label(label, searcher=s)
    assert res["search_basis"] == "k_number"
    assert s.calls[0] == ("510k", "k_number:K203332")
    m = res["matches"][0]
    assert m["record_id"] == "K203332" and m["manufacturer_match"] is True
    assert "K-number K203332 printed on the label equals this record" in m["why_matched"]
    assert res["status"] == "needs_person_to_confirm" and res["confirmed"] is None


def test_gtin_goes_to_udi_endpoint() -> None:
    label = {
        "fields": {
            "gtin": {"value": "00614141999996", "legibility": "clear"},
            "manufacturer": {"value": "Acme Devices", "legibility": "clear"},
        }
    }
    udi = {
        "public_device_record_key": "key-1",
        "brand_name": "Acme Probe",
        "company_name": "Acme Devices, Inc.",
        "version_or_model_number": "AP-1",
        "identifiers": [{"id": "00614141999996", "type": "Primary"}],
        "product_codes": [{"code": "ABC", "name": "Probe, Thing"}],
    }
    s = FakeSearcher(lambda e, q: [udi] if e == "udi" else [])
    res = lm.match_label(label, searcher=s)
    assert res["search_basis"] == "gtin"
    assert s.calls[0][0] == "udi"
    m = res["matches"][0]
    assert m["source"] == "udi" and m["product_code"] == "ABC"
    assert any(w.startswith("GTIN 614141999996") or "GTIN" in w for w in m["why_matched"])


def test_invalid_gtin_is_not_searched() -> None:
    label = {"fields": {"gtin": {"value": "00614141999990", "legibility": "clear"}}}
    s = FakeSearcher(lambda e, q: [])
    res = lm.match_label(label, searcher=s)
    assert s.calls == []
    assert res["matches"] == [] and res["status"] == "no_match_found"


def test_registration_listing_is_searched_and_scored() -> None:
    listing = {
        "proprietary_name": ["TIE-240 thermometer"],
        "registration": {
            "registration_number": "3001234567",
            "owner_operator": {"firm_name": "HoMedics, LLC"},
        },
        "products": [
            {"product_code": "FLL", "openfda": {"device_name": "Thermometer, Electronic, Clinical"}}
        ],
    }
    s = FakeSearcher(lambda e, q: [listing] if e == "registrationlisting" else [])
    res = lm.match_label(HOMEDICS_LABEL, searcher=s)
    m = res["matches"][0]
    assert m["source"] == "registrationlisting" and m["record_id"] == "3001234567"
    assert m["manufacturer_match"] is True
    assert {e for e, _ in s.calls} >= {"510k", "registrationlisting", "classification"}


def test_nothing_matches_says_so_plainly() -> None:
    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(lambda e, q: []))
    assert res["matches"] == []
    assert res["note"] == "No openFDA record matched what was read from this label."
    assert res["status"] == "no_match_found" and res["confirmed"] is None
    assert res["device_type_views"] == {}


def test_empty_reading_has_nothing_to_search() -> None:
    s = FakeSearcher(lambda e, q: [])
    res = lm.match_label({"fields": {}}, searcher=s)
    assert s.calls == []
    assert "nothing to search" in res["note"]


def test_unrelated_records_are_dropped() -> None:
    other = {
        "k_number": "K555555",
        "applicant": "Other Co",
        "device_name": "Hip Implant Stem",
        "product_code": "XYZ",
        "decision_date": "2020-01-01",
    }
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(lambda e, q: [other] if e == "510k" else [])
    )
    assert res["matches"] == []


def test_openfda_failure_is_reported_not_raised() -> None:
    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(default_responder, fail={"510k"}))
    assert res["matches"] == []
    assert any(q["ok"] is False and q["error"] == "OpenFDAAPIError" for q in res["queries"])
    assert all(
        s["elapsed_ms"] is None for s in res["trace"] if s.get("error") and s["model"] == "openFDA"
    )


# --- confirm ------------------------------------------------------------------------------


def test_confirm_records_the_person_and_choice() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    assert lm.confirmed_view(res) is None
    done = lm.confirm(res, 1, "  Dana  Reviewer ", when_utc="2026-10-30T10:00:00Z")
    assert res["confirmed"] is None, "the input is not modified"
    assert done["status"] == "confirmed_by_person"
    c = done["confirmed"]
    assert c["person"] == "Dana Reviewer" and c["index"] == 1
    assert c["record_id"] == res["matches"][1]["record_id"]
    assert c["confirmed_utc"] == "2026-10-30T10:00:00Z"
    view = lm.confirmed_view(done)
    assert view is not None and view["product_code"] == "FLL"


def test_confirm_none_of_these_and_validation() -> None:
    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(default_responder))
    none = lm.confirm(res, None, "Dana")
    assert none["confirmed"]["none_of_these"] is True
    assert lm.confirmed_view(none) is None
    with pytest.raises(ValueError):
        lm.confirm(res, 0, "   ")
    with pytest.raises(ValueError):
        lm.confirm(res, 7, "Dana")
    with pytest.raises(ValueError):
        lm.confirm(res, -1, "Dana")


# --- device-type view, gate, withheld text ----------------------------------------------------


def test_device_type_view_facts_are_gated_or_recomputed() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    view = res["device_type_views"]["FLL"]
    assert view["device_type_name"] == "Thermometer, Electronic, Clinical"
    by = {f["topic"]: f for f in view["facts"]}
    assert by["recalls_total"]["check"] == "gate" and by["recalls_total"]["status"] == "pass"
    assert by["recalls_latest"]["check"] == "gate"
    assert by["clearances_latest"]["check"] == "gate"
    assert by["reports_window"]["check"] == "recomputed"
    assert by["this_week_change"]["status"] == "pass"
    assert view["summary"]["recalls_total"]["total"] == 1
    assert view["summary"]["reports_window"]["count"] == 5
    for f in view["facts"]:
        assert f["status"] == "pass" and f["query_url"].startswith("https://api.fda.gov/")


def test_this_week_change_matches_detector_rules() -> None:
    lc = fake_check("FLL")
    assert lm.recompute_change(lc) == lc.classification
    w = build_window(date(2026, 10, 20))
    spike = classify_counts(
        "FLL",
        WindowCounts(
            9, 4, 50, (("malfunction", 9),), (("malfunction", 4),), (("malfunction", 50),)
        ),
        w,
    )
    assert spike.classification == "spike" == lm.recompute_change(spike)


def test_failed_fact_is_withheld_and_text_never_stored() -> None:
    store = EvidenceStore.from_iterables([])
    secret = (
        "Most recent recall under FLL on openFDA: Z-9999-2099 (Phantom Corp, started 2099-01-01)."
    )
    from maudesignal.gate import RecallClaim

    bad = lm.FactDraft(
        "FLL:recalls_latest",
        "recalls_latest",
        secret,
        "https://api.fda.gov/device/recall.json?search=product_code:FLL&limit=1",
        {"recall_number": "Z-9999-2099", "firm": "Phantom Corp"},
        claims=[RecallClaim(recall_number="Z-9999-2099", product_code="FLL")],
    )
    failing = lm.FactDraft(
        "FLL:reports_total",
        "reports_total",
        "MAUDE holds 77777 reports.",
        None,
        {"total": 77777},
        recheck=lambda: False,
    )
    out = lm.check_facts([bad, failing], store)
    assert [f["status"] for f in out] == ["withheld", "withheld"]
    blob = json.dumps(out)
    for needle in ("Z-9999-2099", "Phantom", "77777", "2099", "MAUDE holds"):
        assert needle not in blob
    assert out[0]["text"] is None and out[0]["data"] is None
    assert out[0]["reason"] == lm.WITHHELD_REASON


def test_withheld_fact_inside_a_full_result_is_not_in_the_json() -> None:
    def tampered(endpoint: str, search: str) -> list[Row]:
        rows = default_responder(endpoint, search)
        if endpoint == "510k" and "product_code:FLL" in search:
            # a K-number that the stored 510(k) row contradicts (wrong product code)
            return [{**rows[0], "k_number": "K424242", "product_code": "ZZZ"}]
        return rows

    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(tampered), check_fn=fake_check)
    facts = {f["topic"]: f for f in res["device_type_views"]["FLL"]["facts"]}
    assert facts["clearances_latest"]["status"] == "withheld"
    assert "K424242" not in json.dumps(res["device_type_views"]["FLL"])


def test_maude_check_failure_marks_reports_unavailable() -> None:
    def broken(code: str) -> LiveCheck:
        raise OpenFDAForbiddenError("403")

    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=broken)
    facts = {f["topic"]: f for f in res["device_type_views"]["FLL"]["facts"]}
    assert facts["reports_total"]["status"] == "unavailable"
    assert facts["reports_total"]["text"] is None


# --- trace and timings ---------------------------------------------------------------------------


def test_trace_has_steps_in_order_and_null_when_not_measured() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    steps = res["trace"]
    assert steps[0]["step"] == "SAM 3.1 crop" and steps[0]["model"] == "SAM 3.1"
    assert steps[1]["step"] == "Muse Spark read" and steps[1]["model"] == "Muse Spark"
    for s in steps[:2]:
        assert s["elapsed_ms"] is None and s["started_utc"] is None
        assert s["timing"] == "not recorded"
    assert steps[-2]["step"] == "Gate check" and steps[-2]["model"] == "gate"
    assert steps[-2]["elapsed_ms"] is not None and steps[-2]["elapsed_ms"] >= 0
    assert steps[-1]["step"] == "Done"
    searches = [s for s in steps if s["model"] == "openFDA"]
    assert searches and all(s["step"].startswith("openFDA search") for s in searches)
    assert all(
        s["count"] is not None and s["url"].startswith("https://api.fda.gov/") for s in searches
    )
    assert {s["model"] for s in steps} <= {"SAM 3.1", "Muse Spark", "openFDA", "gate"}


def test_measured_read_steps_are_passed_through_untouched() -> None:
    read = [
        {
            "step": "SAM 3.1 crop",
            "model": "SAM 3.1",
            "started_utc": "2026-10-30T10:00:00Z",
            "elapsed_ms": 812.4,
            "timing": "measured",
        },
        {
            "step": "Muse Spark read",
            "model": "Muse Spark",
            "started_utc": "2026-10-30T10:00:01Z",
            "elapsed_ms": 9100.0,
            "timing": "measured",
            "input_tokens": 100,
            "output_tokens": 50,
        },
    ]
    res = lm.match_label(HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), read_steps=read)
    assert res["trace"][0]["elapsed_ms"] == 812.4
    assert res["trace"][1]["output_tokens"] == 50


def test_all_query_urls_are_public_openfda_urls() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    urls = [q["url"] for q in res["queries"]] + [m["query_url"] for m in res["matches"]]
    assert urls and all(u.startswith("https://api.fda.gov/") for u in urls)
    assert all("api_key" not in u for u in urls)


def test_lot_and_serial_never_stored() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    blob = json.dumps(res)
    assert "LOT-SECRET" not in blob and "SN-SECRET" not in blob
    assert "lot" not in res["label"]["fields"] and "serial" not in res["label"]["fields"]
    assert res["label"]["session_fields_omitted"] is True


def test_no_forbidden_words_in_generated_text() -> None:
    res = lm.match_label(
        HOMEDICS_LABEL, searcher=FakeSearcher(default_responder), check_fn=fake_check
    )
    blob = json.dumps(res).lower()
    for word in (
        "fda-approved",
        "part 11",
        "validated",
        " safe",
        "unsafe",
        "compliant",
        "overnight",
        "worsening signals",
        "citation-checked",
        "complaint data",
    ):
        assert word not in blob, word


# --- real searcher (mock transport) ----------------------------------------


def test_openfda_searcher_sends_user_agent_and_hides_key() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "k_number" in str(req.url):
            return httpx.Response(
                200, json={"meta": {"results": {"total": 1}}, "results": [{"k_number": "K1"}]}
            )
        if "nothing" in str(req.url):
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(403, text="blocked body")

    with lm.OpenFdaSearcher("SECRETKEY", transport=httpx.MockTransport(handler)) as s:
        a = s.query("510k", "k_number:K123456", limit=1)
        assert a.total == 1 and a.elapsed_ms is not None
        assert a.url.startswith("https://api.fda.gov/device/510k.json?search=k_number:K123456")
        assert "SECRETKEY" not in a.url
        assert "api_key=SECRETKEY" in str(seen[0].url)
        assert "MaudeSignal" in seen[0].headers["user-agent"]
        assert s.query("510k", "device_name:nothing").results == ()
        with pytest.raises(OpenFDAForbiddenError) as err:
            s.query("510k", "device_name:blocked")
        assert "blocked body" not in str(err.value)


def test_plan_queries_put_maker_searches_first() -> None:
    inp = lm.inputs_from_reading(HOMEDICS_LABEL)
    plan = lm.plan_queries(inp)
    assert plan[0].id == "510k-maker-model"
    assert plan[0].search == 'applicant:"homedics"+AND+device_name:"TIE-240"'
    ids = [q.id for q in plan]
    assert ids.index("510k-maker-name") < ids.index("510k-name")
    assert {q.endpoint for q in plan} == {"510k", "registrationlisting"}


def test_read_label_timed_measures_sam_and_spark_separately() -> None:
    from maudesignal.vision import sam
    from tests.unit.test_vision import (
        LABEL_BOX,
        LABEL_PNG,
        FakeClient,
        label_payload,
        sam_transport,
    )

    client = FakeClient([label_payload()])
    with sam.SamClient("k", transport=sam_transport({"label": LABEL_BOX})) as s:
        result, steps = lm.read_label_timed(LABEL_PNG.read_bytes(), client=client, sam=s)
    sam_step, spark_step = steps
    assert sam_step["step"] == "SAM 3.1 crop" and sam_step["timing"] == "measured"
    assert isinstance(sam_step["elapsed_ms"], float) and sam_step["elapsed_ms"] >= 0
    assert spark_step["step"] == "Muse Spark read" and spark_step["timing"] == "measured"
    assert spark_step["elapsed_ms"] >= 0
    assert spark_step["input_tokens"] == result.input_tokens
    assert result.product_code is None, "openFDA is not called by the read step"


def test_read_label_timed_without_sam_marks_it_not_recorded() -> None:
    from tests.unit.test_vision import LABEL_PNG, FakeClient, label_payload

    result, steps = lm.read_label_timed(
        LABEL_PNG.read_bytes(), client=FakeClient([label_payload()]), sam=None
    )
    assert steps[0]["elapsed_ms"] is None and steps[0]["timing"] == "not recorded"
    assert steps[1]["timing"] == "measured"
    assert result.fields["device_name"].value
