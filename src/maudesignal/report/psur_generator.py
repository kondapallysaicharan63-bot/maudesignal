"""PSUR report generator — Phase 5.

Aggregates all prior pipeline outputs for a product code and calls Skill
psur-report-drafter to produce a structured PSUR draft.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.storage.database import Database


@dataclass(frozen=True)
class PsurDraft:
    """Result of one PSUR generation run."""

    report_id: str
    product_code: str
    signal_assessment: str
    executive_summary: str
    sections: list[dict[str, str]]
    recommended_actions: list[str]
    confidence_score: float
    output: dict[str, Any]
    reporting_period_start: str
    reporting_period_end: str


@dataclass
class PsurInput:
    """Aggregated inputs for the PSUR Skill."""

    product_code: str
    device_name: str
    reporting_period_start: str
    reporting_period_end: str
    total_reports: int
    ai_related_count: int
    ai_rate: float
    severity_distribution: dict[str, int] = field(default_factory=dict)
    top_failure_modes: list[dict[str, Any]] = field(default_factory=list)
    root_cause_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    trend_summary: dict[str, Any] | None = None
    pubmed_citations: int = 0
    clinical_trials_count: int = 0


class PsurGenerator:
    """Orchestrate all pipeline stages into a PSUR draft for one product code."""

    def __init__(
        self,
        *,
        extractor: Extractor,
        db: Database,
        skills_root: Path,
    ) -> None:
        """Initialize with extractor, database, and skills directory."""
        self._extractor = extractor
        self._db = db
        loader = SkillLoader(skills_root)
        self._skill = loader.load("psur-report-drafter")

    def generate(
        self,
        *,
        product_code: str,
        device_name: str = "",
        window_days: int = 180,
    ) -> PsurDraft:
        """Generate a PSUR draft for a product code.

        Args:
            product_code: FDA product code.
            device_name: Human-readable device name (optional, uses product_code if blank).
            window_days: Reporting window in days (default 180 = 6 months).
        """
        psur_input = self._aggregate(
            product_code=product_code,
            device_name=device_name or product_code,
            window_days=window_days,
        )
        result = self._extractor.run(self._skill, _to_skill_dict(psur_input))
        report_id = f"psur-{uuid.uuid4().hex[:12]}"

        self._db.insert_psur_report(
            report_id=report_id,
            product_code=product_code,
            reporting_period_start=psur_input.reporting_period_start,
            reporting_period_end=psur_input.reporting_period_end,
            signal_assessment=result.output.get("signal_assessment", "no_signal"),
            skill_version=self._skill.version,
            model_used=result.model_used,
            output_payload=result.output,
            confidence_score=result.output.get("confidence_score", 0.0),
        )

        return PsurDraft(
            report_id=report_id,
            product_code=product_code,
            signal_assessment=result.output.get("signal_assessment", "no_signal"),
            executive_summary=result.output.get("executive_summary", ""),
            sections=result.output.get("sections", []),
            recommended_actions=result.output.get("recommended_actions", []),
            confidence_score=result.output.get("confidence_score", 0.0),
            output=result.output,
            reporting_period_start=psur_input.reporting_period_start,
            reporting_period_end=psur_input.reporting_period_end,
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        *,
        product_code: str,
        device_name: str,
        window_days: int,
    ) -> PsurInput:
        """Gather statistics from all pipeline stages for the product code."""
        now = datetime.now(UTC)
        period_start = (now - timedelta(days=window_days)).date()
        period_end = now.date()
        since = now - timedelta(days=window_days)
        since_naive = since.replace(tzinfo=None)

        # Extractions
        extractor_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="maude-narrative-extractor",
        )
        in_window = [r for r in extractor_rows if r.extraction_ts >= since_naive]
        total = len(in_window)
        ai_count = sum(
            1 for r in in_window if json.loads(r.output_json).get("ai_related_flag") is True
        )
        ai_rate = ai_count / total if total else 0.0

        # Severity distribution
        sev_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="severity-triage",
        )
        sev_in_window = [r for r in sev_rows if r.extraction_ts >= since_naive]
        sev_dist: dict[str, int] = {"death": 0, "serious_injury": 0, "malfunction": 0, "other": 0}
        for r in sev_in_window:
            sev = json.loads(r.output_json).get("severity", "other")
            if sev in sev_dist:
                sev_dist[sev] += 1
            else:
                sev_dist["other"] += 1

        # Failure mode distribution
        classifier_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="ai-failure-mode-classifier",
        )
        mode_counts: dict[str, int] = {}
        for r in [r for r in classifier_rows if r.extraction_ts >= since_naive]:
            cat = json.loads(r.output_json).get("failure_mode_category", "unknown")
            if cat != "not_ai_related":
                mode_counts[cat] = mode_counts.get(cat, 0) + 1
        top_modes = sorted(mode_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_failure_modes = [{"category": k, "count": v} for k, v in top_modes]

        # Root-cause hypotheses
        rc_reports = self._db.list_root_cause_reports(product_code=product_code)
        rc_hypotheses: list[dict[str, Any]] = []
        for rc in rc_reports[:5]:
            out = json.loads(rc.output_json)
            rc_hypotheses.append(
                {
                    "failure_mode": rc.failure_mode_category,
                    "hypothesis": out.get("root_cause_hypothesis", ""),
                    "confidence": rc.confidence_score,
                }
            )

        # Trend summary (most recent snapshot for ai_rate)
        trend_snaps = self._db.list_trend_snapshots(
            product_code=product_code, metric_name="ai_rate", limit=1
        )
        trend_summary: dict[str, Any] | None = None
        if trend_snaps:
            ts = trend_snaps[0]
            out = json.loads(ts.output_json)
            trend_summary = {
                "direction": ts.trend_direction,
                "signal_level": ts.signal_level,
                "narrative": out.get("regulatory_narrative", ""),
            }

        # External sources
        pubmed_count = self._db.count_external_sources(source_type="pubmed")
        ct_count = self._db.count_external_sources(source_type="clinicaltrials")

        return PsurInput(
            product_code=product_code,
            device_name=device_name,
            reporting_period_start=str(period_start),
            reporting_period_end=str(period_end),
            total_reports=total,
            ai_related_count=ai_count,
            ai_rate=ai_rate,
            severity_distribution=sev_dist,
            top_failure_modes=top_failure_modes,
            root_cause_hypotheses=rc_hypotheses,
            trend_summary=trend_summary,
            pubmed_citations=pubmed_count,
            clinical_trials_count=ct_count,
        )


def _to_skill_dict(psur_input: PsurInput) -> dict[str, Any]:
    """Convert PsurInput to the Skill's expected input dict."""
    d: dict[str, Any] = {
        "product_code": psur_input.product_code,
        "device_name": psur_input.device_name,
        "reporting_period_start": psur_input.reporting_period_start,
        "reporting_period_end": psur_input.reporting_period_end,
        "total_reports": psur_input.total_reports,
        "ai_related_count": psur_input.ai_related_count,
        "ai_rate": psur_input.ai_rate,
        "severity_distribution": psur_input.severity_distribution,
        "top_failure_modes": psur_input.top_failure_modes,
        "root_cause_hypotheses": psur_input.root_cause_hypotheses,
        "pubmed_citations": psur_input.pubmed_citations,
        "clinical_trials_count": psur_input.clinical_trials_count,
    }
    if psur_input.trend_summary is not None:
        d["trend_summary"] = psur_input.trend_summary
    return d
