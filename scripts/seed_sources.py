"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Add the scattered sources to the keyless demo database: FDA device recalls and
510(k) clearance records (openFDA) and PubMed abstracts (NCBI E-utilities) for
the demo product codes, so the copilot's ``recalls`` / ``device_510k`` /
``literature`` tools and the citation gate work offline in the public demo.

Run it AFTER ``scripts/seed_demo_data.py`` (which rebuilds the DB and rewrites
the manifest). It replaces only the ``fda_recall`` / ``fda_510k`` / ``pubmed``
rows and adds an ``external_sources`` section to ``SEED_MANIFEST.json``.

No API key is required. ``OPENFDA_API_KEY`` / ``NCBI_API_KEY`` are used if set
(never written anywhere). About 20 openFDA requests and 12 NCBI requests.

Plan:

* recalls: every openFDA recall row for each code (``product_code:XXX``, newest
  first, openFDA's 1,000-row cap) so stored recall counts are exact;
* 510(k): every K-number cited by those recalls, the catalog K-numbers, plus
  the 10 most recent decisions per code;
* PubMed: up to 5 relevance-sorted articles with abstracts per code.

Usage::

    python scripts/seed_sources.py
    python scripts/seed_sources.py --db path/to/other.db --no-manifest
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.config import openfda_api_key_from_env
from maudesignal.sources.openfda_sources import (
    K510_ENDPOINT,
    RECALL_ENDPOINT,
    SOURCE_510K,
    SOURCE_RECALL,
    OpenFDASourceFetcher,
)
from maudesignal.sources.pubmed import PubMedFetcher
from maudesignal.storage.database import Database

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "demo" / "maudesignal_demo.db"
MANIFEST_NAME = "SEED_MANIFEST.json"
MAX_DB_BYTES = 5 * 1024 * 1024
PUBMED_PER_CODE = 5
K510_RECENT_PER_CODE = 10

PUBMED_QUERIES: dict[str, str] = {
    "LLZ": '("MAUDE"[tiab] OR "adverse event reports"[tiab]) AND '
    '("artificial intelligence"[tiab] OR "machine learning"[tiab]) AND hasabstract',
    "QIH": '"artificial intelligence"[tiab] AND triage[tiab] AND '
    '("large vessel occlusion"[tiab] OR "intracranial hemorrhage"[tiab]) AND hasabstract',
    "MYN": '"computer-aided detection"[tiab] AND "false positive"[tiab] AND hasabstract',
    "POK": '"computer-aided diagnosis"[tiab] AND cancer[tiab] AND lesions[tiab] AND hasabstract',
}


def seed_sources(db: Database, codes: list[str]) -> dict[str, Any]:
    """Fetch and store recalls, 510(k) records and PubMed abstracts; return a manifest block."""
    for st in (SOURCE_RECALL, SOURCE_510K, "pubmed"):
        db.delete_external_sources(source_type=st)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    openfda = OpenFDASourceFetcher(db, api_key=openfda_api_key_from_env())
    pubmed = PubMedFetcher(db=db, api_key=os.environ.get("NCBI_API_KEY") or None)
    per_code: dict[str, Any] = {}
    last_updated: str | None = None
    try:
        for code in codes:
            rec = openfda.fetch_recalls(code)
            last_updated = last_updated or rec.last_updated
            time.sleep(0.3)
            recent = openfda.fetch_510k_for_product(code, limit=K510_RECENT_PER_CODE)
            time.sleep(0.3)
            query = PUBMED_QUERIES[code]
            time.sleep(2.0)  # keyless NCBI allows ~3 req/s; back-to-back codes hit 429s
            articles = pubmed.fetch(
                query=query, product_code=code, max_results=PUBMED_PER_CODE, with_abstracts=True
            )
            per_code[code] = {
                "recalls": {
                    "endpoint": RECALL_ENDPOINT,
                    "search": rec.search,
                    "matching_total_at_fetch": rec.matching_total,
                    "stored": rec.stored,
                    "complete": rec.stored >= rec.matching_total,
                },
                "k510_recent": {
                    "endpoint": K510_ENDPOINT,
                    "search": recent.search,
                    "sort": "decision_date:desc",
                    "matching_total_at_fetch": recent.matching_total,
                    "stored": recent.stored,
                },
                "pubmed": {
                    "query": query,
                    "sort": "relevance",
                    "max_results": PUBMED_PER_CODE,
                    "pmids": [a.pmid for a in articles],
                },
            }
            print(
                f"{code}: recalls {rec.stored}/{rec.matching_total}, "
                f"510(k) recent {recent.stored}, pubmed {len(articles)}"
            )
        cited: set[str] = set()
        for row in db.list_external_sources(source_type=SOURCE_RECALL, limit=100_000):
            cited |= {str(k).upper() for k in json.loads(row.raw_json).get("k_numbers") or ()}
        cited |= {d.k_number.upper() for d in db.list_catalog_devices() if d.k_number}
        k510 = openfda.fetch_510k(sorted(cited))
        print(f"510(k) cited by recalls / catalog: {k510.stored} of {len(cited)} K-numbers")
    finally:
        openfda.close()
        pubmed.close()

    return {
        "generated_by": "scripts/seed_sources.py",
        "fetched_at_utc": fetched_at,
        "openfda_meta_last_updated": last_updated,
        "api_key_used": openfda_api_key_from_env() is not None,
        "table": "external_sources (source_type fda_recall / fda_510k / pubmed)",
        "counts": {
            "fda_recall": db.count_external_sources(source_type=SOURCE_RECALL),
            "fda_510k": db.count_external_sources(source_type=SOURCE_510K),
            "pubmed": db.count_external_sources(source_type="pubmed"),
        },
        "k510_cited_by_recalls_or_catalog": {
            "requested": len(cited),
            "stored": k510.stored,
            "search": "k_number:(K...+K...) in chunks of 50",
        },
        "per_product_code": per_code,
        "notes": [
            "Recall rows are product-level (one product_res_number each); one recall event "
            "(res_event_number) can cover several rows.",
            "PubMed articles are linked to a product code only through the query they were "
            "fetched with; they are context, not evidence about a specific MAUDE report.",
            "Stored raw payloads are trimmed (openfda harmonization blocks dropped) to keep the "
            "demo DB small.",
        ],
    }


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--codes", nargs="+", default=list(PUBMED_QUERIES))
    parser.add_argument("--no-manifest", action="store_true")
    args = parser.parse_args()
    if not args.db.exists():
        print(f"{args.db} not found — run scripts/seed_demo_data.py first", file=sys.stderr)
        return 1
    unknown = [c for c in args.codes if c not in PUBMED_QUERIES]
    if unknown:
        print(f"no PubMed query configured for {unknown}", file=sys.stderr)
        return 1
    db = Database(args.db)
    block = seed_sources(db, args.codes)
    conn = sqlite3.connect(args.db)  # reclaim pages freed by the replace
    conn.execute("VACUUM")
    conn.close()
    size = args.db.stat().st_size
    print(f"database size: {size / 1e6:.2f} MB")
    if size > MAX_DB_BYTES:
        print("WARNING: demo DB exceeds 5 MB", file=sys.stderr)
    if not args.no_manifest:
        manifest_path = args.db.parent / MANIFEST_NAME
        manifest: dict[str, Any] = (
            json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        )
        manifest["external_sources"] = block
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"manifest updated: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
