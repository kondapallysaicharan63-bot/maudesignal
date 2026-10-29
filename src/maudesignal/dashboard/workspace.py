"""Signals workspace: the device types on the left, the selected one on the right.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A list-and-detail layout (the pattern of an inbox or an issue tracker). Every
number comes from the deterministic detector and the stored openFDA records, as
on the earlier "What changed" page; nothing here calls a model. The detail pane
gathers what used to be spread over four pages: why the device type is flagged,
its reports, the copilot's recorded answers about it, its CAPA-need evidence
pack with the named-person decision, and MHRA (UK) context.
"""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from maudesignal.copilot.transcript import load_transcripts
from maudesignal.dashboard.copilot_pages import (
    MAUDE_URL,
    SOURCE_FILTERS,
    TRANSCRIPT_DIR,
    render_approvals,
    render_transcript,
    short,
)
from maudesignal.dashboard.live_check_ui import render_live_check
from maudesignal.monitor.compare import CompareRow, compare_signals
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import digest_from_database
from maudesignal.monitor.sources import not_by_manufacturer, sourced_reports
from maudesignal.storage.database import Database

_ARROW = {
    "reports suddenly increased": "trending_up",
    "more serious than usual": "warning",
    "new kind of problem": "new_releases",
    "no change": "remove",
}


def _figure(row: CompareRow) -> str:
    if row.change == "reports suddenly increased" and row.ratio_to_baseline is not None:
        return f"{row.ratio_to_baseline:.2f}×"
    return str(row.this_week)


def _list_caption(row: CompareRow) -> str:
    return f"{row.change[:1].upper() + row.change[1:]} · {row.this_week} this week"


def _ordered(rows: tuple[CompareRow, ...], ranked: list[str]) -> list[CompareRow]:
    """Flagged device types in the digest's ranking order, then the rest by volume."""
    by_code = {r.product_code: r for r in rows}
    first = [by_code[c] for c in ranked if c in by_code]
    rest = sorted(
        (r for r in rows if r.product_code not in ranked),
        key=lambda r: (-r.this_week, r.product_code),
    )
    return first + rest


def page_signals(db: Database) -> None:
    """The workspace: device-type list, then the selected device type's detail."""
    result = detect_from_database(db)
    digest = digest_from_database(db, result)
    codes = sorted({e.product_code for e in db.list_normalized_events() if e.product_code})
    if not codes:
        st.info("No MAUDE reports stored yet.")
        return
    cmp = compare_signals(db, codes)
    rows = _ordered(cmp.rows, [s.product_code for s in digest.ranked])
    by_code = {r.product_code: r for r in rows}
    if st.session_state.get("sig_code") not in by_code:
        st.session_state["sig_code"] = rows[0].product_code

    render_live_check()
    left, right = st.columns([1, 2.7], gap="large")
    with left:
        w = result.window
        n_flagged = digest.increased_count + digest.serious_count + digest.new_count
        st.html(
            '<div class="ms-kicker">Device types · this week</div>'
            f'<p class="ms-muted ms-small">{w.current_start:%b %d} – {w.current_end:%b %d, %Y} '
            f"vs the 4 weeks before. {n_flagged} of {len(rows)} flagged.</p>"
        )
        with st.container(key="ms_siglist"):
            st.radio(
                "Device types",
                [r.product_code for r in rows],
                key="sig_code",
                format_func=lambda c: f"{c} · {_figure(by_code[c])}",
                captions=[_list_caption(r) for r in rows],
                label_visibility="collapsed",
            )
        _remember(db, codes)
    with right:
        _detail(db, by_code[st.session_state["sig_code"]], digest)


def _remember(db: Database, codes: list[str]) -> None:
    from maudesignal.copilot.memory import CopilotMemoryError, load_memory, set_device_types

    mem = load_memory(db)
    with st.expander(
        "Device types you watch" + (f" ({', '.join(mem.device_types)})" if mem.device_types else "")
    ):
        st.caption(
            "You pick the product codes; MaudeSignal never decides which devices are similar. "
            "Saved in the audit trail with your name; the copilot can read it, not change it."
        )
        chosen = st.multiselect(
            "Product codes",
            codes,
            default=[c for c in mem.device_types if c in codes] or codes,
            key="watch_codes",
        )
        who = st.text_input("Your name", key="mem_actor")
        if st.button("Remember", key="mem_save"):
            try:
                set_device_types(db, chosen, actor=who)
                st.success(f"Remembered: {', '.join(sorted(chosen)) or 'none'}.")
            except CopilotMemoryError as exc:
                st.error(str(exc))


def _header_html(row: CompareRow, digest: Any) -> str:
    device = digest.device_types.get(row.product_code, "")
    label = row.change[:1].upper() + row.change[1:]
    flagged = row.change != "no change"
    reason = digest.rank_reasons.get(row.product_code, "").replace(">=", "≥")
    if not reason:
        reason = (
            f"No rule fired: {row.this_week} report(s) this week against a weekly mean of "
            f"{row.baseline_weekly_mean:.2f} before."
        )
    brands = digest.window_brands.get(row.product_code, [])
    named = (
        "Devices named on this week's reports: "
        + ", ".join(f"{html.escape(b)} ({n})" for b, n in brands)
        + "."
        if brands
        else ""
    )
    cls = "ms-tile ms-hero ms-sig-head" if flagged else "ms-tile ms-sig-head"
    return (
        f'<article class="{cls}">'
        f'<div class="ms-kicker"><span class="ms-i" aria-hidden="true">'
        f"{_ARROW.get(row.change, 'remove')}</span>{html.escape(row.product_code)}"
        + (f" · {html.escape(device)}" if device else "")
        + "</div>"
        '<div class="ms-sig-head__row">'
        f'<h2 class="ms-hero__title">{html.escape(label)}</h2>'
        f'<div class="ms-hero__fig ms-num">{_figure(row)}</div></div>'
        f'<p class="ms-hero__deck"><b>{"Why it is flagged." if flagged else "Status."}</b> '
        f"{html.escape(reason)}</p>"
        + (f'<p class="ms-hero__deck ms-small">{named}</p>' if named else "")
        + "</article>"
    )


