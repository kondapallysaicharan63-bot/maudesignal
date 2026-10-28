"""Ranking, why-ranked sentences and device names in the "what changed" digest."""

from __future__ import annotations

import json
from pathlib import Path

from maudesignal.catalog.names import brand_counts, classification_names, report_brands
from maudesignal.monitor.deterioration import EventFact, detect_deterioration, parse_yyyymmdd
from maudesignal.monitor.digest import (
    RANKING_ORDER,
    build_digest,
    digest_from_database,
    digest_to_dict,
    rank_signals,
    render_markdown,
)
from maudesignal.storage.database import Database

AS_OF = parse_yyyymmdd("20260831")


def _f(rid: str, day: str, code: str, event_type: str = "malfunction") -> EventFact:
    return EventFact(rid, code, parse_yyyymmdd(day), event_type)


def _spike(code: str, baseline: int, current: int, severe: int = 0) -> list[EventFact]:
    # One baseline injury whenever the current window has some, so "injury" is
    # not a never-seen event type (which would make it a new signal instead).
    facts = [
        _f(f"{code}b{i}", "20260801", code, "injury" if severe and i == 0 else "malfunction")
        for i in range(baseline)
    ]
    facts += [
        _f(f"{code}c{i}", "20260826", code, "injury" if i < severe else "malfunction")
        for i in range(current)
    ]
    return facts


def test_new_signal_outranks_spike_and_reason_names_the_step() -> None:
    facts = _spike("AAA", 4, 6) + [_f("n1", "20260830", "NEW")]
    digest = build_digest(detect_deterioration(facts, AS_OF))
    assert [s.product_code for s in digest.ranked] == ["NEW", "AAA"]
    assert digest.rank_reasons["NEW"].startswith(
        "Ranked 1 of 2 flagged: new kind of problem: first 1"
    )
    assert (
        "Above AAA: new kind of problem outranks reports suddenly increased."
        in digest.rank_reasons["NEW"]
    )
    assert (
        "Below NEW: new kind of problem outranks reports suddenly increased."
        in digest.rank_reasons["AAA"]
    )


def test_ties_broken_by_ratio_then_count_then_code() -> None:
    # Same rule; BBB has the higher ratio (8 vs mean 1 = 8x) than AAA (6 vs mean 1 = 6x).
    facts = _spike("AAA", 4, 6) + _spike("BBB", 4, 8)
    ranked = rank_signals(detect_deterioration(facts, AS_OF).signals)
    assert [s.product_code for s in ranked] == ["BBB", "AAA"]
    digest = build_digest(detect_deterioration(facts, AS_OF))
    assert "higher ratio to baseline (8.00x vs 6.00x)" in digest.rank_reasons["BBB"]

    # Identical numbers: alphabetical.
    facts = _spike("ZZZ", 4, 6) + _spike("AAA", 4, 6)
    digest = build_digest(detect_deterioration(facts, AS_OF))
    assert [s.product_code for s in digest.ranked] == ["AAA", "ZZZ"]
    assert "ordered by product code (AAA before ZZZ)" in digest.rank_reasons["AAA"]


def test_severe_count_breaks_ties_within_a_rule() -> None:
    # Both spike (4x and 6x); AAA's Injury/Death share moves 2.5% -> 5.0%, far below +15 pp.
    facts = _spike("AAA", 40, 40, severe=2) + _spike("BBB", 40, 60)
    digest = build_digest(detect_deterioration(facts, AS_OF))
    classes = {s.product_code: s.classification for s in digest.ranked}
    assert classes == {"AAA": "spike", "BBB": "spike"}
    assert [s.product_code for s in digest.ranked] == ["AAA", "BBB"]
    assert "more Injury/Death reports this window (2 vs 0)" in digest.rank_reasons["AAA"]


