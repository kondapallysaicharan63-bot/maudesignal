"""Dashboard page: Signal Evaluation & CAPA dossier (PDF) + independent AI reviewer.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stored-first like the other hackathon pages: with no ``META_MODEL_API_KEY`` the
page renders the deterministic dossier, a recorded Muse Spark narrative if one
exists, and recorded Muse Wonder reviewer findings. With a key it can draft the
narrative live and run the reviewer live. Approve / Reject stays on the
Actions page; regenerating here after approval shows the signature block.

Wire-up (in ``dashboard/app.py``)::

    from maudesignal.dashboard.dossier_pages import page_dossier
    page_dossier(db)
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from maudesignal.copilot.spend import SpendLimitError
from maudesignal.dashboard.copilot_pages import CAPA_NEED_NOTE, FRAMING_BANNER
from maudesignal.dashboard.spend_ui import guarded_client
from maudesignal.dossier.builder import DossierError, top_flagged_signal
from maudesignal.dossier.render import pdf_page_png
from maudesignal.dossier.review import (
    WONDER_MODEL,
    ReviewError,
    ReviewResult,
    load_review,
    record_review,
    review_dossier,
)
from maudesignal.dossier.service import DossierOutput, produce, recorded_dir
from maudesignal.monitor.digest import CHANGE_LABELS
from maudesignal.storage.database import Database


def _client(db: Database) -> Any | None:
    """Spend-capped Meta client when a key is present (the key is never displayed or logged)."""
    if not os.environ.get("META_MODEL_API_KEY"):
        return None
    return guarded_client(db)


def _subject_options(db: Database) -> list[tuple[str, str | None, str | None]]:
    """(label, capa_id, product_code) choices: every CAPA-need evidence pack, then top signal."""
    opts: list[tuple[str, str | None, str | None]] = [
        (f"{c.capa_id} · {c.product_code} · {c.status} · {c.title[:60]}", c.capa_id, None)
        for c in db.list_capa_drafts()
    ]
    try:
        top = top_flagged_signal(db)
    except ValueError:
        top = None
    if top is not None:
        opts.append(
            (
                f"Top flagged change · {top.product_code} · "
                f"{CHANGE_LABELS[top.classification]} (no CAPA)",
                None,
                top.product_code,
            )
        )
    return opts


def _findings_frame(r: ReviewResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "severity": f.severity,
                "section": f.section,
                "issue": f.issue_type,
                "statement": f.statement,
                "explanation": f.explanation,
                "evidence ids": ", ".join(f.evidence_ids),
                "id check": f.evidence_check,
            }
            for f in r.findings
        ]
    )


def _show_review(r: ReviewResult, *, source: str) -> None:
    st.caption(
        f"{source} · {r.model} (skill dossier-reviewer v{r.skill_version}) · input as {r.mode} · "
        f"{r.input_tokens:,} in / {r.output_tokens:,} out tokens · est. ${r.cost_usd:.4f} · "
        f"{r.created_at}"
    )
    if r.parse_error:
        st.warning(f"Reviewer output could not be parsed: {r.parse_error}")
    elif not r.findings:
        st.success("The reviewer reported no findings.")
    else:
        st.dataframe(_findings_frame(r), hide_index=True, width="stretch")
    st.caption(
        "Findings are advisory. They are stored in the audit trail and never edit the dossier."
    )


def page_dossier(db: Database) -> None:
    """Signal Evaluation & CAPA dossier page."""
    st.html(FRAMING_BANNER)
    st.subheader("Signal Evaluation & CAPA-need Evidence")
    st.caption(CAPA_NEED_NOTE)
    st.caption(
        "A controlled-record style PDF: document control, approval block (modeled on 21 CFR "
        "11.50), signal numbers re-verified by the gate, evidence table, CAPA record mapped to "
        "ISO 13485 §8.5.2, Form 3500A worksheet (not for submission), audit-trail appendix."
    )
    opts = _subject_options(db)
    if not opts:
        st.info("No CAPA-need evidence packs and no flagged change in this database.")
        return
    labels = [o[0] for o in opts]
    choice = st.selectbox("Document", labels, key="dossier_subject")
    _, capa_id, product_code = opts[labels.index(choice)]
    c1, c2 = st.columns([1, 2])
    use_aw = c1.checkbox("Set awareness date", value=True, key="dossier_aw_on")
    aw: date | None = None
    if use_aw:
        aw = c2.date_input(
            "Awareness date (MDR clock start — human input)",
            value=datetime.now(UTC).date(),
            key="dossier_aw",
        )
    client = _client(db)
    live_narr = False
    if client is not None:
        live_narr = st.checkbox(
            "Draft the narrative live with Muse Spark (≈ $0.01)", key="dossier_live_narr"
        )

    def build(live: Any | None) -> DossierOutput:
        with st.spinner("Building dossier…"):
            return produce(
                db,
                capa_id=capa_id,
                product_code=product_code,
                awareness_date=aw,
                awareness_basis="entered on the dossier page",
                live_client=live,
            )

    try:
        try:
            out = build(client if live_narr else None)
        except SpendLimitError as exc:
            st.warning(f"{exc} No Meta call was made; the narrative is left out.")
            out = build(None)
    except (DossierError, RuntimeError) as exc:
        st.error(f"Could not build the dossier: {exc}")
        return

    d = out.build.data
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Document", d.doc_id)
    m2.metric("Status", d.status)
    m3.metric("Figures re-verified", f"{d.figures_checked - d.figures_failed}/{d.figures_checked}")
    m4.metric("Audit chain", "intact" if d.audit_chain_ok else "BROKEN")
    st.download_button(
        "Download PDF",
        data=out.pdf,
        file_name=f"{d.doc_id}-{d.status}.pdf",
        mime="application/pdf",
        key="dossier_dl",
    )
    if d.narrative.available:
        st.caption(
            f"Narrative: {d.narrative.source} {d.narrative.model} · shown {d.narrative.passed} · "
            f"withheld {d.narrative.withheld}"
        )
    else:
        st.caption(d.narrative.note)

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Preview — page 1**")
        png = pdf_page_png(out.pdf, 1)
        if png is not None:
            st.image(png, width="stretch")
        else:
            b64 = base64.b64encode(out.html.encode("utf-8")).decode("ascii")
            st.html(
                f'<iframe src="data:text/html;base64,{b64}" style="width:100%;height:900px;'
                'border:1px solid var(--rule)"></iframe>'
            )
    with right:
        st.markdown("**Independent reviewer — Muse Wonder 1.0**")
        recorded = load_review(recorded_dir() / f"{d.doc_id}-review.json", out.build.store)
        if client is not None and st.button("Run reviewer live (Standard tier)", key="dossier_rev"):
            try:
                with st.spinner("Muse Wonder is reviewing the dossier…"):
                    r = review_dossier(
                        client,
                        doc_id=d.doc_id,
                        html=out.html,
                        pdf=out.pdf,
                        evidence=out.cited_records(),
                        store=out.build.store,
                        model=os.environ.get("META_REVIEWER_MODEL", WONDER_MODEL),
                    )
                record_review(db, r)
                st.session_state["dossier_review"] = r
            except SpendLimitError as exc:
                st.warning(f"{exc} No Meta call was made; the recorded review (if any) is shown.")
            except (ReviewError, RuntimeError) as exc:
                st.error(str(exc))
        live = st.session_state.get("dossier_review")
        if isinstance(live, ReviewResult) and live.doc_id == d.doc_id:
            _show_review(live, source="Live run")
        elif recorded is not None:
            _show_review(recorded, source="Recorded run")
        else:
            st.info(
                "No reviewer run recorded for this document. With META_MODEL_API_KEY set, run "
                "the reviewer live; findings are stored in the audit trail."
            )
    st.caption(
        "Accept or reject the CAPA-need evidence pack on the Actions & Audit page, then return "
        "here: the regenerated PDF carries the reviewer's printed name, UTC time and meaning. "
        "The MDR worksheet keeps its NOT FOR SUBMISSION stamp."
    )
