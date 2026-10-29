"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Unit tests for the overnight deterioration monitor (detector, digest, fetch, CLI).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from maudesignal.cli import app
from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDARateLimitError
from maudesignal.ingestion.openfda_client import OpenFDAClient, search_param
from maudesignal.ingestion.pipeline import _normalize
from maudesignal.monitor.deterioration import (
    EventFact,
    build_window,
    default_as_of,
    detect_deterioration,
    detect_from_database,
    facts_from_rows,
    parse_yyyymmdd,
)
from maudesignal.monitor.digest import (
    DIGEST_FOOTER,
    build_digest,
    digest_to_dict,
    example_report_ids,
    render_json,
    render_markdown,
)
from maudesignal.monitor.fetch import incremental_fetch, plan_whole_days
from maudesignal.storage.database import Database

runner = CliRunner()
AS_OF = date(2026, 8, 31)  # current window 08-25..08-31, baseline 07-28..08-24

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _f(rid: str, day: str, event_type: str = "malfunction", code: str = "AAA") -> EventFact:
    return EventFact(rid, code, parse_yyyymmdd(day), event_type)


def _many(prefix: str, day: str, n: int, event_type: str = "malfunction") -> list[EventFact]:
    return [_f(f"{prefix}{i:02d}", day, event_type) for i in range(n)]


def _seed_db(db: Database, rows: list[tuple[str, str, str, str]]) -> None:
    """rows: (report_id, product_code, date_received, event_type)."""
    for rid, code, received, event_type in rows:
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code=code,
            date_received=received,
            date_of_event=None,
            raw_payload={"mdr_report_key": rid},
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code=code,
            event_type=event_type,
            event_date=received,
            narrative=None,
            mfr_narrative=None,
            manufacturer=None,
            brand_name=None,
        )


# ----------------------------------------------------------------------
# Windows, parsing, as-of
# ----------------------------------------------------------------------


def test_build_window_boundaries() -> None:
    w = build_window(AS_OF)
    assert w.current_start == date(2026, 8, 25)
    assert w.current_end == AS_OF
    assert w.baseline_end == date(2026, 8, 24)
    assert w.baseline_start == date(2026, 7, 28)
    assert (w.baseline_end - w.baseline_start).days + 1 == 28


def test_parse_yyyymmdd_accepts_both_formats() -> None:
    assert parse_yyyymmdd("20260831") == AS_OF
    assert parse_yyyymmdd("2026-08-31") == AS_OF
    with pytest.raises(ValueError):
        parse_yyyymmdd("2026/08/31")


def test_default_as_of_is_max_date_received_not_today() -> None:
    facts = [_f("1", "20260101"), _f("2", "20260315"), _f("3", "20260202")]
    assert default_as_of(facts) == date(2026, 3, 15)
    result = detect_deterioration(facts)
    assert result.window.as_of == date(2026, 3, 15)


def test_default_as_of_empty_raises() -> None:
    with pytest.raises(ValueError):
        default_as_of([])
    with pytest.raises(ValueError):
        detect_deterioration([])


def test_explicit_as_of_ignores_later_events() -> None:
    facts = _many("b", "20260801", 4) + _many("c", "20260826", 2) + _many("z", "20260905", 9)
    result = detect_deterioration(facts, AS_OF)
    sig = result.signals[0]
    assert result.events_after_as_of == 9
    assert result.events_considered == 6
    assert sig.current_count == 2
    assert all(not rid.startswith("z") for rid in sig.current_report_ids)


def test_code_with_only_future_events_listed_as_stable() -> None:
    facts = _many("b", "20260801", 4) + [_f("x1", "20261001", code="BBB")]
    result = detect_deterioration(facts, AS_OF)
    codes = {s.product_code: s for s in result.signals}
    assert codes["BBB"].classification == "stable"
    assert codes["BBB"].current_count == 0


# ----------------------------------------------------------------------
# Classifications
# ----------------------------------------------------------------------


def test_stable() -> None:
    facts = _many("b", "20260801", 8) + _many("c", "20260826", 3)  # mean 2 -> need 4
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "stable"
    assert sig.triggers == ()
    assert sig.baseline_weekly_mean == 2.0
    assert sig.spike_ratio == 1.5


