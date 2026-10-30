"""Dashboard page "Our devices": does a problem seen in FDA data apply to us?

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A SIMULATED company (``demo/company``) with fictional devices on real product codes.
The problem evidence (real MAUDE reports and recalls) comes from stored openFDA data;
every count is recomputed and every quote checked by the claim gate. A status is set by
a named simulated person and read from a hash-chained audit; this page never sets one.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from maudesignal.company import CompanyView, DeviceView, load_company
from maudesignal.company.build import status_detail
from maudesignal.company.constants import (
    S_COVERED,
    S_MONITORING,
    S_NEEDS_REVIEW,
    S_NOT_APPLICABLE,
    S_TESTING,
    company_dir,
)
from maudesignal.company.patterns import Pattern
from maudesignal.monitor.digest import CHANGE_LABELS

_CHIP = {
    S_NEEDS_REVIEW: "warn",
    S_TESTING: "info",
    S_COVERED: "ok",
    S_NOT_APPLICABLE: "info",
    S_MONITORING: "ok",
}
_MAX_LINKS = 12


def chip(status: str) -> str:
    """HTML status chip (design-system colours, the status words always shown)."""
    return f'<span class="ms-pill {_CHIP.get(status, "info")}">{html.escape(status)}</span>'


def banner_html(text: str) -> str:
    """The banner every surface of the simulated company carries."""
    return (
        '<div class="ms-banner ms-banner--warn" id="company-banner">'
        '<span class="ms-i" aria-hidden="true">science</span>'
        f"<span><b>{html.escape(text)}</b></span></div>"
    )


def _stamp(folder: Path) -> tuple[float, ...]:
    files = [
        folder / "company.json",
        folder / "audit.json",
        *sorted(folder.glob("evidence/*.json")),
    ]
    return tuple(f.stat().st_mtime for f in files if f.is_file())


@st.cache_data(show_spinner=False)
def _load(folder: str, stamp: tuple[float, ...]) -> CompanyView:
    return load_company(Path(folder))


_TABLE_CSS = (
    "<style>.ms-company-table{width:100%;border-collapse:collapse}"
    ".ms-company-table th{text-align:left;padding:8px 10px;"
    "border-bottom:1px solid var(--rule-strong)}"
    ".ms-company-table td{padding:8px 10px;vertical-align:top;"
    "border-bottom:1px solid var(--rule)}"
    ".ms-company-table td:first-child{white-space:nowrap}</style>"
)


def _device_label(d: DeviceView) -> str:
    return f"{d.device_id} · {d.name} ({d.product_code})"


def render_table(view: CompanyView) -> None:
    """Device table with status chips."""
    rows = []
    for d in view.devices:
        s = d.status
        type_name = html.escape(d.device_type_name or "device type not fetched yet")
        who = html.escape(s.actor) if s else ""
        when = s.date_label if s else ""
        patterns = len(d.patterns) if d.evidence.available else "evidence not fetched yet"
        rows.append(
            "<tr>"
            f"<td>{html.escape(d.device_id)}</td>"
            f"<td><b>{html.escape(d.name)}</b><br>"
            f"<span class='ms-fn'>model {html.escape(d.model)}</span></td>"
            f"<td><b>{html.escape(d.product_code)}</b><br>"
            f"<span class='ms-fn'>{type_name}</span></td>"
            f"<td>{chip(s.to_status) if s else 'no status yet'}</td>"
            f"<td>{who}<br><span class='ms-fn'>{when}</span></td>"
            f"<td>{patterns}</td>"
            "</tr>"
        )
    st.html(
        f'{_TABLE_CSS}<div style="overflow-x:auto"><table class="ms-company-table">'
        "<thead><tr><th>ID</th><th>Device (fictional)</th><th>Product code and type</th>"
        "<th>Status</th><th>Set by, date</th><th>Real patterns</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_pattern(p: Pattern) -> None:
    st.markdown(f"**{p.label}** · {p.count} real reports")
    st.caption(
        f"{p.basis}. Count check: {p.gate_reason}. Quotes shown {p.quotes_passed}, "
        f"withheld {p.quotes_withheld}."
    )
    for q in p.quotes:
        st.markdown(f"> {q.text}  \n> [MAUDE report {q.report_id}]({q.url})")
    parts = [f"[{i}]({u})" for (_, u), i in zip(p.links, p.report_ids, strict=False)]
    shown = parts[:_MAX_LINKS]
    more = len(parts) - len(shown)
    st.markdown("Reports: " + " · ".join(shown) + (f" · and {more} more" if more > 0 else ""))


def _render_evidence(d: DeviceView) -> None:
    ev, cp = d.evidence, d.code_patterns
    st.markdown("##### Real problem evidence for this product code")
    if not ev.available:
        st.info(
            f"{d.evidence_note.capitalize() if d.evidence_note else 'Evidence not fetched yet'}. "
            "No count, pattern or quote is shown for this code until the FDA data is fetched."
        )
        return
    window = f"{ev.window_from} to {ev.window_to}" if ev.window_from else "dates not stored"
    st.markdown(
        f"{cp.report_count} stored MAUDE reports, received {window} "
        f"(count check: {cp.report_count_reason})."
    )
    for label, url in ev.queries:
        st.markdown(f"- [{label}]({url})")
    if not d.patterns:
        st.info("No group of 2 or more reports matches the stored rules for this code.")
    for p in d.patterns:
        _render_pattern(p)
    rc = cp.recalls
    if rc is not None:
        st.markdown(
            f"**Recalls on file for this code:** {rc.stored} (count check: {rc.gate_reason})"
        )
        for r in rc.latest:
            link = f" · [FDA recall page]({r.url})" if r.url else ""
            ex = f": {r.excerpt}" if r.excerpt else ""
            when = r.date_initiated or "date n/a"
            state = r.status or "status n/a"
            st.markdown(f"- {r.recall_number} ({when}, {state}){ex}{link}")


def _render_history(view: CompanyView, d: DeviceView) -> None:
    st.markdown("##### Status history")
    ok = "intact" if view.chain_ok else f"BROKEN at entry {view.chain_first_bad}"
    st.caption(
        f"Chain re-verified now over {len(view.audit_entries)} entries: {ok}. "
        "Every status is set by the named simulated person shown, never by this tool."
    )
    rows = "".join(
        "<tr>"
        f"<td>{e.seq}</td><td>{e.date_label}</td><td>{html.escape(e.actor)}</td>"
        f"<td>{html.escape(e.from_status or 'registered as')} → {chip(e.to_status)}</td>"
        f"<td>{html.escape(status_detail(e))}</td><td class='ms-fn'>{e.entry_hash[:12]}…</td></tr>"
        for e in d.history
    )
    st.html(
        f'{_TABLE_CSS}<div style="overflow-x:auto"><table class="ms-company-table">'
        "<thead><tr><th>#</th><th>Date</th><th>Set by</th><th>Change</th>"
        "<th>Detail</th><th>Entry hash</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def render_device(view: CompanyView, d: DeviceView) -> None:
    """Detail of one device: status, sweep row, patterns, evidence, history."""
    s = d.status
    st.markdown(f"### {d.name} · model {d.model}")
    st.markdown(
        f"Product code **{d.product_code}** — {d.device_type_name or 'device type not fetched yet'}"
        + (
            f" ([openFDA classification]({d.device_type_query_url}))"
            if d.device_type_query_url
            else ""
        )
        + f"  \nOwner: {d.owner}"
    )
    if s is not None:
        st.html(
            f"<p>Status: {chip(s.to_status)} set by {html.escape(s.actor)} on {s.date_label}"
            f"{' — ' + html.escape(status_detail(s)) if status_detail(s) else ''}</p>"
        )
    if d.sweep:
        sw = d.sweep
        change = CHANGE_LABELS.get(sw["classification"], sw["classification"])
        st.markdown(
            f"AI-device sweep row ({sw['file']}, as of {sw['as_of']}): **{change}**, "
            f"{sw['current_count']} reports this week vs {sw['baseline_count']} "
            f"in the 4 weeks before, {sw['prior_report_count']:,} earlier reports"
            + (f" ([query]({sw['query_url']}))" if sw.get("query_url") else "")
        )
    _render_evidence(d)
    _render_history(view, d)


def page_company() -> None:
    """The "Our devices" page."""
    folder = company_dir()
    if not (folder / "company.json").is_file():
        st.info("No simulated company file found (demo/company/company.json).")
        return
    view = _load(str(folder), _stamp(folder))
    st.html(banner_html(view.banner))
    st.markdown(f"## Our devices — {view.company}")
    st.caption(
        "Does a problem seen in FDA data apply to us? Pick a device to see the real problem "
        "patterns for its product code, the evidence behind them and who set its status. "
        "Signals are for human review, not medical advice."
    )
    render_table(view)
    labels = {_device_label(d): d for d in view.devices}
    choice = st.selectbox("Open a device", list(labels), key="company_device")
    render_device(view, labels[choice])
