"""Run the claim-gate adversarial set and report false passes and false blocks.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The set is ``tests/fixtures/gate/adversarial.jsonl`` (cases that must be withheld or must
pass) checked against ``tests/fixtures/gate/store.json``. A false pass is a case that must be
blocked but passed; a false block is a case that must pass but was blocked. Both must be 0.
The counts printed here are computed from the files, never typed in.

    PYTHONPATH=src python3 scripts/release/gate_adversarial.py --out-dir release-out
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from report import FAIL, PASS, Report  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "gate"


def confusion(cases: list[dict[str, Any]], statuses: list[str]) -> dict[str, int]:
    """Count outcomes for ``cases`` given the gate's ``statuses`` (same order).

    Args:
        cases: Dicts with an ``expect`` of ``"pass"`` or ``"block"``.
        statuses: The gate's verdict status for each case.

    Returns:
        ``cases``, ``must_block``, ``must_pass``, ``false_pass``, ``false_block``.
    """
    if len(cases) != len(statuses):
        raise ValueError("one status per case is required")
    out = {"cases": len(cases), "must_block": 0, "must_pass": 0, "false_pass": 0, "false_block": 0}
    for case, status in zip(cases, statuses, strict=True):
        if case["expect"] == "block":
            out["must_block"] += 1
            out["false_pass"] += int(status == "pass")
        else:
            out["must_pass"] += 1
            out["false_block"] += int(status == "block")
    return out


def run_gate(fixtures: Path = FIXTURES) -> tuple[list[dict[str, Any]], list[str]]:
    """Load the fixtures and run the real gate over every case."""
    from maudesignal.gate import (
        DeviceRef,
        EvidenceRecord,
        EvidenceStore,
        LiteratureRef,
        RecallRef,
        claim_from_dict,
        verify_sentence,
    )

    data = json.loads((fixtures / "store.json").read_text("utf-8"))
    store = EvidenceStore.from_iterables(
        (EvidenceRecord(**r) for r in data["records"]),
        (DeviceRef(**d) for d in data["devices"]),
        recalls=(
            RecallRef(**{**r, "k_numbers": tuple(r.get("k_numbers", ()))})
            for r in data.get("recalls", [])
        ),
        clearances=(DeviceRef(**d) for d in data.get("clearances", [])),
        literature=(LiteratureRef(**a) for a in data.get("literature", [])),
    )
    lines = (fixtures / "adversarial.jsonl").read_text("utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    statuses = [
        verify_sentence(c["sentence"], [claim_from_dict(d) for d in c["claims"]], store).status
        for c in cases
    ]
    return cases, statuses


def main(argv: list[str] | None = None) -> int:
    """Run the set and write ``gate-adversarial.json`` and ``.md``; exit 1 unless 0 / 0."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    ap.add_argument("--min-cases", type=int, default=50)
    args = ap.parse_args(argv)
    rep = Report("gate adversarial set")
    cases, statuses = run_gate()
    counts = confusion(cases, statuses)
    rep.metrics.update(counts)
    rep.add(
        "enough adversarial cases",
        PASS if counts["cases"] >= args.min_cases else FAIL,
        f"{counts['cases']} cases (need {args.min_cases})",
    )
    rep.add(
        "false passes are 0",
        PASS if counts["false_pass"] == 0 else FAIL,
        f"{counts['false_pass']} of {counts['must_block']} must-block cases passed",
    )
    rep.add(
        "false blocks are 0",
        PASS if counts["false_block"] == 0 else FAIL,
        f"{counts['false_block']} of {counts['must_pass']} must-pass cases were blocked",
    )
    rep.write(args.out_dir, "gate-adversarial")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