def test_spike_at_exact_threshold() -> None:
    facts = _many("b", "20260801", 6) + _many("c", "20260826", 3)  # mean 1.5 -> 3 >= 3
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "spike"
    assert sig.current_count == 3
    assert sig.baseline_count == 6
    assert sig.baseline_weekly_mean == 1.5
    assert sig.spike_ratio == 2.0
    assert sig.current_report_ids == ("c00", "c01", "c02")
    assert len(sig.baseline_report_ids) == 6


def test_spike_requires_minimum_three_reports() -> None:
    # Prior history exists (so not new) but baseline is empty; 2 reports is not a spike.
    facts = [_f("old", "20260101")] + _many("c", "20260826", 2)
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "stable"
    assert sig.spike_ratio is None
    facts.append(_f("c99", "20260830"))
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "spike"


def test_new_signal_first_reports_for_product_code() -> None:
    facts = _many("c", "20260826", 2)
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "new_signal"
    assert sig.prior_report_count == 0
    assert sig.new_event_types == ()


def test_new_signal_never_seen_event_type_outranks_escalation() -> None:
    facts = _many("b", "20260801", 4) + [
        _f("c1", "20260826", "death"),
        _f("c2", "20260827"),
    ]
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.classification == "new_signal"
    assert sig.triggers == ("new_signal", "severity_escalation")
    assert sig.new_event_types == ("death",)
    assert sig.new_event_type_report_ids == ("c1",)
    assert example_report_ids(sig) == ["c1"]


def test_severity_escalation_at_exact_15pp() -> None:
    baseline = _many("b", "20260801", 9) + [_f("bi", "20260802", "injury")]  # 1/10 = 10%
    current = [_f("ci", "20260826", "injury")] + _many("c", "20260827", 3)  # 1/4 = 25%
    sig = detect_deterioration(baseline + current, AS_OF).signals[0]
    assert sig.classification == "severity_escalation"
    assert sig.severe_share_delta_pp == 15.0
    assert sig.current_severe_share == 0.25
    assert sig.baseline_severe_share == 0.1
    assert sig.current_severe_report_ids == ("ci",)
    assert sig.baseline_severe_report_ids == ("bi",)
    assert example_report_ids(sig) == ["ci"]


def test_severity_escalation_just_below_threshold() -> None:
    baseline = _many("b", "20260801", 8) + [_f("bi", "20260802", "injury")]  # 1/9 = 11.1%
    current = [_f("ci", "20260826", "injury")] + _many("c", "20260827", 3)  # 25%
    sig = detect_deterioration(baseline + current, AS_OF).signals[0]
    assert sig.classification == "stable"
    assert sig.severe_share_delta_pp == pytest.approx(13.89, abs=0.01)


def test_severity_needs_nonempty_baseline() -> None:
    facts = [_f("old", "20260101", "injury"), _f("c1", "20260826", "injury")]
    sig = detect_deterioration(facts, AS_OF).signals[0]
    assert sig.baseline_severe_share is None
    assert sig.severe_share_delta_pp is None
    assert sig.classification == "stable"


def test_spike_and_escalation_primary_is_escalation() -> None:
    # Baseline 5 reports, 1 injury (20%); injury already seen, so not a new type.
    baseline = [*_many("b", "20260801", 4), _f("bi", "20260803", "injury")]
    # Current 4 reports (>= 2 x 1.25 and >= 3), 3 injuries (75%, +55 pp).
    current = [_f("c1", "20260826"), *_many("ci", "20260829", 3, "injury")]
    sig = detect_deterioration(baseline + current, AS_OF).signals[0]
    assert sig.triggers == ("severity_escalation", "spike")
    assert sig.classification == "severity_escalation"


def test_facts_from_rows_skips_bad_dates_and_normalizes_types() -> None:
    rows: list[tuple[str, str, str | None, str | None]] = [
        ("1", "AAA", "20260801", "Injury"),
        ("2", "AAA", None, "malfunction"),
        ("3", "AAA", "notadate", "malfunction"),
        ("4", "AAA", "20260802", None),
    ]
    facts, skipped = facts_from_rows(rows)
    assert skipped == 2
    assert [f.event_type for f in facts] == ["injury", "unknown"]


