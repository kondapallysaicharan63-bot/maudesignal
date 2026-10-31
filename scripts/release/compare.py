"""Compare numbers from a run with the numbers the submission quotes.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Pure functions (text in, differences out) so the same logic is unit-tested and used by the
workflows. The expected lines are the ones ``scripts/print_quoted_numbers.py`` prints today;
they change only when a re-recording is approved, and then this file changes with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: Lines ``scripts/print_quoted_numbers.py`` must print, in order, after whitespace is collapsed.
EXPECTED_QUOTED_LINES: tuple[str, ...] = (
    "gate first pass: 63/65 sentences (28 answers)",
    "hand-check: 27/28 answers fully correct; 64/65 sentences correct",
    "LLZ on openFDA: 19,970 reports, 19,823 filed by a manufacturer (99.3%)",
    "AI sweep: 6 of 181 flagged",
)


def _collapse(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def compare_quoted_numbers(
    output: str, expected: tuple[str, ...] = EXPECTED_QUOTED_LINES
) -> list[str]:
    """Differences between the printed quoted-number lines and ``expected`` (empty = same)."""
    got = [_collapse(line) for line in output.splitlines() if line.strip()]
    diffs: list[str] = []
    for i in range(max(len(got), len(expected))):
        want = expected[i] if i < len(expected) else "(no line expected)"
        have = got[i] if i < len(got) else "(line missing)"
        if want != have:
            diffs.append(f"line {i + 1}: expected '{want}', got '{have}'")
    return diffs


#: Figures in the stored demo snapshot answer for LLZ (week of 2026-08-25): the API exposes
#: these, so the post-deploy smoke test compares them. Live openFDA numbers differ by design.
EXPECTED_LLZ_SNAPSHOT: tuple[str, ...] = ("33 reports", "8.75")


def llz_snapshot_diffs(answer: dict[str, Any]) -> list[str] | None:
    """Missing figures in a stored-snapshot LLZ answer, or ``None`` when it is not comparable.

    Args:
        answer: A tool answer (``provenance``, ``speakable``, ``facts``).

    Returns:
        ``None`` when the answer came from live openFDA (its numbers move every day), else the
        list of expected figures that do not appear in it (empty = unchanged).
    """
    kind = (answer.get("provenance") or {}).get("kind")
    if kind != "stored_demo_snapshot":
        return None
    text = " ".join(
        [str(answer.get("speakable", ""))]
        + [str(f.get("text", "")) for f in answer.get("facts", [])]
    )
    return [figure for figure in EXPECTED_LLZ_SNAPSHOT if figure not in text]


def review_findings(directory: Path) -> dict[str, int | None]:
    """Findings count in each ``*-review.json`` under ``directory``.

    ``None`` means the file could not be read as a review (reported as a failure by callers).
    """
    out: dict[str, int | None] = {}
    for path in sorted(directory.glob("*-review.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
            findings = data["findings"]
            out[path.name] = len(findings) if isinstance(findings, list) else None
        except (ValueError, KeyError, OSError):
            out[path.name] = None
    return out


_PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed|deselected)")
_COV_TOTAL = re.compile(r"^TOTAL\s+.*?(\d+(?:\.\d+)?)%\s*$", re.MULTILINE)


def parse_pytest_summary(text: str) -> dict[str, int]:
    """Counts from pytest's last summary line, for example ``1147 passed, 3 skipped``."""
    lines = [ln for ln in text.splitlines() if _PYTEST_COUNT.search(ln) and " in " in ln]
    counts: dict[str, int] = {}
    if lines:
        for n, word in _PYTEST_COUNT.findall(lines[-1]):
            key = "errors" if word == "error" else word
            counts[key] = counts.get(key, 0) + int(n)
    return counts


def parse_coverage_total(text: str) -> float | None:
    """The TOTAL percentage from a ``--cov-report=term`` table, or None when absent."""
    found = _COV_TOTAL.findall(text)
    return float(found[-1]) if found else None


def parse_npm_audit(raw: str) -> dict[str, int]:
    """Vulnerability counts by severity from ``npm audit --json``.

    Raises:
        ValueError: The text is not an npm audit JSON document.
    """
    data = json.loads(raw)
    vulns = data.get("metadata", {}).get("vulnerabilities")
    if not isinstance(vulns, dict):
        raise ValueError("no metadata.vulnerabilities in the npm audit output")
    return {k: int(v) for k, v in vulns.items() if isinstance(v, int)}


def audit_blocks(counts: dict[str, int]) -> int:
    """High plus critical vulnerabilities (the build fails on any)."""
    return counts.get("high", 0) + counts.get("critical", 0)


def count_axe(results: dict[str, Any]) -> dict[str, int]:
    """Violations by impact from an axe-core ``results`` object."""
    out = {"minor": 0, "moderate": 0, "serious": 0, "critical": 0, "unknown": 0}
    for v in results.get("violations", []):
        impact = v.get("impact") or "unknown"
        out[impact if impact in out else "unknown"] += 1
    return out


def axe_blocks(counts: dict[str, int]) -> int:
    """Serious plus critical axe violations (the page fails on any)."""
    return counts.get("serious", 0) + counts.get("critical", 0)
