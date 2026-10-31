"""Tests for the search protocol builder and the evidence-pack appendix (HACKATHON-BUILT).

Uses the transcripts recorded under ``demo/transcripts``; no network, no model.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from maudesignal.copilot.actions import draft_capa
from maudesignal.copilot.protocol import (
    TOOL_DATASETS,
    load_transcripts,
    protocol_for_capa,
    protocol_from_calls,
    protocol_from_transcript,
)
from maudesignal.dossier import build_dossier, render_html

TRANSCRIPTS = Path(__file__).resolve().parents[2] / "demo" / "transcripts"


def _by_label(label: str) -> dict:  # type: ignore[type-arg]
    for t in load_transcripts(TRANSCRIPTS):
        if t["label"] == label:
            return t
    raise AssertionError(label)


def test_every_stored_transcript_yields_rows_from_stored_values_only() -> None:
    transcripts = load_transcripts(TRANSCRIPTS)
    assert len(transcripts) >= 20
    total = 0
    for t in transcripts:
        calls = [c for c in t["tool_calls"] if c["name"] != "draft_capa"]
        rows = protocol_from_transcript(t)
        assert len(rows) == len(calls)
        for row, call in zip(rows, calls, strict=True):
            total += 1
            assert row.tool == call["name"]
            assert row.dataset == TOOL_DATASETS[row.tool]
            assert row.run_at == t["recorded_at_utc"].replace("+00:00", "Z")
            for k, v in row.filters.items():
                assert call["arguments"][k] == v
            if row.count is not None and row.tool != "get_report":  # 1 = record found
                # A count must literally appear in the stored result; never computed.
                assert re.search(rf"\b{row.count}\b", call["result_preview"])
            for d in (row.date_from, row.date_to):
                assert d is None or d in json.dumps(call)
    assert total > 40


def test_known_rows() -> None:
    summary = next(
        r
        for t in load_transcripts(TRANSCRIPTS)
        for r in protocol_from_transcript(t)
        if r.tool == "product_summary"
        and r.date_from is None
        and r.filters == {"product_code": "LLZ"}
    )
    assert summary.count == 121
    assert summary.dataset.startswith("openFDA MAUDE")

    overnight = protocol_from_transcript(_by_label("01-what-changed"))[0]
    assert overnight.tool == "overnight_signals"
    assert (overnight.date_from, overnight.date_to) == ("20260825", "20260831")
    assert overnight.count is None
    assert overnight.count_text == "not recorded"

    sources = protocol_from_transcript(_by_label("21-not-by-manufacturer"))
    dated = [r for r in sources if r.tool == "report_sources" and r.date_from == "20260801"][0]
    assert (dated.date_to, dated.count) == ("20260831", 49)


def test_writes_and_errors_are_handled() -> None:
    rows = protocol_from_calls(
        [
            {"name": "draft_capa", "arguments": {"title": "x"}, "result_preview": "{}"},
            {
                "name": "compare_signals",
                "arguments": {},
                "result_preview": '{"error": "no device types given"}',
            },
            {"name": "get_report", "arguments": {"report_id": "1"}, "result_preview": ""},
        ],
        run_at="2026-10-28T00:00:00+00:00",
    )
    assert [r.tool for r in rows] == ["compare_signals", "get_report"]
    assert all(r.count is None for r in rows)


def test_protocol_for_capa_uses_only_the_transcript_that_made_it() -> None:
    transcripts = load_transcripts(TRANSCRIPTS)
    rows = protocol_for_capa(transcripts, "CAPA-DRAFT-CB63076E")
    assert [r.tool for r in rows] == ["overnight_signals", "get_report", "get_report", "get_report"]
    assert protocol_for_capa(transcripts, "CAPA-DRAFT-NOPE") == []


def test_labels_and_one_timestamp_format() -> None:
    from maudesignal.copilot.protocol import iso_z, tool_label

    assert tool_label("overnight_signals") == "weekly_signals"
    assert tool_label("get_report") == "get_report"
    assert iso_z("2026-10-28T20:36:53+00:00") == "2026-10-28T20:36:53Z"
    assert iso_z("2026-10-28T20:36:53Z") == "2026-10-28T20:36:53Z"
    assert iso_z(None) is None
    for t in load_transcripts(TRANSCRIPTS):
        for r in protocol_from_transcript(t):
            assert r.run_at is not None and r.run_at.endswith("Z") and "+" not in r.run_at
            assert "overnight" not in r.label


def test_committed_demo_db_links_copilot_rows_to_the_pack(tmp_path: Path) -> None:
    """Unedited link: restore the pack transcript 05 recorded, then build its dossier."""
    import shutil

    from maudesignal.copilot.actions import restore_recorded_capas
    from maudesignal.storage.database import Database

    root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "demo.db"
    shutil.copy(root / "data" / "demo" / "maudesignal_demo.db", db_path)
    db = Database(db_path)
    transcripts = load_transcripts(TRANSCRIPTS)
    restored = restore_recorded_capas(db, transcripts)
    assert restored == ["CAPA-DRAFT-CB63076E"]
    assert restore_recorded_capas(db, transcripts) == []  # idempotent
    row = db.get_capa_draft("CAPA-DRAFT-CB63076E")
    assert row is not None and row.status == "draft"
    # contemporaneous: the pack keeps the time the copilot recorded, and the audit entry
    # names the transcript it was restored from
    assert row.created_at == datetime(2026, 10, 28, 20, 36, 53)
    entry = next(
        a
        for a in db.list_audit()
        if a.entity_id == "CAPA-DRAFT-CB63076E" and a.action == "capa.draft"
    )
    payload = json.loads(entry.payload_json)
    assert payload["restored_from"].endswith(".json")
    assert payload["recorded_at_utc"] == "2026-10-28T20:36:53Z"

    b = build_dossier(db, capa_id="CAPA-DRAFT-CB63076E", transcripts=TRANSCRIPTS)
    labels = [r.label for r in b.data.protocol]
    assert labels[-4:] == ["weekly_signals", "get_report", "get_report", "get_report"]
    cited = next(r for r in b.data.protocol if r.tool == "dossier: cited reports")
    assert cited.filters["report_ids"] == ["50426770", "50426773", "50448213"]
    assert cited.count == 3
    assert {r.run_at for r in b.data.protocol[-4:]} == {"2026-10-28T20:36:53Z"}

    html = render_html(b.data)
    assert "Appendix B. Search methodology" in html
    assert 'id="search-methodology"' in html
    assert "weekly_signals" in html and "overnight" not in html.lower()
    assert "report_id=50426770" in html and "not recorded" in html
    assert "report_ids=50426770,50426773,50448213" in html


def test_pack_without_transcripts_shows_builder_rows_only(tmp_path: Path) -> None:
    from tests.unit.test_dossier import CURRENT_IDS, PC
    from tests.unit.test_dossier import _db as dossier_db

    db = dossier_db(tmp_path)
    capa = draft_capa(
        db,
        product_code=PC,
        title="QIH alert failures",
        problem_statement="Alerts were not sent after a server update.",
        report_ids=CURRENT_IDS,
        actor="copilot:muse-spark",
    )
    b = build_dossier(
        db,
        capa_id=capa.capa_id,
        generated_at=datetime(2026, 10, 27, 12, 0, 0),
        transcripts=tmp_path / "missing",
    )
    assert all(r.tool.startswith("dossier:") for r in b.data.protocol)
    # "Run at" is when the builder's queries ran, not the printed (supplied) document time
    assert b.data.protocol[0].run_at != "2026-10-27T12:00:00Z"
    assert b.data.protocol[0].run_at is not None and b.data.protocol[0].run_at.endswith("Z")
    assert b.data.generated_at == datetime(2026, 10, 27, 12, 0, 0)


def test_transcript_dict_carries_protocol() -> None:
    from maudesignal.copilot.agent import CopilotResult, ToolCallTrace
    from maudesignal.copilot.transcript import result_to_dict
    from maudesignal.gate import GateReport

    rep = GateReport(sentences=[])
    res = CopilotResult(
        question="q",
        answer="a",
        report=rep,
        first_pass_report=rep,
        repaired=False,
        tool_calls=[
            ToolCallTrace(
                name="get_report",
                arguments={"report_id": "50426770"},
                result_preview='{"report_id": "50426770"}',
            )
        ],
    )
    d = result_to_dict(res, label="x")
    assert [r["tool"] for r in d["protocol"]] == ["get_report"]
    assert d["protocol"][0]["count"] == 1 and d["protocol"][0]["run_at"].endswith("Z")
    assert [r.tool for r in res.protocol] == ["get_report"]


def test_filtered_recall_count_is_the_keyword_matches_not_the_stored_total() -> None:
    """Transcript 18: recalls(query=...) matched 3; the product code has 561 stored recalls."""
    rows = protocol_from_transcript(_by_label("18-trap-recall"))
    recall = next(r for r in rows if r.tool == "recalls")
    assert recall.filters == {"product_code": "LLZ", "query": "IntelliSpace Cardiovascular"}
    assert recall.count == 3
    assert recall.count_text == "3"
    # without a query the matched count is not in the log: never fall back to the stored total
    bare = protocol_from_calls(
        [
            {
                "name": "recalls",
                "arguments": {"product_code": "LLZ"},
                "result_preview": '{"product_code": "LLZ", "stored_recall_count": 561}',
            }
        ]
    )[0]
    assert bare.count is None and bare.count_text == "not recorded"


def test_restored_pack_is_a_labelled_replay_not_a_copilot_write(tmp_path: Path) -> None:
    import shutil

    from maudesignal.copilot.actions import RESTORE_ACTOR, restore_recorded_capas
    from maudesignal.storage.database import Database

    root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "demo.db"
    shutil.copy(root / "data" / "demo" / "maudesignal_demo.db", db_path)
    db = Database(db_path)
    restore_recorded_capas(db, load_transcripts(TRANSCRIPTS))
    row = db.get_capa_draft("CAPA-DRAFT-CB63076E")
    assert row is not None and row.created_by == RESTORE_ACTOR == "demo-restore"
    assert not any(
        a.actor == "copilot:muse-spark" and a.entity_id == "CAPA-DRAFT-CB63076E"
        for a in db.list_audit()
    )
    b = build_dossier(db, capa_id="CAPA-DRAFT-CB63076E", transcripts=TRANSCRIPTS)
    assert b.data.capa is not None and b.data.capa.restored_from is not None
    html = render_html(b.data)
    src = f"demo/transcripts/{b.data.capa.restored_from}"
    assert f"Restored from {src}" in html
    assert "(recorded 2026-10-28T20:36:53Z)" in html
    assert 'id="restored-note"' in html and "demo-restore" in html
    assert "copilot:muse-spark" not in html


def test_keyless_demo_shows_recorded_narrative_review_and_linked_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed recordings predate the pack binding: still shown, with the note."""
    from maudesignal.dashboard.demo_db import demo_copy_with_recorded_packs
    from maudesignal.dossier.review import load_review
    from maudesignal.dossier.service import recorded_dir
    from maudesignal.storage.database import Database

    monkeypatch.setattr("maudesignal.dashboard.demo_db._COPIES", {})
    root = Path(__file__).resolve().parents[2]
    source = root / "data" / "demo" / "maudesignal_demo.db"
    before = source.read_bytes()
    copy = demo_copy_with_recorded_packs(source)
    assert source.read_bytes() == before and copy != source
    db = Database(copy)
    b = build_dossier(
        db,
        capa_id="CAPA-DRAFT-CB63076E",
        recorded_dir=recorded_dir(),
        transcripts=TRANSCRIPTS,
    )
    assert b.data.narrative.available and b.data.narrative.source == "recorded"
    # The 2026-10-31 recording is bound to its pack (hash), so no "unbound" note is shown.
    # Figures pinned to the stored files: 5 sentences shown, 0 withheld, Wonder 0 findings.
    assert (b.data.narrative.passed, b.data.narrative.withheld) == (5, 0)
    assert b.data.narrative.binding_note == ""
    assert [r.label for r in b.data.protocol][-4:] == [
        "weekly_signals",
        "get_report",
        "get_report",
        "get_report",
    ]
    review = load_review(recorded_dir() / f"{b.data.doc_id}-review.json", b.store)
    assert review is not None and not review.predates_binding
    assert review.findings == []