def test_detect_from_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "m.db")
    _seed_db(
        db,
        [(f"b{i}", "LLZ", "20260801", "malfunction") for i in range(4)]
        + [(f"c{i}", "LLZ", "20260830", "malfunction") for i in range(3)]
        + [("q1", "QIH", "20260831", "injury"), ("q0", "QIH", "", "injury")],
    )
    assert db.max_date_received() == "20260831"
    assert db.max_date_received("LLZ") == "20260830"
    assert db.max_date_received("ZZZ") is None
    assert db.list_product_codes() == ["LLZ", "QIH"]
    result = detect_from_database(db)
    assert result.window.as_of == AS_OF
    assert result.events_skipped_missing_date == 1
    by_code = {s.product_code: s.classification for s in result.signals}
    assert by_code == {"LLZ": "spike", "QIH": "new_signal"}


# ----------------------------------------------------------------------
# Digest
# ----------------------------------------------------------------------


def _mixed_result() -> Any:
    facts = (
        _many("b", "20260801", 6)  # AAA spike
        + _many("c", "20260826", 5)
        + [_f("n1", "20260830", code="NEW"), _f("n2", "20260831", code="NEW")]
        + [_f("s1", "20260801", code="STB"), _f("s2", "20260826", code="STB")]
    )
    return detect_deterioration(facts, AS_OF)


def test_digest_headline_and_counts() -> None:
    digest = build_digest(_mixed_result())
    assert digest.headline == (
        "New kind of problem: 1 · More serious than usual: 0 · Reports suddenly increased: 1"
    )
    assert (
        digest.new_count,
        digest.serious_count,
        digest.increased_count,
        digest.stable_count,
    ) == (1, 0, 1, 1)


def test_render_markdown_sections_and_footer() -> None:
    digest = build_digest(
        _mixed_result(), fetch_summary={"AAA": 2}, notes=("QIH: openFDA fetch failed",)
    )
    md = render_markdown(digest)
    assert md.startswith("# MaudeSignal — what changed, data as of 2026-08-31")
    assert f"**{digest.headline}**" in md
    assert "## AAA — reports suddenly increased" in md
    assert "Reports this window: 5 (baseline: 6 over 4 weeks, weekly mean 1.50; ratio 3.33x)" in md
    assert "Example report ids: c00, c01, c02" in md  # capped at 3
    assert "## NEW — new kind of problem" in md
    assert "First reports ever stored for this product code." in md
    assert "## No change" in md and "STB (1 this window)" in md
    assert "Newly stored this run: AAA 2" in md
    assert "Note: QIH: openFDA fetch failed" in md
    assert md.rstrip().endswith(DIGEST_FOOTER)
    assert DIGEST_FOOTER == (
        "Advisory only — B2B regulatory triage aid, not medical advice. Every item "
        "requires human review; nothing is reported to FDA automatically."
    )
    assert render_markdown(digest) == md  # deterministic


def test_render_markdown_no_signals_and_new_event_type_line() -> None:
    stable = detect_deterioration(_many("b", "20260801", 8) + _many("c", "20260826", 1), AS_OF)
    md = render_markdown(build_digest(stable))
    assert (
        "New kind of problem: 0 · More serious than usual: 0 · Reports suddenly increased: 0" in md
    )
    assert "No product code crossed a rule threshold." in md

    facts = _many("b", "20260801", 4) + [_f("c1", "20260826", "death"), _f("c2", "20260827")]
    md = render_markdown(build_digest(detect_deterioration(facts, AS_OF)))
    assert "Rules fired: new kind of problem, more serious than usual" in md
    assert "never seen before for this code: death (4 earlier reports on file)" in md


def test_render_json_contains_every_number() -> None:
    digest = build_digest(_mixed_result())
    data = json.loads(render_json(digest))
    assert data == digest_to_dict(digest)
    assert data["headline"] == digest.headline
    assert data["counts"]["reports_suddenly_increased"] == 1
    assert data["window"]["baseline_start"] == "2026-07-28"
    assert data["footer"] == DIGEST_FOOTER
    aaa = next(s for s in data["signals"] if s["product_code"] == "AAA")
    assert aaa["classification"] == "spike"
    assert aaa["label"] == "reports suddenly increased"
    assert aaa["current_count"] == len(aaa["current_report_ids"]) == 5
    assert aaa["baseline_count"] == len(aaa["baseline_report_ids"]) == 6
    assert aaa["baseline_weekly_mean"] == 1.5
    assert aaa["example_report_ids"] == ["c00", "c01", "c02"]


# ----------------------------------------------------------------------
# Incremental fetch
# ----------------------------------------------------------------------


