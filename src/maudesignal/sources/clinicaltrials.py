"""ClinicalTrials.gov fetcher using the free v2 API (Phase 4).

ClinicalTrials.gov provides a free REST API (no key required).
API docs: https://clinicaltrials.gov/data-api/api
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.sources.pubmed import _record_id
from maudesignal.storage.database import Database

logger = get_logger(__name__)

_API_BASE = "https://clinicaltrials.gov/api/v2/studies"
_DEFAULT_MAX_RESULTS = 20


@dataclass(frozen=True)
class ClinicalTrial:
    """Parsed ClinicalTrials.gov study summary."""

    nct_id: str
    title: str
    status: str
    phase: str
    start_date: str
    conditions: str
    interventions: str
    url: str
    raw: dict[str, Any]


class ClinicalTrialsFetcher:
    """Fetch ClinicalTrials.gov studies related to a query or product code."""

    def __init__(self, *, db: Database) -> None:
        """Initialize with a Database instance."""
        self._db = db
        self._client = httpx.Client(timeout=30.0)

    def fetch(
        self,
        *,
        query: str,
        product_code: str | None = None,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> list[ClinicalTrial]:
        """Search ClinicalTrials.gov and store results; return fetched trials.

        Args:
            query: Search query (e.g. "artificial intelligence radiology").
            product_code: Optional product code to tag stored records.
            max_results: Maximum number of studies to fetch.
        """
        params: dict[str, str | int] = {
            "query.term": query,
            "pageSize": min(max_results, 100),
            "format": "json",
            "fields": "NCTId,BriefTitle,OverallStatus,Phase,StartDate,Condition,InterventionName",
        }
        try:
            resp = self._client.get(_API_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("clinicaltrials_fetch_failed", query=query, error=str(exc))
            return []

        studies = data.get("studies", [])
        trials: list[ClinicalTrial] = []

        for study in studies:
            trial = _parse_study(study)
            if trial is None:
                continue
            record_id = _record_id("clinicaltrials", trial.nct_id)
            self._db.upsert_external_source(
                record_id=record_id,
                source_type="clinicaltrials",
                source_id=trial.nct_id,
                product_code=product_code,
                title=trial.title,
                authors=None,
                publication_date=trial.start_date,
                abstract=f"Status: {trial.status} | Phase: {trial.phase} | "
                f"Conditions: {trial.conditions}",
                url=trial.url,
                raw_payload=trial.raw,
            )
            trials.append(trial)

        logger.info(
            "clinicaltrials_fetch_complete",
            query=query,
            fetched=len(trials),
            product_code=product_code,
        )
        return trials

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _parse_study(study: dict[str, Any]) -> ClinicalTrial | None:
    """Parse a single study dict from the ClinicalTrials API response."""
    try:
        proto = study.get("protocolSection", {})
        id_mod = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        design_mod = proto.get("designModule", {})
        conds_mod = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})

        nct_id = id_mod.get("nctId", "")
        if not nct_id:
            return None

        title = id_mod.get("briefTitle", "")
        status = status_mod.get("overallStatus", "")
        phase_list = design_mod.get("phases", [])
        phase = ", ".join(phase_list) if phase_list else "N/A"
        start_date = status_mod.get("startDateStruct", {}).get("date", "")
        conditions = "; ".join(conds_mod.get("conditions", [])[:5])
        interventions_list = [iv.get("name", "") for iv in arms_mod.get("interventions", [])[:5]]
        interventions = "; ".join(interventions_list)

        return ClinicalTrial(
            nct_id=nct_id,
            title=title,
            status=status,
            phase=phase,
            start_date=start_date,
            conditions=conditions,
            interventions=interventions,
            url=f"https://clinicaltrials.gov/study/{nct_id}",
            raw=study,
        )
    except Exception:
        return None
