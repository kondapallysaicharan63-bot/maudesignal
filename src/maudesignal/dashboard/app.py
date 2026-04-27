"""Streamlit dashboard for MaudeSignal extraction data."""

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
    """Map maude_report_id -> product_code for join in the records table."""
    events = db.list_normalized_events()
    return {e.maude_report_id: e.product_code for e in events}


def _page_records(db: Database) -> None:
    st.header("Extracted records")
    df = _extractions_dataframe(db)
    if df.empty:
        st.info("No extractions yet. Run `maudesignal extract` to populate.")
        return

    pc_lookup = _product_code_lookup(db)
    df["product_code"] = df["maude_report_id"].map(pc_lookup).fillna("?")

    cols = st.columns(3)
    pc_options = ["(all)"] + sorted({p for p in df["product_code"].dropna() if p})
    pc_sel = cols[0].selectbox("product_code", pc_options)
    sev_options = ["(all)"] + sorted({s for s in df["severity"].dropna() if s})
    sev_sel = cols[1].selectbox("severity", sev_options)
    skill_options = ["(all)"] + sorted({s for s in df["skill_name"].dropna() if s})
    skill_sel = cols[2].selectbox("skill", skill_options)

    filtered = df.copy()
    if pc_sel != "(all)":
        filtered = filtered[filtered["product_code"] == pc_sel]
    if sev_sel != "(all)":
        filtered = filtered[filtered["severity"] == sev_sel]
    if skill_sel != "(all)":
        filtered = filtered[filtered["skill_name"] == skill_sel]

    st.caption(f"{len(filtered)} of {len(df)} rows")
    display_cols = [
        "extraction_ts",
        "maude_report_id",
        "product_code",
        "severity",
        "ai_related_flag",
        "ai_failure_mode",
        "failure_mode",
        "confidence_score",
        "requires_review",
        "skill_name",
    ]
    st.dataframe(filtered[display_cols], use_container_width=True)


def _page_drift(db: Database) -> None:
    st.header("Drift — confidence score over time")
    df = _extractions_dataframe(db)
    if df.empty:
        st.info("No extractions yet.")
        return
    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL].copy()
    if df_ext.empty:
        st.info("No extractor (Skill #1) runs yet.")
        return
    df_ext = df_ext.sort_values("extraction_ts")
    chart_df = df_ext.set_index("extraction_ts")[["confidence_score"]]
    st.line_chart(chart_df)
    st.caption(f"{len(df_ext)} extractor runs plotted.")


def _page_summary(db: Database) -> None:
    st.header("Summary")
    df = _extractions_dataframe(db)
    if df.empty:
        st.info("No extractions yet.")
        return
    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL]
    n_total = len(df_ext)
    n_ai = int(df_ext["ai_related_flag"].fillna(False).astype(bool).sum())
    pct_ai = (n_ai / n_total * 100.0) if n_total else 0.0
    avg_conf = float(df_ext["confidence_score"].mean()) if n_total else 0.0
    cost = db.total_llm_cost_usd()

    cols = st.columns(4)
    cols[0].metric("Total extractions", n_total)
    cols[1].metric("AI-related", f"{pct_ai:.1f}%")
    cols[2].metric("Avg confidence", f"{avg_conf:.2f}")
    cols[3].metric("Total LLM cost", f"${cost:.2f}")


def _render_app(db: Database) -> None:
    st.set_page_config(page_title="MaudeSignal", layout="wide")
    st.title("MaudeSignal — postmarket signal dashboard")
    page = st.sidebar.radio("Page", ["Records", "Drift", "Summary"])
    if page == "Records":
        _page_records(db)
    elif page == "Drift":
        _page_drift(db)
    else:
        _page_summary(db)


def main() -> None:
    """Streamlit entry point. Run via `streamlit run` or `maudesignal-dashboard`."""
    # When invoked directly via `maudesignal-dashboard`, re-exec under streamlit.
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


# Streamlit imports the module directly; trigger render when run as script.
def _is_main_module() -> bool:
    return __name__ == "__main__" or "streamlit" in sys.modules and _running_under_streamlit()


if _is_main_module():
    _db: Any = _load_db()
    _render_app(_db)
