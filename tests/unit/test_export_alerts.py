"""The alert detail exporter: numbers recomputed from stored rows, quotes word for word, nothing invented."""

# ruff: noqa: E501

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ewd = _load("export_web_data")
ea = _load("export_alerts")

FORBIDDEN = re.compile(
    r"\b(safe|unsafe|compliant|validated|overnight)\b|fda[- ]approved|part 11 compliant"
    r"|worsening signals?|citation-checked|complaint data",
    re.I,
)
GOOD = "The monitor stopped updating the waveform after the software update."
OTHER = "The display froze for about ten seconds and then recovered on its own."
NAMED = "Dr. Jones said the device failed during the procedure at the hospital."


def _db(path: Path, this_week: list[tuple[str, str, str, str, str]], baseline: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        create table raw_reports (maude_report_id text primary key, product_code text,
            date_received text, date_of_event text, raw_json text, fetched_at text);
        create table normalized_events (maude_report_id text primary key, product_code text,
            event_type text, event_date text, narrative text, mfr_narrative text,
            manufacturer text, brand_name text, report_source text);
        create table external_sources (record_id text primary key, source_type text,
            source_id text, product_code text, fetched_at text, title text, authors text,
            publication_date text, abstract text, url text, raw_json text);
        create table device_catalog (product_code text primary key, device_name text,
            company_name text, specialty text, decision_date text, k_number text,
            source_keyword text, fetched_at text);
        """)
    rows = list(this_week)
    # four weeks before 2026-09-24: one report every other day, plain malfunctions
    for i in range(baseline):
        day = "20260827" if i == 0 else "20260901"  # the stored rows must span the whole window
        rows.append((f"9{i:04d}", day, "malfunction", "Manufacturer report", OTHER))
    for rid, day, etype, src, text in rows:
        con.execute(
            "insert into raw_reports values (?,?,?,?,?,?)",
            (rid, "AAA", day, day, json.dumps({"product_problems": []}), "2026-10-30"),
        )
        con.execute(
            "insert into normalized_events values (?,?,?,?,?,?,?,?,?)",
            (rid, "AAA", etype, day, text, "", "Maker", "Brand", src),
        )
    for n, firm in (("Z-0001-2026", "Firm A"), ("Z-0002-2026", "Firm B")):
        con.execute(
            "insert into external_sources values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"r{n}",
                "fda_recall",
                n,
                "AAA",
                "2026-10-30",
                None,
                None,
                None,
                None,
                f"https://www.accessdata.fda.gov/recall/{n}",
                json.dumps(
                    {
                        "product_res_number": n,
                        "res_event_number": "1",
                        "cfres_id": "99",
                        "recalling_firm": firm,
                        "product_description": "Monitor",
                        "reason_for_recall": "The software may show an old waveform after a restart.",
                        "recall_status": "Open",
                        "event_date_initiated": "2026-09-05",
                    }
                ),
            ),
        )
    for k, d in (("K111111", "2025-01-02"), ("K222222", "2026-03-04")):
        con.execute(
            "insert into external_sources values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"k{k}",
                "fda_510k",
                k,
                "AAA",
                "2026-10-30",
                None,
                None,
                None,
                None,
                f"https://www.accessdata.fda.gov/cfpmn/{k}",
                json.dumps(
                    {
                        "k_number": k,
                        "applicant": "Maker Inc",
                        "device_name": "Monitor",
                        "decision_date": d,
                    }
                ),
            ),
        )
    con.execute(
        "insert into device_catalog values ('AAA','Monitor, Test',null,null,null,null,"
        "'openfda_classification','2026-10-30')"
    )
    con.commit()
    con.close()


def _row(
    code: str, rule: str, this: int, base: int, severe: tuple[int, int] = (0, 0)
) -> dict[str, Any]:
    w = {
        "as_of": "20260930",
        "current_start": "20260924",
        "current_end": "20260930",
        "baseline_start": "20260827",
        "baseline_end": "20260923",
    }
    return {
        "product_code": code,
        "as_of": "20260930",
        "window": w,
        "classification": rule,
        "current_count": this,
        "current_severe_count": severe[0],
        "baseline_count": base,
        "baseline_weekly_mean": base / 4,
        "baseline_severe_count": severe[1],
        "prior_report_count": 50,
        "queries": [
            [
                "This week, by event type",
                f"https://api.fda.gov/device/event.json?search={code}this",
            ],
            [
                "4 weeks before, by event type",
                f"https://api.fda.gov/device/event.json?search={code}base",
            ],
        ],
    }


@pytest.fixture()
def fx(tmp_path: Path) -> Path:
    """A small repository: code AAA has stored reports, recalls and 510(k)s; BBB has none."""
    week = [
        ("100001", "20260925", "malfunction", "Manufacturer report", f"{GOOD} {OTHER}"),
        ("100002", "20260926", "injury", "User facility report", f"{NAMED} {OTHER}"),
        ("100003", "20260927", "malfunction", "Manufacturer report", ""),
        ("100004", "20260930", "malfunction", "Voluntary report", GOOD),
    ]
    _db(tmp_path / "data/demo/maudesignal_demo.db", week, baseline=8)
    sweep = {
        "meta": {},
        "rows": [_row("AAA", "spike", 4, 8), _row("BBB", "severity_escalation", 5, 2, (2, 0))],
        "errors": [],
    }
    (tmp_path / "demo/sweep").mkdir(parents=True)
    (tmp_path / "demo/sweep/ai-device-sweep.json").write_text(json.dumps(sweep))
    (tmp_path / "digests").mkdir()
    return tmp_path


def _company() -> dict[str, Any]:
    return {
        "devices": [
            {
                "id": "DMC-1",
                "name": "Test Monitor",
                "product_code": "AAA",
                "owner": "Pat Doe (simulated)",
                "status": {"label": "Needs review", "date": "2026-10-30"},
                "device_type": {"name": "Monitor, Test"},
            },
            {
                "id": "DMC-2",
                "name": "Quiet Device",
                "product_code": "CCC",
                "owner": "Sam Roe (simulated)",
                "status": {"label": "Needs review", "date": "2026-10-30"},
                "device_type": {"name": None},
            },
        ]
    }


def _by_id(doc: dict[str, Any]) -> dict[str, Any]:
    return {a["id"]: a for a in doc["alerts"]}


def test_sweep_alert_is_built_from_stored_rows(fx: Path) -> None:
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:AAA"]
    assert a["rule"] == "reports suddenly increased"
    assert a["window"]["this_week"] == {"from": "2026-09-24", "to": "2026-09-30", "count": 4}
    assert a["window"]["baseline_4wk"]["count"] == 8
    assert a["window"]["baseline_4wk"]["weekly_mean"] == 2.0
    labels = {n["label"]: n["value"] for n in a["numbers"]}
    assert (
        labels["Reports in the latest sweep week"] == 4
        and labels["The latest sweep week compared with the weekly average (times)"] == 2.0
    )
    assert all(n["openfda_url"].startswith("https://api.fda.gov/") for n in a["numbers"])
    assert a["reports_total"] == 4 == a["reports_stored"] == len(a["reports"])
    assert a["who_filed"] == {"manufacturer": 2, "user_facility": 1, "other": 1}
    assert a["owner"]["name"] == "Pat Doe (simulated)" and a["owner"]["status"] == "Needs review"
    assert [k["k_number"] for k in a["k510"]] == ["K222222", "K111111"]  # newest first
    assert a["recalls_total"] == 2 and all(r["reason"] for r in a["recalls"])


def test_quotes_are_word_for_word_and_never_hold_a_person(fx: Path) -> None:
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:AAA"]
    texts = {
        "100001": f"{GOOD} {OTHER}",
        "100002": f"{NAMED} {OTHER}",
        "100003": "",
        "100004": GOOD,
    }
    by = {r["report_id"]: r for r in a["reports"]}
    assert by["100001"]["quote"] == GOOD and by["100001"]["quote"] in texts["100001"]
    assert (
        by["100002"]["quote"] == OTHER
    )  # the sentence with a named person is skipped, the next one is used
    assert NAMED not in json.dumps(a)
    assert by["100003"]["quote"] is None and "No sentence" in by["100003"]["quote_note"]
    assert by["100004"]["quote"] == GOOD
    for r in a["reports"]:
        assert (
            r["openfda_url"].startswith("https://api.fda.gov/") and "mdrfoi__id" in r["maude_url"]
        )


def test_gate_counts_are_honest(fx: Path) -> None:
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:AAA"]
    g = a["gate"]
    assert g["checked"] == g["passed"] + g["withheld"] > 0
    assert g["withheld"] == 0  # every fact shown passed
    # 3 quotes + 2 counts (this week, baseline) + 2 recall excerpts + 2 510(k) records
    assert g["checked"] == 3 + 2 + 2 + 2


def test_a_count_the_stored_rows_do_not_support_is_held_back_and_noted(fx: Path) -> None:
    sweep = json.loads((fx / "demo/sweep/ai-device-sweep.json").read_text())
    sweep["rows"][0]["current_count"] = 9  # the file says 9, the stored rows hold 4
    (fx / "demo/sweep/ai-device-sweep.json").write_text(json.dumps(sweep))
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:AAA"]
    assert a["gate"]["withheld"] == 1
    assert any("different count" in n for n in a["notes"])
    assert a["reports_total"] == 9 and a["reports_stored"] == 4
    assert any("4 of the 9" in n for n in a["notes"])


def test_a_code_with_nothing_stored_invents_nothing(fx: Path) -> None:
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:BBB"]
    assert a["rule"] == "more serious than usual"
    assert a["reports"] == [] and a["recalls"] == [] and a["k510"] == [] and a["who_filed"] is None
    assert a["owner"] is None
    assert a["gate"] == {"checked": 0, "passed": 0, "withheld": 0}
    assert any("No reports are stored" in n for n in a["notes"])
    labels = {n["label"]: n["value"] for n in a["numbers"]}
    assert labels["Injury or death reports in the latest sweep week"] == 2


def test_company_alert_without_a_weekly_rule(fx: Path) -> None:
    doc = ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company())
    a = _by_id(doc)["company:DMC-2"]
    assert a["rule"] is None and a["window"] is None and a["numbers"] == []
    assert "No weekly rule fired" in a["rule_words"]
    assert a["owner"]["device_id"] == "DMC-2"
    assert _by_id(doc)["company:DMC-1"]["rule"] == "reports suddenly increased"


def test_digest_alert_uses_the_digest_window(fx: Path) -> None:
    sig = {
        "product_code": "AAA",
        "classification": "spike",
        "current_count": 4,
        "baseline_count": 8,
        "baseline_weekly_mean": 2.0,
        "current_severe_count": 1,
        "baseline_severe_count": 0,
        "prior_report_count": 3,
    }
    digest = {
        "as_of": "2026-09-30",
        "window": {
            "current_start": "2026-09-24",
            "current_end": "2026-09-30",
            "baseline_start": "2026-08-27",
            "baseline_end": "2026-09-23",
        },
        "signals": [sig, {**sig, "product_code": "ZZZ", "classification": "stable"}],
    }
    (fx / "digests/2026-09-30.json").write_text(json.dumps(digest))
    doc = ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company())
    ids = _by_id(doc)
    assert "brief:2026-09-30:AAA" in ids and "brief:2026-09-30:ZZZ" not in ids
    assert ids["brief:2026-09-30:AAA"]["source"]["kind"] == "brief"
    assert ids["brief:2026-09-30:AAA"]["gate"]["withheld"] == 0


def test_at_most_ten_reports_with_the_total(fx: Path) -> None:
    con = sqlite3.connect(fx / "data/demo/maudesignal_demo.db")
    for i in range(14):
        rid = f"2{i:05d}"
        con.execute(
            "insert into raw_reports values (?,?,?,?,?,?)",
            (rid, "AAA", "20260929", "20260929", "{}", "x"),
        )
        con.execute(
            "insert into normalized_events values (?,?,?,?,?,?,?,?,?)",
            (rid, "AAA", "malfunction", "20260929", GOOD, "", "M", "B", "Manufacturer report"),
        )
    con.commit()
    con.close()
    sweep = json.loads((fx / "demo/sweep/ai-device-sweep.json").read_text())
    sweep["rows"][0]["current_count"] = 18
    (fx / "demo/sweep/ai-device-sweep.json").write_text(json.dumps(sweep))
    a = _by_id(ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company()))["sweep:AAA"]
    assert len(a["reports"]) == 10 and a["reports_total"] == 18 == a["reports_stored"]


def test_no_forbidden_word_and_every_step_says_a_person_decides(fx: Path) -> None:
    doc = ea.build_alerts(fx, "2026-10-31T00:00:00Z", _company())
    assert FORBIDDEN.search(json.dumps(doc)) is None
    for a in doc["alerts"]:
        assert any("A person decides" in s for s in a["next_steps"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dr. Smith called", True),
        ("patient Jones fell", True),
        ("A 54-year-old man", True),
        ("aged 61", True),
        ("write to a@b.com", True),
        ("call 555-123-4567", True),
        ("The patient was monitored.", False),
        ("Patient information is limited.", False),
        ("The device stopped.", False),
        ("", False),
    ],
)
def test_personal_details_pattern(text: str, expected: bool) -> None:
    assert ea.has_personal_details(text) is expected


def test_mentions_file_copies_stored_searches_and_never_invents(tmp_path: Path) -> None:
    empty = ea.build_mentions(tmp_path)
    assert empty["codes"] == {} and empty["notes"]
    (tmp_path / "demo/mentions").mkdir(parents=True)
    doc = {"product_code": "llz", "mode": "recorded", "mentions": []}
    (tmp_path / "demo/mentions/LLZ.json").write_text(json.dumps(doc))
    got = ea.build_mentions(tmp_path)
    assert (
        list(got["codes"]) == ["LLZ"]
        and got["codes"]["LLZ"]["mentions"] == []
        and got["notes"] == []
    )


def test_mentions_are_checked_before_they_are_copied(tmp_path: Path) -> None:
    folder = tmp_path / "demo/mentions"
    folder.mkdir(parents=True)
    good = {
        "source_name": "FDA",
        "url": "https://www.fda.gov/x",
        "quote": "The firm sent a letter to customers.",
        "why_matched": "matched: LLZ",
        "badge": "Verified!",
    }
    docs = {
        "LLZ": {
            "product_code": "LLZ",
            "mode": "recorded",
            "dropped": {"quote_not_found": 2, "personal_details": 1, "off_topic": 0},
            "mentions": [
                good,
                {**good, "url": "http://insecure.example/x"},
                {**good, "quote": "   "},
                {**good, "quote": "Dr. Jones said it failed."},
                {**good, "mode": "live"},
                "not a mapping",
            ],
        },
        "QIH": {"product_code": "QIH", "mode": "live", "mentions": [good]},
        "DQK": {"product_code": "DQK", "mentions": [good]},
    }
    for code, d in docs.items():
        (folder / f"{code}.json").write_text(json.dumps(d))
    got = ea.build_mentions(tmp_path)
    assert list(got["codes"]) == ["LLZ"]  # live and mode-less files are not copied
    m = got["codes"]["LLZ"]["mentions"]
    assert len(m) == 1 and m[0]["quote"] == good["quote"]
    assert m[0]["badge"] == "Unverified — not checked against FDA records"
    assert got["codes"]["LLZ"]["dropped"] == {
        "quote_not_found": 2,
        "personal_details": 2,
        "off_topic": 0,
    }


def test_real_stored_data_builds_and_matches_the_committed_file() -> None:
    doc = ea.build_alerts(ROOT, "x")
    ids = [a["id"] for a in doc["alerts"]]
    assert len(ids) == len(set(ids)) > 0
    sweep = json.loads((ROOT / "demo/sweep/ai-device-sweep.json").read_text())
    flagged = {r["product_code"]: r for r in sweep["rows"] if r["classification"] != "stable"}
    for code, row in flagged.items():
        a = _by_id(doc)[f"sweep:{code}"]
        assert a["window"]["this_week"]["count"] == row["current_count"]
        assert a["window"]["baseline_4wk"]["count"] == row["baseline_count"]
    # every shown quote is a sentence of its stored narrative
    con = sqlite3.connect(f"file:{ROOT / 'data/demo/maudesignal_demo.db'}?mode=ro", uri=True)
    for a in doc["alerts"]:
        for r in a["reports"]:
            if not r["quote"]:
                continue
            row = con.execute(
                "select narrative, mfr_narrative from normalized_events where maude_report_id = ?",
                (r["report_id"],),
            ).fetchone()
            if (
                row
            ):  # reports of fetched (not demo-database) codes are checked against their evidence file
                assert r["quote"] in " ".join(" ".join(x for x in row if x).split())
    con.close()
    committed = json.loads((ROOT / "web/public/data/alerts.json").read_text())
    for d in (doc, committed):
        d.pop("generated_utc")
    assert committed == doc, "run: python3 scripts/export_alerts.py"
