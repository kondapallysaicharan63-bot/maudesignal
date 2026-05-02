"""Unit tests for the PSUR report generator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from maudesignal.report.generator import PSURGenerator, _calculate_stats
from maudesignal.storage.database import Database
from maudesignal.storage.models import ExtractionRecord, NormalizedEventRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_row(
    extraction_id: str,
    maude_report_id: str,
    ts: datetime,
    ai_related: bool,
    severity: str,
    failure_mode: str | None = None,
    confidence: float = 0.85,
    requires_review: bool = False,
    skill_name: str = "maude-narrative-extractor",
    failure_mode_category: str | None = None,
) -> ExtractionRecord:
    if skill_name == "maude-narrative-extractor":
        payload = {
            "ai_related_flag": ai_related,
            "severity": severity,
            "failure_mode": failure_mode,
        }
    else:
        # ai-failure-mode-classifier
        payload = {
            "failure_mode_category": failure_mode_category or "not_ai_related",
        }
    return ExtractionRecord(
        extraction_id=extraction_id,
        maude_report_id=maude_report_id,
        extraction_ts=ts,
        skill_name=skill_name,
        skill_version="1.0.0",
        model_used="llama3",
        output_json=json.dumps(payload),
        confidence_score=confidence,
        requires_review=requires_review,
    )


@pytest.fixture()
def populated_db(tmp_path: Path) -> Database:
    """Database with QIH + DQA normalized events and Skill #1/#4 extractions."""
    db = Database(tmp_path / "test.db")
    with db._session() as session:  # noqa: SLF001
        # Normalized events for product-code join
        for rid, pc in [("R001", "QIH"), ("R002", "QIH"), ("R003", "QIH"), ("R004", "DQA")]:
            session.add(
                NormalizedEventRecord(
                    maude_report_id=rid,
                    product_code=pc,
                    event_type="malfunction",
                    event_date="20250101",
                    narrative="test",
                    mfr_narrative=None,
                    manufacturer="Acme",
                    brand_name="Widget",
                )
            )
        # Skill #1 extractions — QIH records
        rows = [
            _make_row(
                "E001",
                "R001",
                datetime(2025, 1, 15, tzinfo=UTC),
                True,
                "malfunction",
                "missed lesion",
                0.92,
            ),
            _make_row(
                "E002",
                "R002",
                datetime(2025, 3, 10, tzinfo=UTC),
                True,
                "serious_injury",
                None,
                0.88,
                True,
            ),
            _make_row(
                "E003",
                "R003",
                datetime(2025, 5, 20, tzinfo=UTC),
                False,
                "other",
                None,
                0.75,
            ),
            # DQA record
            _make_row(
                "E004",
                "R004",
                datetime(2025, 2, 1, tzinfo=UTC),
                True,
                "malfunction",
                None,
                0.80,
            ),
        ]
        for r in rows:
            session.add(r)
        # Skill #4 classifier rows for R001 and R002
        session.add(
            _make_row(
                "C001",
                "R001",
                datetime(2025, 1, 15, tzinfo=UTC),
                True,
                "malfunction",
                skill_name="ai-failure-mode-classifier",
                failure_mode_category="false_negative_clinical",
            )
        )
        session.add(
            _make_row(
                "C002",
                "R002",
                datetime(2025, 3, 10, tzinfo=UTC),
                True,
                "serious_injury",
                skill_name="ai-failure-mode-classifier",
                failure_mode_category="automation_bias",
            )
        )
        session.commit()
    return db


# ---------------------------------------------------------------------------
# _calculate_stats
# ---------------------------------------------------------------------------


