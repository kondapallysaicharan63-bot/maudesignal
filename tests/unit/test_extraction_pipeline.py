"""Unit tests for the extraction pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from maudesignal.common.exceptions import LLMOutputError
from maudesignal.extraction.extractor import ExtractionResult
from maudesignal.extraction.pipeline import (
    _build_classifier_input,
    _build_extractor_input,
    _build_severity_input,
    extract_record,
)
from maudesignal.extraction.skill_loader import LoadedSkill
from maudesignal.storage.database import Database
from maudesignal.storage.models import NormalizedEventRecord


def _make_event(
    *,
    narrative: str | None = "AI algorithm failed to flag LVO.",
    mfr_narrative: str | None = "Investigation pending.",
    event_type: str | None = "injury",
) -> NormalizedEventRecord:
    """Return a NormalizedEventRecord populated with sane defaults."""
    return NormalizedEventRecord(
        maude_report_id="MW001",
        product_code="QIH",
        event_type=event_type,
        event_date="20250115",
        narrative=narrative,
        mfr_narrative=mfr_narrative,
        manufacturer="AcmeMed AI",
        brand_name="StrokeAI v2.1",
    )


def _make_skill(name: str) -> LoadedSkill:
    """Return a LoadedSkill stub — only name and version are read by the pipeline."""
    return LoadedSkill(
        name=name,
        version="1.0.0",
        system_prompt="(stub)",
        output_schema={},
        good_examples=[],
        bad_examples=[],
        skill_root=Path("/tmp") / name,
    )


def _make_extraction_result(
    output: dict[str, Any],
    *,
    extraction_id: str = "ext-1",
) -> ExtractionResult:
    """Return a minimal ExtractionResult with the given output payload."""
    return ExtractionResult(
        output=output,
        model_used="test-model",
        provider_used="test-provider",
        input_tokens=10,
        output_tokens=20,
        cost_estimate_usd=0.0001,
        extraction_id=extraction_id,
    )


# ----------------------------------------------------------------------
# Input builders — pure functions, contract is each Skill's SKILL.md §3
# ----------------------------------------------------------------------


def test_build_extractor_input_passes_through_record_fields() -> None:
    """Skill #1 input contains every field its SKILL.md §3 requires."""
    event = _make_event()
    payload = _build_extractor_input(event)

    assert payload["maude_report_id"] == "MW001"
    assert payload["event_description"] == "AI algorithm failed to flag LVO."
    assert payload["mfr_narrative"] == "Investigation pending."
    assert payload["event_type"] == "injury"
    assert payload["product_code"] == "QIH"
    assert payload["device_problem_codes"] == []
    assert payload["brand_name"] == "StrokeAI v2.1"
    assert payload["manufacturer"] == "AcmeMed AI"


def test_build_extractor_input_coerces_none_to_empty_string() -> None:
    """None narrative/mfr_narrative/event_type become '' so the LLM sees a string."""
    event = _make_event(narrative=None, mfr_narrative=None, event_type=None)
    payload = _build_extractor_input(event)

    assert payload["event_description"] == ""
    assert payload["mfr_narrative"] == ""
    assert payload["event_type"] == ""


def test_build_severity_input_uses_extractor_patient_outcome() -> None:
    """Skill #3 sees patient_outcome forwarded from Skill #1."""
    event = _make_event()
    extractor_output = {"patient_outcome": "Delayed diagnosis; patient recovered"}
    payload = _build_severity_input(event, extractor_output)

    assert payload["maude_report_id"] == "MW001"
    assert payload["product_code"] == "QIH"
    assert payload["event_type"] == "injury"
    assert payload["patient_outcome_extracted"] == "Delayed diagnosis; patient recovered"


def test_build_severity_input_passthrough_none_patient_outcome() -> None:
    """If Skill #1 emitted no patient_outcome, the field is None — not missing."""
    event = _make_event()
    payload = _build_severity_input(event, {})
    assert payload["patient_outcome_extracted"] is None


def test_build_classifier_input_forwards_extractor_decisions() -> None:
    """Skill #4 sees failure_mode, device_problem, ai_related_flag, ai_related_rationale."""
    event = _make_event()
    extractor_output = {
        "failure_mode": "False negative on stroke detection",
        "device_problem": "Algorithm failed to flag hemorrhage",
        "ai_related_flag": True,
        "ai_related_rationale": "AI/ML CADt device per product code",
    }
    payload = _build_classifier_input(event, extractor_output)

    assert payload["extracted_failure_mode"] == "False negative on stroke detection"
    assert payload["extracted_device_problem"] == "Algorithm failed to flag hemorrhage"
    assert payload["ai_related_flag"] is True
    assert payload["ai_related_rationale"] == "AI/ML CADt device per product code"
    assert payload["product_code"] == "QIH"


def test_build_classifier_input_defaults_missing_rationale_to_empty() -> None:
    """Missing ai_related_rationale becomes '' so the Skill always sees a string."""
    event = _make_event()
    payload = _build_classifier_input(event, {"ai_related_flag": None})
    assert payload["ai_related_rationale"] == ""


# ----------------------------------------------------------------------
# extract_record — full 3-Skill orchestration
# ----------------------------------------------------------------------


