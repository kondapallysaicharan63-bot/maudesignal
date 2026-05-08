"""MaudeSignal Streamlit dashboard — FDA AI/ML postmarket surveillance."""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from maudesignal.config import Config
from maudesignal.storage.database import Database

EXTRACTOR_SKILL = "maude-narrative-extractor"
CLASSIFIER_SKILL = "ai-failure-mode-classifier"
ROOT_CAUSE_SKILL = "root-cause-analyzer"

_MAUDE_DETAIL_URL = (
    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"
)

_CSS = """
<style>
/* ── Global typography ─────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}

/* ── FDA blue palette on sidebar ──────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d2137 0%, #1a3a5c 100%);
    border-right: 1px solid #2e5c8a;
}
section[data-testid="stSidebar"] * {
    color: #d4e6f1 !important;
}
section[data-testid="stSidebar"] .stRadio label {
    font-size: 0.95rem;
    padding: 4px 0;
}

/* ── Page header banner ────────────────────────────────────────────────── */
.ms-banner {
    background: linear-gradient(90deg, #1a5276 0%, #1f618d 60%, #2874a6 100%);
    border-radius: 8px;
    padding: 18px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.ms-banner h1 {
    color: #fff !important;
    font-size: 1.55rem !important;
    font-weight: 700 !important;
    margin: 0 !important;
    padding: 0 !important;
}
.ms-banner p {
    color: #a9cce3 !important;
    font-size: 0.82rem !important;
    margin: 4px 0 0 0 !important;
}

/* ── Metric card ───────────────────────────────────────────────────────── */
.ms-card {
    background: #fff;
    border: 1px solid #d5e8f5;
    border-top: 3px solid #2874a6;
    border-radius: 6px;
    padding: 16px 18px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,.07);
}
.ms-card .val {
    font-size: 2rem;
    font-weight: 700;
    color: #1a5276;
    line-height: 1.15;
}
.ms-card .lbl {
    font-size: 0.75rem;
    color: #555;
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-top: 4px;
}

/* ── Section sub-header ────────────────────────────────────────────────── */
.ms-section {
    font-size: 1.05rem;
    font-weight: 600;
    color: #1a5276;
    border-left: 3px solid #2874a6;
    padding-left: 10px;
    margin: 20px 0 10px;
}

/* ── Severity badge ────────────────────────────────────────────────────── */
.badge-death, .badge-malfunction, .badge-injury, .badge-other {
    padding: 2px 8px; border-radius: 4px; font-size: .75rem; color: #fff;
}
.badge-death       { background: #c0392b; }
.badge-malfunction { background: #e67e22; }
.badge-injury      { background: #d4ac0d; }
.badge-other       { background: #7f8c8d; }

/* ── Catalog specialty chip ────────────────────────────────────────────── */
.chip {
    display: inline-block;
    background: #d4e6f1;
    color: #1a5276;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: .73rem;
    font-weight: 600;
}

/* ── Sidebar nav buttons ───────────────────────────────────────────────── */
section[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    text-align: left !important;
    padding: 3px 8px !important;
    font-size: 0.88rem !important;
    color: #d4e6f1 !important;
    box-shadow: none !important;
    width: 100% !important;
    border-radius: 4px !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.1) !important;
}

/* ── Footer ─────────────────────────────────────────────────────────────  */
.ms-footer {
    margin-top: 40px;
    font-size: .72rem;
    color: #aaa;
    text-align: center;
    border-top: 1px solid #e0e0e0;
    padding-top: 10px;
}
</style>
"""

_SEVERITY_ORDER = [
    "death",
    "serious injury",
    "injury",
    "malfunction",
    "other",
    "no answer provided",
]

SEVERITY_COLORS: dict[str, str] = {
    "death": "#b91c1c",
    "serious injury": "#ea580c",
    "injury": "#ca8a04",
    "malfunction": "#1d4ed8",
    "other": "#64748b",
    "no answer provided": "#94a3b8",
    "unknown": "#94a3b8",
}

_FAILURE_MODE_COLORS = {
    "performance_degradation": "#2563eb",
    "false_positive": "#0891b2",
    "false_negative": "#dc2626",
    "software_failure": "#7c3aed",
    "user_interface_failure": "#d97706",
    "hardware_sensor_failure": "#059669",
    "unknown": "#94a3b8",
}

_ASSETS_DIR = Path(__file__).parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "logo.svg"

_PAGE_GROUPS: dict[str, list[str]] = {
    "Monitor": ["Overview", "Records", "Severity"],
    "Analyze": ["Signals & Drift", "Root Cause & Alerts", "Trends & Forecasting"],
    "Configure": ["External Sources", "PSUR Reports", "Device Catalog"],
}


def _nan_to_dash(val: Any) -> str:
    """Normalise None / NaN / 'nan' / 'None' to the em-dash placeholder."""
    if val is None:
        return "—"
    if isinstance(val, float) and math.isnan(val):
        return "—"
    s = str(val)
    if s.lower() in ("nan", "none", ""):
        return "—"
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Data helpers
# ──────────────────────────────────────────────────────────────────────────────


def _maude_url(report_id: str) -> str:
    return _MAUDE_DETAIL_URL.format(report_id)


def _load_db() -> Database:
    config = Config.load()
    return Database(config.db_path)


def _extractions_dataframe(db: Database) -> pd.DataFrame:
    rows = db.list_extractions()
    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        try:
            payload = json.loads(r.output_json)
        except json.JSONDecodeError:
            payload = {}
        records.append(
            {
                "extraction_ts": r.extraction_ts,
                "maude_report_id": r.maude_report_id,
                "skill_name": r.skill_name,
                "skill_version": r.skill_version,
                "confidence_score": r.confidence_score,
                "requires_review": r.requires_review,
                "severity": _nan_to_dash(payload.get("severity")),
                "ai_related_flag": payload.get("ai_related_flag"),
                "ai_failure_mode": _nan_to_dash(payload.get("failure_mode_category")),
                "failure_mode": _nan_to_dash(payload.get("failure_mode")),
                "model_used": r.model_used,
            }
        )
    df = pd.DataFrame.from_records(records)
    # Belt-and-suspenders: collapse any remaining nan strings that survive JSON decode
    for col in ("severity", "ai_failure_mode", "failure_mode"):
        if col in df.columns:
            df[col] = df[col].apply(_nan_to_dash)
    return df


