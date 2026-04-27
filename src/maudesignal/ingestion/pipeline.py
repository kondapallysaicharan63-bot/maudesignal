"""Ingestion pipeline — pulls from openFDA and persists to the database.

This is the high-level orchestrator used by the CLI. It:
1. Queries openFDA for reports matching the filters.
2. Stores each raw report (idempotent, FR-05).
3. Extracts normalized fields for querying.
4. Returns a summary of what was done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maudesignal.common.logging import get_logger, truncate_for_log
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.storage.database import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    """Summary of a single ingestion run (DR-09)."""

    product_code: str
    records_fetched: int
    records_new: int
    records_skipped: int
    skip_reasons: dict[str, int]


def ingest_product_code(
    *,
    client: OpenFDAClient,
    db: Database,
    product_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> IngestionResult:
    """Ingest MAUDE reports for one product code into the database.

    Args:
        client: A configured OpenFDAClient.
        db: The Database instance for persistence.
        product_code: FDA product code to filter by.
        start_date: Earliest date_received (YYYYMMDD).
        end_date: Latest date_received (YYYYMMDD).
        limit: Max records to ingest, or None for all.

    Returns:
        Summary of records fetched / new / skipped.
    """
    fetched = 0
    new_count = 0
    skip_reasons: dict[str, int] = {}

    logger.info(
        "ingestion_start",
        product_code=product_code,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    for raw in client.iter_reports(
        product_code=product_code,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    ):
        fetched += 1
        maude_id = _extract_report_id(raw)
        if not maude_id:
            skip_reasons["missing_report_id"] = (
                skip_reasons.get("missing_report_id", 0) + 1
            )
            continue

        inserted = db.upsert_raw_report(
            maude_report_id=maude_id,
            product_code=product_code,
            date_received=raw.get("date_received"),
            date_of_event=raw.get("date_of_event"),
            raw_payload=raw,
        )
        if inserted:
            new_count += 1

        # Build the normalized view
        normalized = _normalize(raw, product_code)
        if normalized["narrative"] is None and normalized["mfr_narrative"] is None:
            # Per DR-08 — skip extraction-wise but still keep raw.
            # We DO still store the normalized row (empty narratives)
            # so queries show it exists; the extractor will skip it.
            skip_reasons["missing_narrative"] = (
                skip_reasons.get("missing_narrative", 0) + 1
            )

        db.upsert_normalized_event(
            maude_report_id=maude_id,
            product_code=product_code,
            event_type=normalized["event_type"],
            event_date=normalized["event_date"],
            narrative=normalized["narrative"],
            mfr_narrative=normalized["mfr_narrative"],
            manufacturer=normalized["manufacturer"],
            brand_name=normalized["brand_name"],
        )

        if fetched % 25 == 0:
            logger.info(
                "ingestion_progress",
                product_code=product_code,
                fetched=fetched,
                new=new_count,
            )

    result = IngestionResult(
        product_code=product_code,
        records_fetched=fetched,
        records_new=new_count,
        records_skipped=sum(skip_reasons.values()),
        skip_reasons=skip_reasons,
    )

    logger.info(
        "ingestion_complete",
        product_code=product_code,
        fetched=fetched,
        new=new_count,
        skipped=result.records_skipped,
        skip_reasons=skip_reasons,
    )

    return result


# ----------------------------------------------------------------------
# Helpers for pulling fields out of openFDA's nested JSON shape
# ----------------------------------------------------------------------


def _extract_report_id(raw: dict[str, Any]) -> str | None:
    """Return the MDR report number from an openFDA event record."""
    # openFDA uses either mdr_report_key or report_number depending on dataset era
    for key in ("mdr_report_key", "report_number"):
        val = raw.get(key)
        if val:
            return str(val)
    return None


def _normalize(raw: dict[str, Any], product_code: str) -> dict[str, Any]:
    """Extract a flat subset of fields from the nested openFDA payload."""
    device_list = raw.get("device") or []
    device_0 = device_list[0] if device_list else {}

    mdr_text_list = raw.get("mdr_text") or []
    narrative: str | None = None
    mfr_narrative: str | None = None
    for block in mdr_text_list:
        text_type = (block.get("text_type_code") or "").lower()
        text_val = block.get("text")
        if not text_val:
            continue
        if "description of event" in text_type and narrative is None:
            narrative = text_val
        elif "manufacturer narrative" in text_type and mfr_narrative is None:
            mfr_narrative = text_val

    # event_type in openFDA is a list like ["Injury"]
    event_types = raw.get("event_type") or []
    event_type_str = event_types[0].lower() if event_types else None

    return {
        "event_type": event_type_str,
        "event_date": raw.get("date_of_event") or raw.get("date_received"),
        "narrative": narrative,
        "mfr_narrative": mfr_narrative,
        "manufacturer": device_0.get("manufacturer_d_name"),
        "brand_name": device_0.get("brand_name"),
    }
