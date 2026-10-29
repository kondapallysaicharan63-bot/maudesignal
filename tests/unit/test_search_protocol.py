"""Tests for the search protocol builder and the evidence-pack appendix (HACKATHON-BUILT).

Uses the transcripts recorded under ``demo/transcripts``; no network, no model.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

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
            assert row.run_at == t["recorded_at_utc"]
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


def test_evidence_pack_html_has_search_methodology(tmp_path: Path) -> None:
    from tests.unit.test_dossier import CURRENT_IDS, FIXED_TS, PC
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
    # Stored transcript 05 re-pointed at this test CAPA id so its tool calls are linked to it.
    t = dict(_by_label("05-capa-need-evidence"))
    t["capa_ids"] = [capa.capa_id]
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "05.json").write_text(json.dumps(t), encoding="utf-8")

    b = build_dossier(
        db,
        capa_id=capa.capa_id,
        awareness_date=date(2026, 10, 27),
        generated_at=FIXED_TS,
        transcripts=tmp_path / "t",
    )
    tools = [r.tool for r in b.data.protocol]
    assert tools[:2] == ["dossier: current window", "dossier: baseline window"]
    assert tools[-4:] == ["overnight_signals", "get_report", "get_report", "get_report"]
    cur = b.data.protocol[0]
    assert cur.count == int(b.data.signal.current_count.value)
    assert cur.run_at == "2026-10-27T12:00:00Z"
    assert isinstance(FIXED_TS, datetime)

    html = render_html(b.data)
    assert "Appendix B. Search methodology" in html
    assert 'id="search-methodology"' in html
    assert "20260825" in html and "get_report" in html and "report_id=50426770" in html
    assert "not recorded" in html  # overnight_signals has no single matched-count

    # No capa transcripts folder: builder rows only.
    b2 = build_dossier(db, capa_id=capa.capa_id, transcripts=tmp_path / "missing")
    assert all(r.tool.startswith("dossier:") for r in b2.data.protocol)
