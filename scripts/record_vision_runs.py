"""Record real Muse Spark / SAM 3.1 vision runs for the keyless public demo.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Needs META_MODEL_API_KEY (in CI from a GitHub Actions secret; never written
anywhere). Two parts:

1. 510(k) summary reader — for each K-number (default: ``DEMO_K_NUMBERS``) the
   summary PDF is downloaded into ``data/demo/510k/`` (gitignored), its first
   pages are read twice by Muse Spark and checked against openFDA and the text
   layer; the result is written to ``demo/vision/510k-<K>.json``.
2. Label camera — every ``demo/vision/labels/*.jpg|jpeg|png|webp`` photo goes
   through SAM 3.1 → Muse Spark → openFDA; the result is written to
   ``demo/vision/label-<stem>.json`` WITHOUT lot / serial numbers.

    python scripts/record_vision_runs.py
    python scripts/record_vision_runs.py --k K210666 --skip-labels

Exit code 0 when everything requested was recorded, 1 when some items failed,
2 when the key is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.common.exceptions import MaudeSignalError  # noqa: E402
from maudesignal.vision import DEMO_K_NUMBERS  # noqa: E402
from maudesignal.vision.fda_pdf import DEFAULT_CACHE_DIR, DEFAULT_MAX_PAGES  # noqa: E402
from maudesignal.vision.label import read_device_label  # noqa: E402
from maudesignal.vision.openfda510k import OpenFda510k  # noqa: E402
from maudesignal.vision.pipeline import (  # noqa: E402
    DEMO_VISION_DIR,
    read_and_verify_510k,
    save_summary,
)
from maudesignal.vision.sam import DEFAULT_SAM_MODEL, SamClient  # noqa: E402

LABEL_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def main() -> int:
    """Record readings; returns a process exit code."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", nargs="*", help="K-numbers to read (default: the demo set)")
    ap.add_argument("--out", type=Path, default=DEMO_VISION_DIR)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--labels", type=Path, default=DEMO_VISION_DIR / "labels")
    ap.add_argument("--skip-labels", action="store_true")
    ap.add_argument("--skip-510k", action="store_true")
    ap.add_argument("--model", default=os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3"))
    ap.add_argument("--sam-model", default=os.environ.get("META_SAM_MODEL", DEFAULT_SAM_MODEL))
    args = ap.parse_args()

    key = os.environ.get("META_MODEL_API_KEY", "")
    if not key:
        print("META_MODEL_API_KEY is not set; nothing recorded.")
        return 2
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")

    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=base_url)
    failures = 0
    total_cost = 0.0
    with OpenFda510k(os.environ.get("OPENFDA_API_KEY")) as ofda:
        if not args.skip_510k:
            for k in args.k or [k for k, _ in DEMO_K_NUMBERS]:
                try:
                    s = read_and_verify_510k(
                        k,
                        client=client,
                        openfda=ofda,
                        cache_dir=args.cache,
                        max_pages=args.max_pages,
                        model=args.model,
                    )
                except MaudeSignalError as exc:
                    failures += 1
                    print(f"[510k] {k}: FAILED — {exc}")
                    continue
                path = save_summary(s, args.out)
                total_cost += s.cost_usd
                print(
                    f"[510k] {k}: text layer={s.has_text_layer} agreement={s.agreement_pct}% "
                    f"verified={s.count('VERIFIED')} conflict={s.count('CONFLICT')} "
                    f"unverifiable={s.count('UNVERIFIABLE')} cost=${s.cost_usd:.4f} -> "
                    f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"
                )
        if not args.skip_labels and args.labels.is_dir():
            photos = sorted(p for p in args.labels.iterdir() if p.suffix.lower() in LABEL_SUFFIXES)
            with SamClient(key, base_url=base_url, model=args.sam_model) as sam:
                for photo in photos:
                    try:
                        res = read_device_label(
                            photo.read_bytes(),
                            client=client,
                            sam=sam,
                            openfda=ofda,
                            model=args.model,
                        )
                    except MaudeSignalError as exc:
                        failures += 1
                        print(f"[label] {photo.name}: FAILED — {exc}")
                        continue
                    data = res.to_dict(include_session_fields=False)
                    data["image_file"] = photo.name
                    out = args.out / f"label-{photo.stem}.json"
                    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    total_cost += res.cost_usd
                    print(
                        f"[label] {photo.name}: sam={res.sam_prompt} k={res.k_number} "
                        f"({res.k_status}) product_code={res.product_code} "
                        f"basis={res.match_basis} cost=${res.cost_usd:.4f}"
                    )
    print(f"total estimated cost ${total_cost:.4f}; failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
