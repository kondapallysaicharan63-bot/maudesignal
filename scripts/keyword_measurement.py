"""Keyword-matching measurement on the stored LLZ reports (P1 item G, 2026-11-04).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Question: when Investigate matches the word "image"/"images" in a stored LLZ narrative, how often is the report about the
complaint's problem (study images that would not load, display or be retrieved)?

Every count is recomputed from ``data/demo/maudesignal_demo.db`` (frozen demo snapshot). The only typed input is the
adjudication below: each matched report read in full and labelled once, by Claude (not a person), with a one-line
reason. A report id that is not a match, or a match without a label, stops the script. No model is called.

    python3 scripts/keyword_measurement.py            # writes web/public/data/keyword_measurement.json
    python3 scripts/keyword_measurement.py --check    # exits 1 if the committed file differs
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "demo" / "maudesignal_demo.db"
OUT = ROOT / "web" / "public" / "data" / "keyword_measurement.json"
CODE = "LLZ"
TERM = "images"
WORD = re.compile(r"\bimages?\b", re.IGNORECASE)
PROBLEM = "study images would not load, display or be retrieved"

SAME = "same problem"
DIFFERENT = "different image problem"
MENTION = "mention only"

# One label per matched report: (label, reason). Read in full against PROBLEM; adjudicated by Claude, not a person.
ADJUDICATION: dict[str, tuple[str, str]] = {
    "25675205": (SAME, "images pulled by a third party were unreadable"),
    "25676051": (DIFFERENT, "images stored in two locations; no failure to load is described"),
    "25688996": (SAME, "the corresponding images were not available"),
    "25701855": (
        DIFFERENT,
        "no repository folder created for incoming images; storage, not loading",
    ),
    "25701859": (SAME, "jerkiness in loading the web images"),
    "25702620": (
        MENTION,
        "'Image Fusion' is a product name; the event is electrode placement depth",
    ),
    "25751634": (SAME, "images were not transferred, so studies were incomplete"),
    "25775519": (SAME, "images were not displaying"),
    "25839557": (SAME, "query/retrieve of the images from PACS failed"),
    "50515470": (SAME, "unable to fetch images for some records"),
    "50516613": (SAME, "unable to retrieve images from PACS"),
}


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def measure(db: Path = DB) -> dict[str, Any]:
    """Recompute the measurement from the demo database."""
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT maude_report_id, narrative, mfr_narrative FROM normalized_events "
            "WHERE product_code = ? ORDER BY maude_report_id",
            (CODE,),
        ).fetchall()
        recalls = con.execute(
            "SELECT abstract, raw_json FROM external_sources "
            "WHERE source_type = 'fda_recall' AND product_code = ?",
            (CODE,),
        ).fetchall()
    finally:
        con.close()
    matched = [str(r[0]) for r in rows if WORD.search(f"{r[1] or ''} {r[2] or ''}")]
    missing = [m for m in matched if m not in ADJUDICATION]
    extra = [k for k in ADJUDICATION if k not in matched]
    if missing or extra:
        raise SystemExit(
            f"adjudication does not match the stored matches: missing={missing} extra={extra}"
        )
    labels = [ADJUDICATION[m][0] for m in matched]
    n = len(matched)
    same = labels.count(SAME)

    def rec_field(raw: str | None, key: str) -> str:
        try:
            v = json.loads(raw or "{}").get(key)
        except json.JSONDecodeError:
            return ""
        return v if isinstance(v, str) else ""

    any_field = sum(1 for _a, raw in recalls if re.search("image", raw or "", re.IGNORECASE))
    in_reason = sum(
        1 for _a, raw in recalls if re.search("image", rec_field(raw, "reason_for_recall"), re.I)
    )
    in_desc = sum(
        1 for _a, raw in recalls if re.search("image", rec_field(raw, "product_description"), re.I)
    )
    return {
        "schema_version": "1.0",
        "product_code": CODE,
        "term": TERM,
        "match_rule": "whole word 'image' or 'images', any case, in the report narrative or the manufacturer narrative",
        "problem": PROBLEM,
        "source": "data/demo/maudesignal_demo.db (stored demo snapshot)",
        "stored_reports": len(rows),
        "matched": n,
        "same_problem": same,
        "different_image_problem": labels.count(DIFFERENT),
        "mention_only": labels.count(MENTION),
        "pct_same_problem": _pct(same, n),
        "pct_too_broad": _pct(n - same, n),
        "adjudicator": "Claude (AI), not a person; one reader, no second reader",
        "sample": "all matched reports (no sampling)",
        "rows": [
            {"report_id": m, "label": ADJUDICATION[m][0], "reason": ADJUDICATION[m][1]}
            for m in matched
        ],
        "recalls": {
            "stored": len(recalls),
            "mention_image_any_field": any_field,
            "mention_image_in_reason": in_reason,
            "mention_image_in_product_description": in_desc,
        },
        "limits": [
            "One device type (LLZ), one term, one problem; N is small. Not a general precision figure.",
            "Adjudicated by Claude, not a person, and by one reader only.",
            "Recall (reports that describe the problem without the word) was not measured.",
            "A word match is a text match, not a finding of similarity.",
        ],
        "method": "scripts/keyword_measurement.py recomputes every count from the demo database",
    }


def main(argv: list[str] | None = None) -> int:
    """Write (or check) web/public/data/keyword_measurement.json."""
    ap = argparse.ArgumentParser(description="LLZ keyword-matching measurement")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = json.dumps(measure(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("keyword_measurement.json is current" if same else "keyword_measurement.json differs")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
