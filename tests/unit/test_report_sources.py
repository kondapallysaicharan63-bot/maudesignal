"""F12: report source stored, backfilled, counted, gated and shown (no network)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from maudesignal.copilot.tools import ToolContext, call_tool
from maudesignal.gate import SourceCountClaim, normalize_source, verify, verify_sentence
from maudesignal.gate.loader import store_from_database
from maudesignal.ingestion.pipeline import _normalize
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import digest_from_database, digest_to_dict, render_markdown
from maudesignal.monitor.sources import not_by_manufacturer, source_counts, sourced_reports
from maudesignal.storage.database import Database

ROWS = [  # (report_id, code, date_received, source)
    ("r1", "LLZ", "20260801", "Manufacturer report"),
    ("r2", "LLZ", "20260826", "Manufacturer report"),
    ("r3", "LLZ", "20260827", "User Facility report"),
    ("r4", "LLZ", "20260828", "Manufacturer report"),
    ("r5", "LLZ", "20260829", "Manufacturer report"),
    ("r6", "MYN", "20260830", "Voluntary report"),
    ("r7", "MYN", "20260831", None),
]


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "s.db")
    for rid, pc, day, src in ROWS:
        raw: dict[str, str] = {"mdr_report_key": rid}
        if src:
            raw["report_source_code"] = src
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code=pc,
            date_received=day,
            date_of_event=None,
            raw_payload=raw,
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code=pc,
            event_type="malfunction",
            event_date=day,
            narrative=None,
            mfr_narrative=None,
            manufacturer=None,
            brand_name="Brand " + rid,
            report_source=src,
        )
    return db


def test_normalize_source_values() -> None:
    assert normalize_source("User Facility report") == "user facility"
    assert normalize_source("Manufacturer report") == "manufacturer"
    assert normalize_source("hospital reports") == "user facility"
    assert normalize_source("Non-manufacturer") == "non-manufacturer"
    assert normalize_source(None) == "" and normalize_source("lawyer") == ""


def test_ingestion_extracts_source() -> None:
    raw = {"report_source_code": "Voluntary report"}
    assert _normalize(raw, "LLZ")["report_source"] == "Voluntary report"
    assert _normalize({}, "LLZ")["report_source"] == ""


def test_old_database_gets_column_and_backfill_from_raw_json(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    Database(path)  # creates the schema; then make it look like a pre-F12 database
    con = sqlite3.connect(path)
    con.execute("DROP INDEX ix_normalized_events_report_source")
    con.execute("ALTER TABLE normalized_events DROP COLUMN report_source")
    con.execute(
        "INSERT INTO raw_reports (maude_report_id, product_code, date_received, raw_json, "
        "fetched_at) VALUES ('a1', 'LLZ', '20260801', ?, '2026-10-28 00:00:00')",
        (json.dumps({"report_source_code": "Distributor report"}),),
    )
    con.execute(
        "INSERT INTO normalized_events (maude_report_id, product_code) VALUES ('a1', 'LLZ')"
    )
    con.commit()
    con.close()
    (ev,) = Database(path).list_normalized_events()
    assert ev.report_source == "Distributor report"


def test_upsert_without_source_keeps_the_stored_one(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_normalized_event(
        maude_report_id="r3",
        product_code="LLZ",
        event_type="malfunction",
        event_date="20260827",
        narrative=None,
        mfr_narrative=None,
        manufacturer=None,
        brand_name=None,
    )
    stored = {e.maude_report_id: e.report_source for e in db.list_normalized_events()}
    assert stored["r3"] == "User Facility report"


def test_counts_and_non_manufacturer_list(tmp_path: Path) -> None:
    reports = sourced_reports(_db(tmp_path))
    assert source_counts(reports) == {
        "LLZ": {"manufacturer": 4, "user facility": 1},
        "MYN": {"unknown": 1, "voluntary": 1},
    }
    week = source_counts(reports, date_from="20260825", date_to="20260831")
    assert week["LLZ"] == {"manufacturer": 3, "user facility": 1}
    assert [r.report_id for r in not_by_manufacturer(reports)] == ["r6", "r3"]


def test_tool_and_gate_claim(tmp_path: Path) -> None:
    db = _db(tmp_path)
    ctx = ToolContext(db=db, store=store_from_database(db))
    out = call_tool(ctx, "report_sources", json.dumps({"product_code": "LLZ"}))
    assert out["source_counts"] == {"manufacturer": 4, "user facility": 1}
    assert out["non_manufacturer_count"] == 1
    assert out["non_manufacturer_reports"][0]["report_id"] == "r3"
    assert out["latest_date_received"] == "20260829" and "note" not in out
    later = call_tool(
        ctx, "report_sources", json.dumps({"product_code": "LLZ", "date_from": "20261001"})
    )
    # After the stored data: flagged as not covered (copilot.dates), never a count of 0.
    assert later["no_data_for_range"] is True and "report_count" not in later
    assert later["data_covers"]["date_to"] == "20260829"
    assert "do not report it as 0 reports" in later["date_note"]
    ok, bad = verify(
        [
            SourceCountClaim("LLZ", "non-manufacturer", 1),
            SourceCountClaim("MYN", "non-manufacturer", 2),  # an unknown source is not counted
        ],
        ctx.store,
    )
    assert ok.status == "pass" and ok.evidence_ids == ("r3",)
    assert bad.status == "block" and "records show 1" in bad.reason
    assert verify_sentence("LLZ had 2 hospital reports.", [], ctx.store).status == "block"


def test_digest_lists_sources_for_the_window(tmp_path: Path) -> None:
    db = _db(tmp_path)
    digest = digest_from_database(db, detect_from_database(db))
    assert digest.window_sources["LLZ"] == {"manufacturer": 3, "user facility": 1}
    md = render_markdown(digest)
    assert "Filed by (openFDA report source), this window: manufacturer 3, user facility 1" in md
    assert digest_to_dict(digest)["window_sources"]["LLZ"]["user facility"] == 1
