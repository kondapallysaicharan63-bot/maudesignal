"""Dashboard pages for the hackathon features: Copilot and Audit (Signals: ``workspace``).

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
from maudesignal.copilot.product_code import confirm_prompt, describe_check
from maudesignal.copilot.protocol import protocol_from_transcript, tool_label
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
from maudesignal.sources.openfda_sources import k510_url
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPT_DIR = Path(
    os.environ.get("MAUDESIGNAL_TRANSCRIPT_DIR", str(PROJECT_ROOT / "demo" / "transcripts"))
)
MAUDE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"

#: One line under the top bar on every page (the long banner used to repeat on each page).
FRAMING_LINE = (
    "Triage aid for QA/RA teams · not medical advice · only shows facts it can match to "
    "the FDA record · a named person decides · nothing is filed with FDA"
)

_PILL = {"pass": ("ok", "Verified"), "block": ("err", "Withheld")}


#: Recorded runs never shown on screen or used as a fallback answer. Their audit chains are
#: still re-verified on the Audit page (see EXCLUDED_REASON). The files stay on disk.
#: - 00-voice-main: an early voice test whose question uses wording the product no longer uses.
#: - 00-voice-a, 00-voice-b: text-to-speech greeting clips that ask nothing.
#: - 00-voice-c, 00-voice-e: text-to-speech questions superseded by Charan's own recordings
#:   (take1 for c, take4 for e). 00-voice-d stays: no recording of his covers it.
DISPLAY_EXCLUDED_LABELS = (
    "00-voice-main",
    "00-voice-a",
    "00-voice-b",
    "00-voice-c",
    "00-voice-e",
)


def displayable_transcripts(directory: Path = TRANSCRIPT_DIR) -> list[dict[str, Any]]:
    """Recorded copilot runs that may be shown or offered as a fallback answer."""
    return [
        t
        for t in load_transcripts(directory)
        if str(t.get("label", "")) not in DISPLAY_EXCLUDED_LABELS
    ]


def short(text: str, limit: int) -> str:
    """Cut at a word boundary with an ellipsis (list labels)."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


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


def _ymd(d: Any) -> str:
    return str(d.isoformat()).replace("-", "")


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def _voice_html(voice: dict[str, Any]) -> str:
    """Render the "Heard: …" line so the analyst sees exactly what the ASR produced.

    When a deterministic product-code check ran (see copilot/product_code.py),
    a second line states what was heard and which code was asked about, as a statement.
    """
    facts = []
    if voice.get("audio_seconds") is not None:
        facts.append(f"{float(voice['audio_seconds']):.1f} s")
    if voice.get("language"):
        facts.append(str(voice["language"]))
    facts.append("Meta Voice Transcribe")
    out = (
        '<div style="font-size:14px;margin:0 0 4px 0">'
        f"🎙 <b>Heard:</b> “{html.escape(str(voice.get('transcript_text', '')))}”"
        f' <span class="ms-muted" style="font-size:12px">({html.escape(" · ".join(facts))})</span>'
        "</div>"
    )
    line = describe_check(
        voice.get("heard_code"),
        voice.get("suggested_code"),
        voice.get("used_code"),
        voice.get("product_code_status"),
    )
    if line:
        out += f'<div style="font-size:14px;margin:0 0 4px 0">{html.escape(line)}</div>'
    return out


