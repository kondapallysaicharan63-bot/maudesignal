"""Dashboard pages for the hackathon features: What changed, Copilot, Actions & Audit.

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
from collections.abc import Iterator
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
from maudesignal.monitor.digest import (
    CHANGE_LABELS,
    RANKING_ORDER,
    digest_from_database,
    render_markdown,
)
from maudesignal.monitor.sources import not_by_manufacturer, source_counts, sourced_reports
from maudesignal.sources.openfda_sources import k510_url
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPT_DIR = Path(
    os.environ.get("MAUDESIGNAL_TRANSCRIPT_DIR", str(PROJECT_ROOT / "demo" / "transcripts"))
)
MAUDE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"

FRAMING_BANNER = (
    '<div class="ms-frame">'
    "<b>B2B regulatory triage aid for QA/RA teams.</b> Not medical advice. "
    "It only shows facts it can match to the FDA record: every number, quote, device id "
    "and CFR section is checked against stored openFDA records first. "
    "Every action is a draft that a named human approves. "
    "Nothing is filed with FDA automatically.</div>"
)

_PILL = {"pass": ("ok", "Verified"), "block": ("err", "Withheld")}


def _pill(status: str) -> str:
    cls, label = _PILL[status]
    return f'<span class="ms-pill {cls}">{label}</span>'


def _sentence_html(s: dict[str, Any]) -> str:
    text = html.escape(s["text"])
    if s["status"] == "pass":
        body = text
    else:
        body = f'<span class="ms-strike">{text}</span>'
        reasons = "".join(f"<li>{html.escape(r)}</li>" for r in s.get("reasons", []))
        body += f'<ul class="ms-err-text" style="margin:4px 0 0 18px;font-size:13px">{reasons}</ul>'
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
# What changed
# ---------------------------------------------------------------------------


def _hero_html(digest: Any) -> str:
    """The page's one ink tile (design-system HeroSignal): the top-ranked change and why."""
    top = digest.ranked[0]
    device = digest.device_types.get(top.product_code)
    label = CHANGE_LABELS[top.classification]
    brands = digest.window_brands.get(top.product_code, [])
    reason = digest.rank_reasons[top.product_code].replace(">=", "≥")
    fig = (
        f"{top.spike_ratio:.2f}×"
        if top.classification == "spike" and top.spike_ratio is not None
        else str(top.current_count)
    )
    named = (
        "Devices named on this week's reports: "
        + ", ".join(f"{html.escape(b)} ({n} of {top.current_count} reports)" for b, n in brands)
        + "."
        if brands
        else ""
    )
    return (
        '<article class="ms-tile ms-hero" style="margin-bottom:var(--space-2)">'
        '<svg class="ms-hero__rings" viewBox="0 0 300 300" aria-hidden="true">'
        '<circle cx="150" cy="150" r="40"/><circle cx="150" cy="150" r="70"/>'
        '<circle cx="150" cy="150" r="100"/><circle cx="150" cy="150" r="130"/></svg>'
        '<div class="ms-kicker"><span class="ms-i" aria-hidden="true">trending_up</span>'
        f"Top signal: {top.product_code}"
        + (f" · {html.escape(device)}" if device else "")
        + "</div>"
        f'<h2 class="ms-hero__title">{html.escape(label[:1].upper() + label[1:])}</h2>'
        f'<p class="ms-hero__deck"><b>Why it is ranked first.</b> {html.escape(reason)}</p>'
        '<div class="ms-hero__foot">'
        f'<div class="ms-hero__fig ms-num">{fig}<small>'
        f"{top.current_count} reports this week · weekly mean "
        f"{top.baseline_weekly_mean:.2f} before</small></div></div>"
        f'<p class="ms-hero__deck" style="margin:var(--space-4) 0 0;font-size:13px">{named} '
        f"Ranking order: {html.escape('; then '.join(RANKING_ORDER))}. "
        "Deterministic — no model involved. Flagged for a person to review; it does not "
        "decide whether a report or a CAPA is required.</p>"
        "</article>"
    )