def _detail(db: Database, row: CompareRow, digest: Any) -> None:
    st.html(_header_html(row, digest))
    stats = (
        ("This week", str(row.this_week)),
        ("Weekly mean before", f"{row.baseline_weekly_mean:.2f}"),
        ("Injury / death this week", str(row.injury_death_this_week)),
        ("Not filed by a manufacturer", str(row.not_by_manufacturer_this_week)),
        ("Stored, all dates", str(row.stored_total)),
    )
    st.html(
        '<div class="ms-stats">'
        + "".join(
            f'<div><span class="ms-num">{html.escape(v)}</span>{html.escape(k)}</div>'
            for k, v in stats
        )
        + "</div>"
    )
    t_reports, t_ask, t_pack, t_uk = st.tabs(
        ["Reports", "Copilot answers", "Evidence pack", "UK context"]
    )
    with t_reports:
        _reports(db, row.product_code, digest)
    with t_ask:
        _answers(row.product_code)
    with t_pack:
        _evidence_pack(db, row, digest)
    with t_uk:
        _mhra(db, row.product_code)


def _reports(db: Database, code: str, digest: Any) -> None:
    reports = [r for r in sourced_reports(db) if r.product_code == code]
    signal = next((s for s in digest.result.signals if s.product_code == code), None)
    week_ids = set(signal.current_report_ids) if signal else set()
    scope = st.segmented_control(
        "Show",
        ["This week", "All stored", "Not filed by a manufacturer"],
        default="This week",
        key=f"rep_scope_{code}",
        label_visibility="collapsed",
    )
    if scope == "This week":
        rows = [r for r in reports if r.report_id in week_ids]
    elif scope in SOURCE_FILTERS:
        wanted = SOURCE_FILTERS[scope]
        rows = (
            not_by_manufacturer(reports)
            if wanted is None
            else [r for r in reports if r.source == wanted]
        )
    else:
        rows = reports
    st.caption(
        f"{len(rows)} report(s) · newest first · source as reported to openFDA. A manufacturer "
        "already knows the complaints it files itself; the others may be new to it."
    )
    if not rows:
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "FDA record": MAUDE_URL.format(r.report_id.split("-")[0]),
                    "report id": r.report_id,
                    "received": r.date_received or "",
                    "filed by": r.source,
                    "device named": r.brand_name or "",
                }
                for r in sorted(rows, key=lambda r: r.date_received or "", reverse=True)
            ]
        ),
        column_config={
            "FDA record": st.column_config.LinkColumn("FDA record", display_text="open")
        },
        hide_index=True,
        width="stretch",
    )


def _mentions(t: dict[str, Any], code: str) -> bool:
    text = str(t.get("question", "")) + " ".join(
        str(c.get("arguments", "")) for c in t.get("tool_calls", [])
    )
    return code in text.upper()


def _answers(code: str) -> None:
    found = [t for t in load_transcripts(TRANSCRIPT_DIR) if _mentions(t, code)]
    if not found:
        st.caption(f"No recorded copilot answer mentions {code}. Ask about it on the Copilot page.")
        return
    found.sort(key=lambda t: (str(t.get("label", "")).startswith("00-voice"), t["label"]))
    labels = {t["label"]: t for t in found}
    pick = st.selectbox(
        f"Recorded Muse Spark answers about {code} ({len(found)})",
        list(labels),
        format_func=lambda k: ("🎙 " if k.startswith("00-voice") else "")
        + short(str(labels[k]["question"]), 110),
        key=f"ans_{code}",
    )
    with st.container(border=True):
        render_transcript(labels[pick])


def _evidence_pack(db: Database, row: CompareRow, digest: Any) -> None:
    from maudesignal.dashboard.dossier_pages import render_dossier

    drafts = [d for d in db.list_capa_drafts() if d.product_code == row.product_code]
    flagged = row.product_code in {s.product_code for s in digest.ranked}
    if not drafts and not flagged:
        st.caption(
            f"Nothing flagged for {row.product_code} this week, so no evidence pack is prepared. "
            "Ask the copilot to prepare one if a person decides it is needed."
        )
        return
    if drafts:
        render_approvals(db, drafts)
    render_dossier(
        db,
        capa_id=drafts[0].capa_id if drafts else None,
        product_code=None if drafts else row.product_code,
    )


def _mhra(db: Database, code: str) -> None:
    from maudesignal.sources.mhra import SOURCE_MHRA

    rows = [
        r
        for r in db.list_external_sources(source_type=SOURCE_MHRA, limit=500)
        if r.product_code == code
    ]
    st.caption(
        "MHRA (UK) device safety alerts found with search terms a person chose for this device "
        "type. Regulator context only: not FDA data and never counted in any number here."
    )
    if not rows:
        st.caption("None stored for this device type.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "issued": r.publication_date or "",
                    "MHRA (UK) alert": r.title or "",
                    "link": r.url,
                }
                for r in sorted(rows, key=lambda r: r.publication_date or "", reverse=True)
            ]
        ),
        column_config={"link": st.column_config.LinkColumn("link", display_text="open")},
        hide_index=True,
        width="stretch",
    )
