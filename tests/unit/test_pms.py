"""PMS board, note to file, checklists, QMS export, data-as-of (PRD-19..25, 2026-11-03)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from maudesignal.monitor.deterioration import REPORT_MIX_LIMITATION, report_mix_sentence
from maudesignal.pms import (
    DELAY_SENTENCE,
    NOTE_LABEL,
    AsOf,
    BoardError,
    EvidencePack,
    NoteToFileError,
    as_of_text,
    board_state,
    change_status,
    escalation_checklist,
    recall_check,
    record_note_to_file,
    risk_section,
    stored_as_of,
)
from maudesignal.pms.board import mdr_due
from maudesignal.pms.checklists import FORBIDDEN_DECISIONS, has_decision_sentence
from maudesignal.pms.note_to_file import BLANK_FIELD, export_bundle
from maudesignal.pms.simple_pdf import pdf_text
from maudesignal.storage.database import Database

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "pms.db")


def _pack() -> EvidencePack:
    return EvidencePack(
        product_code="DSI",
        device_type="Detector And Alarm, Arrhythmia",
        why="Report mix changed. " + report_mix_sentence(0.03, 0.2, 2, 10),
        reports=[
            {"report_id": "50951017", "date_received": "2026-09-30", "event_type": "Injury"},
            {"report_id": "50911495", "date_received": "2026-09-28", "event_type": "Injury"},
            {"report_id": "50900001", "date_received": "2026-09-27", "event_type": "Malfunction"},
            {"report_id": "50900002", "date_received": "2026-09-26", "event_type": None},
        ],
        recalls=[
            {"id": "Z-1793-2026", "reason": "Circuit board issue; Bad Curve error", "url": "u"},
            {"id": "Z-2052-2026", "reason": None},
        ],
        failure_terms=["circuit board"],
    )


AS_OF = AsOf(latest="2026-09-30", snapshot="stored sweep file, week 2026-09-24 to 2026-09-30")


# ---------------------------------------------------------------- report-mix wording


def test_report_mix_sentence_exact_form() -> None:
    s = report_mix_sentence(0.2, 0.6, 3, 5)
    assert s == (
        "Injury/Death share rose from 20% to 60% (3 of 5 reports). This is a change in "
        "report mix, not proof of increased device risk."
    )
    assert REPORT_MIX_LIMITATION in s


def test_old_label_is_gone_from_user_facing_files() -> None:
    old = "more serious " + "than usual"
    roots = ["src", "web/src", "web/public/data", "docs", "skills", "README.md", "scripts"]
    hits = []
    for r in roots:
        p = ROOT / r
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        for f in files:
            if f.suffix not in {".py", ".ts", ".tsx", ".json", ".md", ".j2", ".html", ".css"}:
                continue
            text = f.read_text("utf-8", errors="ignore").lower()
            for line in text.splitlines():
                if old in line and "changelog" not in line and "renamed" not in line:
                    # Skill changelog lines name the old label on purpose.
                    if re.match(r"^- \d+\.\d+\.\d+ \(2026-11-03\)", line.strip()):
                        continue
                    hits.append(str(f.relative_to(ROOT)))
    assert hits == []


# ---------------------------------------------------------------- data as of


def test_as_of_text_has_every_part() -> None:
    t = as_of_text(AsOf(latest="2026-08-31", snapshot="2026-07-01 to 2026-08-31", live=None))
    assert t.startswith("Data as of: 2026-08-31.")
    assert DELAY_SENTENCE in t and "not because risk is zero" in t
    assert "Stored snapshot: 2026-07-01 to 2026-08-31." in t
    assert t.endswith("Live check: none on this page.")


def test_stored_as_of_reads_the_demo_db(tmp_path: Path) -> None:
    import shutil

    demo = ROOT / "data" / "demo" / "maudesignal_demo.db"
    copy = tmp_path / "demo.db"
    shutil.copy(demo, copy)  # the frozen demo DB is never opened for writing
    a = stored_as_of(Database(copy))
    con = sqlite3.connect(f"file:{demo}?mode=ro", uri=True)
    hi, n = con.execute("select max(date_received), count(*) from raw_reports").fetchone()
    assert a.latest == f"{hi[:4]}-{hi[4:6]}-{hi[6:8]}"
    assert f"({n} stored MAUDE reports)" in (a.snapshot or "")


def test_web_manifest_carries_data_as_of_and_build() -> None:
    m = json.loads((ROOT / "web" / "public" / "data" / "manifest.json").read_text("utf-8"))
    assert m["build"]["version"] == "0.1.0"
    assert re.fullmatch(r"[0-9a-f]{40}", m["build"]["commit"] or "")
    sweep = json.loads((ROOT / "web" / "public" / "data" / "sweep.json").read_text("utf-8"))
    assert m["data_as_of"]["sweep"]["week_end"] == sweep["meta"]["window"]["current_end"]
    assert m["data_as_of"]["sweep"]["checked_utc"] == sweep["meta"]["generated_utc"]


# ---------------------------------------------------------------- board


def test_board_moves_only_by_a_named_person_and_is_audited(db: Database) -> None:
    flagged = {"DSI": "Report mix changed"}
    assert board_state(db, flagged)[0].status == "new"
    with pytest.raises(BoardError, match="named person"):
        change_status(db, product_code="DSI", why="x", current="new", to="under_review", actor="")
    with pytest.raises(BoardError, match="cannot move"):
        change_status(db, product_code="DSI", why="x", current="new", to="closed", actor="Ana Ruiz")
    seq = change_status(
        db,
        product_code="DSI",
        why="Report mix changed",
        current="new",
        to="under_review",
        actor="Ana Ruiz",
        owner="Ben Okafor",
        awareness="2026-11-03",
    )
    change_status(
        db, product_code="DSI", why="x", current="under_review", to="note_to_file", actor="Ana Ruiz"
    )
    row = board_state(db, flagged)[0]
    assert row.status == "note_to_file" and row.owner == "Ben Okafor"
    assert row.due == "2026-12-03" and "803.50" in (row.due_basis or "")
    assert [h[1:3] for h in row.history] == [
        ("new", "under_review"),
        ("under_review", "note_to_file"),
    ]
    e = [x for x in db.list_audit() if x.seq == seq][0]
    assert e.actor == "Ana Ruiz" and e.action == "board_status" and e.entity_id == "board:DSI"
    assert db.verify_audit_chain() == (True, None)


def test_mdr_clock_is_advisory() -> None:
    assert mdr_due("2026-11-06", five_day=True) == (
        "2026-11-13",
        "5 work days, 21 CFR 803.53 (advisory; a person decides)",
    )
    with pytest.raises(BoardError):
        mdr_due("2026-02-31")


def test_tampering_one_audit_entry_breaks_the_chain_at_that_entry(tmp_path: Path) -> None:
    path = tmp_path / "copy.db"
    db = Database(path)
    for to, cur in (
        ("under_review", "new"),
        ("note_to_file", "under_review"),
        ("closed", "note_to_file"),
    ):
        change_status(db, product_code="LLZ", why="w", current=cur, to=to, actor="Ana Ruiz")
    assert db.verify_audit_chain() == (True, None)
    con = sqlite3.connect(path)
    con.execute("update action_audit set actor = 'Someone Else' where seq = 2")
    con.commit()
    con.close()
    assert db.verify_audit_chain() == (False, 2)


# ---------------------------------------------------------------- checklists


def test_checklists_end_with_a_human_decision_and_never_decide() -> None:
    p = _pack()
    esc = escalation_checklist(p)
    assert [c["item"] for c in esc] == [
        "MDR reportability assessment",
        "Recall / correction-and-removal assessment",
        "Field safety action assessment",
    ]
    assert all(c["decision"] is None and "Human decides" in c["decided_by"] for c in esc)
    assert esc[0]["evidence"] == ["50951017", "50911495"]  # injury reports first-class
    rs = risk_section(p)
    mix = {m["event_type"]: (m["count"], m["share"]) for m in rs["severity_mix"]}
    assert mix == {
        "death": (0, 0.0),
        "injury": (2, 0.5),
        "malfunction": (1, 0.25),
        "other / not stated": (1, 0.25),
    }
    assert "not rates" in rs["occurrence"] and "no incidence" in rs["occurrence"]
    rc = recall_check(p)
    assert rc["recalls_naming_the_failure_mode"] == ["Z-1793-2026"]
    assert rc["question"] == "Does this meet your recall procedure?"
    blob = json.dumps([esc, rs, rc]).lower()
    assert not any(f in blob for f in FORBIDDEN_DECISIONS)


def test_decision_sentences_are_detected_but_the_limitation_is_not() -> None:
    assert has_decision_sentence("A recall needed for this device.")
    assert has_decision_sentence("This event is reportable.")
    assert not has_decision_sentence(REPORT_MIX_LIMITATION)


# ---------------------------------------------------------------- note to file + export


def test_note_to_file_matches_its_audit_row(db: Database) -> None:
    with pytest.raises(NoteToFileError, match="name"):
        record_note_to_file(
            db, pack=_pack(), as_of=AS_OF, decision="note_to_file", rationale="x" * 20, approver=""
        )
    with pytest.raises(NoteToFileError, match="rationale"):
        record_note_to_file(
            db, pack=_pack(), as_of=AS_OF, decision="capa", rationale="no", approver="Ana Ruiz"
        )
    n = record_note_to_file(
        db,
        pack=_pack(),
        as_of=AS_OF,
        decision="note_to_file",
        rationale="Mix change driven by two literature-review reports; no new failure mode.",
        approver="Ana Ruiz",
        root=ROOT,
    )
    e = db.list_audit()[-1]
    payload = json.loads(e.payload_json)
    assert (e.seq, e.actor, e.action) == (n.audit_seq, "Ana Ruiz", "note_to_file")
    assert payload["decision"] == "note_to_file"
    assert payload["report_ids"] == ["50951017", "50911495", "50900001", "50900002"]
    md = n.to_markdown()
    for must in (
        NOTE_LABEL,
        "Product code: DSI",
        "Data as of: 2026-09-30",
        "Injury/Death share rose from 3% to 20% (2 of 10 reports)",
        "50951017",
        "Z-1793-2026",
        "Decision: Note to file",
        "Approver: Ana Ruiz",
        f"audit entry #{n.audit_seq}",
        f"Company complaint / CAPA number: {BLANK_FIELD}",
        "Build: MaudeSignal 0.1.0 · commit ",
        "Does this meet your recall procedure?",
    ):
        assert must in md, must
    pdf = n.to_pdf()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    text = pdf_text(pdf)
    assert "Approver: Ana Ruiz" in text and NOTE_LABEL in text and "Page 1 of" in text


def test_export_bundle_prints_version_commit_date_and_blank_number(db: Database) -> None:
    n = record_note_to_file(
        db,
        pack=_pack(),
        as_of=AS_OF,
        decision="escalate",
        rationale="Two injury reports; escalate to RA lead for MDR assessment.",
        approver="Ana Ruiz",
        root=ROOT,
    )
    files = export_bundle(db, n)
    assert sorted(k.split("-", 2)[2] for k in files) == [
        "audit.json",
        "evidence-pack.pdf",
        "note-to-file.md",
        "reports.csv",
    ]
    csv_text = next(v for k, v in files.items() if k.endswith(".csv")).decode()
    assert "# Build: MaudeSignal 0.1.0 · commit" in csv_text
    assert "# Data as of: 2026-09-30" in csv_text
    assert f"# Company complaint / CAPA number: {BLANK_FIELD}" in csv_text
    audit = json.loads(next(v for k, v in files.items() if k.endswith("audit.json")))
    assert audit["chain_ok"] is True and audit["company_complaint_or_capa_number"] == ""
    assert audit["build"]["version"] == "0.1.0"
    # The exported chain re-verifies from its own fields.
    prev = "GENESIS"
    from datetime import datetime

    for e in audit["entries"]:
        h = Database.audit_entry_hash(
            prev,
            datetime.fromisoformat(e["ts"]),
            e["actor"],
            e["action"],
            e["entity_id"],
            e["payload_json"],
        )
        assert e["prev_hash"] == prev and e["entry_hash"] == h
        prev = h


# ---------------------------------------------------------------- sweep date, one source of truth


def test_sweep_date_is_one_source_of_truth() -> None:
    stored = json.loads((ROOT / "demo" / "sweep" / "ai-device-sweep.json").read_text("utf-8"))
    web = json.loads((ROOT / "web" / "public" / "data" / "sweep.json").read_text("utf-8"))
    doc = (ROOT / "docs" / "hackathon" / "AI_SWEEP.md").read_text("utf-8")
    sub = (ROOT / "docs" / "hackathon" / "SUBMISSION_DRAFT.md").read_text("utf-8")
    gen = stored["meta"]["generated_utc"]
    assert web["meta"]["generated_utc"] == gen
    assert web["meta"]["window"] == stored["meta"]["window"]
    assert f"at {gen}" in doc
    run = str(stored["meta"].get("run_id"))
    assert run in doc and run in sub and gen[:10] in sub
    assert "40836844281" not in sub  # the Oct 29 run the docs used to cite


def test_validation_page_gate_count_matches_the_fixture() -> None:
    rows = [
        json.loads(line)
        for line in (ROOT / "tests/fixtures/gate/adversarial.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    block = sum(1 for r in rows if r["expect"] == "block")
    page = (ROOT / "web/src/pms/ValidationPage.tsx").read_text("utf-8")
    assert f"{len(rows)} cases ({block} must be withheld, {len(rows) - block} must pass)" in page


@pytest.mark.parametrize("as_of", ["20260824", "20260831"])
def test_committed_digests_equal_a_fresh_run_on_the_demo_db(tmp_path: Path, as_of: str) -> None:
    """digests/ were regenerated, not hand-edited: same bytes as a no-fetch run."""
    import shutil

    from typer.testing import CliRunner

    from maudesignal.cli import app

    db = tmp_path / "demo.db"
    shutil.copy(ROOT / "data" / "demo" / "maudesignal_demo.db", db)
    out = tmp_path / "out"
    res = CliRunner().invoke(
        app, ["monitor", "--db", str(db), "--as-of", as_of, "--no-fetch", "--out-dir", str(out)]
    )
    assert res.exit_code == 0, res.output
    day = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"
    for ext in ("md", "json"):
        assert (out / f"{day}.{ext}").read_text("utf-8") == (
            ROOT / "digests" / f"{day}.{ext}"
        ).read_text("utf-8")
