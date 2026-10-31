"""The release-check "python" job: every step runs, every result goes into the report.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs ruff, black, mypy (strict, via ``python -m mypy``), the full unit suite with a coverage
floor, the gate adversarial set (false pass / false block must be 0 / 0), the secret scan, the
quoted-number comparison and the evidence-pack review findings (must be 0). A step that fails
does not stop the others, so one run shows everything that is wrong. The pytest and coverage
numbers in the report are parsed from pytest's own output.

    python3 scripts/release/python_job.py --out-dir release-out --cov-floor 70
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from compare import (  # noqa: E402
    compare_quoted_numbers,
    parse_coverage_total,
    parse_pytest_summary,
    review_findings,
)
from gate_adversarial import confusion, run_gate  # noqa: E402
from report import FAIL, PASS, Report  # noqa: E402

TAIL = 400


def run(cmd: list[str], env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    """Run ``cmd`` in the repository root; returns ``(exit code, combined output)``."""
    import os

    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(  # noqa: S603 - fixed commands from this file
        cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tail(text: str, n: int = TAIL) -> str:
    """The last ``n`` characters of ``text`` on one line."""
    return " ".join(text.strip().splitlines()[-4:])[-n:]


def step(rep: Report, name: str, cmd: list[str]) -> tuple[int, str]:
    """Run one command and record PASS (exit 0) or FAIL with the output tail."""
    code, out = run(cmd)
    rep.add(name, PASS if code == 0 else FAIL, f"exit {code}: {tail(out)}", group="python")
    return code, out


def main(argv: list[str] | None = None) -> int:
    """Run every step; write ``python-job.json`` and ``.md``; exit 1 on any failure."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    ap.add_argument("--cov-floor", type=float, default=70.0)
    ap.add_argument("--tests", default="tests/unit")
    args = ap.parse_args(argv)
    py = sys.executable
    rep = Report("python")

    # Python code the repository owns: not web/ (its qa scripts have their own line rules).
    targets = [d for d in ("src", "tests", "scripts", "api") if (ROOT / d).is_dir()]
    step(rep, f"ruff check {' '.join(targets)}", [py, "-m", "ruff", "check", *targets])
    step(rep, f"black --check {' '.join(targets)}", [py, "-m", "black", "--check", *targets])
    step(rep, "mypy --strict (src/maudesignal)", [py, "-m", "mypy", "src/maudesignal"])

    code, out = run(
        [
            py, "-m", "pytest", args.tests, "-q", "-p", "no:cacheprovider",
            "--cov=src/maudesignal", "--cov-report=term", f"--cov-fail-under={args.cov_floor}",
        ]  # fmt: skip
    )
    counts = parse_pytest_summary(out)
    total = parse_coverage_total(out)
    rep.metrics.update(pytest=counts, coverage_percent=total, coverage_floor=args.cov_floor)
    rep.add(
        "pytest tests/unit (tests/e2e, the Streamlit UI tests, is not run here)",
        PASS if code == 0 and counts.get("passed", 0) > 0 and not counts.get("failed") else FAIL,
        f"exit {code}: {counts}",
        group="python",
    )
    rep.add(
        "coverage at or above the floor",
        PASS if total is not None and total >= args.cov_floor else FAIL,
        f"{total}% (floor {args.cov_floor}%)",
        group="python",
    )

    try:
        cases, statuses = run_gate()
        gate = confusion(cases, statuses)
        rep.metrics["gate"] = gate
        rep.add(
            "gate adversarial: false pass 0 and false block 0",
            PASS if gate["false_pass"] == 0 and gate["false_block"] == 0 else FAIL,
            f"{gate['cases']} cases: false pass {gate['false_pass']}, "
            f"false block {gate['false_block']}",
            group="gate",
        )
    except Exception as exc:  # the gate could not run at all: a failure, not a skip
        rep.add("gate adversarial: false pass 0 and false block 0", FAIL, repr(exc), group="gate")

    step(rep, "no API key in any tracked file", [py, "scripts/scan_secrets.py"])
    step(rep, "release scripts compile", [py, "-m", "py_compile", *map(str, _release_scripts())])

    code, out = run([py, "scripts/print_quoted_numbers.py"], {"PYTHONPATH": "src"})
    diffs = compare_quoted_numbers(out) if code == 0 else [f"print_quoted_numbers exit {code}"]
    rep.metrics["quoted_numbers"] = out.strip().splitlines()
    rep.add(
        "quoted numbers unchanged",
        PASS if not diffs else FAIL,
        "; ".join(diffs) or "all four lines match",
        group="numbers",
    )

    reviews = review_findings(ROOT / "demo" / "dossier")
    rep.metrics["review_findings"] = reviews
    bad = {k: v for k, v in reviews.items() if v != 0}
    rep.add(
        "evidence-pack review findings are 0",
        PASS if reviews and not bad else FAIL,
        f"{len(reviews)} review files; not zero or unreadable: {bad}" if bad or not reviews else "",
        group="numbers",
    )

    rep.write(args.out_dir, "python-job")
    return rep.exit_code()


def _release_scripts() -> list[Path]:
    return sorted(HERE.glob("*.py"))


if __name__ == "__main__":
    sys.exit(main())