def test_single_flag_reason_and_markdown_json() -> None:
    facts = _spike("AAA", 4, 6) + [_f("s1", "20260801", "STB"), _f("s2", "20260826", "STB")]
    digest = build_digest(detect_deterioration(facts, AS_OF))
    reason = digest.rank_reasons["AAA"]
    assert reason == (
        "Ranked 1 of 1 flagged: reports suddenly increased: 6 reports this window vs a "
        "baseline weekly mean of 1.00 (6.00x; the rule needs >= 2x and >= 3 reports). It is "
        "the only product code that crossed a rule threshold; 1 other code(s) stayed below every "
        "threshold."
    )
    md = render_markdown(digest)
    assert f"- Why this rank: {reason}" in md
    assert "- Ranking (most urgent first): " + "; then ".join(RANKING_ORDER) in md
    data = digest_to_dict(digest)
    assert data["ranking"] == [
        {
            "rank": 1,
            "product_code": "AAA",
            "classification": "spike",
            "label": "reports suddenly increased",
            "reason": reason,
        }
    ]
    assert data["rules"]["ranking_order"] == list(RANKING_ORDER)


def test_stable_only_has_empty_ranking() -> None:
    facts = [_f("s1", "20260801", "STB"), _f("s2", "20260826", "STB")]
    digest = build_digest(detect_deterioration(facts, AS_OF))
    assert digest.ranked == () and digest.rank_reasons == {}
    assert digest_to_dict(digest)["ranking"] == []


def test_brand_counts_group_spellings() -> None:
    brands = {
        "1": "IntelliSpace Cardiovascular",
        "2": "INTELLISPACE CARDIOVASCULAR",
        "3": "IntelliSpace Cardiovascular",
        "4": "Vue PACS",
    }
    assert brand_counts(["1", "2", "3", "4", "5"], brands) == [
        ("IntelliSpace Cardiovascular", 3),
        ("Vue PACS", 1),
    ]


def _db_with_reports(tmp_path: Path) -> Database:
    db = Database(tmp_path / "demo.db")
    rows = [(f"b{i}", "20260801", "Vue PACS") for i in range(4)] + [
        (f"c{i}", "20260826", "MERGE PACS" if i else "") for i in range(6)
    ]
    for rid, day, brand in rows:
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code="LLZ",
            date_received=day,
            date_of_event=None,
            raw_payload={"mdr_report_key": rid},
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code="LLZ",
            event_type="malfunction",
            event_date=day,
            narrative=None,
            mfr_narrative=None,
            manufacturer=None,
            brand_name=brand,
        )
    return db


def test_names_from_manifest_and_classification_rows_only(tmp_path: Path) -> None:
    db = _db_with_reports(tmp_path)
    db.upsert_catalog_device(
        product_code="QIH",
        device_name="One cleared device",
        company_name="X",
        specialty=None,
        decision_date=None,
        k_number="K000001",
        source_keyword="ai",
    )
    db.upsert_catalog_device(
        product_code="MYN",
        device_name="Analyzer, Medical Image",
        company_name=None,
        specialty=None,
        decision_date=None,
        k_number=None,
        source_keyword="openfda_classification",
    )
    (tmp_path / "SEED_MANIFEST.json").write_text(
        json.dumps(
            {
                "queries": [
                    {"product_code": "LLZ", "device_name": "System, Image Processing, Radiological"}
                ]
            }
        ),
        encoding="utf-8",
    )
    names = classification_names(db)
    # A 510(k) row names one device, not the product code, so QIH has no name here.
    assert names == {
        "LLZ": "System, Image Processing, Radiological",
        "MYN": "Analyzer, Medical Image",
    }
    assert "c0" not in report_brands(db)  # blank brand is not a name


def test_digest_from_database_adds_device_line(tmp_path: Path) -> None:
    db = _db_with_reports(tmp_path)
    (tmp_path / "SEED_MANIFEST.json").write_text(
        json.dumps(
            {
                "queries": [
                    {"product_code": "LLZ", "device_name": "System, Image Processing, Radiological"}
                ]
            }
        ),
        encoding="utf-8",
    )
    from maudesignal.monitor.deterioration import detect_from_database

    digest = digest_from_database(db, detect_from_database(db))
    md = render_markdown(digest)
    assert (
        "- Device: FDA device type System, Image Processing, Radiological; "
        "named on this window's reports: MERGE PACS (5 of 6 reports)"
    ) in md
    data = digest_to_dict(digest)
    assert data["window_brands"] == {"LLZ": [{"brand": "MERGE PACS", "reports": 5}]}
