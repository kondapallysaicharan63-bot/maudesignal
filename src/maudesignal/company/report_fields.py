"""Public reader for the openFDA event fields the company evidence stores.

``scripts/fetch_company_evidence.py`` used to import two private helpers of
``maudesignal.ingestion.pipeline``. This module is the public, company-owned version of
the same field reading (no patient fields). A unit test pins it to the pipeline helpers
on sample records, so a change on either side is caught.
"""

from __future__ import annotations

from typing import Any


def report_id(raw: dict[str, Any]) -> str | None:
    """The MDR report number of an openFDA event record, or None."""
    for key in ("mdr_report_key", "report_number"):
        val = raw.get(key)
        if val:
            return str(val)
    return None


def event_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Event type, narratives, manufacturer, brand and report source of one record."""
    device_list = raw.get("device") or []
    device_0 = device_list[0] if device_list else {}
    narrative: str | None = None
    mfr_narrative: str | None = None
    for block in raw.get("mdr_text") or []:
        text_type = (block.get("text_type_code") or "").lower()
        text_val = block.get("text")
        if not text_val:
            continue
        if "description of event" in text_type and narrative is None:
            narrative = text_val
        elif "manufacturer narrative" in text_type and mfr_narrative is None:
            mfr_narrative = text_val
    raw_type = raw.get("event_type")
    if isinstance(raw_type, list):
        raw_type = raw_type[0] if raw_type else None
    return {
        "event_type": str(raw_type).strip().lower() if raw_type else None,
        "narrative": narrative,
        "mfr_narrative": mfr_narrative,
        "manufacturer": device_0.get("manufacturer_d_name"),
        "brand_name": device_0.get("brand_name"),
        "report_source": raw.get("report_source_code") or "",
    }
