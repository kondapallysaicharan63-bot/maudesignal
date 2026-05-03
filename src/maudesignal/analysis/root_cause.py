"""Root-cause analysis pipeline (Phase 2).

Clusters extractions by failure_mode_category for a product code, then
calls Skill root-cause-analyzer to synthesize a structured hypothesis.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.storage.database import Database

_MIN_CLUSTER_SIZE = 3
_MAX_EXCERPTS = 10


@dataclass(frozen=True)
class RootCauseCluster:
    """A cluster of extractions sharing one failure_mode_category."""

    product_code: str
    failure_mode_category: str
    cluster_size: int
    narrative_excerpts: list[str]
    severity_distribution: dict[str, int]
    date_range_days: int


@dataclass(frozen=True)
class RootCauseRun:
    """Result of analyzing one cluster."""

    cluster: RootCauseCluster
    output: dict[str, Any]
    report_id: str
    skipped: bool = False
    skip_reason: str | None = None


class RootCauseAnalyzer:
    """Clusters extractions and runs Skill root-cause-analyzer on each cluster."""

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
        self._skill = loader.load("root-cause-analyzer")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        product_code: str,
        device_name: str = "",
        min_cluster_size: int = _MIN_CLUSTER_SIZE,
    ) -> list[RootCauseRun]:
        """Analyze all failure-mode clusters for a product code.

        Returns one RootCauseRun per cluster (including skipped ones).
        """
        clusters = self._build_clusters(product_code, min_cluster_size)
        results: list[RootCauseRun] = []
        for cluster in clusters:
            run = self._analyze_cluster(cluster, device_name)
            results.append(run)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_clusters(self, product_code: str, min_cluster_size: int) -> list[RootCauseCluster]:
        """Group ai-failure-mode-classifier extractions by failure_mode_category."""
        classifier_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="ai-failure-mode-classifier",
        )
        extractor_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="maude-narrative-extractor",
        )
        severity_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="severity-triage",
        )

        # Build lookup dicts keyed by maude_report_id
        excerpts_by_id: dict[str, str] = {}
        for row in extractor_rows:
            out = json.loads(row.output_json)
            exc = out.get("narrative_excerpt") or ""
            if exc:
                excerpts_by_id[row.maude_report_id] = exc[:200]

        severity_by_id: dict[str, str] = {}
        for row in severity_rows:
            out = json.loads(row.output_json)
            sev = out.get("severity") or "other"
            severity_by_id[row.maude_report_id] = sev

        event_dates_by_id: dict[str, datetime] = {}
        for row in classifier_rows:
            event_dates_by_id[row.maude_report_id] = row.extraction_ts

        # Group by category
        by_category: dict[str, list[str]] = {}
        for row in classifier_rows:
            out = json.loads(row.output_json)
            cat = out.get("failure_mode_category") or "other_ai_related"
            if cat == "not_ai_related":
                continue
            by_category.setdefault(cat, []).append(row.maude_report_id)

        clusters: list[RootCauseCluster] = []
        for category, report_ids in by_category.items():
            if len(report_ids) < min_cluster_size:
                continue
            excerpts = [excerpts_by_id[rid] for rid in report_ids if rid in excerpts_by_id]
            excerpts = excerpts[:_MAX_EXCERPTS]

            sev_dist: dict[str, int] = {
                "death": 0,
                "serious_injury": 0,
                "malfunction": 0,
                "other": 0,
            }
            for rid in report_ids:
                sev = severity_by_id.get(rid, "other")
                if sev in sev_dist:
                    sev_dist[sev] += 1
                else:
                    sev_dist["other"] += 1

            dates = [event_dates_by_id[rid] for rid in report_ids if rid in event_dates_by_id]
            date_range = 0
            if len(dates) >= 2:
                date_range = (max(dates) - min(dates)).days

            clusters.append(
                RootCauseCluster(
                    product_code=product_code,
                    failure_mode_category=category,
                    cluster_size=len(report_ids),
                    narrative_excerpts=excerpts,
                    severity_distribution=sev_dist,
                    date_range_days=date_range,
                )
            )
        return clusters

    def _analyze_cluster(self, cluster: RootCauseCluster, device_name: str) -> RootCauseRun:
        """Run Skill root-cause-analyzer on one cluster."""
        input_record: dict[str, Any] = {
            "product_code": cluster.product_code,
            "device_name": device_name or cluster.product_code,
            "failure_mode_category": cluster.failure_mode_category,
            "cluster_size": cluster.cluster_size,
            "narrative_excerpts": cluster.narrative_excerpts,
            "severity_distribution": cluster.severity_distribution,
            "date_range_days": cluster.date_range_days,
        }
        result = self._extractor.run(self._skill, input_record)
        report_id = _stable_report_id(cluster.product_code, cluster.failure_mode_category)
        self._db.insert_root_cause_report(
            report_id=report_id,
            product_code=cluster.product_code,
            failure_mode_category=cluster.failure_mode_category,
            cluster_size=cluster.cluster_size,
            skill_version=self._skill.version,
            model_used=result.model_used,
            output_payload=result.output,
            confidence_score=result.output.get("confidence_score", 0.0),
            requires_review=result.output.get("requires_human_review", True),
        )
        return RootCauseRun(cluster=cluster, output=result.output, report_id=report_id)


def _stable_report_id(product_code: str, category: str) -> str:
    """Generate a time-unique report ID for a cluster."""
    token = f"{product_code}:{category}:{datetime.now(UTC).isoformat()}"
    digest = hashlib.sha256(token.encode()).hexdigest()[:12]
    return f"rc-{digest}-{uuid.uuid4().hex[:8]}"
