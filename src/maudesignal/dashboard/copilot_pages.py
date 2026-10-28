"""Dashboard pages for the hackathon features: Overnight, Copilot, Actions & Audit.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stored-first: the public deployment has no API key. The Copilot page replays
transcripts recorded from real Muse Spark runs (``demo/transcripts``) and runs
the citation gate live — the gate is deterministic and needs no model. If
``META_MODEL_API_KEY`` is present (local use), the page also offers live
questions, typed or spoken (spoken → Meta Voice Transcribe → text → copilot).
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from maudesignal.copilot.actions import ActionError, decide_capa
from maudesignal.copilot.audit_export import load_exports
from maudesignal.copilot.spend import SpendLimitError
from maudesignal.copilot.transcript import load_transcripts
from maudesignal.dashboard.spend_ui import cap_notice, guarded_client, recorded_fallback
from maudesignal.dashboard.spend_ui import guard as spend_guard
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
from maudesignal.monitor.digest import RANKING_ORDER, digest_from_database, render_markdown
from maudesignal.monitor.sources import not_by_manufacturer, source_counts, sourced_reports
from maudesignal.sources.openfda_sources import k510_url
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
    return ", ".join(_evidence_link(i) for i in list(dict.fromkeys(ids))[:5])


def _evidence_link(eid: str) -> str:
    """Markdown link for one evidence id: MAUDE report, PubMed, 510(k), or plain text."""
    if eid.startswith("PMID "):
        return f"[{eid}](https://pubmed.ncbi.nlm.nih.gov/{eid[5:]}/)"
    if re.fullmatch(r"K\d{6}", eid):
        return f"[{eid}]({k510_url(eid)})"
    if re.fullmatch(r"\d{7}-\d{4}-\d{5}|\d{6,10}", eid):
        return f"[{eid}]({MAUDE_URL.format(eid.split('-')[0])})"
    return eid  # recall numbers and other ids: shown, not linked


# ---------------------------------------------------------------------------
# Overnight
# ---------------------------------------------------------------------------


def page_overnight(db: Database) -> None:
    """Overnight deterioration digest (deterministic, no model)."""
    st.html(FRAMING_BANNER)
    result = detect_from_database(db)
    digest = digest_from_database(db, result)
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
    if digest.ranked:
        top = digest.ranked[0]
        device = digest.device_types.get(top.product_code)
        brands = digest.window_brands.get(top.product_code, [])
        with st.container(border=True):
            st.markdown(
                f"**Top signal: {top.product_code}**"
                + (f" · {html.escape(device)}" if device else "")
            )
            st.markdown(f"**Why it is ranked first.** {digest.rank_reasons[top.product_code]}")
            if brands:
                st.caption(
                    "Devices named on this week's reports: "
                    + ", ".join(f"{b} ({n} of {top.current_count} reports)" for b, n in brands)
                    + "."
                )
            st.caption(
                "Ranking order: "
                + "; then ".join(RANKING_ORDER)
                + ". Deterministic — no model involved."
            )
    st.markdown(render_markdown(digest))
    _who_filed(db, digest)
    digests = sorted((PROJECT_ROOT / "digests").glob("*.md"))
    if digests:
        with st.expander(f"Archived digests ({len(digests)})"):
            for p in reversed(digests):
                st.markdown(f"**{p.stem}**")
                st.code(p.read_text(encoding="utf-8")[:4000], language="markdown")


SOURCE_FILTERS = {
    "Not filed by a manufacturer": None,
    "Manufacturer": "manufacturer",
    "User facility (e.g. hospital)": "user facility",
    "Voluntary": "voluntary",
    "Distributor": "distributor",
}


def _who_filed(db: Database, digest: Any) -> None:
    """F12: report sources per device type, and a filterable list of the reports."""
    reports = sourced_reports(db)
    if not reports:
        return
    w = digest.result.window
    week = source_counts(reports, date_from=_ymd(w.current_start), date_to=_ymd(w.current_end))
    stored = source_counts(reports)
    st.subheader("Who filed the reports")
    st.caption(
        "openFDA report source. A manufacturer already knows the complaints it files itself; "
        "reports filed by a user facility (such as a hospital), a voluntary reporter or a "
        "distributor are the ones it may not have seen. Counted from the stored records."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "device type (product code)": pc,
                    "FDA device type": digest.device_types.get(pc, ""),
                    "this week": ", ".join(f"{k} {v}" for k, v in week.get(pc, {}).items()) or "0",
                    "all stored": ", ".join(f"{k} {v}" for k, v in counts.items()),
                }
                for pc, counts in stored.items()
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    c1, c2 = st.columns(2)
    choice = c1.selectbox("Show reports filed by", list(SOURCE_FILTERS), key="src_filter")
    codes = c2.multiselect("Device types", sorted(stored), default=sorted(stored), key="src_codes")
    wanted = SOURCE_FILTERS[choice]
    rows = (
        not_by_manufacturer(reports)
        if wanted is None
        else [r for r in reports if r.source == wanted]
    )
    rows = [r for r in rows if r.product_code in codes]
    st.markdown(f"**{choice}: {len(rows)} stored report(s)** (all stored dates, newest first)")
    if rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "report": MAUDE_URL.format(r.report_id.split("-")[0]),
                        "report id": r.report_id,
                        "date received": r.date_received or "",
                        "source": r.source,
                        "device type": r.product_code,
                        "device named": r.brand_name or "",
                    }
                    for r in rows
                ]
            ),
            column_config={
                "report": st.column_config.LinkColumn("FDA record", display_text="open")
            },
            hide_index=True,
            use_container_width=True,
        )


def _ymd(d: Any) -> str:
    return str(d.isoformat()).replace("-", "")


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def _voice_html(voice: dict[str, Any]) -> str:
    """Render the "Heard: …" line so the analyst sees exactly what the ASR produced."""
    facts = []
    if voice.get("audio_seconds") is not None:
        facts.append(f"{float(voice['audio_seconds']):.1f} s")
    if voice.get("language"):
        facts.append(str(voice["language"]))
    facts.append("Meta Voice Transcribe")
    return (
        '<div style="font-size:14px;color:#1c2b33;margin:0 0 4px 0">'
        f"🎙 <b>Heard:</b> “{html.escape(str(voice.get('transcript_text', '')))}”"
        f' <span style="color:#65676b;font-size:12px">({html.escape(" · ".join(facts))})</span>'
        "</div>"
    )


def _render_transcript(t: dict[str, Any]) -> None:
    if t.get("fallback_for"):
        st.caption(
            f"You asked: “{t['fallback_for']}”. Live quota reached, so this is the closest "
            f"recorded Muse Spark answer (recorded {t.get('recorded_at_utc', '')}), not a new call."
        )
    if isinstance(t.get("voice"), dict):
        st.html(_voice_html(t["voice"]))
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
    from maudesignal.copilot.tools import ToolContext
    from maudesignal.copilot.transcript import result_to_dict

    if "copilot_agent" not in st.session_state:
        ctx = ToolContext(db=db, store=store_from_database(db))
        model = os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3")
        # Every chat call the agent makes passes the per-session and daily caps.
        st.session_state["copilot_agent"] = CopilotAgent(guarded_client(db), ctx, model=model)
        st.session_state["copilot_log"] = []
    _voice_question(db, st.session_state["copilot_agent"])
    q = st.chat_input("Ask about stored signals…")
    if q:
        try:
            spend_guard(db).check("copilot")
            with st.spinner("Muse Spark is working…"):
                res = st.session_state["copilot_agent"].ask(q)
            st.session_state["copilot_log"].append(result_to_dict(res))
        except SpendLimitError as exc:
            _fallback(q, str(exc))
    for t in reversed(st.session_state["copilot_log"]):
        with st.container(border=True):
            _render_transcript(t)


def _fallback(question: str, message: str) -> None:
    """Cap reached: show the closest recorded answer; no Meta call is made."""
    cap_notice(message)
    t = recorded_fallback(question, load_transcripts(TRANSCRIPT_DIR))
    if t is None:
        st.info("No recorded answers are available yet.")
        return
    st.session_state["copilot_log"].append(t)


def _voice_question(db: Database, agent: Any) -> None:  # pragma: no cover - needs a live key
    """Record a spoken question → Meta Voice Transcribe → the same gated copilot."""
    import hashlib

    from maudesignal.copilot.transcript import result_to_dict
    from maudesignal.copilot.voice import (
        DEFAULT_VOICE_MODEL,
        MetaTranscriber,
        Transcript,
        VoiceTranscribeError,
        ask_by_voice,
    )

    clip = st.audio_input(
        "🎙 Or ask by voice (transcribed by Meta Voice Transcribe, then answered as text)",
        sample_rate=16000,
        key="copilot_voice",
    )
    if clip is None:
        return
    data = clip.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("copilot_voice_done") == digest:
        return  # Streamlit reruns keep the widget value; ask each recording once.
    st.session_state["copilot_voice_done"] = digest
    g = spend_guard(db)
    model = os.environ.get("META_VOICE_MODEL", DEFAULT_VOICE_MODEL)
    heard: list[Transcript] = []

    def count_voice(t: Transcript) -> None:
        heard.append(t)
        g.record(kind="voice", model=model, cost_usd=t.cost_usd)

    try:
        g.check("voice")
        with (
            MetaTranscriber(
                os.environ["META_MODEL_API_KEY"],
                base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
                model=model,
            ) as transcriber,
            st.spinner("Transcribing, then Muse Spark is working…"),
        ):
            ans = ask_by_voice(
                transcriber, agent, data, filename="question.wav", on_transcribed=count_voice
            )
    except VoiceTranscribeError as exc:
        st.error(f"Voice question not asked: {exc}")
        return
    except SpendLimitError as exc:
        _fallback(heard[0].text if heard else "voice question", str(exc))
        return
    st.session_state["copilot_log"].append(
        result_to_dict(ans.result, voice=ans.transcript.to_voice_block())
    )


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
    if not rows:
        _recorded_audit_trails()
        return
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


def _recorded_audit_trails() -> None:
    """Show the audit trails saved by the live recording runs (stored-first demo)."""
    exports = load_exports(TRANSCRIPT_DIR)
    if not exports:
        st.caption("No audit entries yet. Ask the copilot something to start the trail.")
        return
    st.caption(
        "This public demo database has no live actions, so these are the trails written "
        "during the recorded Meta runs (voice transcription, copilot answers, CAPA drafts). "
        "Every hash is recomputed here from the stored fields."
    )
    for doc in exports:
        entries = doc.get("entries", [])
        ok, bad = doc["verified"]
        label = f"Recorded run `{doc.get('run_label', doc['file'])}` · {len(entries)} entries"
        if ok:
            st.success(f"{label} · hash chain intact.")
        else:
            st.error(f"{label} · hash chain broken at entry {bad}.")
        if entries:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "seq": e["seq"],
                            "time (UTC)": e["ts"],
                            "actor": e["actor"],
                            "action": e["action"],
                            "entity": e["entity_id"],
                            "detail": _audit_detail(e),
                            "hash": e["entry_hash"][:12],
                        }
                        for e in entries
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )


def _audit_detail(entry: dict[str, Any]) -> str:
    """One readable line per entry: what was heard, asked or drafted."""
    try:
        payload = json.loads(entry.get("payload_json") or "{}")
    except ValueError:
        return ""
    if entry.get("action", "").startswith("voice."):
        return f"heard: {payload.get('transcript_text', '')!r} ({payload.get('audio_seconds')} s)"
    if entry.get("action") == "copilot.answer":
        g = payload.get("gate_final", {})
        return (
            f"asked: {payload.get('question', '')[:80]!r} · gate "
            f"{g.get('passed', 0)}/{g.get('passed', 0) + g.get('blocked', 0)} passed"
        )
    return str(payload.get("title") or "")
