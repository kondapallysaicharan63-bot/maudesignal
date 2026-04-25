"""Unit tests for the storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from safesignal.storage.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A fresh database in a temp directory."""
    return Database(tmp_path / "test.db")


def test_upsert_raw_report_is_idempotent(db: Database) -> None:
    """FR-05 / NFR-05: re-ingesting same record is a no-op."""
    payload = {"mdr_report_key": "MW123", "event_type": ["Injury"]}

    first = db.upsert_raw_report(
        maude_report_id="MW123",
        product_code="QIH",
        date_received="20250101",
        date_of_event=None,
        raw_payload=payload,
    )
    second = db.upsert_raw_report(
        maude_report_id="MW123",
        product_code="QIH",
        date_received="20250101",
        date_of_event=None,
        raw_payload=payload,
    )

    assert first is True
    assert second is False
    assert db.count_raw_reports() == 1
    assert db.count_raw_reports("QIH") == 1
    assert db.count_raw_reports("ZZZ") == 0


def test_normalized_event_roundtrip(db: Database) -> None:
    """Normalized events can be written and read back."""
    db.upsert_normalized_event(
        maude_report_id="MW456",
        product_code="QIH",
        event_type="injury",
        event_date="20250115",
        narrative="AI algorithm failed to flag LVO.",
        mfr_narrative=None,
        manufacturer="AcmeMed AI",
        brand_name="StrokeAI v2.1",
    )
    events = db.list_normalized_events(product_code="QIH")
    assert len(events) == 1
    assert events[0].maude_report_id == "MW456"
    assert events[0].narrative == "AI algorithm failed to flag LVO."


def test_audit_log_cost_accumulates(db: Database) -> None:
    """Total LLM cost sums across audit rows (FR-12)."""
    for i in range(3):
        db.insert_audit_log(
            call_id=f"call-{i}",
            skill_name="maude-narrative-extractor",
            skill_version="1.0.0",
            model="claude-sonnet-4-6",
            input_hash="a" * 64,
            output_hash="b" * 64,
            input_tokens=1000,
            output_tokens=500,
            cost_estimate_usd=0.01,
        )
    assert db.total_llm_cost_usd() == pytest.approx(0.03)
