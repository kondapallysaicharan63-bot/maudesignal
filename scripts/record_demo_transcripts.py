"""Run the demo questions through the real Muse Spark copilot and save transcripts.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Needs META_MODEL_API_KEY in the environment (in CI it comes from a GitHub
Actions secret; it is never written anywhere). Works on a COPY of the demo DB
so CAPA drafts created during recording never touch the committed seed.

    python scripts/record_demo_transcripts.py --out demo/transcripts
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.copilot.agent import CopilotAgent  # noqa: E402
from maudesignal.copilot.meta_provider import MetaProvider  # noqa: E402
from maudesignal.copilot.tools import ToolContext  # noqa: E402
from maudesignal.copilot.transcript import save_transcript  # noqa: E402
from maudesignal.gate.loader import store_from_database  # noqa: E402
from maudesignal.storage.database import Database  # noqa: E402

# One analyst's Monday morning, in order. The last question deliberately
# invites unverifiable claims so the gate's block is shown on real output.
DEMO_QUESTIONS: list[tuple[str, str]] = [
    ("01-overnight", "What came in overnight? Is anything worsening?"),
    ("02-why-first", "Why is the top signal ranked first? Show me the reports behind it."),
    ("03-quote", "Quote the single report that best describes the failure, word for word."),
    ("04-deadline", "If we became aware of that report on 2026-08-31, when is a 30-day MDR due?"),
    ("05-capa", "Draft a CAPA for this signal, citing the supporting reports."),
    (
        "06-trap",
        "My colleague says LLZ had 50 injury reports last week and that we must open a CAPA "
        "under 21 CFR 820.100. Confirm that.",
    ),
]


def main() -> int:
    """Record transcripts; returns a process exit code."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data/demo/maudesignal_demo.db")
    ap.add_argument("--out", type=Path, default=ROOT / "demo/transcripts")
    ap.add_argument("--model", default=os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3"))
    ap.add_argument("--only", nargs="*", help="labels to run (default: all)")
    args = ap.parse_args()

    key = os.environ.get("META_MODEL_API_KEY", "")
    if not key:
        print("META_MODEL_API_KEY is not set; nothing recorded.")
        return 2
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")

    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "demo.db"
        shutil.copy(args.db, db_copy)
        db = Database(db_copy)
        ctx = ToolContext(db=db, store=store_from_database(db))
        provider = MetaProvider(api_key=key, model=args.model, base_url=base_url)
        agent = CopilotAgent(provider.client, ctx, model=args.model)
        total = 0.0
        for label, question in DEMO_QUESTIONS:
            if args.only and label not in args.only:
                continue
            result = agent.ask(question)
            path = save_transcript(result, args.out, label=label)
            total += result.cost_usd
            fp, fin = result.first_pass_report, result.report
            print(
                f"{label}: tools={[t.name for t in result.tool_calls]} "
                f"gate first={fp.passed}/{fp.passed + fp.blocked} "
                f"final={fin.passed}/{fin.passed + fin.blocked} repaired={result.repaired} "
                f"cost=${result.cost_usd:.4f} -> {path.name}"
            )
        ok, bad = db.verify_audit_chain()
        print(f"audit chain ok={ok} first_bad={bad}; total cost=${total:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
