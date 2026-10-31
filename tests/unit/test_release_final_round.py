"""Final release round: budget line in load(), no-answer handling in smoke."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(RELEASE))

import netutil  # noqa: E402
import report as rpt  # noqa: E402


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


def test_smoke_clean_is_a_fail_when_nothing_answered() -> None:
    import smoke

    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    s.clean("smoke key 1: audit list holds no key", netutil.Response(0, error="refused"))
    c = rep.checks[-1]
    assert c.status == rpt.FAIL and c.detail == "no answer to check (HTTP 0)"
    s.clean("x", netutil.Response(200, body=b"{}"))
    assert rep.checks[-1].status == rpt.PASS


def test_smoke_scan_helper_fails_on_http_0_and_500() -> None:
    import smoke

    for status in (0, 500):
        rep = rpt.Report("t")
        s = smoke.Smoke("https://a", "", rep, [])
        scanned = s.scan("no key", netutil.Response(status, body=b"{}"), lambda text: False, "x")
        c = rep.checks[-1]
        assert scanned is False
        assert c.status == rpt.FAIL and c.detail == f"no answer to check (HTTP {status})"
        s.clean("clean too", netutil.Response(status, body=b"{}"))
        assert rep.checks[-1].detail == f"no answer to check (HTTP {status})"
    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    assert s.scan("ok", netutil.Response(200, body=b"fine"), lambda text: False, "x")
    assert rep.checks[-1].status == rpt.PASS
    s.scan("bad", netutil.Response(200, body=b"found"), lambda text: "found" in text, "hit")
    assert rep.checks[-1].status == rpt.FAIL and rep.checks[-1].detail == "hit"


def test_smoke_cost_that_is_not_a_non_negative_number_is_the_full_cap() -> None:
    import smoke

    for bad in (None, "0.01", True, -0.01, float("nan"), float("inf"), [], {}):
        assert smoke.spent_usd({"cost_usd": bad}) is None
    assert smoke.spent_usd({}) is None
    assert smoke.spent_usd({"cost_usd": 0}) == 0.0
    assert smoke.spent_usd({"cost_usd": 0.02}) == 0.02
    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    assert s.budget.reserve("ask")
    s.note_live("x", netutil.Response(200, {}, b'{"cost_usd": -1}', 5), "ask")
    assert s.live_cost == 0.25 and s.budget.spent == 0.25
