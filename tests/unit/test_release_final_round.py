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
    assert "page=$page" in first  # every page of results
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
