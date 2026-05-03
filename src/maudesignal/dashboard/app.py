"""MaudeSignal Streamlit dashboard — FDA AI/ML postmarket surveillance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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
_FAILURE_MODE_COLORS = {
    "performance_degradation": "#2874a6",
    "false_positive": "#1abc9c",
    "false_negative": "#e74c3c",
    "software_failure": "#9b59b6",
    "user_interface_failure": "#f39c12",
    "hardware_sensor_failure": "#16a085",
    "unknown": "#95a5a6",
}


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
                "severity": payload.get("severity"),
                "ai_related_flag": payload.get("ai_related_flag"),
                "ai_failure_mode": payload.get("failure_mode_category"),
                "failure_mode": payload.get("failure_mode"),
                "model_used": r.model_used,
            }
        )
    return pd.DataFrame.from_records(records)


def _product_code_lookup(db: Database) -> dict[str, str]:
    events = db.list_normalized_events()
    return {e.maude_report_id: e.product_code for e in events}


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
        st.bar_chart(sev_df.set_index("Severity"), use_container_width=True, height=230)

    with col_right:
        st.markdown('<p class="ms-section">AI Failure Mode Breakdown</p>', unsafe_allow_html=True)
        df_cls = df[df["skill_name"] == CLASSIFIER_SKILL]
        if df_cls.empty:
            st.caption("No Skill #4 classifications yet.")
        else:
            fm_counts = df_cls["ai_failure_mode"].fillna("unknown").value_counts().head(8)
            fm_df = fm_counts.reset_index()
            fm_df.columns = pd.Index(["Failure Mode", "Count"])
            st.bar_chart(fm_df.set_index("Failure Mode"), use_container_width=True, height=230)

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

    st.caption(f"**{len(filtered)}** of {len(df)} rows")

    display_cols = [
        "maude_report_id",
        "product_code",
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
    col_b.markdown(f"**Event type:** {event.event_type or '—'}")
    col_b.markdown(f"**Event date:** {event.event_date or '—'}")
    col_c.markdown(f"**Official FDA record:** [open ↗]({_maude_url(selected_id)})")

    if not detail_row.empty:
        row = detail_row.iloc[0]
        sev = row.get("severity") or "—"
        conf = row.get("confidence_score")
        ai_flag = row.get("ai_related_flag")
        fm = row.get("ai_failure_mode") or "—"
        col_c.markdown(
            f"**Severity:** {sev}  \n"
            f"**AI-related:** {'✅' if ai_flag else '❌'}  \n"
            f"**Failure mode:** {fm}  \n"
            f"**Confidence:** {conf:.3f}"
            if conf is not None
            else ""
        )

    if event.narrative:
        with st.expander("Patient / Reporter Narrative", expanded=True):
            st.text(event.narrative)
    if event.mfr_narrative:
        with st.expander("Manufacturer Narrative"):
            st.text(event.mfr_narrative)


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
            rows = []
            for r in reports:
                out = json.loads(r.output_json)
                rows.append(
                    {
                        "product_code": r.product_code,
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
                with st.expander(
                    f"**{row['product_code']}** — {row['failure_mode']} "
                    f"(cluster={row['cluster_size']}, conf={row['confidence']:.2f})"
                ):
                    st.markdown(f"**Status:** {review_badge}")
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
# App shell
# ──────────────────────────────────────────────────────────────────────────────


def _render_app(db: Database) -> None:
    st.set_page_config(
        page_title="MaudeSignal",
        page_icon="🔬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🔬 MaudeSignal")
        st.caption("FDA AI/ML Postmarket Surveillance")
        st.divider()
        page = st.radio(
            "Navigation",
            ["Overview", "Records", "Signals & Drift", "Root Cause & Alerts", "Device Catalog"],
            label_visibility="collapsed",
        )
        st.divider()
        n_cat = db.count_catalog_devices()
        n_raw = db.count_raw_reports()
        n_rules = len(db.list_alert_rules(active_only=True))
        st.caption(f"📦 Catalog: {n_cat} devices")
        st.caption(f"📄 MAUDE reports: {n_raw:,}")
        st.caption(f"🔔 Alert rules: {n_rules} active")
        cost = db.total_llm_cost_usd()
        st.caption(f"💵 LLM cost: ${cost:.4f}")

    # ── Header banner ─────────────────────────────────────────────────────────
    page_subtitles = {
        "Overview": "Executive summary of postmarket signal activity",
        "Records": "Structured extraction results per MAUDE report",
        "Signals & Drift": "Temporal signal trends and confidence drift",
        "Root Cause & Alerts": "Root-cause hypotheses and alert rule management",
        "Device Catalog": "FDA-cleared AI/ML device registry",
    }
    st.markdown(
        f'<div class="ms-banner">'
        f"<div>"
        f"<h1>MaudeSignal</h1>"
        f'<p>{page_subtitles.get(page or "Overview", "")}</p>'
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Route ─────────────────────────────────────────────────────────────────
    if page == "Overview":
        _page_summary(db)
    elif page == "Records":
        _page_records(db)
    elif page == "Signals & Drift":
        _page_drift(db)
    elif page == "Root Cause & Alerts":
        _page_root_cause(db)
    elif page == "Device Catalog":
        _page_catalog(db)

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
