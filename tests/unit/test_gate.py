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
    QuoteClaim,
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