def test_plan_whole_days() -> None:
    days = [("20260901", 4), ("20260903", 1), ("20260904", 5), ("20260905", 7), ("20260906", 8)]
    assert plan_whole_days(days, 20) == ("20260905", 17)
    assert plan_whole_days(days, 3) == (None, 0)
    assert plan_whole_days([], 20) == (None, 0)


class _FakeClient:
    """Stands in for OpenFDAClient: per-day counts + records."""

    def __init__(self, records: dict[str, list[dict[str, Any]]], fail: set[str] | None = None):
        self.records = records
        self.fail = fail or set()
        self.calls: list[tuple[str, str | None, str | None, int | None]] = []

    def count_by_date_received(
        self, product_code: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[tuple[str, int]]:
        if product_code in self.fail:
            raise OpenFDARateLimitError("429")
        counts: dict[str, int] = {}
        for r in self.records.get(product_code, []):
            if start_date is None or r["date_received"] >= start_date:
                counts[r["date_received"]] = counts.get(r["date_received"], 0) + 1
        return sorted(counts.items())

    def iter_reports(
        self,
        product_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append((product_code, start_date, end_date, limit))
        for r in self.records.get(product_code, []):
            if (start_date or "0") <= r["date_received"] <= (end_date or "99999999"):
                yield r


def _rec(rid: str, day: str, event_type: str = "Malfunction") -> dict[str, Any]:
    return {"mdr_report_key": rid, "date_received": day, "event_type": event_type}


def test_incremental_fetch_whole_days_within_budget(tmp_path: Path) -> None:
    db = Database(tmp_path / "f.db")
    _seed_db(db, [("a0", "AAA", "20260831", "malfunction"), ("b0", "BBB", "20260831", "x")])
    client = _FakeClient(
        {
            "AAA": [_rec("a0", "20260831")]
            + [_rec(f"a1{i}", "20260901") for i in range(2)]
            + [_rec(f"a2{i}", "20260902") for i in range(3)],
            "BBB": [_rec(f"b1{i}", "20260901") for i in range(5)],
        }
    )
    report = incremental_fetch(db=db, client=client, max_new=4)  # type: ignore[arg-type]
    aaa = report.items[0]
    assert (aaa.start_date, aaa.end_date, aaa.planned, aaa.new) == ("20260901", "20260901", 2, 2)
    assert client.calls == [("AAA", "20260901", "20260901", 2)]
    assert any("BBB: 20260901 has 5 reports" in n for n in report.notes)
    assert report.new_by_code == {"AAA": 2}
    assert report.total_fetched == 2
    assert db.max_date_received("AAA") == "20260901"


def test_incremental_fetch_budget_exhausted_and_errors(tmp_path: Path) -> None:
    db = Database(tmp_path / "f.db")
    _seed_db(
        db,
        [
            ("a0", "AAA", "20260831", "malfunction"),
            ("b0", "BBB", "20260831", "malfunction"),
            ("c0", "CCC", "20260831", "malfunction"),
        ],
    )
    client = _FakeClient({"AAA": [_rec("a1", "20260901")], "CCC": []}, fail={"BBB"})
    report = incremental_fetch(db=db, client=client, max_new=1)  # type: ignore[arg-type]
    assert report.new_by_code == {"AAA": 1}
    assert any("BBB" in n and "budget exhausted" in n for n in report.notes)
    assert any("CCC" in n and "budget exhausted" in n for n in report.notes)

    report = incremental_fetch(db=db, client=client, max_new=5)  # type: ignore[arg-type]
    assert any("BBB: openFDA fetch failed" in n for n in report.notes)
    assert {i.product_code: i.fetched for i in report.items} == {"AAA": 0, "CCC": 0}


# ----------------------------------------------------------------------
# openFDA client + pipeline fixes used by the monitor
# ----------------------------------------------------------------------


def test_search_param_turns_plus_into_spaces() -> None:
    q = "device.device_report_product_code:LLZ+AND+date_received:[20260701+TO+20260831]"
    assert search_param(q) == (
        "device.device_report_product_code:LLZ AND date_received:[20260701 TO 20260831]"
    )


def _client_returning(response: httpx.Response) -> OpenFDAClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "%2B" not in str(request.url)
        assert request.url.params["count"] == "date_received"
        return response

    client = OpenFDAClient(api_key="k")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_count_by_date_received_parses_and_sorts() -> None:
    body = {"results": [{"time": "20260902", "count": 3}, {"time": "20260901", "count": 1}]}
    with _client_returning(httpx.Response(200, json=body)) as client:
        assert client.count_by_date_received("LLZ", start_date="20260901") == [
            ("20260901", 1),
            ("20260902", 3),
        ]


def test_count_by_date_received_404_and_errors() -> None:
    with _client_returning(httpx.Response(404)) as client:
        assert client.count_by_date_received("ZZZ") == []
    with _client_returning(httpx.Response(400, text="bad")) as client:
        with pytest.raises(OpenFDAAPIError):
            client.count_by_date_received("ZZZ")


def test_normalize_accepts_string_event_type_from_live_api() -> None:
    assert _normalize({"event_type": "Malfunction"}, "LLZ")["event_type"] == "malfunction"
    assert _normalize({"event_type": ["Injury"]}, "LLZ")["event_type"] == "injury"
    assert _normalize({"event_type": ""}, "LLZ")["event_type"] is None


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _cli_db(tmp_path: Path) -> Path:
    path = tmp_path / "cli.db"
    db = Database(path)
    _seed_db(
        db,
        [(f"b{i}", "LLZ", "20260801", "malfunction") for i in range(4)]
        + [(f"c{i}", "LLZ", "20260830", "malfunction") for i in range(3)]
        + [("m1", "MYN", "20260810", "malfunction")],
    )
    return path


def test_cli_monitor_no_fetch_writes_digests(tmp_path: Path) -> None:
    db_path = _cli_db(tmp_path)
    out = tmp_path / "digests"
    result = runner.invoke(
        app, ["monitor", "--db", str(db_path), "--no-fetch", "--out-dir", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "LLZ: reports suddenly increased" in " ".join(result.output.split())
    md = (out / "2026-08-30.md").read_text(encoding="utf-8")
    assert "## LLZ — reports suddenly increased" in md
    assert md.rstrip().endswith(DIGEST_FOOTER)
    data = json.loads((out / "2026-08-30.json").read_text(encoding="utf-8"))
    assert data["as_of"] == "2026-08-30"
    assert data["fetch_summary"] == {}


def test_cli_monitor_as_of_iso_and_compact(tmp_path: Path) -> None:
    db_path = _cli_db(tmp_path)
    out = tmp_path / "d"
    for as_of in ("2026-08-23", "20260816"):
        result = runner.invoke(
            app,
            [
                "monitor",
                "--db",
                str(db_path),
                "--no-fetch",
                "--as-of",
                as_of,
                "--out-dir",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
    assert (out / "2026-08-23.md").exists()
    assert (out / "2026-08-16.json").exists()


def test_cli_monitor_rejects_bad_as_of_and_missing_db(tmp_path: Path) -> None:
    db_path = _cli_db(tmp_path)
    bad = runner.invoke(app, ["monitor", "--db", str(db_path), "--no-fetch", "--as-of", "Aug"])
    assert bad.exit_code == 2
    missing = runner.invoke(app, ["monitor", "--db", str(tmp_path / "nope.db"), "--no-fetch"])
    assert missing.exit_code == 2


def test_cli_monitor_empty_db_exits_1(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    Database(path)
    result = runner.invoke(
        app, ["monitor", "--db", str(path), "--no-fetch", "--out-dir", str(tmp_path / "o")]
    )
    assert result.exit_code == 1


def test_cli_monitor_fetch_path_uses_incremental_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maudesignal.monitor import fetch as fetch_mod

    db_path = _cli_db(tmp_path)
    seen: dict[str, int] = {}

    def fake_fetch(*, db: Database, client: object, max_new: int) -> fetch_mod.FetchReport:
        seen["max_new"] = max_new
        return fetch_mod.FetchReport(
            items=(fetch_mod.CodeFetch("LLZ", "20260831", "20260831", 1, 1, 1),),
            notes=("MYN: not checked — --max-new budget exhausted",),
        )

    monkeypatch.setattr(fetch_mod, "incremental_fetch", fake_fetch)
    out = tmp_path / "o"
    result = runner.invoke(
        app, ["monitor", "--db", str(db_path), "--max-new", "7", "--out-dir", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert seen["max_new"] == 7
    data = json.loads((out / "2026-08-30.json").read_text(encoding="utf-8"))
    assert data["fetch_summary"] == {"LLZ": 1}
    assert data["notes"] == ["MYN: not checked — --max-new budget exhausted"]
