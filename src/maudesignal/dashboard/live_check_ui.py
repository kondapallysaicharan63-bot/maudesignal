"""Signals page: "Check any device type" on openFDA, live.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Anyone can type a three-letter FDA product code and get the same this-week-vs-
the-4-weeks-before check the stored device types get (``monitor.live_check``):
counts only, no model, nothing stored, and a link to the openFDA query behind
every figure. Results are cached per code for six hours and each browser session
gets a fixed number of checks, so the public demo stays inside openFDA's limits.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDARateLimitError
from maudesignal.config import openfda_api_key_from_env
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.monitor.live_check import (
    LiveCheck,
    LiveCheckError,
    check_product_code,
    normalize_code,
)

#: Written by ``scripts/ai_device_sweep.py`` (GitHub Actions); shown when present.
SWEEP_FILE = Path(__file__).resolve().parents[3] / "demo" / "sweep" / "ai-device-sweep.json"

#: Live checks one browser session may run (cached repeats are free).
SESSION_CHECKS = 10
_COUNT_KEY = "live_checks_used"
_RESULT_KEY = "live_check_result"


def _check(code: str, day: str) -> LiveCheck:
    with OpenFDAClient(api_key=openfda_api_key_from_env()) as client:
        return check_product_code(client, code, datetime.strptime(day, "%Y-%m-%d").date())


#: One openFDA check per code per six hours, shared by every session.
_cached_check: Callable[[str, str], LiveCheck] = st.cache_data(ttl=6 * 3600, show_spinner=False)(
    _check
)


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def reason(r: LiveCheck) -> str:
    """The rule that fired, in plain words, with its numbers."""
    if r.as_of is None:
        return "No report in the last two years, so there is no current week to compare."
    if r.classification == "new_signal":
        if not r.prior_report_count:
            return f"First reports ever for this device type: {r.current_count} this week."
        return (
            "A kind of report never seen before for this device type: "
            + ", ".join(r.new_event_types)
            + "."
        )
    if r.classification == "severity_escalation":
        return (
            f"Injury or death in {_pct(r.current_severe_share)} of this week's reports "
            f"against {_pct(r.baseline_severe_share)} in the 4 weeks before "
            f"(+{r.severe_share_delta_pp:.0f} points)."
        )
    if r.classification == "spike":
        return (
            f"{r.current_count} reports this week against a weekly mean of "
            f"{r.baseline_weekly_mean:.2f} in the 4 weeks before ({r.spike_ratio:.2f}×)."
        )
    return (
        f"No rule fired: {r.current_count} report(s) this week against a weekly mean of "
        f"{r.baseline_weekly_mean:.2f} before."
    )


def _figure(r: LiveCheck) -> str:
    if r.classification == "spike" and r.spike_ratio is not None:
        return f"{r.spike_ratio:.2f}×"
    return str(r.current_count)


def _result_html(r: LiveCheck) -> str:
    flagged = r.classification != "stable"
    label = r.change[:1].upper() + r.change[1:]
    when = (
        f"{r.window.current_start:%b %d} – {r.window.current_end:%b %d, %Y} "
        "(the latest week on openFDA) vs the 4 weeks before"
        if r.window
        else "No report in the last two years"
    )
    stats = (
        ("This week", str(r.current_count)),
        ("Weekly mean before", f"{r.baseline_weekly_mean:.2f}"),
        ("Injury / death this week", str(r.current_severe_count)),
        ("openFDA, all dates", f"{r.all_dates_total:,}"),
    )
    return (
        f'<article class="{"ms-tile ms-hero ms-sig-head" if flagged else "ms-tile ms-sig-head"}">'
        f'<div class="ms-kicker"><span class="ms-i" aria-hidden="true">public</span>'
        f"Live from openFDA · {html.escape(r.product_code)}</div>"
        f'<div class="ms-sig-head__row"><h2 class="ms-hero__title">{html.escape(label)}</h2>'
        f'<div class="ms-hero__fig ms-num">{_figure(r)}</div></div>'
        f'<p class="ms-hero__deck"><b>{"Why it is flagged." if flagged else "Status."}</b> '
        f"{html.escape(reason(r))}</p>"
        f'<p class="ms-hero__deck ms-small">{html.escape(when)}.</p></article>'
        '<div class="ms-stats">'
        + "".join(
            f'<div><span class="ms-num">{html.escape(v)}</span>{html.escape(k)}</div>'
            for k, v in stats
        )
        + "</div>"
    )


def render_live_check() -> None:
    """The input row and, after a check, its result with the queries behind it."""
    with st.container(key="ms_livecheck"):
        st.html(
            '<div class="ms-kicker">Check any device type</div>'
            '<p class="ms-muted ms-small">Type any FDA product code. MaudeSignal asks openFDA '
            "for counts (no report text, nothing stored, no AI model) and applies the same "
            "rules as the device types below.</p>"
        )
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        with c1:
            text = st.text_input(
                "Any FDA product code",
                key="live_code",
                placeholder="e.g. LLZ, QIH, FLL",
                max_chars=3,
            )
        with c2:
            go = st.button("Check on openFDA", key="live_go", width="stretch")
        if go:
            _run(text)
        r = st.session_state.get(_RESULT_KEY)
        if isinstance(r, LiveCheck):
            st.html(_result_html(r))
            with st.expander("Where each number comes from (open the openFDA query)"):
                for name, url in r.queries:
                    st.markdown(f"- [{name}]({url})")
                st.caption(
                    "openFDA lags real time by weeks, so 'this week' is the latest week it has. "
                    "A triage signal for a person to review, not a finding."
                )


def _run(text: str) -> None:
    try:
        code = normalize_code(text)
    except LiveCheckError as exc:
        st.error(str(exc))
        return
    used = int(st.session_state.get(_COUNT_KEY, 0))
    if used >= SESSION_CHECKS:
        st.warning(
            f"This session has used its {SESSION_CHECKS} live checks. Reload the page later, or "
            "run MaudeSignal yourself (it is open source)."
        )
        return
    try:
        with st.spinner(f"Asking openFDA about {code}…"):
            r = _cached_check(code, datetime.now(UTC).strftime("%Y-%m-%d"))
    except OpenFDARateLimitError:
        st.error("openFDA's rate limit was reached. Try again in a minute.")
        return
    except OpenFDAAPIError as exc:
        st.error(f"openFDA could not be reached just now ({exc}). Try again in a minute.")
        return
    st.session_state[_COUNT_KEY] = used + 1
    st.session_state[_RESULT_KEY] = r


def load_sweep(path: Path = SWEEP_FILE) -> dict[str, Any] | None:
    """The latest AI-device sweep, or None when it has not run yet."""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("rows") else None


def sweep_summary(data: dict[str, Any]) -> str:
    """One sentence: how many AI device types were flagged, in which week."""
    m = data["meta"]
    flagged = [r for r in data["rows"] if r["classification"] != "stable"]
    w = m["window"]
    return (
        f"{len(flagged)} of {len(data['rows'])} AI device types on FDA's list were flagged "
        f"for {w['current_start']} – {w['current_end']} (the latest week on openFDA), "
        f"checked {m['generated_utc'][:10]}."
    )


def render_sweep() -> None:
    """Every product code on FDA's AI device list, checked for the same week."""
    data = load_sweep()
    if data is None:
        return
    flagged = sorted(
        (r for r in data["rows"] if r["classification"] != "stable"),
        key=lambda r: (-r["current_count"], r["product_code"]),
    )
    with st.expander("Across FDA's AI device list: " + sweep_summary(data)):
        m = data["meta"]
        st.caption(
            f"FDA's AI-Enabled Medical Device List: {m['devices_on_list']} devices, "
            f"{m['codes_on_list']} product codes; {m['codes_checked']} checked"
            + (" (keyless run, capped)" if m.get("capped") else "")
            + ". Same rules, counts only. A triage signal for a person to review, not a "
            "finding about any device or company."
        )
        if flagged:
            st.dataframe(
                [
                    {
                        "Product code": r["product_code"],
                        "AI devices on list": r["ai_devices_on_list"],
                        "Change": r["change"],
                        "This week": r["current_count"],
                        "Weekly mean before": round(r["baseline_weekly_mean"], 2),
                        "Injury / death this week": r["current_severe_count"],
                        "openFDA query": r["queries"][1][1] if len(r["queries"]) > 1 else "",
                    }
                    for r in flagged
                ],
                hide_index=True,
                column_config={"openFDA query": st.column_config.LinkColumn(display_text="open")},
            )
