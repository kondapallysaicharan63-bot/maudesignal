"""Streamlit PMS board + note to file (PRD-19/20), over ``maudesignal.pms``.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

Rows are the product codes the deterministic monitor flags in the stored data. A status
changes only by a named person and is written to the database's hash-chained audit trail
(the keyless demo writes to a temporary copy, never the committed demo database). This is
not a QMS; nothing is filed with FDA.
"""

from __future__ import annotations

import streamlit as st

from maudesignal.monitor import detect_from_database
from maudesignal.monitor.digest import rule_evidence
from maudesignal.pms.asof import as_of_text, stored_as_of
from maudesignal.pms.board import (
    BOARD_LABEL,
    STATUS_LABELS,
    TRANSITIONS,
    BoardError,
    board_state,
    change_status,
)
from maudesignal.pms.checklists import EvidencePack
from maudesignal.pms.note_to_file import (
    DECISIONS,
    NOTE_LABEL,
    NoteToFileError,
    export_bundle,
    record_note_to_file,
)
from maudesignal.storage.database import Database


def page_board(db: Database) -> None:
    """PMS board: flagged code, why flagged, status, owner, advisory due date, audit link."""
    st.warning(f"{BOARD_LABEL} Nothing is filed with FDA.")
    st.info(as_of_text(stored_as_of(db)))
    result = detect_from_database(db)
    flagged = {s.product_code: rule_evidence(s) for s in result.signals if not s.is_stable}
    rows = board_state(db, flagged)
    ok, bad = db.verify_audit_chain()
    st.caption(
        "Audit chain verified." if ok else f"Audit chain broken at entry #{bad}: an entry changed."
    )
    if not rows:
        st.info("No product code is flagged in the stored data.")
        return
    st.dataframe(
        [
            {
                "Flagged code": r.product_code,
                "Why flagged": r.why,
                "Status": STATUS_LABELS[r.status],
                "Owner": r.owner or "",
                "Due date (MDR clock, advisory)": f"{r.due} — {r.due_basis}" if r.due else "",
                "Audit": f"#{r.audit_seq}" if r.audit_seq else "",
            }
            for r in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
    code = st.selectbox("Row", [r.product_code for r in rows], key="board_code")
    row = next(r for r in rows if r.product_code == code)
    with st.form("board_change"):
        to = st.selectbox(
            "Move to", TRANSITIONS[row.status], format_func=lambda s: STATUS_LABELS[s]
        )
        actor = st.text_input("Your name")
        owner = st.text_input("Owner", value=row.owner or "")
        aware = st.text_input("Awareness date (YYYY-MM-DD, for the advisory MDR clock)")
        if st.form_submit_button("Record status change"):
            try:
                seq = change_status(
                    db,
                    product_code=code,
                    why=row.why,
                    current=row.status,
                    to=to,
                    actor=actor,
                    owner=owner or None,
                    awareness=aware or None,
                )
                st.success(f"Recorded as audit entry #{seq}.")
                st.rerun()
            except BoardError as exc:
                st.error(str(exc))
    st.subheader("Note to file")
    st.caption(NOTE_LABEL)
    with st.form("note_to_file"):
        decision = st.radio("Decision (yours)", list(DECISIONS), format_func=DECISIONS.__getitem__)
        rationale = st.text_area("Rationale (typed by you)")
        approver = st.text_input("Approver name")
        if st.form_submit_button("Record decision"):
            facts = list(db.list_event_facts(code))
            pack = EvidencePack(
                product_code=code,
                device_type=None,
                why=row.why,
                reports=[
                    {"report_id": rid, "date_received": d, "event_type": et}
                    for rid, _c, d, et in facts[-20:]
                ],
            )
            try:
                note = record_note_to_file(
                    db,
                    pack=pack,
                    as_of=stored_as_of(db, code),
                    decision=decision,
                    rationale=rationale,
                    approver=approver,
                )
                st.session_state["board_note"] = export_bundle(db, note)
                st.success(f"Recorded as audit entry #{note.audit_seq}.")
            except NoteToFileError as exc:
                st.error(str(exc))
    for name, data in st.session_state.get("board_note", {}).items():
        st.download_button(f"Download {name}", data, file_name=name, key=f"dl-{name}")