def _product_code_lookup(db: Database) -> dict[str, str]:
    events = db.list_normalized_events()
    return {e.maude_report_id: e.product_code for e in events}


def _device_name_lookup(db: Database) -> dict[str, str]:
    """Return product_code -> device_name from catalog."""
    devices = db.list_catalog_devices()
    return {d.product_code: d.device_name for d in devices}


def _catalog_dataframe(db: Database) -> pd.DataFrame:
    devices = db.list_catalog_devices()
    if not devices:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "product_code": d.product_code,
                "device_name": d.device_name,
                "company_name": d.company_name or "",
                "specialty": d.specialty or "",
                "decision_date": d.decision_date or "",
                "k_number": d.k_number or "",
                "source_keyword": d.source_keyword or "",
            }
            for d in devices
        ]
    )


# ──────────────────────────────────────────────────────────────────────────────
# Page: Overview
# ──────────────────────────────────────────────────────────────────────────────


def _page_summary(db: Database) -> None:
    df = _extractions_dataframe(db)
    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL] if not df.empty else pd.DataFrame()

    n_raw = db.count_raw_reports()
    n_catalog = db.count_catalog_devices()
    n_total = len(df_ext)
    n_ai = int(df_ext["ai_related_flag"].fillna(False).astype(bool).sum()) if n_total else 0
    pct_ai = (n_ai / n_total * 100.0) if n_total else 0.0
    avg_conf = float(df_ext["confidence_score"].mean()) if n_total else 0.0
    n_review = int(df_ext["requires_review"].fillna(False).astype(bool).sum()) if n_total else 0
    cost = db.total_llm_cost_usd()

    # KPI row
    st.markdown('<p class="ms-section">Key Performance Indicators</p>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, val, lbl in [
        (c1, str(n_catalog), "Catalog Devices"),
        (c2, f"{n_raw:,}", "MAUDE Reports"),
        (c3, str(n_total), "Extractions"),
        (c4, f"{pct_ai:.1f}%", "AI-Signal Rate"),
        (c5, f"{avg_conf:.3f}", "Avg Confidence"),
    ]:
        col.markdown(
            f'<div class="ms-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Top 5 product codes with device names
    if not df_ext.empty:
        st.markdown(
            '<p class="ms-section">Top 5 Product Codes by Extraction Count</p>',
            unsafe_allow_html=True,
        )
        pc_lookup = _product_code_lookup(db)
        dn_lookup = _device_name_lookup(db)
        df_ext_copy = df_ext.copy()
        df_ext_copy["product_code"] = df_ext_copy["maude_report_id"].map(pc_lookup).fillna("?")
        top5 = (
            df_ext_copy.groupby("product_code")
            .size()
            .reset_index(name="Extractions")
            .sort_values("Extractions", ascending=False)
            .head(5)
        )
        top5["Device Name"] = top5["product_code"].map(dn_lookup).fillna("—")
        top5 = top5.rename(columns={"product_code": "Product Code"})
        st.dataframe(
            top5[["Product Code", "Device Name", "Extractions"]],
            use_container_width=True,
            hide_index=True,
        )

    if df_ext.empty:
        st.info("No extractions yet. Run `maudesignal extract --product-code QIH --limit 5`.")
        return

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<p class="ms-section">Severity Distribution</p>', unsafe_allow_html=True)
        sev_counts = (
            df_ext["severity"]
            .fillna("unknown")
            .value_counts()
            .reindex(_SEVERITY_ORDER + ["unknown"], fill_value=0)
        )
        sev_df = sev_counts[sev_counts > 0].reset_index()
        sev_df.columns = pd.Index(["Severity", "Count"])
        if sev_df.empty:
            st.info("No severity data yet.")
        else:
            sev_chart = (
                alt.Chart(sev_df)
                .mark_bar()
                .encode(
                    x=alt.X("Severity:N", sort=list(_SEVERITY_ORDER), axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Count:Q"),
                    color=alt.Color(
                        "Severity:N",
                        scale=alt.Scale(
                            domain=list(SEVERITY_COLORS.keys()),
                            range=list(SEVERITY_COLORS.values()),
                        ),
                        legend=None,
                    ),
                    tooltip=["Severity", "Count"],
                )
                .properties(height=230)
            )
            st.altair_chart(sev_chart, use_container_width=True)

    with col_right:
        st.markdown('<p class="ms-section">AI Failure Mode Breakdown</p>', unsafe_allow_html=True)
        df_cls = df[df["skill_name"] == CLASSIFIER_SKILL]
        if df_cls.empty:
            st.caption("No Skill #4 classifications yet.")
        else:
            fm_counts = df_cls["ai_failure_mode"].fillna("unknown").value_counts().head(8)
            fm_df = fm_counts.reset_index()
            fm_df.columns = pd.Index(["Failure Mode", "Count"])
            if fm_df.empty:
                st.caption("No failure mode classifications yet.")
            else:
                fm_chart = (
                    alt.Chart(fm_df)
                    .mark_bar(color="#2563eb")
                    .encode(
                        x=alt.X("Failure Mode:N", axis=alt.Axis(labelAngle=-30)),
                        y=alt.Y("Count:Q"),
                        color=alt.Color(
                            "Failure Mode:N",
                            scale=alt.Scale(
                                domain=list(_FAILURE_MODE_COLORS.keys()),
                                range=list(_FAILURE_MODE_COLORS.values()),
                            ),
                            legend=None,
                        ),
                        tooltip=["Failure Mode", "Count"],
                    )
                    .properties(height=230)
                )
                st.altair_chart(fm_chart, use_container_width=True)

    st.markdown('<p class="ms-section">Requires Human Review</p>', unsafe_allow_html=True)
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("Flagged for review", n_review)
    col_r2.metric("Review rate", f"{(n_review / n_total * 100) if n_total else 0:.1f}%")
    col_r3.metric("LLM cost to date", f"${cost:.4f}")


# ──────────────────────────────────────────────────────────────────────────────
# Page: Records
# ──────────────────────────────────────────────────────────────────────────────


def _page_records(db: Database) -> None:
    df = _extractions_dataframe(db)
    if df.empty:
        st.info(
            "No extractions yet.  \nRun `maudesignal ingest --product-code QIH --limit 20` "
            "then `maudesignal extract --product-code QIH --limit 5`."
        )
        return

    pc_lookup = _product_code_lookup(db)
    df["product_code"] = df["maude_report_id"].map(pc_lookup).fillna("?")
    dn_lookup = _device_name_lookup(db)
    df["device_name"] = df["product_code"].map(dn_lookup).fillna("—")

    st.markdown('<p class="ms-section">Filters</p>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    pc_options = ["(all)"] + sorted({p for p in df["product_code"].dropna() if p and p != "?"})
    sev_options = ["(all)"] + sorted({s for s in df["severity"].dropna() if s})
    skill_options = ["(all)"] + sorted({s for s in df["skill_name"].dropna() if s})
    ai_options = ["(all)", "AI-related", "Not AI-related"]

    pc_sel = f1.selectbox("Product code", pc_options, key="rec_pc")
    sev_sel = f2.selectbox("Severity", sev_options, key="rec_sev")
    skill_sel = f3.selectbox("Skill", skill_options, key="rec_skill")
    ai_sel = f4.selectbox("AI flag", ai_options, key="rec_ai")

    device_search = st.text_input(
        "Search device name", key="rec_device_search", placeholder="e.g. radiology"
    )

    filtered = df.copy()
    if pc_sel != "(all)":
        filtered = filtered[filtered["product_code"] == pc_sel]
    if sev_sel != "(all)":
        filtered = filtered[filtered["severity"] == sev_sel]
    if skill_sel != "(all)":
        filtered = filtered[filtered["skill_name"] == skill_sel]
    if ai_sel == "AI-related":
        filtered = filtered[filtered["ai_related_flag"].fillna(False).astype(bool)]
    elif ai_sel == "Not AI-related":
        filtered = filtered[~filtered["ai_related_flag"].fillna(False).astype(bool)]
    if device_search.strip():
        q = device_search.strip().lower()
        filtered = filtered[filtered["device_name"].str.lower().str.contains(q, na=False)]

    st.caption(f"**{len(filtered)}** of {len(df)} rows")

    display_cols = [
        "maude_report_id",
        "product_code",
        "device_name",
        "severity",
        "ai_related_flag",
        "ai_failure_mode",
        "confidence_score",
        "requires_review",
        "skill_name",
        "extraction_ts",
    ]
    st.dataframe(
        filtered[display_cols].sort_values("extraction_ts", ascending=False),
        use_container_width=True,
        height=320,
        column_config={
            "maude_report_id": st.column_config.TextColumn("Report ID"),
            "product_code": st.column_config.TextColumn("Code"),
            "device_name": st.column_config.TextColumn("Device Name"),
            "severity": st.column_config.TextColumn("Severity"),
            "ai_related_flag": st.column_config.CheckboxColumn("AI-Related"),
            "ai_failure_mode": st.column_config.TextColumn("Failure Mode"),
            "confidence_score": st.column_config.NumberColumn("Confidence", format="%.2f"),
            "requires_review": st.column_config.CheckboxColumn("Needs Review"),
            "skill_name": st.column_config.TextColumn("Skill"),
            "extraction_ts": st.column_config.DatetimeColumn("Extracted At"),
        },
    )

    st.divider()
    st.markdown('<p class="ms-section">Record Detail</p>', unsafe_allow_html=True)
    report_ids = filtered["maude_report_id"].dropna().unique().tolist()
    if not report_ids:
        st.info("No records match the current filters.")
        return

    selected_id = st.selectbox("Select a MAUDE report ID", report_ids, key="rec_detail_id")
    if not selected_id:
        return

    event = db.get_normalized_event(selected_id)
    if event is None:
        st.warning(f"Normalized event not found for {selected_id}.")
        return

    detail_row = filtered[filtered["maude_report_id"] == selected_id]

    col_a, col_b, col_c = st.columns(3)
    col_a.markdown(f"**Manufacturer:** {event.manufacturer or '—'}")
    col_a.markdown(f"**Brand / Device:** {event.brand_name or '—'}")
    col_b.markdown(f"**Product code:** {event.product_code}")
    col_b.markdown(f"**Device Name:** {dn_lookup.get(event.product_code, '—')}")
    col_b.markdown(f"**Event type:** {event.event_type or '—'}")
    col_b.markdown(f"**Event date:** {event.event_date or '—'}")
    col_c.markdown(f"**Official FDA record:** [open ↗]({_maude_url(selected_id)})")

    if not detail_row.empty:
        row = detail_row.iloc[0]
        sev = _nan_to_dash(row.get("severity"))
        conf = row.get("confidence_score")
        ai_flag = row.get("ai_related_flag")
        fm = _nan_to_dash(row.get("ai_failure_mode"))
        conf_str = f"{conf:.3f}" if conf is not None else "—"
        col_c.markdown(
            f"**Severity:** {sev}  \n"
            f"**AI-related:** {'✅' if ai_flag else '❌'}  \n"
            f"**Failure mode:** {fm}  \n"
            f"**Confidence:** {conf_str}"
        )

    if event.narrative:
        with st.expander("Patient / Reporter Narrative", expanded=True):
            st.text(event.narrative)
    if event.mfr_narrative:
        with st.expander("Manufacturer Narrative"):
            st.text(event.mfr_narrative)

    st.divider()
    st.markdown('<p class="ms-section">Export</p>', unsafe_allow_html=True)
    csv_data = filtered[display_cols].to_csv(index=False)
    st.download_button(
        label="Download CSV",
        data=csv_data,
        file_name=f"maudesignal_records_{(pc_sel or 'all').replace('(all)', 'all')}.csv",
        mime="text/csv",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Page: Signals (drift + failure analysis)
# ──────────────────────────────────────────────────────────────────────────────


def _page_drift(db: Database) -> None:
    df = _extractions_dataframe(db)
    if df.empty:
        st.info("No extractions yet.")
        return

    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL].copy()

    if not df_ext.empty:
        st.markdown(
            '<p class="ms-section">Confidence Score — Extraction Timeline</p>',
            unsafe_allow_html=True,
        )
        df_ext = df_ext.sort_values("extraction_ts")
        st.line_chart(
            df_ext.set_index("extraction_ts")[["confidence_score"]],
            use_container_width=True,
            height=250,
        )

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown(
            '<p class="ms-section">AI-Related Signal Rate by Product Code</p>',
            unsafe_allow_html=True,
        )
        pc_lookup = _product_code_lookup(db)
        df_ext = df_ext.copy()
        df_ext["product_code"] = df_ext["maude_report_id"].map(pc_lookup).fillna("?")
        if not df_ext.empty:
            grouped = df_ext.groupby("product_code").agg(
                total=("maude_report_id", "count"),
                ai_count=("ai_related_flag", lambda x: x.fillna(False).astype(bool).sum()),
            )
            grouped["ai_rate"] = grouped["ai_count"] / grouped["total"]
            st.bar_chart(grouped[["ai_rate"]], use_container_width=True, height=240)

    with col_r:
        st.markdown(
            '<p class="ms-section">Confidence Distribution</p>',
            unsafe_allow_html=True,
        )
        if not df_ext.empty:
            bins = pd.cut(df_ext["confidence_score"], bins=10)
            dist = bins.value_counts().sort_index()
            dist_df = dist.reset_index()
            dist_df.columns = pd.Index(["bin", "count"])
            dist_df["bin"] = dist_df["bin"].astype(str)
            st.bar_chart(dist_df.set_index("bin"), use_container_width=True, height=240)

    st.markdown(
        '<p class="ms-section">Records Flagged for Human Review</p>', unsafe_allow_html=True
    )
    n_review = int(df_ext["requires_review"].fillna(False).astype(bool).sum())
    n_total = len(df_ext)
    if n_total:
        pct = n_review / n_total
        st.progress(pct, text=f"{n_review} / {n_total} ({pct * 100:.1f}%) require human review")


# ──────────────────────────────────────────────────────────────────────────────
# Page: Severity
# ──────────────────────────────────────────────────────────────────────────────


def _page_severity(db: Database) -> None:
    """Render the Severity breakdown page."""
    st.subheader("Severity Analysis")

    df = _extractions_dataframe(db)
    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL] if not df.empty else pd.DataFrame()

    if df_ext.empty:
        st.info("No extractions yet. Run `maudesignal extract --product-code QIH --limit 5`.")
        return

    sev_filled = df_ext["severity"].fillna("unknown")

    # KPI counts for key severity levels
    n_death = int((sev_filled == "death").sum())
    n_serious = int((sev_filled == "serious injury").sum())
    n_malfunction = int((sev_filled == "malfunction").sum())
    n_other = int(sev_filled.isin(["other", "injury", "no answer provided", "unknown"]).sum())

    st.markdown('<p class="ms-section">Severity KPIs</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    for col, val, lbl in [
        (c1, str(n_death), "Deaths"),
        (c2, str(n_serious), "Serious Injuries"),
        (c3, str(n_malfunction), "Malfunctions"),
        (c4, str(n_other), "Other / Unknown"),
    ]:
        col.markdown(
            f'<div class="ms-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Severity distribution bar chart
    st.markdown('<p class="ms-section">Severity Distribution</p>', unsafe_allow_html=True)
    sev_counts = sev_filled.value_counts().reindex(_SEVERITY_ORDER + ["unknown"], fill_value=0)
    sev_df = sev_counts[sev_counts > 0].reset_index()
    sev_df.columns = pd.Index(["Severity", "Count"])
    if not sev_df.empty:
        sev_chart = (
            alt.Chart(sev_df)
            .mark_bar()
            .encode(
                x=alt.X("Severity:N", sort=list(_SEVERITY_ORDER), axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Count:Q"),
                color=alt.Color(
                    "Severity:N",
                    scale=alt.Scale(
                        domain=list(SEVERITY_COLORS.keys()),
                        range=list(SEVERITY_COLORS.values()),
                    ),
                    legend=None,
                ),
                tooltip=["Severity", "Count"],
            )
            .properties(height=260)
        )
        st.altair_chart(sev_chart, use_container_width=True)

    # Breakdown by product code
    st.markdown(
        '<p class="ms-section">Severity Breakdown by Product Code</p>', unsafe_allow_html=True
    )
    pc_lookup = _product_code_lookup(db)
    dn_lookup = _device_name_lookup(db)
    df_ext_pc = df_ext.copy()
    df_ext_pc["product_code"] = df_ext_pc["maude_report_id"].map(pc_lookup).fillna("?")
    df_ext_pc["severity_filled"] = df_ext_pc["severity"].fillna("unknown")

    pivot = df_ext_pc.groupby(["product_code", "severity_filled"]).size().unstack(fill_value=0)
    if not pivot.empty:
        pivot_reset = pivot.reset_index()
        pivot_reset.insert(1, "Device Name", pivot_reset["product_code"].map(dn_lookup).fillna("—"))
        st.dataframe(pivot_reset, use_container_width=True, hide_index=True)

    # Records flagged by severity level
    st.markdown(
        '<p class="ms-section">Records Flagged for Review by Severity</p>',
        unsafe_allow_html=True,
    )
    sev_filter_opts = ["(all)"] + _SEVERITY_ORDER + ["unknown"]
    sev_sel = st.selectbox("Filter by severity", sev_filter_opts, key="sev_page_filter")

    df_review = df_ext_pc.copy()
    if sev_sel != "(all)":
        df_review = df_review[df_review["severity_filled"] == sev_sel]

    df_flagged = df_review[df_review["requires_review"].fillna(False).astype(bool)]
    st.caption(f"**{len(df_flagged)}** record(s) flagged for review under this filter")
    if not df_flagged.empty:
        flagged_cols = [
            "maude_report_id",
            "product_code",
            "severity_filled",
            "confidence_score",
            "extraction_ts",
        ]
        st.dataframe(
            df_flagged[flagged_cols]
            .rename(columns={"severity_filled": "severity"})
            .sort_values("extraction_ts", ascending=False),
            use_container_width=True,
            height=280,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Page: Device Catalog
# ──────────────────────────────────────────────────────────────────────────────


def _page_catalog(db: Database) -> None:
    df = _catalog_dataframe(db)

    if df.empty:
        st.info(
            "Catalog is empty.  \n"
            "Run `maudesignal catalog update` to discover all FDA-cleared AI/ML devices."
        )
        return

    n_catalog = len(df)
    n_raw = db.count_raw_reports()

    c1, c2, c3 = st.columns(3)
    for col, val, lbl in [
        (c1, str(n_catalog), "Catalog Devices"),
        (c2, str(len(df["specialty"].replace("", None).dropna().unique())), "Specialties"),
        (c3, f"{n_raw:,}", "MAUDE Reports Ingested"),
    ]:
        col.markdown(
            f'<div class="ms-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<p class="ms-section">Browse Devices</p>', unsafe_allow_html=True)

    f1, f2, f3 = st.columns(3)
    specialties = ["(all)"] + sorted({s for s in df["specialty"] if s and s.strip()})
    specialty_sel = f1.selectbox("Specialty", specialties, key="cat_spec")
    search = f2.text_input("Search name / company", key="cat_search")
    source_opts = ["(all)"] + sorted({s for s in df["source_keyword"] if s})
    source_sel = f3.selectbox("Source", source_opts, key="cat_src")

    filtered = df.copy()
    if specialty_sel != "(all)":
        filtered = filtered[filtered["specialty"] == specialty_sel]
    if search.strip():
        q = search.strip().lower()
        mask = (
            filtered["device_name"].str.lower().str.contains(q, na=False)
            | filtered["company_name"].str.lower().str.contains(q, na=False)
            | filtered["product_code"].str.lower().str.contains(q, na=False)
        )
        filtered = filtered[mask]
    if source_sel != "(all)":
        filtered = filtered[filtered["source_keyword"] == source_sel]

    st.caption(f"**{len(filtered)}** of {n_catalog} devices")

    st.dataframe(
        filtered[
            [
                "product_code",
                "device_name",
                "company_name",
                "specialty",
                "decision_date",
                "k_number",
            ]
        ].rename(
            columns={
                "product_code": "Code",
                "device_name": "Device Name",
                "company_name": "Company",
                "specialty": "Specialty",
                "decision_date": "Decision Date",
                "k_number": "510(k) Number",
            }
        ),
        use_container_width=True,
        height=400,
    )

    st.markdown('<p class="ms-section">Devices by Specialty</p>', unsafe_allow_html=True)
    spec_counts = df["specialty"].replace("", None).dropna().value_counts().head(15).reset_index()
    spec_counts.columns = pd.Index(["Specialty", "Count"])
    st.bar_chart(spec_counts.set_index("Specialty"), use_container_width=True, height=280)


# ──────────────────────────────────────────────────────────────────────────────
# Page: Root Cause & Alerts  (Phase 2)
# ──────────────────────────────────────────────────────────────────────────────


def _page_root_cause(db: Database) -> None:
    tab_rc, tab_alerts, tab_events = st.tabs(["Root Cause Reports", "Alert Rules", "Alert History"])

    # ── Root cause reports ───────────────────────────────────────────────────
    with tab_rc:
        reports = db.list_root_cause_reports()
        if not reports:
            st.info(
                "No root-cause reports yet.  \n"
                "Run `maudesignal analyze root-cause --product-code <code>` after extraction."
            )
        else:
            dn_lookup = _device_name_lookup(db)
            rows = []
            for r in reports:
                out = json.loads(r.output_json)
                rows.append(
                    {
                        "product_code": r.product_code,
                        "device_name": dn_lookup.get(r.product_code, "—"),
                        "failure_mode": r.failure_mode_category,
                        "cluster_size": r.cluster_size,
                        "confidence": r.confidence_score,
                        "review": r.requires_review,
                        "hypothesis": (out.get("root_cause_hypothesis") or "")[:120],
                        "factors": ", ".join(out.get("contributing_factors") or []),
                        "recommendation": (out.get("recommended_investigation") or "")[:120],
                        "analysis_ts": r.analysis_ts,
                    }
                )
            df_rc = pd.DataFrame(rows)
            st.caption(f"**{len(df_rc)}** root-cause report(s) on record")

            needs_review = df_rc[df_rc["review"] == True]  # noqa: E712
            if not needs_review.empty:
                st.warning(
                    f"⚠️ **{len(needs_review)} report(s) require human review** "
                    "(low confidence or small cluster)."
                )

            pc_opts = ["(all)"] + sorted(df_rc["product_code"].unique())
            pc_sel = st.selectbox("Filter by product code", pc_opts, key="rc_pc")
            filtered_rc = df_rc if pc_sel == "(all)" else df_rc[df_rc["product_code"] == pc_sel]

            for _, row in filtered_rc.iterrows():
                review_badge = "🔴 Review required" if row["review"] else "🟢 Auto-accepted"
                device_label = row["device_name"]
                with st.expander(
                    f"**{row['product_code']}** ({device_label}) — {row['failure_mode']} "
                    f"(cluster={row['cluster_size']}, conf={row['confidence']:.2f})"
                ):
                    st.markdown(f"**Status:** {review_badge}")
                    st.markdown(f"**Device:** {device_label}")
                    st.markdown(f"**Hypothesis:** {row['hypothesis']}")
                    st.markdown(f"**Contributing factors:** {row['factors']}")
                    st.markdown(f"**Recommended investigation:** {row['recommendation']}")
                    st.caption(f"Analyzed: {row['analysis_ts']}")

    # ── Alert rules ───────────────────────────────────────────────────────────
    with tab_alerts:
        rules = db.list_alert_rules(active_only=False)
        if not rules:
            st.info(
                "No alert rules configured.  \n"
                "Use `maudesignal alert add` from the CLI to create one."
            )
        else:
            rule_rows = [
                {
                    "ID": r.rule_id,
                    "Metric": r.metric,
                    "Threshold": r.threshold,
                    "Window (days)": r.window_days,
                    "Delivery": r.delivery,
                    "Scope": r.product_code or "all",
                    "Active": "✅" if r.active else "❌",
                    "Description": r.description or "",
                }
                for r in rules
            ]
            st.dataframe(
                pd.DataFrame(rule_rows),
                use_container_width=True,
                hide_index=True,
            )

    # ── Alert history ─────────────────────────────────────────────────────────
    with tab_events:
        events = db.list_alert_events(limit=200)
        if not events:
            st.info("No alerts have fired yet.")
        else:
            event_rows = [
                {
                    "Fired At": e.fired_at,
                    "Rule ID": e.rule_id,
                    "Metric": e.metric,
                    "Value": round(e.metric_value, 4),
                    "Threshold": e.threshold,
                    "Scope": e.product_code or "all",
                    "Delivered": "✅" if e.delivered else "❌",
                }
                for e in events
            ]
            df_ev = pd.DataFrame(event_rows)
            st.caption(f"**{len(df_ev)}** alert event(s) in history")
            st.dataframe(df_ev, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────────────────────────
# Page: Trends & Forecasting (Phase 3)
# ──────────────────────────────────────────────────────────────────────────────


def _page_trends(db: Database) -> None:
    """Render the Trends & Forecasting page."""
    st.subheader("Trends & Forecasting")

    with st.expander("Trend detection (CLI command)", expanded=False):
        st.caption("This panel builds the CLI command. Run it from your terminal.")
        trend_pc = st.text_input("Product code", key="trend_pc_input", placeholder="e.g. QIH")
        if st.button("Show CLI command", key="trend_run_btn"):
            if not trend_pc.strip():
                st.error("Product code is required.")
            else:
                cmd = f"maudesignal forecast trends {trend_pc.strip()}"
                st.code(cmd, language="bash")

    snapshots = db.list_trend_snapshots(limit=200)
    if not snapshots:
        st.info(
            "No trend snapshots found. Run `maudesignal forecast trends <product_code>` "
            "to generate trend analysis."
        )
        return

    dn_lookup = _device_name_lookup(db)
    rows = []
    for s in snapshots:
        try:
            out = json.loads(s.output_json)
        except json.JSONDecodeError:
            out = {}
        rows.append(
            {
                "Product Code": s.product_code,
                "Device": dn_lookup.get(s.product_code, "—"),
                "Metric": s.metric_name,
                "Direction": out.get("trend_direction", s.trend_direction),
                "Strength": out.get("trend_strength", "?"),
                "Signal Level": s.signal_level,
                "Significant": out.get("is_statistically_significant", False),
                "MK Tau": round(s.mk_tau, 3),
                "p-value": round(s.mk_p_value, 4),
                "Slope/period": round(s.slope_per_period, 5),
                "Recent": round(s.recent_value, 3),
                "Baseline": round(s.baseline_value, 3),
                "Window (days)": s.window_days,
                "Confidence": round(s.confidence_score, 2),
                "Analyzed At": s.analysis_ts,
            }
        )
    df = pd.DataFrame(rows)

    tab_summary, tab_detail, tab_narratives = st.tabs(
        ["Summary Table", "Signal Distribution", "Regulatory Narratives"]
    )

    with tab_summary:
        st.caption(f"**{len(df)}** trend snapshot(s)")

        product_codes = sorted(df["Product Code"].unique())
        selected_pc = st.selectbox("Filter by product code", ["All"] + product_codes)
        view = df if selected_pc == "All" else df[df["Product Code"] == selected_pc]

        def _color_signal(val: str) -> str:
            colors = {
                "critical": "background-color: #fadbd8",
                "elevated": "background-color: #fdebd0",
                "routine": "background-color: #d5f5e3",
                "low": "background-color: #ebedef",
            }
            return colors.get(val, "")

        styled = view.style.applymap(_color_signal, subset=["Signal Level"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab_detail:
        signal_counts = df["Signal Level"].value_counts().reset_index()
        signal_counts.columns = ["Signal Level", "Count"]
        st.caption("Signal level distribution across all snapshots")
        if not signal_counts.empty:
            st.bar_chart(signal_counts.set_index("Signal Level")["Count"])

        metric_counts = df["Metric"].value_counts().reset_index()
        metric_counts.columns = ["Metric", "Snapshots"]
        st.caption("Snapshot count by metric")
        st.dataframe(metric_counts, use_container_width=True, hide_index=True)

    with tab_narratives:
        st.caption("Regulatory narratives from the trend-interpreter Skill")
        for s in snapshots[:20]:
            try:
                out = json.loads(s.output_json)
            except json.JSONDecodeError:
                continue
            narrative = out.get("regulatory_narrative")
            if not narrative:
                continue
            signal = s.signal_level
            icon = {"critical": "🔴", "elevated": "🟡", "routine": "🔵", "low": "⚪"}.get(
                signal, "⚫"
            )
            device_label = dn_lookup.get(s.product_code, "—")
            with st.expander(
                f"{icon} {s.product_code} ({device_label}) — {s.metric_name} "
                f"({s.trend_direction}, {signal})"
            ):
                st.write(narrative)
                action = out.get("recommended_action")
                if action:
                    st.info(f"**Recommended action:** {action}")


# ──────────────────────────────────────────────────────────────────────────────
# Page: PSUR Reports (Phase 5)
# ──────────────────────────────────────────────────────────────────────────────


def _page_psur(db: Database) -> None:
    """Render the PSUR Reports page."""
    st.subheader("PSUR Report Drafts")

    with st.expander("PSUR generation (CLI command)", expanded=False):
        st.caption("This panel builds the CLI command. Run it from your terminal.")
        gen_pc = st.text_input("Product code", key="psur_gen_pc", placeholder="e.g. QIH")
        gen_device = st.text_input("Device name (optional)", key="psur_gen_device")
        gen_window = st.number_input(
            "Reporting window (days)",
            value=180,
            min_value=30,
            max_value=730,
            key="psur_gen_window",
        )
        if st.button("Show CLI command", key="psur_gen_btn"):
            if not gen_pc.strip():
                st.error("Product code is required.")
            else:
                cmd = (
                    f"maudesignal psur generate {gen_pc.strip()}"
                    f' --device-name "{gen_device}" --window {gen_window}'
                )
                st.code(cmd, language="bash")

    reports = db.list_psur_reports(limit=100)
    if not reports:
        st.info(
            "No PSUR reports found. Run `maudesignal psur generate <product_code>` "
            "to generate a PSUR draft."
        )
        return

    dn_lookup = _device_name_lookup(db)
    rows = []
    for r in reports:
        try:
            out = json.loads(r.output_json)
        except json.JSONDecodeError:
            out = {}
        rows.append(
            {
                "Report ID": r.report_id,
                "Product": r.product_code,
                "Device": dn_lookup.get(r.product_code, "—"),
                "Period Start": r.reporting_period_start,
                "Period End": r.reporting_period_end,
                "Signal": r.signal_assessment,
                "Confidence": round(r.confidence_score, 2),
                "Drafted At": r.drafted_at,
                "_out": out,
            }
        )
    df = pd.DataFrame(rows)

    # Summary metrics
    n_confirmed = sum(1 for r in reports if r.signal_assessment == "confirmed_signal")
    n_potential = sum(1 for r in reports if r.signal_assessment == "potential_signal")
    n_none = sum(1 for r in reports if r.signal_assessment == "no_signal")
    c1, c2, c3 = st.columns(3)
    c1.metric("Confirmed Signals", n_confirmed)
    c2.metric("Potential Signals", n_potential)
    c3.metric("No Signal", n_none)

    tab_table, tab_detail = st.tabs(["All Drafts", "View Draft"])

    with tab_table:

        def _color_signal(val: str) -> str:
            colors = {
                "confirmed_signal": "background-color: #fadbd8",
                "potential_signal": "background-color: #fdebd0",
                "no_signal": "background-color: #d5f5e3",
            }
            return colors.get(val, "")

        display_cols = [c for c in df.columns if c != "_out"]
        styled = df[display_cols].style.applymap(_color_signal, subset=["Signal"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab_detail:
        if not reports:
            return
        report_ids = [r.report_id for r in reports]
        selected_id = st.selectbox("Select report to view", report_ids)
        selected = next((r for r in rows if r["Report ID"] == selected_id), None)
        if selected is None:
            return

        out = selected["_out"]
        st.markdown(f"**Report:** `{selected_id}`")
        st.markdown(
            f"**Product:** {selected['Product']}  |  "
            f"**Device:** {selected['Device']}  |  "
            f"**Period:** {selected['Period Start']} → {selected['Period End']}  |  "
            f"**Signal:** {selected['Signal']}  |  "
            f"**Confidence:** {selected['Confidence']}"
        )
        st.divider()

        exec_sum = out.get("executive_summary", "")
        if exec_sum:
            st.markdown("**Executive Summary**")
            st.write(exec_sum)

        sections = out.get("sections", [])
        for sec in sections:
            with st.expander(sec.get("title", "Section")):
                st.write(sec.get("content", ""))

        actions = out.get("recommended_actions", [])
        if actions:
            st.markdown("**Recommended Actions**")
            for i, action in enumerate(actions, 1):
                st.markdown(f"{i}. {action}")

        st.caption("⚠️ DRAFT — REQUIRES HUMAN REVIEW BEFORE SUBMISSION TO ANY REGULATORY BODY")


# ──────────────────────────────────────────────────────────────────────────────
# Page: External Sources (Phase 4)
# ──────────────────────────────────────────────────────────────────────────────


def _page_sources(db: Database) -> None:
    """Render the External Sources page."""
    st.subheader("External Sources")

    with st.expander("Source fetch (CLI command)", expanded=False):
        st.caption("This panel builds the CLI command. Run it from your terminal.")
        src_query = st.text_input(
            "Search query",
            key="src_query",
            placeholder="e.g. AI radiology device failure",
        )
        src_pc = st.text_input("Product code (optional)", key="src_pc_input")
        if st.button("Show CLI command", key="src_fetch_btn"):
            if not src_query.strip():
                st.error("Search query is required.")
            else:
                pc_flag = f"--product-code {src_pc.strip()}" if src_pc.strip() else ""
                cmd = f'maudesignal sources fetch --query "{src_query}" {pc_flag}'.strip()
                st.code(cmd, language="bash")

    all_sources = db.list_external_sources(limit=500)
    if not all_sources:
        st.info(
            "No external sources found. Run `maudesignal sources fetch pubmed --query ...` "
            "or `maudesignal sources fetch clinicaltrials --query ...` to populate."
        )
        return

    pubmed_count = sum(1 for s in all_sources if s.source_type == "pubmed")
    ct_count = sum(1 for s in all_sources if s.source_type == "clinicaltrials")

    col1, col2 = st.columns(2)
    col1.metric("PubMed Articles", pubmed_count)
    col2.metric("Clinical Trials", ct_count)

    tab_pubmed, tab_trials = st.tabs(["PubMed Publications", "ClinicalTrials.gov"])

    with tab_pubmed:
        pubmed = [s for s in all_sources if s.source_type == "pubmed"]
        if not pubmed:
            st.info("No PubMed records. Run `sources fetch pubmed --query ...`")
        else:
            product_codes = sorted({s.product_code for s in pubmed if s.product_code})
            filter_pc = st.selectbox(
                "Filter by product code (PubMed)", ["All"] + product_codes, key="pm_pc"
            )
            view = (
                pubmed if filter_pc == "All" else [s for s in pubmed if s.product_code == filter_pc]
            )
            rows = [
                {
                    "PMID": s.source_id,
                    "Title": s.title or "",
                    "Authors": s.authors or "",
                    "Date": s.publication_date or "",
                    "Product": s.product_code or "—",
                    "URL": s.url or "",
                }
                for s in view
            ]
            df_pm = pd.DataFrame(rows)
            st.caption(f"**{len(df_pm)}** PubMed article(s)")
            st.dataframe(df_pm, use_container_width=True, hide_index=True)

    with tab_trials:
        trials = [s for s in all_sources if s.source_type == "clinicaltrials"]
        if not trials:
            st.info("No ClinicalTrials records. Run `sources fetch clinicaltrials --query ...`")
        else:
            product_codes_ct = sorted({s.product_code for s in trials if s.product_code})
            filter_pc_ct = st.selectbox(
                "Filter by product code (ClinicalTrials)",
                ["All"] + product_codes_ct,
                key="ct_pc",
            )
            view_ct = (
                trials
                if filter_pc_ct == "All"
                else [s for s in trials if s.product_code == filter_pc_ct]
            )
            rows_ct = [
                {
                    "NCT ID": s.source_id,
                    "Title": s.title or "",
                    "Summary": (s.abstract or "")[:100],
                    "Date": s.publication_date or "",
                    "Product": s.product_code or "—",
                    "URL": s.url or "",
                }
                for s in view_ct
            ]
            df_ct = pd.DataFrame(rows_ct)
            st.caption(f"**{len(df_ct)}** ClinicalTrials record(s)")
            st.dataframe(df_ct, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────────────────────────
# App shell
# ──────────────────────────────────────────────────────────────────────────────


def _render_app(db: Database) -> None:
    st.set_page_config(
        page_title="MaudeSignal",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    # Single source-of-truth nav key — must be initialised before any widget renders
    if "nav_active_page" not in st.session_state:
        st.session_state["nav_active_page"] = "Overview"

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        if _LOGO_PATH.exists():
            st.image(str(_LOGO_PATH), width=150)
        else:
            st.markdown("## MaudeSignal")
        st.caption("FDA AI/ML Postmarket Surveillance")
        st.divider()

        # ── Global date-range filter (P2-1) ──────────────────────────────────
        st.markdown("**Date range**")
        date_preset = st.selectbox(
            "Date range",
            ["Last 30 days", "Last 90 days", "Last 12 months", "All time"],
            index=2,
            key="global_date_preset",
            label_visibility="collapsed",
        )
        now = datetime.now(UTC)
        _preset_map = {
            "Last 30 days": now - timedelta(days=30),
            "Last 90 days": now - timedelta(days=90),
            "Last 12 months": now - timedelta(days=365),
            "All time": datetime(2000, 1, 1, tzinfo=UTC),
        }
        global_since: datetime = _preset_map[date_preset]
        st.session_state["global_since"] = global_since

        st.divider()

        # ── Grouped navigation — button-based, no post-widget state mutation ──
        for group_name, pages in _PAGE_GROUPS.items():
            st.markdown(f"**{group_name}**")
            for p in pages:
                is_active = st.session_state["nav_active_page"] == p
                label = f"● {p}" if is_active else f"○ {p}"
                if st.button(label, key=f"nav_btn_{p}", use_container_width=True):
                    st.session_state["nav_active_page"] = p
                    st.rerun()

        st.divider()

        # ── Sidebar footer (P2-7) ─────────────────────────────────────────────
        n_cat = db.count_catalog_devices()
        n_raw = db.count_raw_reports()
        n_rules = len(db.list_alert_rules(active_only=True))
        cost = db.total_llm_cost_usd()
        last_ext = db.list_extractions()
        if last_ext:
            last_ts = max(r.extraction_ts for r in last_ext)
            delta = datetime.now() - last_ts
            freshness = f"{delta.seconds // 3600}h ago" if delta.days == 0 else f"{delta.days}d ago"
        else:
            freshness = "never"
        st.caption(f"📦 Catalog: {n_cat} devices")
        st.caption(f"📄 MAUDE reports: {n_raw:,}")
        st.caption(f"🔔 Alert rules: {n_rules} active")
        st.caption(f"💵 LLM cost: ${cost:.4f}")
        st.caption(f"🕐 Last extraction: {freshness}")

    page: str = st.session_state["nav_active_page"]

    # ── Catalog-empty warning for device names (P1-3) ─────────────────────────
    if n_cat == 0:
        st.warning(
            "Device names not populated. "
            "Run **`maudesignal catalog fetch`** to discover all FDA-cleared AI/ML devices.",
            icon="⚠️",
        )

    # ── Header banner ─────────────────────────────────────────────────────────
    page_subtitles = {
        "Overview": "Executive summary of postmarket signal activity",
        "Records": "Structured extraction results per MAUDE report",
        "Severity": "Severity distribution, KPIs, and records flagged by severity level",
        "Signals & Drift": "Temporal signal trends and confidence drift",
        "Root Cause & Alerts": "Root-cause hypotheses and alert rule management",
        "Trends & Forecasting": "Statistical trend detection (Mann-Kendall + linear regression)",
        "External Sources": "PubMed publications and ClinicalTrials.gov studies",
        "PSUR Reports": "Automated periodic safety update report drafts",
        "Device Catalog": "FDA-cleared AI/ML device registry",
    }
    st.markdown(
        f'<div class="ms-banner">'
        f"<div>"
        f"<h1>MaudeSignal</h1>"
        f'<p>{page_subtitles.get(page, "")}</p>'
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Route (P1-4: spinner on transition) ──────────────────────────────────
    _page_fn = {
        "Overview": _page_summary,
        "Records": _page_records,
        "Severity": _page_severity,
        "Signals & Drift": _page_drift,
        "Root Cause & Alerts": _page_root_cause,
        "Trends & Forecasting": _page_trends,
        "External Sources": _page_sources,
        "PSUR Reports": _page_psur,
        "Device Catalog": _page_catalog,
    }
    fn = _page_fn.get(page, _page_summary)
    with st.spinner("Loading…"):
        fn(db)

    st.markdown(
        '<div class="ms-footer">MaudeSignal — open-source FDA AI/ML postmarket surveillance '
        "| Data: openFDA (public domain) | Not for clinical use</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    """Streamlit entry point. Run via `streamlit run` or `maudesignal-dashboard`."""
    if not _running_under_streamlit():
        import subprocess

        script = Path(__file__).resolve()
        subprocess.run(["streamlit", "run", str(script)], check=False)
        return
    db = _load_db()
    _render_app(db)


def _running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def _is_main_module() -> bool:
    return __name__ == "__main__" or "streamlit" in sys.modules and _running_under_streamlit()


if _is_main_module():
    _db: Any = _load_db()
    _render_app(_db)