def test_calculate_stats_basic() -> None:
    records = [
        {
            "ai_related_flag": True,
            "severity": "malfunction",
            "confidence_score": 0.9,
            "requires_review": False,
            "failure_mode_category": "algorithm_drift",
        },
        {
            "ai_related_flag": True,
            "severity": "serious_injury",
            "confidence_score": 0.8,
            "requires_review": True,
            "failure_mode_category": "false_negative_clinical",
        },
        {
            "ai_related_flag": False,
            "severity": "other",
            "confidence_score": 0.7,
            "requires_review": False,
            "failure_mode_category": None,
        },
    ]
    stats = _calculate_stats(records)
    assert stats["total"] == 3
    assert stats["ai_related_count"] == 2
    assert abs(stats["ai_related_pct"] - 66.67) < 0.1
    assert stats["requires_review_count"] == 1
    assert abs(stats["avg_confidence"] - (0.9 + 0.8 + 0.7) / 3) < 0.001
    assert stats["severity_breakdown"]["malfunction"] == 1
    assert stats["severity_breakdown"]["serious_injury"] == 1
    assert "algorithm_drift" in stats["failure_mode_breakdown"]


def test_calculate_stats_empty() -> None:
    stats = _calculate_stats([])
    assert stats["total"] == 0
    assert stats["ai_related_pct"] == 0.0
    assert stats["avg_confidence"] == 0.0


# ---------------------------------------------------------------------------
# PSURGenerator.generate — happy path
# ---------------------------------------------------------------------------


def test_generate_creates_markdown(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    result = gen.generate("QIH", "2025-01-01", "2025-12-31", tmp_path / "out")

    assert Path(result["markdown_path"]).exists()
    content = Path(result["markdown_path"]).read_text()

    for section in (
        "Executive Summary",
        "Reporting Period",
        "Severity Distribution",
        "AI-Related Failure Analysis",
        "Drift",
        "Recommendations",
        "Methodology",
        "Source Report IDs",
        "REGULATORY DISCLAIMER",
    ):
        assert section in content, f"Missing section: {section}"


def test_generate_counts_are_correct(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    result = gen.generate("QIH", "2025-01-01", "2025-12-31", tmp_path / "out")
    # R001, R002, R003 are QIH extractions within 2025
    assert result["record_count"] == 3
    # R001 + R002 are AI-related
    assert result["ai_related_count"] == 2


def test_generate_filters_by_product_code(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    result = gen.generate("DQA", "2025-01-01", "2025-12-31", tmp_path / "out")
    assert result["record_count"] == 1


def test_generate_filters_by_date_range(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    # Only R001 (Jan 15) falls in Jan window
    result = gen.generate("QIH", "2025-01-01", "2025-01-31", tmp_path / "out")
    assert result["record_count"] == 1


def test_generate_includes_failure_mode_categories(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    result = gen.generate("QIH", "2025-01-01", "2025-12-31", tmp_path / "out")
    content = Path(result["markdown_path"]).read_text()
    # R001 classifier row provides false_negative_clinical
    assert "False Negative Clinical" in content or "false_negative_clinical" in content.lower()


def test_generate_raises_on_empty(populated_db: Database, tmp_path: Path) -> None:
    gen = PSURGenerator(populated_db)
    with pytest.raises(ValueError, match="No maude-narrative-extractor extractions"):
        gen.generate("XXXX", "2025-01-01", "2025-12-31", tmp_path / "out")


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------


def test_generate_pdf_when_weasyprint_available(populated_db: Database, tmp_path: Path) -> None:
    mock_wp = MagicMock()
    mock_instance = MagicMock()
    mock_instance.write_pdf.return_value = b"%PDF-fake"
    mock_wp.HTML.return_value = mock_instance

    with patch.dict("sys.modules", {"weasyprint": mock_wp}):
        gen = PSURGenerator(populated_db)
        result = gen.generate("QIH", "2025-01-01", "2025-12-31", tmp_path / "out")

    assert result["pdf_path"] is not None
    assert Path(result["pdf_path"]).read_bytes() == b"%PDF-fake"


def test_generate_pdf_none_when_weasyprint_missing(populated_db: Database, tmp_path: Path) -> None:

    with patch.dict("sys.modules", {"weasyprint": None}):
        gen = PSURGenerator(populated_db)
        result = gen.generate("QIH", "2025-01-01", "2025-12-31", tmp_path / "out")

    assert result["pdf_path"] is None
    # Markdown still created
    assert Path(result["markdown_path"]).exists()
