"""Gold-set tests for Skill #1 (maude-narrative-extractor).

Each test case is drawn from skills/maude-narrative-extractor/examples/good.jsonl.
The LLM is mocked to return an output that satisfies the Skill schema; we then
verify that:
  1. The pipeline accepts the output (schema validation passes).
  2. Key fields (ai_related_flag, severity, confidence_score) match expectations.
  3. The record is persisted correctly to the extractions table.

These tests are marked @pytest.mark.gold_set and run with the full suite.
They use no real API calls — the LLM provider is fully mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from maudesignal.extraction.llm_providers.base import LLMMessage, LLMProvider, LLMResponse
from maudesignal.extraction.pipeline import extract_record
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_ROOT = _REPO_ROOT / "skills"
_GOOD_JSONL = _SKILLS_ROOT / "maude-narrative-extractor" / "examples" / "good.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_gold_case(case_id: str) -> dict:
    """Load a single gold-set case by case_id from good.jsonl."""
    with _GOOD_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case["case_id"] == case_id:
                return case
    raise ValueError(f"Gold case {case_id!r} not found in {_GOOD_JSONL}")


def _make_extractor_llm_response(case: dict, report_id: str) -> str:
    """Build a Skill #1 JSON response from the gold case expected_output."""
    exp = case["expected_output"]
    now = datetime.now(UTC).isoformat()
    conf = (exp["confidence_score_min"] + exp["confidence_score_max"]) / 2.0
    # Clamp to [0.0, 0.95] as per schema
    conf = min(conf, 0.95)

    payload = {
        "maude_report_id": report_id,
        "extraction_ts": now,
        "skill_name": "maude-narrative-extractor",
        "skill_version": "1.0.0",
        "model_used": "mock-model",
        "failure_mode": exp.get("failure_mode"),
        "severity": exp.get("severity", "unknown"),
        "patient_outcome": exp.get("patient_outcome"),
        "device_problem": exp.get("device_problem"),
        "ai_related_flag": exp.get("ai_related_flag"),
        "ai_related_rationale": exp.get("ai_related_rationale", "Mocked rationale."),
        "confidence_score": round(conf, 3),
        "requires_human_review": exp.get("requires_human_review", False),
        "narrative_excerpt": case["input"]["event_description"][:200],
        "narrative_truncated": False,
        "extraction_notes": None,
    }
    return json.dumps(payload)


def _make_severity_response(report_id: str, severity: str) -> str:
    """Minimal valid Skill #3 response."""
    return json.dumps(
        {
            "maude_report_id": report_id,
            "triage_ts": datetime.now(UTC).isoformat(),
            "skill_name": "severity-triage",
            "skill_version": "1.0.0",
            "model_used": "mock-model",
            "severity": severity,
            "severity_rationale": "Mocked rationale.",
            "evidence_quotes": ["Mocked evidence."],
            "maude_event_type": "malfunction",
            "agrees_with_maude_event_type": True,
            "confidence_score": 0.80,
            "requires_human_review": False,
        }
    )


def _make_classifier_response(report_id: str) -> str:
    """Minimal valid Skill #4 response."""
    return json.dumps(
        {
            "maude_report_id": report_id,
            "classification_ts": datetime.now(UTC).isoformat(),
            "skill_name": "ai-failure-mode-classifier",
            "skill_version": "1.0.0",
            "model_used": "mock-model",
            "failure_mode_category": "false_negative_clinical",
            "category_rationale": "Mocked rationale.",
            "evidence_quotes": ["Mocked evidence."],
            "secondary_modes_observed": [],
            "is_multi_mode": False,
            "confidence_score": 0.80,
            "requires_human_review": False,
        }
    )


