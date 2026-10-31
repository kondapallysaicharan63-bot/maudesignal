"""Final release round: guard inside the live job, budget line in load(), no-answer handling."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(RELEASE))

import netutil  # noqa: E402
import report as rpt  # noqa: E402


def test_live_job_guard_is_its_first_step_and_there_is_no_gate_job() -> None:
    import yaml

    rc = yaml.safe_load((WORKFLOWS / "release-check.yml").read_text())
    jobs = rc["jobs"]
    assert "gate-live" not in jobs
    live = jobs["live"]
    assert "needs" not in live  # not behind a separate gate job
    assert live["concurrency"]["group"] == "release-live"
    assert live["concurrency"]["cancel-in-progress"] is False
    assert live["permissions"]["actions"] == "read"
    steps = live["steps"]
    first = json.dumps(steps[0])
    assert "run_attempt" in first and "RUN_ATTEMPT" in first  # attempts, not runs
    assert "&page=" in first and "created=%3E%3D" in first  # every page, 31-day window
    assert "/attempts/" in first  # attempts are read one by one
    assert "actions/workflows/release-check.yml/runs" in first
    assert '"MAX_LIVE_RUNS_PER_DAY": "3"' in first
    assert "exit 1" in steps[0]["run"]
    assert "uses" not in steps[0]  # nothing (checkout, installs) runs ahead of the guard
    for later in steps[1:]:
        assert "run_live" not in json.dumps(later)
    assert "gate-live" not in json.dumps(jobs["report"])
    assert set(jobs["report"]["needs"]) >= {"python", "web", "api-contract", "e2e", "live"}


def test_smoke_load_records_a_fail_line_when_the_budget_lowers_the_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import budget
    import smoke

    monkeypatch.setattr(smoke, "run_load", lambda *a, **k: [])
    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [], budget.Budget(max_usd=0.50))
    s.load(1, 0.1, 5)  # 0.50 carries two asks at 0.25
    line = next(c for c in rep.checks if c.detail.startswith("skipped: budget ("))
    assert line.status == rpt.FAIL and line.detail.startswith("skipped: budget (3 asks)")
    rep2 = rpt.Report("t")
    smoke.Smoke("https://a", "", rep2, []).load(1, 0.1, 0)
    assert not [c for c in rep2.checks if "skipped: budget" in c.detail]


def test_smoke_no_answer_is_not_a_clean_key_check() -> None:
    import smoke

    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    assert s.budget.reserve("ask")
    s.note_live("x", netutil.Response(0, {}, b"", 90_000, "timeout"), "ask")
    line = next(c for c in rep.checks if c.name == "x: no key in the response")
    assert line.status == rpt.FAIL and "no answer" in line.detail
    rep2 = rpt.Report("t")
    s2 = smoke.Smoke("https://a", "", rep2, [])
    assert s2.budget.reserve("ask")
    s2.note_live("y", netutil.Response(200, {}, b'{"cost_usd": 0.01}', 5), "ask")
    ok = next(c for c in rep2.checks if c.name == "y: no key in the response")
    assert ok.status == rpt.PASS


def _run_live_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make: Any) -> dict[str, Any]:
    import live_check

    monkeypatch.setattr(live_check, "request", make)
    monkeypatch.setenv("META_MODEL_API_KEY", "set-for-test")
    live_check.main(["--base", "http://x", "--out-dir", str(tmp_path)])
    doc = json.loads((tmp_path / "live-check.json").read_text())
    out: dict[str, Any] = {c["name"]: c for c in doc["checks"]}
    out["_metrics"] = doc.get("metrics", {})
    return out


def test_live_check_counts_unanswered_calls_at_their_full_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake(method: str, url: str, **kw: Any) -> netutil.Response:
        return netutil.Response(0, {}, b"", 90_000, "timeout")  # never an answer

    names = _run_live_check(monkeypatch, tmp_path, fake)
    calls = names["_metrics"]["calls"]
    # every call that was made had no answer: each counts at its cap (never $0), and the total
    # is the sum, shown in the cap line
    assert calls and all(c["http"] == 0 and c["cost_usd"] in (0.12, 0.15) for c in calls)
    total = sum(c["cost_usd"] for c in calls)
    assert names["_metrics"]["total_cost_usd"] == pytest.approx(total)
    assert names["total cost is within the cap"]["detail"].startswith(f"${total:.4f}")


def test_live_check_counts_a_200_without_cost_at_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake(method: str, url: str, **kw: Any) -> netutil.Response:
        body = {"mode": "live", "answer": {"spoken_text": "x"}, "heard": "q"}  # no cost_usd
        return netutil.Response(200, {}, json.dumps(body).encode(), 1)

    names = _run_live_check(monkeypatch, tmp_path, fake)
    calls = names["_metrics"]["calls"]
    assert calls and all(c["cost_usd"] > 0 for c in calls)
    assert names["_metrics"]["total_cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in calls))


# ---- the daily guard, run for real against a stub curl -------------------------------------

import os  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

_STUB = """#!/usr/bin/env python3
import json, os, sys
url = sys.argv[-1]
path = url.split("api.github.com/repos/o/r", 1)[1]
route = path.split("?")[0]
import urllib.parse
page = urllib.parse.parse_qs(urllib.parse.urlparse(path).query).get("page", ["1"])[0]
data = json.load(open(os.environ["FIXTURE"]))
key = route + "#" + page if route.endswith("/runs") else route
if key not in data:
    sys.stderr.write("no fixture for " + key)
    sys.exit(22)
