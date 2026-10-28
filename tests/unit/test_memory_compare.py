"""Copilot memory, signal compare, their tools, streamed progress (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from maudesignal.copilot.agent import CopilotAgent
from maudesignal.copilot.memory import (
    CopilotMemoryError,
    load_memory,
    pin_note,
    remove_note,
    set_device_types,
)
from maudesignal.copilot.tools import ToolContext, call_tool
from maudesignal.dashboard.copilot_pages import progress_line, stream_verified
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.compare import compare_signals
from maudesignal.storage.database import Database
from tests.unit.test_copilot_agent import FakeClient, _answer, _call, _final, _msg


def _db(tmp_path: Path) -> Database:
    """LLZ spikes this week (6 vs a 1/week baseline); MYN is stable."""
    db = Database(tmp_path / "m.db")
    rows = [(f"b{i}", "LLZ", f"202608{i + 1:02d}", "Malfunction", None) for i in range(0, 28, 7)]
    rows += [(f"c{i}", "LLZ", f"202608{25 + i}", "Malfunction", None) for i in range(5)]
    rows += [("c9", "LLZ", "20260830", "Injury", "User Facility report")]
    rows += [("m1", "MYN", "20260805", "Malfunction", None)]
    rows += [("m2", "MYN", "20260826", "Malfunction", "Voluntary report")]
    for rid, pc, day, et, src in rows:
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
            event_type=et,
            event_date=day,
            narrative="text",
            mfr_narrative=None,
            manufacturer=None,
            brand_name="B",
            report_source=src or "Manufacturer report",
        )
    return db


def test_memory_is_replayed_from_the_audit_chain(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert load_memory(db).device_types == []
    set_device_types(db, ["llz", " myn ", "LLZ"], actor="Dana QA")
    mem = load_memory(db)
    assert mem.device_types == ["LLZ", "MYN"] and mem.device_types_set_by == "Dana QA"
    n = pin_note(db, "LLZ jumped this week.", actor="Dana QA", evidence_ids=["c0"])
    assert [x.note_id for x in load_memory(db).notes] == [n.note_id]
    remove_note(db, n.note_id, actor="Dana QA")
    assert load_memory(db).notes == []
    actions = [r.action for r in db.list_audit(entity_id="MEMORY")]
    assert actions == ["memory.device_types", "memory.note", "memory.note_removed"]
    assert db.verify_audit_chain() == (True, None)


@pytest.mark.parametrize(
    ("codes", "actor"), [(["LL1"], "x"), (["LLZ"], " "), ([f"A{i:02d}" for i in range(30)], "x")]
)
def test_memory_rejects_bad_changes(tmp_path: Path, codes: list[str], actor: str) -> None:
    with pytest.raises(CopilotMemoryError):
        set_device_types(_db(tmp_path), codes, actor=actor)


def test_memory_note_rules(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(CopilotMemoryError):
        pin_note(db, "  ", actor="x")
    with pytest.raises(CopilotMemoryError):
        pin_note(db, "x" * 501, actor="x")
    with pytest.raises(CopilotMemoryError):
        remove_note(db, "N-999", actor="x")


def test_compare_numbers_match_the_detector(tmp_path: Path) -> None:
    cmp = compare_signals(_db(tmp_path), ["MYN", "LLZ", "llz", "ZZZ"])
    assert [r.product_code for r in cmp.rows] == ["MYN", "LLZ"]
    assert cmp.unknown_codes == ("ZZZ",)
    llz = cmp.rows[1]
    # The Injury report is an event type never seen for LLZ, which outranks the increase.
    assert llz.this_week == 6 and llz.change == "new kind of problem"
    assert llz.injury_death_this_week == 1 and llz.not_by_manufacturer_this_week == 1
    assert llz.stored_total == 10
    assert cmp.rows[0].not_by_manufacturer_this_week == 1  # the voluntary MYN report
    d = cmp.to_dict()
    assert d["window"] == {"date_from": "20260824", "date_to": "20260830"}  # latest stored day


def test_tools_read_memory_and_compare(tmp_path: Path) -> None:
    db = _db(tmp_path)
    ctx = ToolContext(db=db, store=store_from_database(db))
    assert "error" in call_tool(ctx, "compare_signals", "{}")  # nothing remembered yet
    set_device_types(db, ["LLZ"], actor="Dana QA")
    assert call_tool(ctx, "my_device_types", "{}")["device_types"] == ["LLZ"]
    out = call_tool(ctx, "compare_signals", "{}")
    assert [r["product_code"] for r in out["rows"]] == ["LLZ"]
    out = call_tool(ctx, "compare_signals", json.dumps({"product_codes": ["MYN"]}))
    assert out["rows"][0]["product_code"] == "MYN"


def test_ask_streams_progress_events(tmp_path: Path) -> None:
    db = _db(tmp_path)
    ctx = ToolContext(db=db, store=store_from_database(db))
    answer = _answer(
        ("LLZ has 10 reports.", [{"kind": "count", "product_code": "LLZ", "value": 10}]),
    )
    client = FakeClient(
        [_msg(tool_calls=[_call("compare_signals", {"product_codes": ["LLZ"]})]), *_final(answer)]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    res = CopilotAgent(client, ctx).ask("Compare LLZ", on_event=lambda k, d: events.append((k, d)))
    kinds = [k for k, _ in events]
    assert kinds[:3] == ["model", "tool", "model"] and kinds[-1] == "done"
    assert ("gate", {"stage": "first pass", "passed": 1, "blocked": 0}) in events
    assert res.report.passed == 1
    assert all(progress_line(k, d) for k, d in events)


def test_stream_shows_only_verified_sentences() -> None:
    t = {
        "final": {
            "sentences": [
                {"text": "LLZ has 10 reports.", "status": "pass"},
                {"text": "LLZ has 500 deaths.", "status": "block"},
            ]
        }
    }
    text = "".join(stream_verified(t))
    assert "10 reports" in text and "500" not in text
    assert "nothing is shown" in "".join(stream_verified({"final": {"sentences": []}}))


def test_exploratory_findings_are_fixed(tmp_path: Path) -> None:
    """Found by exploratory testing on 2026-10-28: lower-case codes, a string of codes,
    and an empty CAPA-need evidence pack."""
    db = _db(tmp_path)
    ctx = ToolContext(db=db, store=store_from_database(db))
    lower = call_tool(ctx, "product_summary", json.dumps({"product_code": "llz "}))
    assert lower["product_code"] == "LLZ" and lower["report_count"] == 10
    one_string = call_tool(ctx, "compare_signals", json.dumps({"product_codes": "llz, myn"}))
    assert [r["product_code"] for r in one_string["rows"]] == ["LLZ", "MYN"]
    empty = call_tool(
        ctx,
        "draft_capa",
        json.dumps(
            {"product_code": "LLZ", "title": "t", "problem_statement": "p", "report_ids": []}
        ),
    )
    assert "at least one" in empty["error"]


def test_literature_ranks_by_matching_terms() -> None:
    """2026-10-28 recordings: "AI radiology software failures" matched nothing because
    every word had to appear; relevant abstracts were stored. Now ranked by terms."""
    from maudesignal.gate.evidence import EvidenceStore, LiteratureRef

    store = EvidenceStore(
        literature=[
            LiteratureRef("1", "Artificial intelligence in radiology", "Software failures seen."),
            LiteratureRef("2", "Deep learning for stroke", "Radiology triage software."),
            LiteratureRef("3", "Hip replacement outcomes", "Orthopaedic follow-up."),
        ]
    )
    ctx = ToolContext(db=None, store=store)  # type: ignore[arg-type]
    out = call_tool(ctx, "literature", json.dumps({"query": "AI radiology software failures"}))
    assert [a["pmid"] for a in out["articles"]] == ["1", "2"]  # 4 of 4 terms, then 3 of 4
    assert call_tool(ctx, "literature", json.dumps({"query": "the of"}))["matched"] == 3
