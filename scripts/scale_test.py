"""Performance / scalability / stress on seeded data (no network, no Meta calls).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Seeds synthetic MAUDE-shaped records (clearly fake ids, generated text) into a
throwaway SQLite database at growing sizes and times the deterministic paths a
page load or a copilot answer runs: detection + digest, loading the gate's
evidence store, gating a 6-sentence answer, compare, and the report-source
counts. Stops at the first size where a step exceeds ``--limit-s`` (the
"breaking point" for an interactive page) or memory exceeds ``--limit-mb``.

    python scripts/scale_test.py --sizes 1000 10000 50000 100000 200000
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import TypeVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.gate import (  # noqa: E402
    CountClaim,
    QuoteClaim,
    RecordClaim,
    ShareClaim,
    verify_answer,  # noqa: E402
)
from maudesignal.gate.loader import store_from_database  # noqa: E402
from maudesignal.monitor.compare import compare_signals  # noqa: E402
from maudesignal.monitor.deterioration import detect_from_database  # noqa: E402
from maudesignal.monitor.digest import digest_from_database  # noqa: E402
from maudesignal.monitor.sources import source_counts, sourced_reports  # noqa: E402
from maudesignal.storage.database import Database  # noqa: E402

CODES = ["LLZ", "QIH", "MYN", "POK", "QAS", "DQK", "JAK", "OEB"]
TYPES = ["malfunction", "malfunction", "malfunction", "injury", "death", "other"]
SOURCES = ["Manufacturer report"] * 8 + ["User Facility report", "Voluntary report"]
END = date(2026, 8, 31)
T = TypeVar("T")


def seed(path: Path, n: int, rng: random.Random) -> None:
    """Write ``n`` synthetic reports spread over 180 days before END."""
    Database(path)  # creates the schema
    con = sqlite3.connect(path)
    raw, norm = [], []
    for i in range(n):
        rid = f"SYN{i:09d}"
        pc = CODES[i % len(CODES)]
        day = (END - timedelta(days=rng.randrange(180))).strftime("%Y%m%d")
        src = rng.choice(SOURCES)
        raw.append(
            (rid, pc, day, None, json.dumps({"report_source_code": src}), "2026-10-28 00:00:00")
        )
        text = f"Synthetic narrative {i}: the software displayed result {rng.randrange(10**6)}."
        norm.append(
            (rid, pc, rng.choice(TYPES), day, text, None, "Synth Co", f"Brand{i % 37}", src)
        )
    con.executemany("INSERT INTO raw_reports VALUES (?,?,?,?,?,?)", raw)
    con.executemany("INSERT INTO normalized_events VALUES (?,?,?,?,?,?,?,?,?)", norm)
    con.commit()
    con.close()


def timed(fn: Callable[[], T]) -> tuple[T, float]:
    """Run ``fn`` and return its result with the elapsed wall time in seconds."""
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


def run(n: int, limit_s: float) -> dict[str, float | int | bool]:
    """Seed ``n`` records and time each step."""
    rng = random.Random(n)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scale.db"
        _, t_seed = timed(lambda: seed(path, n, rng))
        db = Database(path)
        det, t_detect = timed(lambda: detect_from_database(db))
        _, t_digest = timed(lambda: digest_from_database(db, det))
        store, t_store = timed(lambda: store_from_database(db))
        first = store.records[0]
        sentences = [
            (
                "LLZ count.",
                [CountClaim("LLZ", sum(1 for r in store.records if r.product_code == "LLZ"))],
            ),
            ("QIH injury share.", [ShareClaim("QIH", "injury", 16.7)]),
            ("Quote.", [QuoteClaim(first.text[:40], report_id=first.report_id)]),
            ("Record.", [RecordClaim(first.report_id, first.product_code)]),
            ("Fake quote.", [QuoteClaim("the device exploded", report_id=first.report_id)]),
            ("Plain sentence with no number.", []),
        ]
        _, t_gate = timed(lambda: verify_answer(sentences, store))
        _, t_compare = timed(lambda: compare_signals(db, CODES[:4]))
        _, t_sources = timed(lambda: source_counts(sourced_reports(db)))
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    page = t_detect + t_digest + t_compare + t_sources
    answer = t_store + t_gate
    return {
        "records": n,
        "seed_s": round(t_seed, 2),
        "detect_s": round(t_detect, 3),
        "digest_s": round(t_digest, 3),
        "what_changed_page_s": round(page, 3),
        "gate_store_load_s": round(t_store, 3),
        "gate_6_sentences_s": round(t_gate, 3),
        "copilot_gate_path_s": round(answer, 3),
        "peak_rss_mb": round(rss_mb, 1),
        "over_limit": page > limit_s or answer > limit_s,
    }


def main() -> int:
    """Run each size until one crosses the limit; print a Markdown table."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000, 100000])
    ap.add_argument("--limit-s", type=float, default=5.0)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    rows = []
    for n in args.sizes:
        r = run(n, args.limit_s)
        rows.append(r)
        print(json.dumps(r), flush=True)
        if r["over_limit"]:
            break
    cols = list(rows[0])
    print("\n| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in cols) + " |")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