print(json.dumps(data[key]))
"""

NOW = datetime.now(UTC)
TODAY = NOW.strftime("%Y-%m-%dT%H:00:00Z")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:00:00Z")
RUNS = "/actions/workflows/release-check.yml/runs"


def _guard_script() -> str:
    import yaml

    rc = yaml.safe_load((WORKFLOWS / "release-check.yml").read_text())
    return str(rc["jobs"]["live"]["steps"][0]["run"])


def _run_guard(
    tmp_path: Path, fixture: dict[str, Any], run_id: int, attempt: int
) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    curl = bindir / "curl"
    curl.write_text(_STUB)
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps(fixture))
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FIXTURE": str(fx),
        "HAS_KEY": "true",
        "GH_TOKEN": "x",
        "REPO": "o/r",
        "RUN_ID": str(run_id),
        "RUN_ATTEMPT": str(attempt),
        "MAX_LIVE_RUNS_PER_DAY": "3",
    }
    return subprocess.run(
        ["bash", "-c", _guard_script()], env=env, capture_output=True, text=True, timeout=60
    )


def _run(rid: int, attempts: int, created: str, branch: str = "release/live-x") -> dict[str, Any]:
    return {"id": rid, "run_attempt": attempts, "created_at": created, "head_branch": branch}


def _jobs(rid: int, n: int, started: str) -> dict[str, Any]:
    job = {"name": "Live (real Muse calls)", "started_at": started, "conclusion": "success"}
    return {f"/actions/runs/{rid}/attempts/{n}/jobs": {"total_count": 1, "jobs": [job]}}


def test_guard_counts_a_rerun_of_a_run_created_yesterday(tmp_path: Path) -> None:
    # run 99 was created yesterday: attempt 1 ran yesterday, attempt 2 today; run 5 ran today
    fx: dict[str, Any] = {
        RUNS
        + "#1": {
            "workflow_runs": [
                _run(99, 2, YESTERDAY),
                _run(5, 1, TODAY),
                _run(6, 1, TODAY, "release/other"),  # not a live branch
                _run(77, 1, TODAY),
            ]
        }
    }
    fx.update(_jobs(99, 1, YESTERDAY))
    fx.update(_jobs(99, 2, TODAY))
    fx.update(_jobs(5, 1, TODAY))
    # a new run 77 (created today): 2 attempts used today, so this is the 3rd and passes
    r = _run_guard(tmp_path, fx, 77, 1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "attempt 3 of at most 3" in r.stdout
    # attempt 3 of run 99: 99/2 and 5/1 used today -> the 3rd, passes
    fx[RUNS + "#1"]["workflow_runs"] = [_run(99, 3, YESTERDAY), _run(5, 1, TODAY)]
    fx.update(_jobs(99, 3, TODAY))
    assert _run_guard(tmp_path, fx, 99, 3).returncode == 0
    # attempt 4 of the old run 99: 99/2, 99/3 and 5/1 used today -> refused
    fx[RUNS + "#1"]["workflow_runs"] = [_run(99, 4, YESTERDAY), _run(5, 1, TODAY)]
    fx.update(_jobs(99, 4, TODAY))
    r = _run_guard(tmp_path, fx, 99, 4)
    assert r.returncode == 1, r.stdout
    assert "attempt 4 today" in r.stdout


def test_guard_stops_attempt_4_of_a_run_created_today(tmp_path: Path) -> None:
    fx: dict[str, Any] = {RUNS + "#1": {"workflow_runs": [_run(10, 4, TODAY)]}}
    for n in (1, 2, 3, 4):
        fx.update(_jobs(10, n, TODAY))
    r = _run_guard(tmp_path, fx, 10, 4)
    assert r.returncode == 1 and "attempt 4 today" in r.stdout
    r = _run_guard(tmp_path, fx, 10, 3)  # attempts 1 and 2 used, this is the 3rd
    assert r.returncode == 0 and "attempt 3 of at most 3" in r.stdout


def test_guard_pages_through_all_results_and_fails_when_a_list_is_unreadable(
    tmp_path: Path,
) -> None:
    page1 = [_run(1000 + i, 1, YESTERDAY, "release/other") for i in range(100)]
    page2 = [_run(1, 1, TODAY), _run(2, 1, TODAY), _run(3, 1, TODAY)]
    fx: dict[str, Any] = {
        RUNS + "#1": {"workflow_runs": page1},
        RUNS + "#2": {"workflow_runs": page2},
    }
    for rid in (1, 2, 3):
        fx.update(_jobs(rid, 1, TODAY))
    r = _run_guard(tmp_path, fx, 50, 1)  # 3 used on page 2 -> this would be the 4th
    assert r.returncode == 1 and "attempt 4 today" in r.stdout
    del fx[RUNS + "#2"]  # page 2 cannot be read: no guess, fail
    r = _run_guard(tmp_path, fx, 50, 1)
    assert r.returncode == 1 and "could not be read" in r.stdout
    # 20 full pages: the list may be incomplete, fail
    full = {RUNS + f"#{p}": {"workflow_runs": page1} for p in range(1, 21)}
    r = _run_guard(tmp_path, full, 50, 1)
    assert r.returncode == 1 and "incomplete" in r.stdout
    # a job list that cannot be read fails as well
    r = _run_guard(tmp_path, {RUNS + "#1": {"workflow_runs": [_run(1, 1, TODAY)]}}, 50, 1)
    assert r.returncode == 1 and "could not be read" in r.stdout


def test_smoke_clean_is_a_fail_when_nothing_answered() -> None:
    import smoke

    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    s.clean("smoke key 1: audit list holds no key", netutil.Response(0, error="refused"))
    c = rep.checks[-1]
    assert c.status == rpt.FAIL and "no answer (HTTP 0)" in c.detail
    s.clean("x", netutil.Response(200, body=b"{}"))
    assert rep.checks[-1].status == rpt.PASS
