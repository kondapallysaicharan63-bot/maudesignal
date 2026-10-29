"""Fetch MHRA (UK) device safety alerts into the demo database (keyless GOV.UK API).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs in GitHub Actions (this repository's container cannot reach gov.uk). One
search per product code, terms from ``data/demo/mhra_queries.json``. Alerts are
stored as ``mhra_alert`` external sources: UK context, never FDA evidence.

    python scripts/fetch_mhra_alerts.py [--db data/demo/maudesignal_demo.db] [--count 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.sources.mhra import fetch_mhra_alerts  # noqa: E402
from maudesignal.storage.database import Database  # noqa: E402


def main() -> int:
    """Fetch and store; returns a process exit code (1 if every search failed)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data/demo/maudesignal_demo.db")
    ap.add_argument("--queries", type=Path, default=ROOT / "data/demo/mhra_queries.json")
    ap.add_argument("--count", type=int, default=10)
    args = ap.parse_args()
    queries = {
        k: v
        for k, v in json.loads(args.queries.read_text(encoding="utf-8")).items()
        if not k.startswith("_")
    }
    db = Database(args.db)
    failures = 0
    for pc, q in queries.items():
        try:
            alerts = fetch_mhra_alerts(db, query=q, product_code=pc, count=args.count)
            print(f"[mhra] {pc} '{q}': {len(alerts)} device alert(s) stored")
        except Exception as exc:  # noqa: BLE001 - report every search, keep going
            failures += 1
            print(f"[mhra] {pc} '{q}': FAILED — {type(exc).__name__}: {exc}")
    return 1 if failures == len(queries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