def page_changes(db: Database) -> None:
    """What changed this week: the deterministic digest (no model)."""
    st.html(FRAMING_BANNER)
    result = detect_from_database(db)
    digest = digest_from_database(db, result)
    if digest.ranked:
        st.html(_hero_html(digest))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reports suddenly increased", digest.increased_count)
    c2.metric("More serious than usual", digest.serious_count)
    c3.metric("New kind of problem", digest.new_count)
    c4.metric("No change", digest.stable_count)
    w = result.window
    st.caption(
        f"As of {w.as_of.isoformat()} (latest openFDA date_received in this database). "
        f"This week: {w.current_start} → {w.current_end}; baseline: "
        f"{w.baseline_start} → {w.baseline_end}."
    )
    _compare_section(db)
    _mhra_section(db)
    st.markdown(render_markdown(digest))
    _who_filed(db, digest)
    digests = sorted((PROJECT_ROOT / "digests").glob("*.md"))
    if digests:
        with st.expander(f"Archived digests ({len(digests)})"):
            for p in reversed(digests):
                st.markdown(f"**{p.stem}**")
                st.code(p.read_text(encoding="utf-8")[:4000], language="markdown")


def _compare_section(db: Database) -> None:
    """Signal compare for the device types the user chooses, and the remembered list."""
    from maudesignal.copilot.memory import CopilotMemoryError, load_memory, set_device_types
    from maudesignal.monitor.compare import compare_signals

    codes = sorted({e.product_code for e in db.list_normalized_events() if e.product_code})
    mem = load_memory(db)
    st.subheader("Compare the device types you choose")
    st.caption(
        "You pick the product codes; MaudeSignal does not decide which devices are similar. "
        "Same 7-day window and rules as above. Deterministic — no model involved."
    )
    default = [c for c in mem.device_types if c in codes] or codes
    chosen = st.multiselect("Device types (FDA product codes)", codes, default=default, key="cmp")
    if chosen:
        cmp = compare_signals(db, chosen)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "device type": r.product_code,
                        "change": r.change,
                        "this week": r.this_week,
                        "weekly mean before": r.baseline_weekly_mean,
                        "ratio": r.ratio_to_baseline,
                        "injury/death this week": r.injury_death_this_week,
                        "not filed by a manufacturer": r.not_by_manufacturer_this_week,
                        "stored, all dates": r.stored_total,
                    }
                    for r in cmp.rows
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander(
        "Remember these device types"
        + (f" (remembered: {', '.join(mem.device_types)})" if mem.device_types else "")
    ):
        st.caption(
            "Saved as an entry in the tamper-evident audit trail with your name. The copilot "
            "can read this list (tool `my_device_types`) but cannot change it."
        )
        who = st.text_input("Your name", key="mem_actor")
        if st.button("Remember this list", key="mem_save"):
            try:
                set_device_types(db, chosen, actor=who)
                st.success(f"Remembered: {', '.join(sorted(chosen)) or 'none'}.")
            except CopilotMemoryError as exc:
                st.error(str(exc))


def _mhra_section(db: Database) -> None:
    """MHRA (UK) device safety alerts: regulator context, clearly separate from FDA data."""
    from maudesignal.sources.mhra import SOURCE_MHRA

    rows = db.list_external_sources(source_type=SOURCE_MHRA, limit=200)
    with st.expander(f"UK regulator context: MHRA device safety alerts ({len(rows)} stored)"):
        st.caption(
            "From the MHRA (UK) via the public GOV.UK search API, searched with terms a person "
            "chose for each device type (`data/demo/mhra_queries.json`). Context only: not FDA "
            "data, not counted in any number on this page."
        )
        if not rows:
            st.caption("None stored yet (`scripts/fetch_mhra_alerts.py`).")
            return
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "searched for (FDA product code)": r.product_code or "",
                        "issued": r.publication_date or "",
                        "MHRA alert": r.title or "",
                        "link": r.url or "",
                    }
                    for r in sorted(rows, key=lambda r: r.publication_date or "", reverse=True)
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={"link": st.column_config.LinkColumn("link")},
        )


