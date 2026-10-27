"""Build the demo Signal Evaluation & CAPA dossier (draft + approved PDFs).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Works with NO key: every section except the narrative is deterministic, and the
narrative is taken from a recorded Muse Spark run in ``demo/dossier/`` if one
exists (it is re-gated on every build). Always works on a COPY of the demo DB.

    python scripts/build_demo_dossier.py --out demo/dossier

With META_MODEL_API_KEY set (e.g. GitHub Actions secret; never written
anywhere) it also drafts the narrative with Muse Spark and runs the
Muse Wonder reviewer, saving ``<docid>-narrative.json`` / ``<docid>-review.json``.
``--illustration`` adds one Muse Image cover ($0.01; off by default).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.copilot.actions import decide_capa, draft_capa  # noqa: E402
from maudesignal.dossier.builder import top_worsening_signal  # noqa: E402
from maudesignal.dossier.illustration import IllustrationError, generate_illustration  # noqa: E402
from maudesignal.dossier.model import Illustration  # noqa: E402
from maudesignal.dossier.review import WONDER_MODEL, review_dossier, save_review  # noqa: E402
from maudesignal.dossier.service import produce  # noqa: E402
from maudesignal.storage.database import Database  # noqa: E402

DEMO_ACTOR = "copilot:muse-spark"
DEMO_REVIEWER = "Demo Reviewer"


def main() -> int:
    """Build the demo dossiers; returns a process exit code."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data/demo/maudesignal_demo.db")
    ap.add_argument("--out", type=Path, default=ROOT / "demo/dossier")
    ap.add_argument("--illustration", action="store_true", help="add a Muse Image cover ($0.01)")
    ap.add_argument("--no-live", action="store_true", help="ignore META_MODEL_API_KEY")
    args = ap.parse_args()

    key = "" if args.no_live else os.environ.get("META_MODEL_API_KEY", "")
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")
    client = None
    if key:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=base_url)

    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "demo.db"
        shutil.copy(args.db, db_copy)
        db = Database(db_copy)
        sig = top_worsening_signal(db)
        if sig is None:
            print("no worsening signal in the demo DB")
            return 1
        week_end = datetime.strptime(str(db.max_date_received()), "%Y%m%d").date()
        capa = draft_capa(
            db,
            product_code=sig.product_code,
            title=f"{sig.product_code} report {sig.classification}: evaluate for corrective action",
            problem_statement=(
                f"The overnight monitor classified product code {sig.product_code} as "
                f"'{sig.classification}' for the week ending {week_end.isoformat()}. "
                "The cited MAUDE reports from that week are attached for complaint review."
            ),
            report_ids=list(sig.current_report_ids),
            actor=DEMO_ACTOR,
        )
        assert capa.created_at is not None
        awareness = capa.created_at.date()
        basis = "assumed = CAPA draft creation date (demo); confirm"

        illus: Illustration | None = None
        if args.illustration and key:
            try:
                illus = generate_illustration(
                    api_key=key, classification="Image processing system", base_url=base_url
                )
            except IllustrationError as exc:
                print(f"illustration skipped: {exc}")

        draft = produce(
            db,
            capa_id=capa.capa_id,
            awareness_date=awareness,
            awareness_basis=basis,
            narrative_dir=args.out,
            live_client=client,
            save_live_narrative=client is not None,
            illustration=illus,
        )
        doc_id = draft.doc_id
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{doc_id}-draft.pdf").write_bytes(draft.pdf)
        narr = draft.build.data.narrative.source or "omitted"
        print(f"{doc_id}-draft.pdf  {len(draft.pdf):,} bytes  narrative={narr}")

        if client is not None:
            r = review_dossier(
                client,
                doc_id=doc_id,
                html=draft.html,
                pdf=draft.pdf,
                evidence=draft.cited_records(),
                store=draft.build.store,
                model=os.environ.get("META_REVIEWER_MODEL", WONDER_MODEL),
            )
            save_review(r, args.out / f"{doc_id}-review.json")
            print(f"review: {len(r.findings)} findings, ${r.cost_usd:.4f}, mode={r.mode}")

        decide_capa(
            db,
            capa_id=capa.capa_id,
            decision="approved",
            reviewer=DEMO_REVIEWER,
            note="Demo approval: open CAPA and assign owner.",
        )
        approved = produce(
            db,
            capa_id=capa.capa_id,
            awareness_date=awareness,
            awareness_basis=basis,
            narrative_dir=args.out,
            illustration=illus,
        )
        (args.out / f"{doc_id}-approved.pdf").write_bytes(approved.pdf)
        print(f"{doc_id}-approved.pdf  {len(approved.pdf):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
