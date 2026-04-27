"""Extraction pipeline — runs the three-Skill chain against a record.

Mirrors the shape of ``ingestion/pipeline.py``: a small orchestrator that
sequences calls into the lower-level :class:`Extractor` (which itself
runs one Skill against one record).

Skill chain per record:

  1. ``maude-narrative-extractor`` (Skill #1) — primary extraction.
  2. ``severity-triage`` (Skill #3) — standardized severity per FDA MDR.
  3. ``ai-failure-mode-classifier`` (Skill #4) — AI taxonomy assignment.

Skill #4 honors the activation rule from its SKILL.md §2: if Skill #1
emits ``ai_related_flag == false``, the extractor's non-AI verdict is
trusted and Skill #4 is skipped. Skills #1 and #3 always run.

Each Skill output is persisted as its own ``ExtractionRecord`` row keyed
by ``extraction_id`` and tagged with ``skill_name`` / ``skill_version``,
so re-extractions and per-Skill queries remain straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.common.logging import get_logger
from maudesignal.extraction.extractor import ExtractionResult, Extractor
from maudesignal.extraction.skill_loader import LoadedSkill
from maudesignal.storage.database import Database
from maudesignal.storage.models import NormalizedEventRecord

logger = get_logger(__name__)


@dataclass(frozen=True)
class RecordExtractionResult:
    """Per-record summary of the three-Skill chain.

    Each ``*_result`` is the ``ExtractionResult`` returned by the
    underlying :class:`Extractor` for that Skill, or ``None`` if the
    Skill did not run (skipped or upstream Skill failed).

    ``errors`` collects ``(skill_name, exception_message)`` for any Skill
    that errored. The pipeline does not raise — it captures errors so
    the caller can decide what to do per record.
    """

    maude_report_id: str
    extractor_result: ExtractionResult | None = None
    severity_result: ExtractionResult | None = None
    classifier_result: ExtractionResult | None = None
    classifier_skipped_reason: str | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        """True if at least one Skill produced a validated output."""
        return any(
            r is not None
            for r in (self.extractor_result, self.severity_result, self.classifier_result)
        )


def extract_record(
    *,
    extractor: Extractor,
    db: Database,
    event: NormalizedEventRecord,
    skill_extractor: LoadedSkill,
    skill_severity: LoadedSkill,
    skill_classifier: LoadedSkill,
) -> RecordExtractionResult:
    """Run all three Skills against a single normalized event.

    Args:
        extractor: A configured :class:`Extractor` (provider already chosen).
        db: Database for writing each Skill's extraction row.
        event: A row from ``normalized_events``.
        skill_extractor: Loaded Skill #1 (maude-narrative-extractor).
        skill_severity: Loaded Skill #3 (severity-triage).
        skill_classifier: Loaded Skill #4 (ai-failure-mode-classifier).

    Returns:
        A :class:`RecordExtractionResult` with per-Skill outputs and any errors.
    """
    errors: list[tuple[str, str]] = []

    # Skill #1 — primary extraction. Skills #3 and #4 read its output.
    extractor_input = _build_extractor_input(event)
    extractor_result: ExtractionResult | None = None
    try:
        extractor_result = extractor.run(skill=skill_extractor, input_record=extractor_input)
        _persist(db, event.maude_report_id, skill_extractor, extractor_result)
    except MaudeSignalError as exc:
        errors.append((skill_extractor.name, str(exc)))
        logger.warning(
            "skill_failed",
            skill=skill_extractor.name,
            maude_report_id=event.maude_report_id,
            error=str(exc),
        )
        # Without Skill #1 output, #3 and #4 cannot meaningfully run.
        return RecordExtractionResult(maude_report_id=event.maude_report_id, errors=errors)

    extractor_output = extractor_result.output

    # Skill #3 — severity-triage.
    severity_result: ExtractionResult | None = None
    severity_input = _build_severity_input(event, extractor_output)
    try:
        severity_result = extractor.run(skill=skill_severity, input_record=severity_input)
        _persist(db, event.maude_report_id, skill_severity, severity_result)
    except MaudeSignalError as exc:
        errors.append((skill_severity.name, str(exc)))
        logger.warning(
            "skill_failed",
            skill=skill_severity.name,
            maude_report_id=event.maude_report_id,
            error=str(exc),
        )

    # Skill #4 — ai-failure-mode-classifier. Skip if Skill #1 says non-AI.
    classifier_result: ExtractionResult | None = None
    classifier_skipped_reason: str | None = None
    if extractor_output.get("ai_related_flag") is False:
        classifier_skipped_reason = "extractor_ai_related_flag_false"
        logger.info(
            "skill_skipped",
            skill=skill_classifier.name,
            maude_report_id=event.maude_report_id,
            reason=classifier_skipped_reason,
        )
    else:
        classifier_input = _build_classifier_input(event, extractor_output)
        try:
            classifier_result = extractor.run(skill=skill_classifier, input_record=classifier_input)
            _persist(db, event.maude_report_id, skill_classifier, classifier_result)
        except MaudeSignalError as exc:
            errors.append((skill_classifier.name, str(exc)))
            logger.warning(
                "skill_failed",
                skill=skill_classifier.name,
                maude_report_id=event.maude_report_id,
                error=str(exc),
            )

    return RecordExtractionResult(
        maude_report_id=event.maude_report_id,
        extractor_result=extractor_result,
        severity_result=severity_result,
        classifier_result=classifier_result,
        classifier_skipped_reason=classifier_skipped_reason,
        errors=errors,
    )


# ----------------------------------------------------------------------
# Input shaping per Skill (each Skill's SKILL.md §3 is the contract)
# ----------------------------------------------------------------------


def _build_extractor_input(event: NormalizedEventRecord) -> dict[str, Any]:
    """Build the input dict for Skill #1 (maude-narrative-extractor)."""
    return {
        "maude_report_id": event.maude_report_id,
        "event_description": event.narrative or "",
        "mfr_narrative": event.mfr_narrative or "",
        "event_type": event.event_type or "",
        "product_code": event.product_code,
        "device_problem_codes": [],
        "brand_name": event.brand_name or "",
        "manufacturer": event.manufacturer or "",
    }


