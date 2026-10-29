"""openFDA device recalls + 510(k) clearance records, stored as external sources.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A QA/RA analyst investigating a signal today opens MAUDE, the recall database,
the 510(k) database and PubMed in four tabs. This module brings the two FDA
pieces next to the MAUDE reports MaudeSignal already stores, so the copilot can
answer from them and the citation gate can verify anything it repeats.

Rows are stored in the pre-existing ``external_sources`` table
(``ExternalSourceRecord``) with ``source_type`` ``"fda_recall"`` or
``"fda_510k"``; the demo DB therefore works offline.

Endpoints (keyless; ``OPENFDA_API_KEY`` used when set, never stored):
    https://api.fda.gov/device/recall.json  (search ``product_code:XXX``)
    https://api.fda.gov/device/510k.json    (search ``k_number:K...`` / ``product_code:XXX``)

Field names were checked against live responses on 2026-10-27:
recall rows carry ``product_res_number`` (e.g. ``Z-0186-2027``),
``res_event_number``, ``product_code``, ``k_numbers``, ``recalling_firm``,
``product_description``, ``reason_for_recall``, ``recall_status``,
``event_date_initiated`` (``YYYY-MM-DD``), ``cfres_id``; 510(k) rows carry
``k_number``, ``applicant``, ``device_name``, ``product_code``,
``decision_date``, ``decision_code``, ``decision_description``,
``statement_or_summary``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.ingestion.openfda_client import search_param
from maudesignal.storage.database import Database

logger = get_logger(__name__)

RECALL_ENDPOINT = "https://api.fda.gov/device/recall.json"
K510_ENDPOINT = "https://api.fda.gov/device/510k.json"
SOURCE_RECALL = "fda_recall"
SOURCE_510K = "fda_510k"
OPENFDA_MAX_LIMIT = 1000  # openFDA per-request cap

_RECALL_KEEP = (
    "product_res_number",
    "res_event_number",
    "cfres_id",
    "product_code",
    "k_numbers",
    "pma_numbers",
    "recalling_firm",
    "product_description",
    "reason_for_recall",
    "root_cause_description",
    "action",
    "recall_status",
    "event_date_initiated",
    "event_date_posted",
    "event_date_terminated",
    "product_quantity",
)
_510K_KEEP = (
    "k_number",
    "applicant",
    "device_name",
    "product_code",
    "decision_date",
    "decision_code",
    "decision_description",
    "statement_or_summary",
    "clearance_type",
    "date_received",
    "advisory_committee_description",
)


def record_id(source_type: str, source_id: str) -> str:
    """Stable primary key for an external source row (same scheme as PubMed)."""
    digest = hashlib.sha256(f"{source_type}:{source_id}".encode()).hexdigest()[:16]
    return f"{source_type}-{digest}"


def recall_url(cfres_id: str | None) -> str | None:
    """Public FDA recall database page for a recall row."""
    if not cfres_id:
        return None
    return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={cfres_id}"


def k510_url(k_number: str) -> str:
    """Public FDA 510(k) database page for a K-number."""
    return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k_number}"


@dataclass(frozen=True)
class SourceFetchResult:
    """Outcome of one openFDA source query."""

    search: str
    matching_total: int
    stored: int
    last_updated: str | None = None


class OpenFDASourceFetcher:
    """Fetch openFDA recall and 510(k) records into ``external_sources``."""

    def __init__(
        self,
        db: Database,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Create a fetcher.

        Args:
            db: Database to store rows in.
            api_key: Optional openFDA key (never stored).
            client: Optional injected HTTP client (tests use a mock transport).
        """
        self._db = db
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def _get(
        self, endpoint: str, search: str, limit: int, *, sort: str | None = None
    ) -> tuple[list[dict[str, Any]], int, str | None]:
        params: dict[str, str | int] = {"search": search_param(search), "limit": limit}
        if sort:
            params["sort"] = sort
        if self._api_key:
            params["api_key"] = self._api_key
        resp = self._client.get(endpoint, params=params)
        if resp.status_code == 404:  # openFDA: "No matches found!"
            return [], 0, None
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        meta = data.get("meta", {})
        total = int(meta.get("results", {}).get("total", 0))
        results: list[dict[str, Any]] = data.get("results", [])
        return results, total, meta.get("last_updated")

    def fetch_recalls(
        self, product_code: str, *, limit: int = OPENFDA_MAX_LIMIT
    ) -> SourceFetchResult:
        """Fetch (up to ``limit``) recalls for one product code, newest first, and store them."""
        search = f"product_code:{product_code}"
        rows, total, updated = self._get(
            RECALL_ENDPOINT,
            search,
            max(1, min(limit, OPENFDA_MAX_LIMIT)),
            sort="event_date_initiated:desc",
        )
        stored = 0
        for r in rows:
            number = str(r.get("product_res_number") or r.get("cfres_id") or "").strip()
            if not number:
                continue
            slim = {k: r[k] for k in _RECALL_KEEP if k in r}
            self._db.upsert_external_source(
                record_id=record_id(SOURCE_RECALL, number),
                source_type=SOURCE_RECALL,
                source_id=number,
                product_code=str(r.get("product_code") or product_code),
                title=r.get("product_description"),
                authors=r.get("recalling_firm"),
                publication_date=r.get("event_date_initiated"),
                abstract=r.get("reason_for_recall"),
                url=recall_url(r.get("cfres_id")),
                raw_payload=slim,
            )
            stored += 1
        logger.info("recalls_fetched", product_code=product_code, total=total, stored=stored)
        return SourceFetchResult(search, total, stored, updated)

    def _store_510k(self, rows: list[dict[str, Any]]) -> int:
        stored = 0
        for r in rows:
            k = str(r.get("k_number") or "").strip().upper()
            if not k:
                continue
            slim = {key: r[key] for key in _510K_KEEP if key in r}
            self._db.upsert_external_source(
                record_id=record_id(SOURCE_510K, k),
                source_type=SOURCE_510K,
                source_id=k,
                product_code=r.get("product_code"),
                title=r.get("device_name"),
                authors=r.get("applicant"),
                publication_date=r.get("decision_date"),
                abstract=None,
                url=k510_url(k),
                raw_payload=slim,
            )
            stored += 1
        return stored

    def fetch_510k(self, k_numbers: list[str]) -> SourceFetchResult:
        """Fetch and store specific 510(k) records by K-number (one request per 50)."""
        ks = sorted({k.strip().upper() for k in k_numbers if k and k.strip()})
        total = stored = 0
        updated: str | None = None
        search = ""
        for i in range(0, len(ks), 50):
            chunk = ks[i : i + 50]
            search = "k_number:(" + "+".join(chunk) + ")"
            rows, n, updated = self._get(K510_ENDPOINT, search, len(chunk))
            total += n
            stored += self._store_510k(rows)
        return SourceFetchResult(search, total, stored, updated)

    def fetch_510k_for_product(self, product_code: str, *, limit: int = 10) -> SourceFetchResult:
        """Fetch and store the most recent 510(k) decisions for one product code."""
        search = f"product_code:{product_code}"
        rows, total, updated = self._get(
            K510_ENDPOINT, search, max(1, min(limit, OPENFDA_MAX_LIMIT)), sort="decision_date:desc"
        )
        return SourceFetchResult(search, total, self._store_510k(rows), updated)
