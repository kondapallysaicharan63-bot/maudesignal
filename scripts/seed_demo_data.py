"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Build the keyless demo database ``data/demo/maudesignal_demo.db``.

Fetches real FDA MAUDE device adverse-event reports from openFDA
(https://api.fda.gov/device/event.json) through the EXISTING ingestion code
(:class:`maudesignal.ingestion.openfda_client.OpenFDAClient` +
:func:`maudesignal.ingestion.pipeline.ingest_product_code`) and fills the
510(k) AI/ML device catalog with the EXISTING
:class:`maudesignal.catalog.fetcher.CatalogFetcher`. Writes
``data/demo/SEED_MANIFEST.json`` with the fetch timestamp, openFDA
``meta.last_updated``, the exact queries, and per-code counts.

No API key is required. ``OPENFDA_API_KEY`` is used if set (never written
anywhere). The whole run is ~20 HTTP requests and ~140 records, far below the
keyless 1,000 requests/day limit.

Seed plan (chosen 2026-10-27 by probing openFDA ``count=`` endpoints):

* ``LLZ`` (System, Image Processing, Radiological — the regulation 892.2050
  home of most AI radiology software) is the only AI-relevant code with
  steady weekly volume. Its *complete* Jul–Aug 2026 window is fetched so the
  7-day vs 4-week detector sees true counts, not a sample. (Sep 2026 alone
  holds ~270 LLZ reports — over the keyless demo budget.)
* ``QIH`` (Automated Radiological Image Processing Software), ``MYN``
  (Analyzer, Medical Image — CAD) and ``POK`` (Computer-Assisted Diagnostic
  Software For Lesions Suspicious For Cancer) are AI/CAD codes with only a
  handful of reports ever; all of them are fetched.
* Probed but returning zero reports: QAS, QFM, QDQ, QKQ, QBS, QJU, QPN.
  QNO and PIE return reports but are not AI devices (tongue stimulator,
  esophageal dilator), so they are excluded.

Usage::

    python scripts/seed_demo_data.py            # rebuild from scratch
    python scripts/seed_demo_data.py --no-catalog
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from maudesignal.catalog.fetcher import CatalogFetcher
from maudesignal.config import openfda_api_key_from_env
from maudesignal.ingestion.openfda_client import (
    OPENFDA_EVENT_ENDPOINT,
    OpenFDAClient,
    _build_query,
    search_param,
)
from maudesignal.ingestion.pipeline import ingest_product_code
from maudesignal.storage.database import Database

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "demo" / "maudesignal_demo.db"
MANIFEST_NAME = "SEED_MANIFEST.json"
MAX_TOTAL_RECORDS = 160  # hard cap; keyless openFDA allows 1,000 requests/day


@dataclass(frozen=True)
class SeedQuery:
    """One product-code query in the seed plan."""

    product_code: str
    device_name: str
    start_date: str | None
    end_date: str | None
    rationale: str


SEED_PLAN: tuple[SeedQuery, ...] = (
    SeedQuery(
        "LLZ",
        "System, Image Processing, Radiological",
        "20260701",
        "20260831",
        "complete Jul-Aug 2026 window so weekly counts are exact",
    ),
    SeedQuery("QIH", "Automated Radiological Image Processing Software", None, None, "all reports"),
    SeedQuery("MYN", "Analyzer, Medical Image", None, None, "all reports"),
    SeedQuery(
        "POK",
        "Computer-Assisted Diagnostic Software For Lesions Suspicious For Cancer",
        None,
        None,
        "all reports",
    ),
)


def _probe(query: str, api_key: str | None) -> tuple[int, str | None]:
    """Return (total matching records, meta.last_updated) for a search query."""
    params: dict[str, str | int] = {"search": search_param(query), "limit": 1}
    if api_key:
        params["api_key"] = api_key
    resp = httpx.get(OPENFDA_EVENT_ENDPOINT, params=params, timeout=30.0)
    if resp.status_code == 404:
        return 0, None
    resp.raise_for_status()
    meta: dict[str, Any] = resp.json().get("meta", {})
    total = int(meta.get("results", {}).get("total", 0))
    return total, meta.get("last_updated")


def seed(db_path: Path, *, with_catalog: bool) -> dict[str, Any]:
    """Rebuild the demo database and return the manifest dict."""
    api_key = openfda_api_key_from_env()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)

    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    last_updated: str | None = None
    queries: list[dict[str, Any]] = []
    budget = MAX_TOTAL_RECORDS

    with OpenFDAClient(api_key=api_key) as client:
        for plan in SEED_PLAN:
            query = _build_query(plan.product_code, plan.start_date, plan.end_date)
            total, updated = _probe(query, api_key)
            last_updated = last_updated or updated
            limit = min(total, budget)
            result = ingest_product_code(
                client=client,
                db=db,
                product_code=plan.product_code,
                start_date=plan.start_date,
                end_date=plan.end_date,
                limit=limit,
            )
            budget -= result.records_fetched
            stored = db.count_raw_reports(plan.product_code)
            queries.append(
                {
                    "product_code": plan.product_code,
                    "device_name": plan.device_name,
                    "rationale": plan.rationale,
                    "endpoint": OPENFDA_EVENT_ENDPOINT,
                    "search": query,
                    "example_url": (
                        f"{OPENFDA_EVENT_ENDPOINT}?search={query}&limit={max(limit, 1)}"
                    ),
                    "date_received_start": plan.start_date,
                    "date_received_end": plan.end_date,
                    "matching_total_at_fetch": total,
                    "records_fetched": result.records_fetched,
                    "records_stored": stored,
                    "complete": result.records_fetched >= total,
                    "date_received_min_max": _date_span(db, plan.product_code),
                    "skip_reasons": result.skip_reasons,
                }
            )
            print(f"{plan.product_code}: matching={total} fetched={result.records_fetched}")
            time.sleep(0.3)

    catalog: dict[str, Any] = {"populated": False}
    if with_catalog:
        cat = CatalogFetcher(db, api_key=api_key).update()
        in_catalog = {d.product_code for d in db.list_catalog_devices()}
        catalog = {
            "populated": True,
            "source": "openFDA 510(k) keyword search via maudesignal.catalog.fetcher",
            "devices_found": cat.devices_found,
            "keywords_searched": cat.keywords_searched,
            "errors": cat.errors,
            "seeded_codes_in_catalog": sorted(
                q.product_code for q in SEED_PLAN if q.product_code in in_catalog
            ),
        }
        print(f"catalog: {cat.devices_found} product codes, {len(cat.errors)} errors")

    return {
        "schema_version": "1.0",
        "generated_by": "scripts/seed_demo_data.py",
        "fetched_at_utc": fetched_at,
        "openfda_meta_last_updated": last_updated,
        "api_key_used": api_key is not None,
        "max_total_records": MAX_TOTAL_RECORDS,
        "database": (
            str(db_path.relative_to(REPO_ROOT))
            if db_path.is_relative_to(REPO_ROOT)
            else db_path.name
        ),
        "product_codes": [q.product_code for q in SEED_PLAN],
        "record_counts": {q["product_code"]: q["records_stored"] for q in queries},
        "total_records": sum(q["records_stored"] for q in queries),
        "max_date_received": db.max_date_received(),
        "queries": queries,
        "catalog": catalog,
        "notes": [
            "Data are public, de-identified FDA MAUDE reports; no PHI.",
            "Counts reflect openFDA at fetch time; openFDA re-publishes weekly, so a "
            "re-run may differ slightly.",
            "MAUDE product codes are reporter-assigned; a few LLZ reports may concern "
            "non-AI devices.",
        ],
    }


def _date_span(db: Database, product_code: str) -> list[str | None]:
    dates = sorted(d for _, pc, d, _ in db.list_event_facts(product_code) if d and pc)
    return [dates[0], dates[-1]] if dates else [None, None]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2] if __doc__ else None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-catalog", action="store_true", help="Skip the 510(k) catalog step.")
    args = parser.parse_args(argv)

    db_path: Path = args.db.resolve()
    manifest = seed(db_path, with_catalog=not args.no_catalog)
    manifest_path = db_path.parent / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    size_kb = db_path.stat().st_size / 1024
    print(f"wrote {db_path} ({size_kb:.0f} KB) and {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
