"""Check results and the JSON + Markdown report both release pipelines upload.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Status words (one place, so every script uses the same ones):

* ``PASS`` ran and held.
* ``FAIL`` ran and did not hold.
* ``SKIPPED`` should have run and did not. For a required check this counts as a failure.
* ``BLOCKED`` could not run because an input is missing (for example a secret). Never PASS.
* ``NOT_PRESENT`` the feature is not in this build. Reported by name; a failure only when the
  check is required.
* ``KNOWN_GAP`` the environment cannot test it (for example a fake microphone on one browser).
  Reported by name, not counted as a pass.

The overall verdict is FAIL if any check failed, else BLOCKED if any check was blocked, else
INFO if no check passed (only notes and gaps), else PASS. Numbers in a report come from the
run; nothing is typed in.

    python3 scripts/release/report.py merge a.json b.json --json out.json --md out.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PASS, FAIL, SKIPPED, BLOCKED = "PASS", "FAIL", "SKIPPED", "BLOCKED"
NOT_PRESENT, KNOWN_GAP = "NOT_PRESENT", "KNOWN_GAP"
INFO = "INFO"  # a report of only notes and gaps: nothing was checked, so never PASS
STATUSES = (PASS, FAIL, SKIPPED, BLOCKED, NOT_PRESENT, KNOWN_GAP)
MAX_DETAIL = 600


@dataclass
class Check:
    """One check: what ran, how it ended, and the real numbers from the run."""

    name: str
    status: str
    detail: str = ""
    group: str = ""
    required: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)

    def counts_as_failure(self) -> bool:
        """True for FAIL, and for SKIPPED or NOT_PRESENT on a required check."""
        if self.status == FAIL:
            return True
        return self.required and self.status in (SKIPPED, NOT_PRESENT)


@dataclass
class Report:
    """A list of checks plus free-form numbers (``metrics``) for one pipeline job."""

    title: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    started_utc: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def add(
        self,
        name: str,
        status: str,
        detail: str = "",
        *,
        group: str = "",
        required: bool = True,
        **metrics: Any,
    ) -> Check:
        """Record one check and echo it to the log."""
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        check = Check(name, status, detail[:MAX_DETAIL], group, required, dict(metrics))
        self.checks.append(check)
        print(f"{status:<11} {name}" + (f"  <- {check.detail}" if check.detail else ""), flush=True)
        return check

    def ok(self, name: str, condition: bool, detail: str = "", **kw: Any) -> bool:
        """Record PASS when ``condition`` holds, else FAIL with ``detail``."""
        self.add(name, PASS if condition else FAIL, "" if condition else detail, **kw)
        return condition

    def counts(self) -> dict[str, int]:
        """Number of checks per status (every status present, zero included)."""
        out = dict.fromkeys(STATUSES, 0)
        for c in self.checks:
            out[c.status] += 1
        return out

    def failures(self) -> list[Check]:
        """The checks that make the verdict FAIL."""
        return [c for c in self.checks if c.counts_as_failure()]

    def verdict(self) -> str:
        """FAIL, BLOCKED or PASS (see the module text)."""
        if self.failures() or not self.checks:  # nothing ran: never a pass
            return FAIL
        if any(c.status == BLOCKED for c in self.checks):
            return BLOCKED
        if not any(c.status == PASS for c in self.checks):  # only notes and gaps: nothing passed
            return INFO
        return PASS

    def exit_code(self) -> int:
        """1 on FAIL, 0 otherwise (BLOCKED is reported in the verdict, not as a crash)."""
        return 1 if self.verdict() == FAIL else 0

    def to_dict(self) -> dict[str, Any]:
        """The JSON form."""
        return {
            "title": self.title,
            "started_utc": self.started_utc,
            "verdict": self.verdict(),
            "counts": self.counts(),
            "metrics": self.metrics,
            "checks": [c.__dict__ for c in self.checks],
        }

    def to_markdown(self) -> str:
        """The Markdown form: verdict, counts, failures first, then every check."""
        return render_markdown([self.to_dict()])

    def write(self, out_dir: Path, stem: str) -> tuple[Path, Path]:
        """Write ``<stem>.json`` and ``<stem>.md`` and append the Markdown to the job summary."""
        out_dir.mkdir(parents=True, exist_ok=True)
        jpath, mpath = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
        jpath.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
        mpath.write_text(self.to_markdown(), "utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as fh:
                fh.write(self.to_markdown() + "\n")
        return jpath, mpath


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def overall(verdicts: list[str]) -> str:
    """FAIL if any job failed (or none ran), else BLOCKED if any was blocked, else PASS."""
    if FAIL in verdicts or not verdicts:
        return FAIL
    if BLOCKED in verdicts:
        return BLOCKED
    # an INFO report (only notes and gaps) neither passes nor fails the whole
    return PASS if any(v != INFO for v in verdicts) else INFO


def render_markdown(reports: list[dict[str, Any]]) -> str:
    """Markdown for one or more report dicts (as ``Report.to_dict`` writes them)."""
    lines: list[str] = []
    if len(reports) > 1:
        lines += [f"# Release report: {overall([r['verdict'] for r in reports])}", ""]
        lines += ["| Job | Verdict | " + " | ".join(STATUSES) + " |"]
        lines += ["|---|---|" + "---|" * len(STATUSES)]
        for r in reports:
            c = r["counts"]
            lines.append(
                f"| {_cell(r['title'])} | {r['verdict']} | "
                + " | ".join(str(c.get(s, 0)) for s in STATUSES)
                + " |"
            )
        lines.append("")
    for r in reports:
        lines += [f"## {r['title']}: {r['verdict']}", ""]
        lines.append("Counts: " + ", ".join(f"{s} {r['counts'].get(s, 0)}" for s in STATUSES))
        lines += [f"Started: {r['started_utc']}", ""]
        bad = [
            c
            for c in r["checks"]
            if c["status"] == FAIL or (c["required"] and c["status"] in (SKIPPED, NOT_PRESENT))
        ]
        if bad:
            lines += ["### Failures", ""]
            lines += [f"- **{c['status']}** {c['name']}: {c['detail']}" for c in bad]
            lines.append("")
        if r["metrics"]:
            lines += ["### Numbers from this run", ""]
            lines += [f"- {k}: `{json.dumps(v, sort_keys=True)}`" for k, v in r["metrics"].items()]
            lines.append("")
        lines += ["### All checks", "", "| Status | Group | Check | Detail |", "|---|---|---|---|"]
        for c in r["checks"]:
            lines.append(
                f"| {c['status']} | {_cell(c['group'])} | {_cell(c['name'])} | "
                f"{_cell(c['detail'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def merge(reports: list[dict[str, Any]], title: str = "release-report") -> dict[str, Any]:
    """One document from several job reports: overall verdict, per-job reports inside."""
    return {
        "title": title,
        "verdict": overall([r["verdict"] for r in reports]),
        "jobs": reports,
        "counts": {s: sum(r["counts"].get(s, 0) for r in reports) for s in STATUSES},
    }


def missing_report(path: Path) -> dict[str, Any]:
    """The stand-in for a job report that was not produced: a FAIL, never silently dropped."""
    return {
        "title": path.stem,
        "verdict": FAIL,
        "started_utc": "",
        "counts": dict.fromkeys(STATUSES, 0) | {FAIL: 1},
        "metrics": {},
        "checks": [
            {
                "name": "report file exists",
                "status": FAIL,
                "detail": f"{path.name} was not produced",
                "group": "",
                "required": True,
                "metrics": {},
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ``merge`` several report JSON files into one JSON + Markdown pair."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="merge job reports")
    m.add_argument("inputs", nargs="+", type=Path)
    m.add_argument("--json", type=Path, required=True)
    m.add_argument("--md", type=Path, required=True)
    m.add_argument("--title", default="release-report")
    args = ap.parse_args(argv)
    loaded = [
        json.loads(p.read_text("utf-8")) if p.exists() else missing_report(p) for p in args.inputs
    ]
    doc = merge(loaded, args.title)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", "utf-8")
    args.md.write_text(render_markdown(loaded), "utf-8")
    print(f"{args.title}: {doc['verdict']}")
    return 0 if doc["verdict"] != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