def _extractor_output_ai_true() -> dict[str, Any]:
    """A representative Skill #1 output where ai_related_flag is true."""
    return {
        "failure_mode": "False negative on stroke detection",
        "device_problem": "Algorithm failed to flag hemorrhage",
        "patient_outcome": "Delayed diagnosis; patient recovered",
        "ai_related_flag": True,
        "ai_related_rationale": "Product code is an AI/ML CADt device.",
        "confidence_score": 0.85,
        "requires_human_review": False,
        "severity": "serious_injury",
    }


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A fresh database in a temp dir — pipeline persists each Skill row."""
    return Database(tmp_path / "test.db")


def test_extract_record_runs_all_three_skills_when_ai_true(db: Database) -> None:
    """Happy path: Skill #1 says ai_related_flag=true → #3 and #4 both run."""
    extractor = MagicMock()
    extractor.run.side_effect = [
        _make_extraction_result(_extractor_output_ai_true(), extraction_id="ext-1"),
        _make_extraction_result(
            {"severity": "serious_injury", "confidence_score": 0.9, "requires_human_review": False},
            extraction_id="ext-2",
        ),
        _make_extraction_result(
            {
                "failure_mode_category": "false_negative_clinical",
                "confidence_score": 0.88,
                "requires_human_review": False,
            },
            extraction_id="ext-3",
        ),
    ]

    result = extract_record(
        extractor=extractor,
        db=db,
        event=_make_event(),
        skill_extractor=_make_skill("maude-narrative-extractor"),
        skill_severity=_make_skill("severity-triage"),
        skill_classifier=_make_skill("ai-failure-mode-classifier"),
    )

    assert extractor.run.call_count == 3
    assert result.extractor_result is not None
    assert result.severity_result is not None
    assert result.classifier_result is not None
    assert result.classifier_skipped_reason is None
    assert result.errors == []
    assert result.any_success is True


def test_extract_record_skips_classifier_when_ai_flag_false(db: Database) -> None:
    """Skill #4 SKILL.md §2: skip when extractor's ai_related_flag is false."""
    extractor_output = _extractor_output_ai_true() | {"ai_related_flag": False}
    extractor = MagicMock()
    extractor.run.side_effect = [
        _make_extraction_result(extractor_output, extraction_id="ext-1"),
        _make_extraction_result(
            {"severity": "malfunction", "confidence_score": 0.7, "requires_human_review": False},
            extraction_id="ext-2",
        ),
    ]

    result = extract_record(
        extractor=extractor,
        db=db,
        event=_make_event(),
        skill_extractor=_make_skill("maude-narrative-extractor"),
        skill_severity=_make_skill("severity-triage"),
        skill_classifier=_make_skill("ai-failure-mode-classifier"),
    )

    assert extractor.run.call_count == 2  # #4 not invoked
    assert result.classifier_result is None
    assert result.classifier_skipped_reason == "extractor_ai_related_flag_false"
    assert result.errors == []


def test_extract_record_runs_classifier_when_ai_flag_null(db: Database) -> None:
    """ai_related_flag=None means uncertain — Skill #4 still runs (Skill says so)."""
    extractor_output = _extractor_output_ai_true() | {"ai_related_flag": None}
    extractor = MagicMock()
    extractor.run.side_effect = [
        _make_extraction_result(extractor_output, extraction_id="ext-1"),
        _make_extraction_result(
            {"severity": "other", "confidence_score": 0.6, "requires_human_review": True},
            extraction_id="ext-2",
        ),
        _make_extraction_result(
            {
                "failure_mode_category": "not_ai_related",
                "confidence_score": 0.7,
                "requires_human_review": True,
            },
            extraction_id="ext-3",
        ),
    ]

    result = extract_record(
        extractor=extractor,
        db=db,
        event=_make_event(),
        skill_extractor=_make_skill("maude-narrative-extractor"),
        skill_severity=_make_skill("severity-triage"),
        skill_classifier=_make_skill("ai-failure-mode-classifier"),
    )

    assert extractor.run.call_count == 3
    assert result.classifier_skipped_reason is None
    assert result.classifier_result is not None


def test_extract_record_short_circuits_when_skill1_fails(db: Database) -> None:
    """Skill #1 failing makes #3 and #4 useless — orchestrator should not call them."""
    extractor = MagicMock()
    extractor.run.side_effect = LLMOutputError("schema violation")

    result = extract_record(
        extractor=extractor,
        db=db,
        event=_make_event(),
        skill_extractor=_make_skill("maude-narrative-extractor"),
        skill_severity=_make_skill("severity-triage"),
        skill_classifier=_make_skill("ai-failure-mode-classifier"),
    )

    assert extractor.run.call_count == 1
    assert result.extractor_result is None
    assert result.severity_result is None
    assert result.classifier_result is None
    assert len(result.errors) == 1
    assert result.errors[0][0] == "maude-narrative-extractor"
    assert result.any_success is False


def test_extract_record_continues_when_skill3_fails(db: Database) -> None:
    """A Skill #3 failure should not block Skill #4 — they're independent."""
    extractor = MagicMock()
    extractor.run.side_effect = [
        _make_extraction_result(_extractor_output_ai_true(), extraction_id="ext-1"),
        LLMOutputError("severity-triage schema violation"),
        _make_extraction_result(
            {
                "failure_mode_category": "false_negative_clinical",
                "confidence_score": 0.85,
                "requires_human_review": False,
            },
            extraction_id="ext-3",
        ),
    ]

    result = extract_record(
        extractor=extractor,
        db=db,
        event=_make_event(),
        skill_extractor=_make_skill("maude-narrative-extractor"),
        skill_severity=_make_skill("severity-triage"),
        skill_classifier=_make_skill("ai-failure-mode-classifier"),
    )

    assert extractor.run.call_count == 3
    assert result.extractor_result is not None
    assert result.severity_result is None
    assert result.classifier_result is not None
    assert len(result.errors) == 1
    assert result.errors[0][0] == "severity-triage"
    assert result.any_success is True
