"""Print the numbers every recording and the submission quote, from the stored data.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Run before and after any re-recording; the output must be identical:

    python scripts/print_quoted_numbers.py

Nothing is typed in here. Each number is recomputed from files in the repo:

* gate, first pass: ``first_pass`` of the fifth recording's 28 transcripts
  (``demo/transcripts/20261028T*.json``), summed over sentences;
* hand-check: the ``Hand verdict`` column of ``docs/hackathon/HAND_CHECK.md``, same rule as
  ``scripts/hand_check.py`` (an answer is fully correct when every sentence is ``correct``);
* LLZ on openFDA: the "all dates" table in ``docs/hackathon/SOURCE_COUNTS.md``;
* AI sweep: flagged vs rows in ``demo/sweep/ai-device-sweep.json``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hand_check import _cell, _old_verdicts, _vkey  # type: ignore[import-not-found]  # noqa: E402

FIFTH_RECORDING_PREFIX = "20261028T"
LLZ_ROW = re.compile(
    r"^\| LLZ \| (?P<total>[\d,]+) \|.*\| (?P<mfr>[\d,]+) \((?P<pct>[\d.]+)%\) \|$"
)


def gate_first_pass(root: Path = ROOT) -> tuple[int, int, int]:
    """(answers, sentences passed first time, sentences) over the fifth recording."""
    answers = passed = total = 0
    for path in sorted((root / "demo/transcripts").glob(f"{FIFTH_RECORDING_PREFIX}*.json")):
        t = json.loads(path.read_text(encoding="utf-8"))
        fp = t["first_pass"]
        answers += 1
        passed += int(fp["passed"])
        total += int(fp["passed"]) + int(fp["blocked"])
    return answers, passed, total


def hand_check(root: Path = ROOT) -> tuple[int, int, int, int]:
    """(answers checked, answers fully correct, sentences checked, sentences correct)."""
    old = _old_verdicts(root / "docs/hackathon/HAND_CHECK.md")
    answers = fully = sentences = correct = 0
    for path in sorted((root / "demo/transcripts").glob(f"{FIFTH_RECORDING_PREFIX}*.json")):
        t: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        keys = [
            _vkey(f"{t['label']}#{i}", _cell(s["text"]))
            for i, s in enumerate(t["final"]["sentences"], 1)
        ]
        if not all(k in old for k in keys):
            continue
        answers += 1
        sentences += len(keys)
        ok = sum(old[k].startswith("correct") for k in keys)
        correct += ok
        fully += ok == len(keys)
    return answers, fully, sentences, correct


def llz_openfda(root: Path = ROOT) -> tuple[int, int, str]:
    """(LLZ reports on openFDA, filed by a manufacturer, share text) from SOURCE_COUNTS.md."""
    for line in (root / "docs/hackathon/SOURCE_COUNTS.md").read_text(encoding="utf-8").splitlines():
        m = LLZ_ROW.match(line)
        if m:
            return int(m["total"].replace(",", "")), int(m["mfr"].replace(",", "")), m["pct"]
    raise SystemExit("LLZ row not found in docs/hackathon/SOURCE_COUNTS.md")


def sweep(root: Path = ROOT) -> tuple[int, int]:
    """(codes flagged, codes in the stored sweep)."""
    rows = json.loads((root / "demo/sweep/ai-device-sweep.json").read_text("utf-8"))["rows"]
    return sum(r["classification"] != "stable" for r in rows), len(rows)


def lines(root: Path = ROOT) -> list[str]:
    """The quoted numbers as printable lines."""
    n, p, t = gate_first_pass(root)
    a, f, s, c = hand_check(root)
    total, mfr, pct = llz_openfda(root)
    flagged, rows = sweep(root)
    return [
        f"gate first pass:  {p}/{t} sentences ({n} answers)",
        f"hand-check:       {f}/{a} answers fully correct; {c}/{s} sentences correct",
        f"LLZ on openFDA:   {total:,} reports, {mfr:,} filed by a manufacturer ({pct}%)",
        f"AI sweep:         {flagged} of {rows} flagged",
    ]


if __name__ == "__main__":
    print("\n".join(lines()))
