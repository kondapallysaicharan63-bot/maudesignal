"""Dashboard pages for the hackathon features: Overnight, Copilot, Actions & Audit.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stored-first: the public deployment has no API key. The Copilot page replays
transcripts recorded from real Muse Spark runs (``demo/transcripts``) and runs
the citation gate live — the gate is deterministic and needs no model. If
``META_MODEL_API_KEY`` is present (local use), the page also offers live
questions.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from maudesignal.copilot.actions import ActionError, decide_capa
from maudesignal.copilot.transcript import load_transcripts
from maudesignal.gate import (
    CountClaim,
    DeviceClaim,
    QuoteClaim,
    RegulationClaim,
    ShareClaim,
    verify_sentence,
)
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import build_digest, render_markdown
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPT_DIR = Path(
    os.environ.get("MAUDESIGNAL_TRANSCRIPT_DIR", str(PROJECT_ROOT / "demo" / "transcripts"))
)
MAUDE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"

FRAMING_BANNER = (
    '<div style="border:1px solid #c9d3df;border-left:6px solid #1877F2;border-radius:8px;'
    'padding:10px 14px;margin:0 0 14px 0;background:#f5f8fc;font-size:14px;color:#1c2b33">'
    "<b>B2B regulatory triage aid for QA/RA teams.</b> Not medical advice. "
    "Every number, quote, device id and CFR section is re-checked against stored openFDA "
    "records before it is shown. Every action is a draft that a named human approves. "
    "Nothing is filed with FDA automatically.</div>"
)

_PILL = {
    "pass": ("#e7f6ec", "#1e7b3a", "VERIFIED"),
    "block": ("#fdecea", "#b3261e", "WITHHELD"),
}


def _pill(status: str) -> str:
    bg, fg, label = _PILL[status]
    return (
        f'<span style="background:{bg};color:{fg};font-weight:600;font-size:11px;'
        f'padding:2px 8px;border-radius:10px;margin-right:6px">{label}</span>'
    )


def _sentence_html(s: dict[str, Any]) -> str:
    text = html.escape(s["text"])
    if s["status"] == "pass":
        body = text
    else:
        body = f'<span style="text-decoration:line-through;color:#8a8d91">{text}</span>'
        reasons = "".join(f"<li>{html.escape(r)}</li>" for r in s.get("reasons", []))
        body += f'<ul style="margin:4px 0 0 18px;color:#b3261e;font-size:13px">{reasons}</ul>'
    return f'<div style="margin:6px 0">{_pill(s["status"])}{body}</div>'


def _evidence_links(s: dict[str, Any]) -> str:
    ids: list[str] = []
    for c in s.get("claims", []):
        ids += [i for i in c.get("evidence_ids", []) if i and not i.startswith("21 CFR")]
    links = [f"[{i}]({MAUDE_URL.format(i.split('-')[0])})" for i in dict.fromkeys(ids)][:5]
    return ", ".join(links)


# ---------------------------------------------------------------------------
# Overnight
# ---------------------------------------------------------------------------


def page_overnight(db: Database) -> None:
    """Overnight deterioration digest (deterministic, no model)."""
    st.html(FRAMING_BANNER)
    result = detect_from_database(db)
    digest = build_digest(result)
    c1, c2, c3 = st.columns(3)
    c1.metric("New signals", digest.new_count)
    c2.metric("Worsening", digest.worsening_count)
    c3.metric("Stable", digest.stable_count)
    w = result.window
    st.caption(
        f"As of {w.as_of.isoformat()} (latest openFDA date_received in this database). "
        f"This week: {w.current_start} → {w.current_end}; baseline: "
        f"{w.baseline_start} → {w.baseline_end}."
    )
    st.markdown(render_markdown(digest))
    digests = sorted((PROJECT_ROOT / "digests").glob("*.md"))
    if digests:
        with st.expander(f"Archived digests ({len(digests)})"):
            for p in reversed(digests):
                st.markdown(f"**{p.stem}**")
                st.code(p.read_text(encoding="utf-8")[:4000], language="markdown")


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def _render_transcript(t: dict[str, Any]) -> None:
    st.markdown(f"**Q:** {t['question']}")
    for s in t["final"]["sentences"]:
        st.html(_sentence_html(s))
        links = _evidence_links(s)
        if links and s["status"] == "pass":
            st.caption(f"Evidence: {links}")
    fp, fin = t["first_pass"], t["final"]
    u = t["usage"]
    meta = (
        f"Model `{t['model']}` · tools: {', '.join(c['name'] for c in t['tool_calls']) or 'none'}"
        f" · gate first pass {fp['passed']}/{fp['passed'] + fp['blocked']} sentences"
        f" → final {fin['passed']}/{fin['passed'] + fin['blocked']}"
        f"{' (after a repair turn)' if t['repaired'] else ''}"
        f" · {u['input_tokens'] + u['output_tokens']:,} tokens · ${u['cost_usd']:.4f}"
        f" · recorded {t['recorded_at_utc']}"
    )
    st.caption(meta)
    if t["repaired"]:
        with st.expander("What the gate blocked on the first pass"):
            for s in t["first_pass"]["sentences"]:
                st.html(_sentence_html(s))
    with st.expander("Tool calls"):
        for c in t["tool_calls"]:
            st.markdown(f"`{c['name']}` `{json.dumps(c['arguments'])}`")
            st.code(c["result_preview"], language="json")


def _gate_playground(db: Database) -> None:
    st.markdown(
        "Type a claim the way a model might state it. The gate recomputes it from the "
        "stored records — no model involved."
    )
    store = store_from_database(db)
    codes = sorted({r.product_code for r in store.records}) or ["LLZ"]
    kind = st.selectbox(
        "Claim type",
        ["Report count", "Share of event type", "Verbatim quote", "510(k) number", "CFR section"],
    )
    claim: Any
    sentence: str
    if kind == "Report count":
        pc = st.selectbox("Product code", codes)
        n = int(st.number_input("Claimed number of reports", min_value=0, value=50))
        claim, sentence = CountClaim(pc, n), f"{pc} has {n} reports."
    elif kind == "Share of event type":
        pc = st.selectbox("Product code", codes)
        et = st.selectbox("Event type", ["Malfunction", "Injury", "Death"])
        pct = float(st.number_input("Claimed %", min_value=0.0, max_value=100.0, value=40.0))
        claim, sentence = ShareClaim(pc, et, pct), f"{pct}% of {pc} reports are {et}."
    elif kind == "Verbatim quote":
        rid = st.selectbox("Attributed to report", [r.report_id for r in store.records[:200]])
        q = st.text_input("Quote", value="the device failed to alert the clinician")
        claim, sentence = QuoteClaim(q, rid), f'Report says "{q}".'
    elif kind == "510(k) number":
        k = st.text_input("510(k) number", value="K123456")
        pc = st.selectbox("Claimed product code", codes)
        claim, sentence = DeviceClaim(k, pc), f"{k} is a {pc} device."
    else:
        sec = st.text_input("21 CFR section", value="820.100")
        claim, sentence = RegulationClaim(sec), f"See 21 CFR {sec}."
    v = verify_sentence(sentence, [claim], store)
    cv = v.claim_verdicts[0]
    st.html(
        _sentence_html({"text": sentence, "status": v.status, "reasons": v.reasons})
        + (
            f'<div style="font-size:13px;color:#1e7b3a">{html.escape(cv.reason)}</div>'
            if v.status == "pass"
            else ""
        )
    )


def page_copilot(db: Database) -> None:
    """Copilot: replay of real Muse Spark runs + live gate playground (+ live mode if keyed)."""
    st.html(FRAMING_BANNER)
    tab_replay, tab_gate, tab_live = st.tabs(
        ["Recorded Muse Spark runs", "Try to fool the gate", "Ask live"]
    )
    with tab_replay:
        transcripts = load_transcripts(TRANSCRIPT_DIR)
        if not transcripts:
            st.info(
                "No recorded runs yet. They are produced by "
                "`scripts/record_demo_transcripts.py` with a Meta Model API key."
            )
        for t in transcripts:
            with st.container(border=True):
                _render_transcript(t)
    with tab_gate:
        _gate_playground(db)
    with tab_live:
        if not os.environ.get("META_MODEL_API_KEY"):
            st.info(
                "Live questions need a Meta Model API key, which the public demo does not "
                "hold (stored-first by design). Run locally with META_MODEL_API_KEY set."
            )
            return
        _live_copilot(db)


def _live_copilot(db: Database) -> None:  # pragma: no cover - needs a live key
    from maudesignal.copilot.agent import CopilotAgent
    from maudesignal.copilot.meta_provider import MetaProvider
    from maudesignal.copilot.tools import ToolContext
    from maudesignal.copilot.transcript import result_to_dict

    if "copilot_agent" not in st.session_state:
        provider = MetaProvider(
            api_key=os.environ["META_MODEL_API_KEY"],
            model=os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3"),
            base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
        )
        ctx = ToolContext(db=db, store=store_from_database(db))
        st.session_state["copilot_agent"] = CopilotAgent(provider.client, ctx, model=provider.model)
        st.session_state["copilot_log"] = []
    q = st.chat_input("Ask about stored signals…")
    if q:
        with st.spinner("Muse Spark is working…"):
            res = st.session_state["copilot_agent"].ask(q)
        st.session_state["copilot_log"].append(result_to_dict(res))
    for t in reversed(st.session_state["copilot_log"]):
        with st.container(border=True):
            _render_transcript(t)


# ---------------------------------------------------------------------------
# Actions & audit
# ---------------------------------------------------------------------------


def page_actions(db: Database) -> None:
    """CAPA drafts awaiting a named human decision, plus the tamper-evident audit trail."""
    st.html(FRAMING_BANNER)
    drafts = db.list_capa_drafts()
    st.subheader(f"CAPA drafts ({sum(1 for d in drafts if d.status == 'draft')} awaiting review)")
    if not drafts:
        st.caption("No drafts yet. Ask the copilot to draft a CAPA for a signal.")
    reviewer = st.text_input("Your name (recorded as the approver)", key="capa_reviewer")
    for d in drafts:
        with st.container(border=True):
            st.markdown(f"**{d.title}** · `{d.capa_id}` · {d.product_code} · status **{d.status}**")
            st.write(d.problem_statement)
            ids = json.loads(d.report_ids_json)
            st.caption(
                "Supporting reports: "
                + ", ".join(f"[{i}]({MAUDE_URL.format(i.split('-')[0])})" for i in ids)
            )
            st.caption(f"Drafted by {d.created_by} at {d.created_at:%Y-%m-%d %H:%M} UTC")
            if d.status == "draft":
                c1, c2, _ = st.columns([1, 1, 4])
                for col, decision, label in (
                    (c1, "approved", "Approve"),
                    (c2, "rejected", "Reject"),
                ):
                    if col.button(label, key=f"{decision}_{d.capa_id}"):
                        try:
                            decide_capa(db, capa_id=d.capa_id, decision=decision, reviewer=reviewer)
                            st.rerun()
                        except ActionError as exc:
                            st.error(str(exc))
            else:
                st.caption(f"{d.status} by {d.decided_by}: {d.decision_note or ''}")

    st.subheader("Audit trail")
    rows = db.list_audit()
    ok, bad = db.verify_audit_chain()
    if ok:
        st.success(f"Hash chain intact across {len(rows)} entries.")
    else:
        st.error(f"Hash chain broken at entry {bad} — the trail was edited.")
    if rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "seq": r.seq,
                        "time (UTC)": r.ts,
                        "actor": r.actor,
                        "action": r.action,
                        "entity": r.entity_id,
                        "hash": r.entry_hash[:12],
                    }
                    for r in rows
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
