"""The release-check "web" job: install, build, unit tests, npm audit, bundle secret scan.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

    python3 scripts/release/web_job.py --out-dir release-out

Every step runs even when an earlier one failed, and the numbers in the report come from the
tools' own output: the vitest summary, the ``npm audit --json`` counts, the number of files the
bundle scan read. High or critical vulnerabilities fail the job. A missing ``web/`` folder is a
failure (the release branch must carry the web app), never a skip.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from bundle_scan import scan_dir  # noqa: E402
from compare import audit_blocks, parse_npm_audit  # noqa: E402
from report import FAIL, PASS, Report  # noqa: E402

TAIL = 400


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run ``cmd`` in ``cwd``; returns ``(exit code, combined output)``."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def tail(text: str) -> str:
    """The last lines of ``text`` on one line."""
    return " ".join(text.strip().splitlines()[-4:])[-TAIL:]


def vitest_numbers(text: str) -> dict[str, int]:
    """Test and file counts from vitest's summary (``Tests  57 passed (57)``)."""
    out: dict[str, int] = {}
    for label, key in (("Test Files", "files"), ("Tests", "tests")):
        m = re.search(rf"{label}\s+(?:(\d+) failed \|\s*)?(\d+) passed", text)
        if m:
            out[f"{key}_passed"] = int(m.group(2))
            out[f"{key}_failed"] = int(m.group(1) or 0)
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the steps; write ``web-job.json`` and ``.md``; exit 1 on any failure."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    ap.add_argument("--web", type=Path, default=ROOT / "web")
    args = ap.parse_args(argv)
    rep = Report("web")
    web: Path = args.web
    if not (web / "package.json").is_file():
        rep.add("web/ is in this branch", FAIL, f"{web}/package.json not found", group="web")
        rep.write(args.out_dir, "web-job")
        return rep.exit_code()
    code, out = run(["npm", "ci", "--no-audit", "--no-fund"], web)
    rep.add("npm ci", PASS if code == 0 else FAIL, f"exit {code}: {tail(out)}", group="web")
    code, out = run(["npm", "run", "build"], web)
    rep.add("npm run build", PASS if code == 0 else FAIL, f"exit {code}: {tail(out)}", group="web")
    code, out = run(["npm", "test"], web)
    nums = vitest_numbers(out)
    rep.metrics["vitest"] = nums
    good = code == 0 and nums.get("tests_passed", 0) > 0 and nums.get("tests_failed", 1) == 0
    rep.add("npm test (vitest)", PASS if good else FAIL, f"exit {code}: {nums}", group="web")
    code, out = run(["npm", "audit", "--audit-level=high", "--json"], web)
    try:
        counts = parse_npm_audit(out)
        rep.metrics["npm_audit"] = counts
        blocked = audit_blocks(counts)
        rep.add(
            "npm audit: no high or critical vulnerability",
            PASS if blocked == 0 else FAIL,
            f"{counts}",
            group="web",
        )
    except ValueError as exc:
        rep.add(
            "npm audit: no high or critical vulnerability",
            FAIL,
            f"unreadable: {exc}; exit {code}",
            group="web",
        )
    dist = web / "dist"
    if not dist.is_dir():
        rep.add(
            "bundle secret scan",
            FAIL,
            "web/dist does not exist (the build did not produce it)",
            group="security",
        )
    else:
        files, hits = scan_dir(dist)
        rep.metrics["bundle_files_scanned"] = files
        rep.add(
            "bundle secret scan: no key-shaped string or key name with a value",
            PASS if files and not hits else FAIL,
            f"{files} files read; hits: {[(f, k, n) for f, k, n in hits]}",
            group="security",
        )
    rep.write(args.out_dir, "web-job")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
