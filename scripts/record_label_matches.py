"""Record the label -> possible matches -> device-type view step for every label photo.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

For every photo in ``demo/vision/labels/`` this writes
``demo/vision/label-match-<name>.json`` (no lot / serial, ever):

* With ``META_MODEL_API_KEY``: SAM 3.1 finds the label, Muse Spark reads it (both timed),
  then openFDA is searched (K-number / UDI / model + name + maker), up to 3 possible
  matches are ranked, and each matched device type gets its facts, all checked by the
  claim-level gate.
* Without the key: the stored reading ``demo/vision/label-<name>.json`` is used and the
  SAM / Spark steps are marked "not recorded" (no timing is invented). The openFDA part
  still runs, so this is testable without any Meta credit.

* With ``--reuse-readings``: no Meta call at all (no key needed, none used). The reading,
  the SAM / Spark timings and the costs already stored in ``label-match-<name>.json`` are
  kept as recorded (timings are marked ``recorded <date>``); only the openFDA search, the
  device-type views, the gate and the trace are run again.

Nothing is confirmed here: a person confirms a match in the app.

    python3 scripts/record_label_matches.py
    python3 scripts/record_label_matches.py --only label-thermometer-1.jpg --out /tmp/x

Exit code 0 when every photo was recorded, 1 when some failed, 2 when a photo has no
reading to work from (keyless and no stored reading for any photo).
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
from maudesignal.vision.label_match import (  # noqa: E402
    NOT_RECORDED,
    OpenFdaSearcher,
    default_check_fn,
    match_label,
    not_recorded_read_steps,
    read_label_timed,
    reading_from_match,
    recorded_model_info,
    recorded_read_steps,
)
from maudesignal.vision.pipeline import DEMO_VISION_DIR  # noqa: E402
from maudesignal.vision.sam import DEFAULT_SAM_MODEL, SamClient  # noqa: E402

LABEL_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def stem_name(photo: Path) -> str:
    """``label-thermometer-1.jpg`` -> ``thermometer-1`` (no ``label-label-`` doubling)."""
    return photo.stem.removeprefix("label-")


def main() -> int:
    """Record the matches; returns a process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--labels", type=Path, default=DEMO_VISION_DIR / "labels")
    ap.add_argument("--readings", type=Path, default=DEMO_VISION_DIR, help="stored label-*.json")
    ap.add_argument("--out", type=Path, default=DEMO_VISION_DIR)
    ap.add_argument(
        "--reuse-readings",
        action="store_true",
        help="re-run only openFDA / views / gate / trace over the readings stored in "
        "label-match-*.json (no Meta call, no key needed)",
    )
    ap.add_argument("--only", nargs="*", help="photo file names to process (default: all)")
    ap.add_argument("--model", default=os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3"))
    ap.add_argument("--sam-model", default=os.environ.get("META_SAM_MODEL", DEFAULT_SAM_MODEL))
    args = ap.parse_args()

    if not args.labels.is_dir():
        print(f"{args.labels} is not a directory; nothing to do.")
        return 2
    photos = sorted(p for p in args.labels.iterdir() if p.suffix.lower() in LABEL_SUFFIXES)
    if args.only:
        photos = [p for p in photos if p.name in set(args.only)]
    key = "" if args.reuse_readings else os.environ.get("META_MODEL_API_KEY", "")
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")
    mode = (
        "readings stored in label-match-*.json (--reuse-readings; no Meta call)"
        if args.reuse_readings
        else "SAM 3.1 + Muse Spark re-run" if key else "stored readings (no META_MODEL_API_KEY)"
    )
    print(f"[label-match] {len(photos)} photo(s); reading from: {mode}")

    client = None
    if key:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=base_url)
    openfda_key = os.environ.get("OPENFDA_API_KEY") or None
    check_fn = default_check_fn(openfda_key)
    args.out.mkdir(parents=True, exist_ok=True)
    failures = skipped = recorded = 0
    total_cost = 0.0

    sam_ctx = SamClient(key, base_url=base_url, model=args.sam_model) if key else None
    try:
        with OpenFdaSearcher(openfda_key) as searcher:
            for photo in photos:
                name = stem_name(photo)
                try:
                    if client is not None:
                        result, read_steps = read_label_timed(
                            photo.read_bytes(), client=client, sam=sam_ctx, model=args.model
                        )
                        reading = result.to_dict(include_session_fields=False)
                        info = {
                            "model": result.model,
                            "skill_version": result.skill_version,
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "cost_usd": {
                                "spark": result.spark_cost_usd,
                                "sam": result.sam_cost_usd,
                                "total": result.cost_usd,
                            },
                        }
                        total_cost += result.cost_usd
                    elif args.reuse_readings:
                        prev_path = args.readings / f"label-match-{name}.json"
                        if not prev_path.is_file():
                            skipped += 1
                            print(
                                f"[label-match] {photo.name}: SKIPPED, no stored match "
                                f"{prev_path.name} to reuse"
                            )
                            continue
                        prev = json.loads(prev_path.read_text(encoding="utf-8"))
                        reading = reading_from_match(prev)
                        read_steps = recorded_read_steps(prev)
                        info = recorded_model_info(prev)
                    else:
                        stored = args.readings / f"label-{name}.json"
                        if not stored.is_file():
                            skipped += 1
                            print(
                                f"[label-match] {photo.name}: SKIPPED, no stored reading "
                                f"{stored.name}"
                            )
                            continue
                        reading = json.loads(stored.read_text(encoding="utf-8"))
                        read_steps = not_recorded_read_steps(
                            "stored reading; SAM and Spark were not re-run in this process"
                        )
                        info = {}
                    out = match_label(
                        reading,
                        searcher=searcher,
                        check_fn=check_fn,
                        read_steps=read_steps,
                        image_file=photo.name,
                        model_info=info,
                    )
                except MaudeSignalError as exc:
                    failures += 1
                    print(f"[label-match] {photo.name}: FAILED, {type(exc).__name__}: {exc}")
                    continue
                path = args.out / f"label-match-{name}.json"
                path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
                recorded += 1
                timings = [
                    s["elapsed_ms"] for s in out["trace"] if s["model"] in ("SAM 3.1", "Muse Spark")
                ]
                shown = "/".join(NOT_RECORDED if t is None else str(t) for t in timings)
                print(
                    f"[label-match] {photo.name}: basis={out['search_basis']} "
                    f"matches={len(out['matches'])} status={out['status']} "
                    f"sam/spark ms={shown} "
                    f"-> {path}"
                )
    finally:
        if sam_ctx is not None:
            sam_ctx.close()
    print(
        f"recorded: {recorded}; skipped: {skipped}; failures: {failures}; "
        f"estimated Meta cost this run ${total_cost:.4f}"
    )
    if photos and recorded == 0 and failures == 0:
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