CAPA_NEED_NOTE = (
    "Whether a CAPA is required is decided by the company's own CAPA-need form. "
    "This document is evidence only."
)

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
        width="stretch",
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
            width="stretch",
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
        '<div style="font-size:14px;margin:0 0 4px 0">'
        f"🎙 <b>Heard:</b> “{html.escape(str(voice.get('transcript_text', '')))}”"
        f' <span class="ms-muted" style="font-size:12px">({html.escape(" · ".join(facts))})</span>'
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
            f'<div class="ms-ok-text" style="font-size:13px">{html.escape(cv.reason)}</div>'
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
        # Typed questions first (the demo's story order); spoken clips after them.
        transcripts = sorted(
            load_transcripts(TRANSCRIPT_DIR),
            key=lambda t: (str(t.get("label", "")).startswith("00-voice"), str(t.get("label", ""))),
        )
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
            with st.status("Muse Spark is working…", expanded=True) as status:
                res = st.session_state["copilot_agent"].ask(
                    q, on_event=lambda kind, data: status.write(progress_line(kind, data))
                )
                status.update(label="Checked by the citation gate", state="complete")
            st.write_stream(stream_verified(result_to_dict(res)))
            st.session_state["copilot_log"].append(result_to_dict(res))
        except SpendLimitError as exc:
            _fallback(q, str(exc))
    for t in reversed(st.session_state["copilot_log"]):
        with st.container(border=True):
            _render_transcript(t)


def progress_line(kind: str, data: dict[str, Any]) -> str:
    """One line of live progress for the Ask tab (what the agent is doing right now)."""
    if kind == "model":
        return f"Muse Spark, step {data.get('round')}…"
    if kind == "tool":
        return f"Looking up stored records: `{data.get('name')}`"
    if kind == "gate":
        return (
            f"Citation gate ({data.get('stage')}): {data.get('passed', 0)} sentence(s) "
            f"matched the FDA record, {data.get('blocked', 0)} withheld"
        )
    if kind == "repair":
        return "Asking Muse Spark to correct the withheld sentences (one repair turn)…"
    if kind == "done":
        return "Done."
    return kind


def stream_verified(t: dict[str, Any]) -> Iterator[str]:
    """Yield only gate-verified sentences, word by word (nothing unverified is streamed)."""
    import time

    shown = [s["text"] for s in t.get("final", {}).get("sentences", []) if s["status"] == "pass"]
    if not shown:
        yield "Nothing could be matched to the FDA record, so nothing is shown."
        return
    for sentence in shown:
        for word in sentence.split(" "):
            yield word + " "
            time.sleep(0.015)
        yield "\n\n"


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
    """CAPA-need evidence packs awaiting a named person's decision, and the audit trail."""
    st.html(FRAMING_BANNER)
    drafts = db.list_capa_drafts()
    st.subheader(
        f"CAPA-need evidence pack ({sum(1 for d in drafts if d.status == 'draft')} awaiting review)"
    )
    st.caption(CAPA_NEED_NOTE)
    if not drafts:
        st.caption("None yet. Ask the copilot to prepare the CAPA-need evidence pack for a signal.")
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
            st.caption(f"Prepared by {d.created_by} at {d.created_at:%Y-%m-%d %H:%M} UTC")
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
            width="stretch",
        )


def _recorded_audit_trails() -> None:
    """Show the audit trails saved by the live recording runs (stored-first demo)."""
    exports = load_exports(TRANSCRIPT_DIR)
    if not exports:
        st.caption("No audit entries yet. Ask the copilot something to start the trail.")
        return
    st.caption(
        "This public demo database has no live actions, so these are the trails written "
        "during the recorded Meta runs (voice transcription, copilot answers, "
        "CAPA-need evidence packs). "
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
                width="stretch",
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