def render_transcript(t: dict[str, Any]) -> None:
    """One recorded or live answer: question, gated sentences, evidence, run facts."""
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
    tools = ", ".join(tool_label(c["name"]) for c in t["tool_calls"]) or "none"
    meta = (
        f"Model `{t['model']}` · tools: {tools}"
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
    # Always rebuilt from the stored calls (deterministic), so a count fixed in the builder
    # shows here too and the filters and times print the same way as in the PDF.
    rows = protocol_from_transcript(t)
    if rows:
        with st.expander(f"Search protocol ({len(rows)} searches)"):
            st.caption(
                "What was searched, so a reviewer can repeat it. "
                '"not recorded" means the stored log did not keep that value.'
            )
            st.dataframe(
                [
                    {
                        "Search": row.label,
                        "Dataset": row.dataset,
                        "Filters": row.filters_text,
                        "From": row.date_from or "",
                        "To": row.date_to or "",
                        "Count": row.count_text,
                        "Run at (UTC)": row.run_at or "not recorded",
                    }
                    for row in rows
                ],
                hide_index=True,
            )
    with st.expander("Tool calls"):
        for c in t["tool_calls"]:
            st.markdown(f"`{tool_label(c['name'])}` `{json.dumps(c['arguments'])}`")
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
        et = st.selectbox("Event type", ["Any", "Injury", "Death", "Malfunction"])
        n = int(st.number_input("Claimed number of reports", min_value=0, value=50))
        if et == "Any":
            claim, sentence = CountClaim(pc, n), f"{pc} has {n} reports."
        else:
            claim, sentence = CountClaim(pc, n, et), f"{pc} has {n} {et} reports."
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
    """Copilot: recorded Muse Spark answers (list and detail), the gate playground, live mode."""
    tab_replay, tab_gate, tab_live = st.tabs(
        ["Recorded Muse Spark answers", "Try to fool the gate", "Ask live"]
    )
    with tab_replay:
        # Typed questions first (the demo's story order); spoken clips after them.
        # displayable_transcripts() applies DISPLAY_EXCLUDED_LABELS (the one exclusion list).
        transcripts = sorted(
            displayable_transcripts(),
            key=lambda t: (str(t.get("label", "")).startswith("00-voice"), str(t.get("label", ""))),
        )
        if not transcripts:
            st.info(
                "No recorded runs yet. They are produced by "
                "`scripts/record_demo_transcripts.py` with a Meta Model API key."
            )
        else:
            by_label = {str(t["label"]): t for t in transcripts}
            left, right = st.columns([1, 2.2], gap="large")
            with left:
                st.html(
                    f'<div class="ms-kicker">{len(transcripts)} recorded questions</div>'
                    '<p class="ms-muted ms-small">Real Muse Spark runs; every sentence was '
                    "checked by the gate before it was shown. Counts come from the stored demo "
                    "sample, not from every report openFDA holds for the device type.</p>"
                )
                with st.container(key="ms_qlist"):
                    pick = st.radio(
                        "Questions",
                        list(by_label),
                        format_func=lambda k: ("🎙 " if k.startswith("00-voice") else "")
                        + short(str(by_label[k]["question"]), 90),
                        key="cp_pick",
                        label_visibility="collapsed",
                    )
            with right, st.container(border=True):
                render_transcript(by_label[str(pick)])
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
            render_transcript(t)


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
    t = recorded_fallback(question, displayable_transcripts())
    if t is None:
        st.info("No recorded answers are available yet.")
        return
    st.session_state["copilot_log"].append(t)


def _voice_question(db: Database, agent: Any) -> None:  # pragma: no cover - needs a live key
    """Record a spoken question → Meta Voice Transcribe → the same gated copilot.

    A corrected product code is never applied on its own: the analyst picks
    "Ask about <suggested>" or "Ask as heard (<heard>)" and only then is the model asked.
    """
    import hashlib

    from maudesignal.copilot.transcript import result_to_dict
    from maudesignal.copilot.voice import (
        DEFAULT_VOICE_MODEL,
        MetaTranscriber,
        Transcript,
        VoiceTranscribeError,
        answer_prepared,
        prepare_voice_question,
    )

    model = os.environ.get("META_VOICE_MODEL", DEFAULT_VOICE_MODEL)
    g = spend_guard(db)

    def finish(prepared: Any, use_suggestion: bool) -> None:
        try:
            with st.spinner("Muse Spark is working…"):
                ans = answer_prepared(model, agent, prepared, use_suggestion=use_suggestion)
        except SpendLimitError as exc:
            _fallback(prepared.transcript.text, str(exc))
            return
        st.session_state["copilot_log"].append(
            result_to_dict(ans.result, voice=ans.transcript.to_voice_block())
        )

    pending = st.session_state.get("copilot_voice_pending")
    if pending is not None:
        prompt = confirm_prompt(pending.check)
        if prompt is None:
            st.session_state.pop("copilot_voice_pending", None)
        else:
            question, ask_suggested, ask_heard = prompt
            st.html(_voice_html(pending.transcript.to_voice_block()))
            st.markdown(f"**{question}**")
            c1, c2, _ = st.columns([1, 1, 3])
            choice: bool | None = None
            if c1.button(ask_suggested, key="voice_ask_suggested"):
                choice = True
            if c2.button(ask_heard, key="voice_ask_heard"):
                choice = False
            if choice is not None:
                st.session_state.pop("copilot_voice_pending", None)
                finish(pending, choice)
                st.rerun()
            return

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
            st.spinner("Transcribing…"),
        ):
            prepared = prepare_voice_question(
                transcriber, agent, data, filename="question.wav", on_transcribed=count_voice
            )
    except VoiceTranscribeError as exc:
        st.error(f"Voice question not asked: {exc}")
        return
    except SpendLimitError as exc:
        _fallback(heard[0].text if heard else "voice question", str(exc))
        return
    if prepared.check.needs_confirmation:
        st.session_state["copilot_voice_pending"] = prepared
        st.rerun()
    finish(prepared, False)