def _build_severity_input(
    event: NormalizedEventRecord,
    extractor_output: dict[str, Any],
) -> dict[str, Any]:
    """Build the input dict for Skill #3 (severity-triage)."""
    return {
        "maude_report_id": event.maude_report_id,
        "event_description": event.narrative or "",
        "mfr_narrative": event.mfr_narrative or "",
        "event_type": event.event_type or "",
        "patient_outcome_extracted": extractor_output.get("patient_outcome"),
        "product_code": event.product_code,
    }


def _build_classifier_input(
    event: NormalizedEventRecord,
    extractor_output: dict[str, Any],
) -> dict[str, Any]:
    """Build the input dict for Skill #4 (ai-failure-mode-classifier)."""
    return {
        "maude_report_id": event.maude_report_id,
        "event_description": event.narrative or "",
        "mfr_narrative": event.mfr_narrative or "",
        "extracted_failure_mode": extractor_output.get("failure_mode"),
        "extracted_device_problem": extractor_output.get("device_problem"),
        "ai_related_flag": extractor_output.get("ai_related_flag"),
        "ai_related_rationale": extractor_output.get("ai_related_rationale", ""),
        "product_code": event.product_code,
    }


def _persist(
    db: Database,
    maude_report_id: str,
    skill: LoadedSkill,
    result: ExtractionResult,
) -> None:
    """Write one Skill's validated output to the extractions table."""
    db.insert_extraction(
        extraction_id=result.extraction_id,
        maude_report_id=maude_report_id,
        skill_name=skill.name,
        skill_version=skill.version,
        model_used=result.model_used,
        output_payload=result.output,
        confidence_score=float(result.output.get("confidence_score", 0.0)),
        requires_review=bool(result.output.get("requires_human_review", True)),
    )
