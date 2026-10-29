"""MHRA (UK) medical device safety alerts, via the public GOV.UK search API.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
Adopted by the project owner as the one non-FDA source (see CLAUDE.md §3).

The UK Medicines and Healthcare products Regulatory Agency publishes device
safety alerts and field safety notice roundups as GOV.UK documents of format
``medical_safety_alert``. This adapter searches them by keyword, keeps alerts
whose ``alert_type`` concerns devices, and stores each as an external source
(``source_type = "mhra_alert"``) so the gate can verify quotes from it.

They are **context, never FDA evidence**: they are not counted in any MAUDE
number, signal or comparison, and every surface labels them "MHRA (UK)". The
demo data covers FDA/MAUDE only; MaudeSignal does not claim EU MDR or other
regulators' coverage.

API: ``GET https://www.gov.uk/api/search.json`` (no key, documented at
https://docs.publishing.service.gov.uk/repos/search-api/using-the-search-api.html).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.sources.openfda_sources import record_id
from maudesignal.storage.database import Database

logger = get_logger(__name__)

SOURCE_MHRA = "mhra_alert"
SEARCH_URL = "https://www.gov.uk/api/search.json"
GOV_UK = "https://www.gov.uk"
FIELDS = (
    "title",
    "description",
    "link",
    "public_timestamp",
    "issued_date",
    "alert_type",
    "medical_specialism",
)
#: Alert types about devices (drug alerts are left out).
DEVICE_ALERT_TYPES = frozenset(
    {
        "devices",
        "medical-device-alert",
        "field-safety-notices",
        "device-safety-information",
        "national-patient-safety-alert",
    }
)
MAX_COUNT = 50


@dataclass(frozen=True)
class MhraAlert:
    """One MHRA safety alert as stored."""

    alert_id: str  # GOV.UK slug, e.g. "class-2-medical-device-..."
    title: str
    description: str
    issued: str | None  # YYYY-MM-DD
    alert_type: str | None
    url: str
    specialisms: tuple[str, ...]


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("value") or value.get("label")
    return str(value) if value else None


def parse_results(payload: dict[str, Any], *, devices_only: bool = True) -> list[MhraAlert]:
    """GOV.UK search results -> alerts (drug-only alerts dropped when ``devices_only``)."""
    out: list[MhraAlert] = []
    for r in payload.get("results") or []:
        link = str(r.get("link") or "")
        if not link:
            continue
        alert_type = _first(r.get("alert_type"))
        if devices_only and alert_type and alert_type not in DEVICE_ALERT_TYPES:
            continue
        issued = _first(r.get("issued_date")) or _first(r.get("public_timestamp"))
        spec = r.get("medical_specialism") or []
        out.append(
            MhraAlert(
                alert_id=link.rstrip("/").rsplit("/", 1)[-1],
                title=str(r.get("title") or ""),
                description=str(r.get("description") or ""),
                issued=issued[:10] if issued else None,
                alert_type=alert_type,
                url=link if link.startswith("http") else GOV_UK + link,
                specialisms=tuple(str(_first(s) or "") for s in spec if _first(s)),
            )
        )
    return out


def search_params(query: str, count: int = 20) -> dict[str, Any]:
    """Query parameters for one GOV.UK search (newest first)."""
    return {
        "filter_format": "medical_safety_alert",
        "q": query,
        "count": max(1, min(count, MAX_COUNT)),
        "order": "-public_timestamp",
        "fields": list(FIELDS),
    }


def store_alerts(db: Database, alerts: list[MhraAlert], *, product_code: str | None) -> int:
    """Upsert alerts as ``mhra_alert`` external sources tagged with the chosen product code."""
    for a in alerts:
        db.upsert_external_source(
            record_id=record_id(SOURCE_MHRA, a.alert_id),
            source_type=SOURCE_MHRA,
            source_id=a.alert_id,
            product_code=product_code,
            title=a.title,
            authors="MHRA (UK)",
            publication_date=a.issued,
            abstract=a.description,
            url=a.url,
            raw_payload={
                "alert_type": a.alert_type,
                "specialisms": list(a.specialisms),
                "regulator": "MHRA (UK)",
            },
        )
    return len(alerts)


def fetch_mhra_alerts(
    db: Database,
    *,
    query: str,
    product_code: str | None = None,
    count: int = 20,
    client: httpx.Client | None = None,
) -> list[MhraAlert]:
    """Search MHRA device alerts for ``query``, store them, and return them."""
    own = client is None
    http = client or httpx.Client(timeout=30.0, headers={"User-Agent": "MaudeSignal"})
    try:
        resp = http.get(SEARCH_URL, params=search_params(query, count))
        resp.raise_for_status()
        alerts = parse_results(resp.json())
    finally:
        if own:
            http.close()
    store_alerts(db, alerts, product_code=product_code)
    logger.info("mhra_alerts_stored", query=query, product_code=product_code, n=len(alerts))
    return alerts
