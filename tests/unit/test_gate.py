"""Tests for the claim-level citation gate (HACKATHON-BUILT).

The adversarial set in tests/fixtures/gate/adversarial.jsonl covers fabricated
and drifted quotes, real quotes pinned to the wrong report, stale and inflated
numbers, fake / mismatched 510(k) numbers, hallucinated and superseded CFR
sections, and checkable mentions with no claim attached. The gate must produce
zero false passes and zero false blocks on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from maudesignal.gate import (
    ClaimParseError,
    DeviceRef,
    EvidenceRecord,
    EvidenceStore,
    LiteratureRef,
    QuoteClaim,
    RecallRef,
    RegulationClaim,
    claim_from_dict,
    verify,
    verify_answer,
    verify_sentence,
)
from maudesignal.gate.cfr import find_cfr_citations

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gate"


def _load_store() -> EvidenceStore:
    data = json.loads((FIXTURES / "store.json").read_text())
    return EvidenceStore.from_iterables(
        (EvidenceRecord(**r) for r in data["records"]),
        (DeviceRef(**d) for d in data["devices"]),
        recalls=(
            RecallRef(**{**r, "k_numbers": tuple(r.get("k_numbers", ()))})
            for r in data.get("recalls", [])
        ),
        clearances=(DeviceRef(**d) for d in data.get("clearances", [])),
        literature=(LiteratureRef(**a) for a in data.get("literature", [])),
    )


def _load_cases() -> list[dict[str, Any]]:
    lines = (FIXTURES / "adversarial.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


STORE = _load_store()
CASES = _load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_adversarial_case(case: dict[str, Any]) -> None:
    claims = [claim_from_dict(d) for d in case["claims"]]
    verdict = verify_sentence(case["sentence"], claims, STORE)
    assert verdict.status == case["expect"], (case["category"], verdict.reasons)


def test_adversarial_set_confusion_matrix() -> None:
    false_pass = false_block = 0
    for case in CASES:
        claims = [claim_from_dict(d) for d in case["claims"]]
        status = verify_sentence(case["sentence"], claims, STORE).status
        if status == "pass" and case["expect"] == "block":
            false_pass += 1
        if status == "block" and case["expect"] == "pass":
            false_block += 1
    assert len(CASES) >= 50
    assert (false_pass, false_block) == (0, 0)


def test_blocked_reason_names_the_real_record() -> None:
    rid = STORE.records[3].report_id
    (v,) = verify([QuoteClaim("crashed when loading a study", STORE.records[0].report_id)], STORE)
    assert v.status == "block"
    assert rid in v.reason


def test_superseded_cfr_reason_mentions_qmsr() -> None:
    (v,) = verify([RegulationClaim("820.100")], STORE)
    assert v.status == "block" and "QMSR" in v.reason


def test_render_redacts_blocked_sentences() -> None:
    report = verify_answer(
        [
            ("Human review is required.", []),
            ("Open a CAPA under 21 CFR 820.100.", [RegulationClaim("820.100")]),
        ],
        STORE,
    )
    assert report.passed == 1 and report.blocked == 1
    text = report.render()
    assert text.startswith("Human review is required.")
    assert "820.100" in text and "Withheld" in text
    assert "820.100" not in report.render(show_blocked_reason=False)
    assert report.claim_counts == {"pass": 0, "block": 1}


def test_find_cfr_citations_variants() -> None:
    text = "See 21 CFR 803.50, 21 C.F.R. § 803.53 and 21 CFR Part 806.10; again 21 CFR 803.50."
    assert find_cfr_citations(text) == ["803.50", "803.53", "806.10"]


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "telepathy"},
        {"kind": "count", "product_code": "QIH"},
        {"kind": "count", "product_code": "QIH", "value": "many"},
        {"kind": "quote", "quote": "some words here", "report_id": None, "source_id": None},
        {"kind": "quote", "quote": "some words here"},
        {"kind": "recall", "product_code": "QIH"},
        {"kind": "recall_count", "product_code": "QIH", "value": "x"},
        {"kind": "literature", "pmid": "1", "year": "recent"},
    ],
)
def test_claim_parse_errors(bad: dict[str, Any]) -> None:
    with pytest.raises(ClaimParseError):
        claim_from_dict(bad)


def test_store_from_database(tmp_path: Path) -> None:
    from maudesignal.gate.loader import store_from_database
    from maudesignal.storage.database import Database

    db = Database(tmp_path / "t.db")
    raw = {"report_number": "1234567-2026-00001", "date_received": "20261001"}
    db.upsert_raw_report(
        maude_report_id="1234567-2026-00001",
        product_code="QIH",
        date_received="20261001",
        date_of_event=None,
        raw_payload=raw,
    )
    db.upsert_normalized_event(
        maude_report_id="1234567-2026-00001",
        product_code="QIH",
        event_type="Malfunction",
        event_date=None,
        narrative="Software failed to send the alert.",
        mfr_narrative="Investigation found a queue timeout.",
        manufacturer="Acme",
        brand_name="Acme Triage",
    )
    store = store_from_database(db)
    rec = store.record("1234567-2026-00001")
    assert rec is not None and rec.date_received == "20261001"
    assert store.find_quote("queue timeout") == ["1234567-2026-00001"]


def test_new_claim_kinds_parse_strict_shape() -> None:
    from maudesignal.gate import LiteratureClaim, RecallClaim, RecallCountClaim

    q = claim_from_dict({"kind": "quote", "quote": "abc", "report_id": None, "source_id": "Z-1"})
    assert isinstance(q, QuoteClaim) and q.source_id == "Z-1" and q.attributed_to == "Z-1"
    legacy = claim_from_dict({"kind": "quote", "quote": "abc", "report_id": "r1"})
    assert isinstance(legacy, QuoteClaim) and legacy.report_id == "r1" and legacy.source_id is None
    r = claim_from_dict({"kind": "recall", "recall_number": " Z-9001-2026 ", "product_code": ""})
    assert r == RecallClaim("Z-9001-2026", None)
    rc = claim_from_dict(
        {"kind": "recall_count", "product_code": "QIH", "value": 2, "date_from": None}
    )
    assert rc == RecallCountClaim("QIH", 2)
    lit = claim_from_dict({"kind": "literature", "pmid": "pmid:90000001", "year": None})
    assert lit == LiteratureClaim("90000001", None)


def test_source_verdict_reasons() -> None:
    from maudesignal.gate import DeviceClaim, LiteratureClaim, RecallClaim

    (dev,) = verify([DeviceClaim("K990777", "LLZ")], STORE)
    assert dev.status == "pass" and dev.reason.startswith("openFDA 510(k)")
    (cat,) = verify([DeviceClaim("K990001", "QIH")], STORE)
    assert cat.reason.startswith("catalog")  # catalog wins over the 510(k) table
    (wrong,) = verify([RecallClaim("Z-9001-2026", "LLZ")], STORE)
    assert wrong.status == "block" and "QIH" in wrong.reason
    (moved,) = verify([QuoteClaim("may be larger than the actual", source_id="Z-9001-2026")], STORE)
    assert moved.status == "block" and "Z-9003-2025" in moved.reason
    (lit,) = verify([LiteratureClaim("90000002", 2021)], STORE)
    assert lit.status == "pass" and lit.evidence_ids == ("PMID 90000002",)
    (short,) = verify([QuoteClaim("abc", source_id="90000001")], STORE)
    assert short.status == "block"
    (orphan,) = verify([QuoteClaim("long enough words")], STORE)
    assert orphan.status == "block" and "not attributed" in orphan.reason


def test_store_loads_external_sources(tmp_path: Path) -> None:
    from maudesignal.gate.loader import store_from_database
    from maudesignal.storage.database import Database

    db = Database(tmp_path / "s.db")
    db.upsert_external_source(
        record_id="r1",
        source_type="fda_recall",
        source_id="Z-0001-2026",
        product_code="LLZ",
        title="Viewer v1",
        authors="Acme",
        publication_date="2026-09-05",
        abstract="Report and displayed images may not match.",
        url=None,
        raw_payload={"res_event_number": "99899", "k_numbers": ["k192176"], "recall_status": "O"},
    )
    db.upsert_external_source(
        record_id="k1",
        source_type="fda_510k",
        source_id="K192176",
        product_code="LLZ",
        title="IntelePACS",
        authors="Intelerad",
        publication_date="2020-04-02",
        abstract=None,
        url=None,
        raw_payload={"decision_code": "SESE"},
    )
    for pmid, abstract in (("123", "Real abstract text."), ("456", "Source: JAMA")):
        db.upsert_external_source(
            record_id=f"p{pmid}",
            source_type="pubmed",
            source_id=pmid,
            product_code="LLZ",
            title=f"Title {pmid}",
            authors=None,
            publication_date="2024 Jan",
            abstract=abstract,
            url=None,
            raw_payload={"source": "J"},
        )
    store = store_from_database(db)
    (rec,) = store.recalls
    assert rec.date_initiated == "20260905" and rec.k_numbers == ("K192176",)
    assert store.recalls_by_number("99899") == [rec]
    assert store.clearance("k192176") is not None and store.device("K192176") is None
    legacy, real = store.article("456"), store.article("123")
    assert legacy is not None and legacy.abstract == ""  # legacy "Source: <journal>" row
    assert real is not None and real.year == 2024
    assert store.source_text("PMID: 123") is not None and store.source_text("nope") is None
    assert store.find_quote_in_sources("displayed images may not match") == ["recall Z-0001-2026"]
    assert db.delete_external_sources(source_type="pubmed") == 2
    assert store_from_database(db).literature == []
