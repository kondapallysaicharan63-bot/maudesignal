"""Unit tests for Phase 5: PSUR report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from maudesignal.report.psur_generator import PsurGenerator, PsurInput, _to_skill_dict
from maudesignal.storage.database import Database

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _in_memory_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _fake_extractor_result(output: dict[str, Any]) -> MagicMock:
    result = MagicMock()
    result.output = output
    result.model_used = "test-model"
    return result


def _good_psur_output(
    signal: str = "potential_signal",
) -> dict[str, Any]:
    return {
        "product_code": "QIH",
        "reporting_period_start": "2025-11-01",
        "reporting_period_end": "2026-04-30",
        "drafted_at": "2026-05-01T14:30:00Z",
        "skill_name": "psur-report-drafter",
        "skill_version": "1.0.0",
        "model_used": "test-model",
        "executive_summary": (
            "During the reporting period November 2025 through April 2026, "
            "10 MAUDE adverse event reports were identified for product code QIH, "
            "with 50% classified as AI-related. A potential signal has been identified. "
            "DRAFT — REQUIRES HUMAN REVIEW BEFORE SUBMISSION."
        ),
        "signal_assessment": signal,
        "sections": [
            {
                "title": "1. Reporting Period Overview",
                "content": "Covers Nov 2025–Apr 2026. DRAFT — REQUIRES HUMAN REVIEW.",
            },
            {
                "title": "2. Adverse Event Summary",
                "content": "Ten events; 2 serious injuries. DRAFT.",
            },
            {
                "title": "3. AI-Related Signal Analysis",
                "content": "50% AI-related rate observed. DRAFT.",
            },
            {
                "title": "4. Root Cause Analysis Summary",
                "content": "One hypothesis identified. DRAFT.",
            },
            {"title": "5. Trend Analysis", "content": "Moderate increasing trend. DRAFT."},
            {"title": "6. Literature Review", "content": "2 PubMed articles found. DRAFT."},
            {"title": "7. Signal Assessment", "content": "Potential signal identified. DRAFT."},
            {"title": "8. Recommended Actions", "content": "Continue monitoring. DRAFT."},
        ],
        "recommended_actions": [
            "Continue monthly MAUDE signal monitoring.",
            "Initiate CAPA review for top failure mode cluster.",
        ],
        "confidence_score": 0.80,
    }


# ──────────────────────────────────────────────────────────────────────────────
# _to_skill_dict
# ──────────────────────────────────────────────────────────────────────────────


class TestToSkillDict:
    def test_required_fields_present(self) -> None:
        psur_input = PsurInput(
            product_code="QIH",
            device_name="Test Device",
            reporting_period_start="2025-11-01",
            reporting_period_end="2026-04-30",
            total_reports=10,
            ai_related_count=5,
            ai_rate=0.5,
        )
        d = _to_skill_dict(psur_input)
        assert d["product_code"] == "QIH"
        assert d["total_reports"] == 10
        assert d["ai_rate"] == pytest.approx(0.5)
        assert "trend_summary" not in d

    def test_trend_summary_included_when_present(self) -> None:
        psur_input = PsurInput(
            product_code="QIH",
            device_name="Test Device",
            reporting_period_start="2025-11-01",
            reporting_period_end="2026-04-30",
            total_reports=5,
            ai_related_count=2,
            ai_rate=0.4,
            trend_summary={"direction": "increasing", "signal_level": "elevated"},
        )
        d = _to_skill_dict(psur_input)
        assert "trend_summary" in d
        assert d["trend_summary"]["direction"] == "increasing"

    def test_pubmed_and_ct_counts(self) -> None:
        psur_input = PsurInput(
            product_code="QIH",
            device_name="Test",
            reporting_period_start="2025-11-01",
            reporting_period_end="2026-04-30",
            total_reports=0,
            ai_related_count=0,
            ai_rate=0.0,
            pubmed_citations=3,
            clinical_trials_count=2,
        )
        d = _to_skill_dict(psur_input)
        assert d["pubmed_citations"] == 3
        assert d["clinical_trials_count"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# DB: PsurReportRecord
# ──────────────────────────────────────────────────────────────────────────────


class TestPsurReportDB:
    def test_insert_and_list(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        db.insert_psur_report(
            report_id="psur-abc123",
            product_code="QIH",
            reporting_period_start="2025-11-01",
            reporting_period_end="2026-04-30",
            signal_assessment="potential_signal",
            skill_version="1.0.0",
            model_used="test-model",
            output_payload={"confidence_score": 0.8},
            confidence_score=0.8,
        )
        reports = db.list_psur_reports()
        assert len(reports) == 1
        r = reports[0]
        assert r.report_id == "psur-abc123"
        assert r.product_code == "QIH"
        assert r.signal_assessment == "potential_signal"
        assert r.confidence_score == pytest.approx(0.8)

    def test_filter_by_product_code(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for pc, signal in [("QIH", "potential_signal"), ("MYH", "no_signal")]:
            db.insert_psur_report(
                report_id=f"psur-{pc}",
                product_code=pc,
                reporting_period_start="2025-11-01",
                reporting_period_end="2026-04-30",
                signal_assessment=signal,
                skill_version="1.0.0",
                model_used="test",
                output_payload={},
                confidence_score=0.5,
            )
        qih = db.list_psur_reports(product_code="QIH")
        assert len(qih) == 1
        assert qih[0].signal_assessment == "potential_signal"

    def test_list_returns_most_recent_first(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for rid in ["psur-old", "psur-new"]:
            db.insert_psur_report(
                report_id=rid,
                product_code="QIH",
                reporting_period_start="2025-11-01",
                reporting_period_end="2026-04-30",
                signal_assessment="no_signal",
                skill_version="1.0.0",
                model_used="test",
                output_payload={},
                confidence_score=0.5,
            )
        reports = db.list_psur_reports()
        assert reports[0].report_id == "psur-new"

    def test_output_json_round_trips(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        payload = {"sections": [{"title": "Overview", "content": "Test."}]}
        db.insert_psur_report(
            report_id="psur-json",
            product_code="QIH",
            reporting_period_start="2025-11-01",
            reporting_period_end="2026-04-30",
            signal_assessment="no_signal",
            skill_version="1.0.0",
            model_used="test",
            output_payload=payload,
            confidence_score=0.6,
        )
        reports = db.list_psur_reports()
        loaded = json.loads(reports[0].output_json)
        assert loaded["sections"][0]["title"] == "Overview"


# ──────────────────────────────────────────────────────────────────────────────
# PsurGenerator
# ──────────────────────────────────────────────────────────────────────────────


class TestPsurGenerator:
    def _make_generator(self, tmp_path: Path, extractor_output: dict[str, Any]) -> PsurGenerator:
        skills_root = Path(__file__).parent.parent.parent / "skills"
        db = _in_memory_db(tmp_path)
        mock_extractor = MagicMock()
        mock_extractor.run.return_value = _fake_extractor_result(extractor_output)
        generator = PsurGenerator.__new__(PsurGenerator)
        generator._extractor = mock_extractor
        generator._db = db
        from maudesignal.extraction.skill_loader import SkillLoader

        loader = SkillLoader(skills_root)
        generator._skill = loader.load("psur-report-drafter")
        return generator

    def test_generate_stores_report(self, tmp_path: Path) -> None:
        generator = self._make_generator(tmp_path, _good_psur_output())
        draft = generator.generate(product_code="QIH")
        assert draft.product_code == "QIH"
        assert draft.signal_assessment == "potential_signal"
        assert draft.confidence_score == pytest.approx(0.8)
        stored = generator._db.list_psur_reports(product_code="QIH")
        assert len(stored) == 1

    def test_generate_returns_draft_with_sections(self, tmp_path: Path) -> None:
        generator = self._make_generator(tmp_path, _good_psur_output())
        draft = generator.generate(product_code="QIH")
        assert len(draft.sections) >= 6
        assert len(draft.recommended_actions) >= 1
        assert len(draft.executive_summary) > 50

    def test_generate_confirmed_signal(self, tmp_path: Path) -> None:
        generator = self._make_generator(tmp_path, _good_psur_output(signal="confirmed_signal"))
        draft = generator.generate(product_code="QIH")
        assert draft.signal_assessment == "confirmed_signal"

    def test_report_id_has_psur_prefix(self, tmp_path: Path) -> None:
        generator = self._make_generator(tmp_path, _good_psur_output())
        draft = generator.generate(product_code="QIH")
        assert draft.report_id.startswith("psur-")

    def test_generate_aggregates_empty_db(self, tmp_path: Path) -> None:
        generator = self._make_generator(tmp_path, _good_psur_output())
        draft = generator.generate(product_code="UNKNOWN")
        assert draft.product_code == "UNKNOWN"
        # Extractor was called once
        generator._extractor.run.assert_called_once()