class _MockProvider(LLMProvider):
    """Returns pre-programmed responses in sequence."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-model"

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self._responses:
            raise RuntimeError("MockProvider has no more responses")
        text = self._responses.pop(0)
        return LLMResponse(
            text=text,
            model="mock-model",
            input_tokens=100,
            output_tokens=50,
            provider="mock",
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


def _run_gold_case(
    case: dict,
    tmp_path: Path,
    *,
    ai_related: bool | None = True,
) -> tuple[dict, Database]:
    """Run the 3-Skill pipeline against a gold case with a mocked provider."""
    report_id = case["input"]["maude_report_id"]
    db = Database(tmp_path / "test.db")

    # Pre-insert the normalized event
    db.upsert_normalized_event(
        maude_report_id=report_id,
        product_code=case["input"]["product_code"],
        event_type=None,
        event_date=None,
        narrative=case["input"]["event_description"],
        mfr_narrative=case["input"].get("mfr_narrative"),
        manufacturer=case["input"].get("manufacturer"),
        brand_name=case["input"].get("brand_name"),
    )
    event = db.get_normalized_event(report_id)
    assert event is not None

    severity = case["expected_output"].get("severity", "malfunction")
    responses = [
        _make_extractor_llm_response(case, report_id),
        _make_severity_response(report_id, severity),
    ]
    if ai_related is not False:
        responses.append(_make_classifier_response(report_id))

    loader = SkillLoader(_SKILLS_ROOT)
    skill_ext = loader.load("maude-narrative-extractor")
    skill_sev = loader.load("severity-triage")
    skill_cls = loader.load("ai-failure-mode-classifier")

    from maudesignal.config import Config
    from maudesignal.extraction.extractor import Extractor

    config = Config(
        llm_provider="groq",
        groq_api_key="gsk_fake",
        groq_model="mock-model",
        anthropic_api_key=None,
        claude_model_extraction="mock-model",
        claude_model_reasoning="mock-model",
        openai_api_key=None,
        openai_model="mock-model",
        gemini_api_key=None,
        gemini_model="mock-model",
        provider_fallback_order="groq",
        openfda_api_key=None,
        db_path=tmp_path / "test.db",
        log_level="WARNING",
        cost_ceiling_usd=150.0,
        project_root=_REPO_ROOT,
    )
    extractor = Extractor(config=config, db=db)

    mock_provider = _MockProvider(responses)
    with patch.object(extractor, "_provider", mock_provider):
        result = extract_record(
            extractor=extractor,
            db=db,
            event=event,
            skill_extractor=skill_ext,
            skill_severity=skill_sev,
            skill_classifier=skill_cls,
        )

    assert not result.errors, f"Pipeline errors: {result.errors}"
    assert result.extractor_result is not None
    return result.extractor_result.output, db


# ---------------------------------------------------------------------------
# Gold-set test cases
# ---------------------------------------------------------------------------


@pytest.mark.gold_set
def test_gold_01_ai_false_negative(tmp_path: Path) -> None:
    """Clear AI false-negative case — high confidence, AI-related, serious injury."""
    case = _load_gold_case("good_01_ai_false_negative")
    output, db = _run_gold_case(case, tmp_path)

    exp = case["expected_output"]
    assert output["ai_related_flag"] is True
    assert output["severity"] == exp["severity"]
    assert exp["confidence_score_min"] <= output["confidence_score"] <= exp["confidence_score_max"]
    assert output["requires_human_review"] is exp["requires_human_review"]
    # Record persisted to DB
    rows = db.list_extractions(skill_name="maude-narrative-extractor")
    assert len(rows) == 1


@pytest.mark.gold_set
def test_gold_02_vague_narrative(tmp_path: Path) -> None:
    """Vague narrative — low confidence, review required, AI flag uncertain."""
    case = _load_gold_case("good_02_vague_narrative")
    output, _ = _run_gold_case(case, tmp_path, ai_related=None)

    exp = case["expected_output"]
    assert exp["confidence_score_min"] <= output["confidence_score"] <= exp["confidence_score_max"]
    assert output["requires_human_review"] is True


@pytest.mark.gold_set
def test_gold_03_clear_hardware_failure_not_ai(tmp_path: Path) -> None:
    """Non-AI hardware failure — ai_related_flag must be False, classifier skipped."""
    case = _load_gold_case("good_03_clear_hardware_failure")

    report_id = case["input"]["maude_report_id"]
    db = Database(tmp_path / "test.db")
    db.upsert_normalized_event(
        maude_report_id=report_id,
        product_code=case["input"]["product_code"],
        event_type=None,
        event_date=None,
        narrative=case["input"]["event_description"],
        mfr_narrative=case["input"].get("mfr_narrative"),
        manufacturer=None,
        brand_name=None,
    )
    event = db.get_normalized_event(report_id)
    assert event is not None

    # Only 2 LLM calls expected (extractor + severity); classifier skipped because ai=False
    responses = [
        _make_extractor_llm_response(case, report_id),
        _make_severity_response(report_id, "malfunction"),
    ]

    loader = SkillLoader(_SKILLS_ROOT)
    skill_ext = loader.load("maude-narrative-extractor")
    skill_sev = loader.load("severity-triage")
    skill_cls = loader.load("ai-failure-mode-classifier")

    from maudesignal.config import Config
    from maudesignal.extraction.extractor import Extractor

    config = Config(
        llm_provider="groq",
        groq_api_key="gsk_fake",
        groq_model="mock-model",
        anthropic_api_key=None,
        claude_model_extraction="mock-model",
        claude_model_reasoning="mock-model",
        openai_api_key=None,
        openai_model="mock-model",
        gemini_api_key=None,
        gemini_model="mock-model",
        provider_fallback_order="groq",
        openfda_api_key=None,
        db_path=tmp_path / "test.db",
        log_level="WARNING",
        cost_ceiling_usd=150.0,
        project_root=_REPO_ROOT,
    )
    extractor = Extractor(config=config, db=db)
    mock_provider = _MockProvider(responses)

    with patch.object(extractor, "_provider", mock_provider):
        result = extract_record(
            extractor=extractor,
            db=db,
            event=event,
            skill_extractor=skill_ext,
            skill_severity=skill_sev,
            skill_classifier=skill_cls,
        )

    assert not result.errors
    assert result.extractor_result is not None
    assert result.extractor_result.output["ai_related_flag"] is False
    # Classifier must be skipped when ai_related_flag is False
    assert result.classifier_result is None
    assert result.classifier_skipped_reason == "extractor_ai_related_flag_false"
    # Provider consumed exactly 2 responses (extractor + severity), not 3
    assert len(mock_provider._responses) == 0
