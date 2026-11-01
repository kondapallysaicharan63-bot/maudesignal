"""Record the website's "Recorded example" for Investigate a complaint (no network, no model).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). Feature F25.

Runs the same code as ``POST /v1/investigate`` over the stored copy of FDA data in the demo
database (raw openFDA records fetched on 2026-10-27) and writes the answer to
``web/src/fixtures/investigateExample.json``. The counts are those of the stored copy, which the
answer says in ``source_note``; each link still opens the live openFDA query.

    python3 scripts/record_investigate_example.py            # write the fixture
    python3 scripts/record_investigate_example.py --check    # fail when the file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.connector.investigate import run_investigation  # noqa: E402
from maudesignal.connector.investigate_stored import StoredSource  # noqa: E402

DB = ROOT / "data" / "demo" / "maudesignal_demo.db"
OUT = ROOT / "web" / "src" / "fixtures" / "investigateExample.json"
CODE = "LLZ"
DESCRIPTION = "The report manager would not let users save a study, and images came up unreadable."
#: The day the stored copy was fetched from openFDA; the 12-month window ends here.
RETRIEVED = datetime(2026, 10, 27, 18, 0, 0, tzinfo=UTC)


def build() -> dict[str, Any]:
    """The fixture: the example input and the recorded answer."""
    source = StoredSource.from_db(DB)
    answer = run_investigation(source, CODE, DESCRIPTION, now=RETRIEVED)
    n = sum(1 for e in source.events if CODE in json.dumps(e.get("device", "")))
    answer = answer.model_copy(
        update={
            "mode": "recorded",
            "source_note": (
                f"Recorded example. The counts are for the stored copy of {n} {CODE} reports "
                f"fetched from openFDA on {source.fetched[:10]}, not for all of openFDA. "
                "Each link opens the live openFDA query, which may show a larger number."
            ),
        }
    )
    return {
        "input": {"product_code": CODE, "description": DESCRIPTION},
        "answer": answer.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    """Write (or check) the fixture."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 when the file is out of date")
    args = ap.parse_args(argv)
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("investigate example is up to date" if same else "investigate example is STALE")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
