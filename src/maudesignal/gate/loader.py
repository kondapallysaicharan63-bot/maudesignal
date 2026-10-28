"""Build an ``EvidenceStore`` from MaudeSignal's database.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

import json
import re
from typing import Any

from maudesignal.gate.evidence import (
    DeviceRef,
    EvidenceRecord,
    EvidenceStore,
    LiteratureRef,
    RecallRef,
)
from maudesignal.sources.openfda_sources import SOURCE_510K, SOURCE_RECALL
from maudesignal.storage.database import Database
from maudesignal.storage.models import ExternalSourceRecord

SOURCE_PUBMED = "pubmed"
_MAX_SOURCES = 100_000
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _raw(row: ExternalSourceRecord) -> dict[str, Any]:
    try:
        data = json.loads(row.raw_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _ymd(iso: str | None) -> str | None:
    """'2021-08-12' -> '20210812' (None stays None)."""
    if not iso:
        return None
    digits = iso.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else None


def recall_from_row(row: ExternalSourceRecord) -> RecallRef:
    """Convert a stored ``fda_recall`` row to gate evidence."""
    raw = _raw(row)
    return RecallRef(
        recall_number=row.source_id,
        product_code=row.product_code or str(raw.get("product_code") or ""),
        event_number=(str(raw["res_event_number"]) if raw.get("res_event_number") else None),
        recalling_firm=row.authors,
        product_description=row.title or "",
        reason_for_recall=row.abstract or "",
        recall_status=raw.get("recall_status"),
        date_initiated=_ymd(row.publication_date),
        k_numbers=tuple(str(k).upper() for k in raw.get("k_numbers") or ()),
    )


def clearance_from_row(row: ExternalSourceRecord) -> DeviceRef:
    """Convert a stored ``fda_510k`` row to gate evidence."""
    raw = _raw(row)
    return DeviceRef(
        k_number=row.source_id,
        product_code=row.product_code or str(raw.get("product_code") or ""),
        device_name=row.title or "",
        company_name=row.authors,
        decision_date=row.publication_date,
        decision_code=raw.get("decision_code"),
        statement_or_summary=raw.get("statement_or_summary"),
    )


def article_from_row(row: ExternalSourceRecord) -> LiteratureRef:
    """Convert a stored ``pubmed`` row to gate evidence."""
    raw = _raw(row)
    m = _YEAR_RE.search(row.publication_date or "")
    abstract = row.abstract or ""
    if abstract.startswith("Source: "):  # legacy rows hold only the journal name
        abstract = ""
    return LiteratureRef(
        pmid=row.source_id,
        title=row.title or "",
        abstract=abstract,
        year=int(m.group(0)) if m else None,
        journal=raw.get("source"),
        product_code=row.product_code,
    )


def store_from_database(db: Database, *, product_code: str | None = None) -> EvidenceStore:
    """Load stored MAUDE events, the 510(k) catalog and fetched sources as gate evidence.

    Args:
        db: Open MaudeSignal database.
        product_code: Optional filter on MAUDE events to keep the store small
            (recalls, 510(k) records and literature are always loaded).
    """
    dates = db.date_received_lookup()
    records = [
        EvidenceRecord(
            report_id=ev.maude_report_id,
            product_code=ev.product_code,
            event_type=ev.event_type,
            date_received=dates.get(ev.maude_report_id),
            text=" ".join(t for t in (ev.narrative, ev.mfr_narrative) if t),
            manufacturer=ev.manufacturer,
            brand_name=ev.brand_name,
            report_source=ev.report_source,
        )
        for ev in db.list_normalized_events(product_code=product_code)
    ]
    devices = [
        DeviceRef(
            k_number=d.k_number,
            product_code=d.product_code,
            device_name=d.device_name,
            company_name=d.company_name,
        )
        for d in db.list_catalog_devices()
        if d.k_number
    ]

    def rows(source_type: str) -> list[ExternalSourceRecord]:
        found = db.list_external_sources(source_type=source_type, limit=_MAX_SOURCES)
        return sorted(found, key=lambda r: r.source_id)

    return EvidenceStore(
        records=records,
        devices=devices,
        recalls=[recall_from_row(r) for r in rows(SOURCE_RECALL)],
        clearances=[clearance_from_row(r) for r in rows(SOURCE_510K)],
        literature=[article_from_row(r) for r in rows(SOURCE_PUBMED)],
    )