# ---------------------------------------------------------------------------
# Actions & audit
# ---------------------------------------------------------------------------


def _restored_note(db: Database, capa_id: str) -> str:
    """'Restored from demo/transcripts/<file> (recorded <UTC>)' for a replayed pack, else ''."""
    for a in db.list_audit(entity_id=capa_id):
        if a.action != "capa.draft":
            continue
        try:
            payload = json.loads(a.payload_json)
        except ValueError:
            return ""
        src = payload.get("restored_from")
        if not src:
            return ""
        when = payload.get("recorded_at_utc")
        return f"Restored from demo/transcripts/{src}" + (f" (recorded {when})" if when else "")
    return ""


def render_approvals(db: Database, drafts: list[Any]) -> None:
    """CAPA-need evidence packs with the named-person Accept / Reject decision."""
    st.caption(CAPA_NEED_NOTE)
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
            restored = _restored_note(db, d.capa_id)
            if restored:
                st.caption(restored)
            if d.status == "draft":
                c1, c2, _ = st.columns([1, 1, 4])
                for col, decision, label in (
                    (c1, "approved", "Accept"),
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


def page_audit(db: Database) -> None:
    """Every decision and model answer, in one tamper-evident trail."""
    drafts = db.list_capa_drafts()
    pending = [d for d in drafts if d.status == "draft"]
    if drafts:
        st.subheader(f"CAPA-need evidence packs ({len(pending)} awaiting a decision)")
        render_approvals(db, drafts)
    from maudesignal.dashboard.demo_db import keyless

    rows = db.list_audit()
    if not rows:
        _recorded_audit_trails()
        return
    if keyless():
        # The keyless demo runs on a copy of the demo database with the recorded packs
        # restored, so its own trail holds only those restore entries; the recorded Meta
        # runs' trails are shown too.
        _recorded_audit_trails()
        st.subheader("This demo database")
    ok, bad = db.verify_audit_chain()
    if ok:
        st.success(f"Hash chain intact across {len(rows)} entries.")
    else:
        st.error(f"Hash chain broken at entry {bad} — the trail was edited.")
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
    runs, rows = [], []
    for doc in exports:
        entries = doc.get("entries", [])
        ok, bad = doc["verified"]
        run = str(doc.get("run_label", doc["file"]))
        runs.append(
            {
                "recorded run": run,
                "entries": len(entries),
                "hash chain": "intact" if ok else f"broken at entry {bad}",
            }
        )
        if run in DISPLAY_EXCLUDED_LABELS:
            continue  # chain verified above; its entries are not listed (see the caption)
        rows += [
            {
                "run": run,
                "seq": e["seq"],
                "time (UTC)": e["ts"],
                "actor": e["actor"],
                "action": e["action"],
                "detail": _audit_detail(e),
                "hash": e["entry_hash"][:12],
            }
            for e in entries
        ]
    broken = [r for r in runs if r["hash chain"] != "intact"]
    total = sum(len(d.get("entries", [])) for d in exports)
    if broken:
        st.error(f"Hash chain broken in {len(broken)} recorded run(s).")
    else:
        st.success(f"Hash chain intact in all {len(runs)} recorded runs ({total} entries).")
    hidden = [r["recorded run"] for r in runs if r["recorded run"] in DISPLAY_EXCLUDED_LABELS]
    if hidden:
        st.caption(
            f"Not listed in the Copilot answers: {', '.join(hidden)}. They are an early voice "
            "test, two text-to-speech greetings, and two text-to-speech questions replaced by "
            "recordings of a person's own voice. Their chains are included in the check above."
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with st.expander("Per run"):
        st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")


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
