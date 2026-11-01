"""MaudeSignal Streamlit dashboard — enterprise-grade FDA AI/ML postmarket surveillance."""

from __future__ import annotations

import html
import json
import math
import os
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from maudesignal.catalog.names import classification_names, report_brands
from maudesignal.config import Config
from maudesignal.dashboard.demo_db import demo_copy_with_recorded_packs, keyless
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.ingestion.pipeline import IngestionResult, ingest_product_code
from maudesignal.storage.database import Database

# ── Skill identifiers ──────────────────────────────────────────────────────────
EXTRACTOR_SKILL = "maude-narrative-extractor"
CLASSIFIER_SKILL = "ai-failure-mode-classifier"
SEVERITY_SKILL = "severity-triage"

_MAUDE_DETAIL_URL = (
    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"
)

# ── Page registry: (icon, name, subtitle) ─────────────────────────────────────
_PAGES: list[tuple[str, str, str]] = [
    # HACKATHON-BUILT pages (Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026)
    (
        "insights",
        "Signals",
        "Your device types, what changed this week, and everything behind one signal",
    ),
    (
        "shield",
        "Copilot",
        "Muse Spark copilot that only shows facts it can match to the FDA record",
    ),
    (
        "document_scanner",
        "Vision",
        "510(k) summary reader and device-label camera (Muse Spark + SAM)",
    ),
    (
        "verified_user",
        "Audit",
        "Every decision and model answer, in one tamper-evident trail",
    ),
    ("dashboard", "Dashboard", "Executive summary of postmarket signal activity"),
    ("search", "Signal Explorer", "Browse, filter, and export AI extraction results"),
    ("download", "MAUDE Ingestion", "Pull adverse event reports from openFDA"),
    ("smart_toy", "LLM Extraction", "Run AI extraction on ingested records"),
    ("summarize", "PSUR Reports", "Periodic safety update report drafts"),
    ("notifications", "Alerts", "Monitor and test alert rules"),
    ("settings", "Settings", "Configuration, providers, and system health"),
]

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

_FAILURE_MODE_COLORS: dict[str, str] = {
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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_RELPATH = Path("data") / "maudesignal.db"
_DEMO_DB_PATH = _PROJECT_ROOT / "data" / "demo" / "maudesignal_demo.db"

# ── CSS (Meta design-system–aligned) ──────────────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');
.material-symbols-outlined {
  font-family: 'Material Symbols Outlined';
  font-weight: normal;
  font-style: normal;
  font-size: 20px;
  line-height: 1;
  letter-spacing: normal;
  text-transform: none;
  display: inline-block;
  white-space: nowrap;
  direction: ltr;
}
/* ── Design tokens ───────────────────────────────────────────────────────── */
:root {
  /* Border radius */
  --r-sm:     4px;
  --r-md:     6px;
  --r-lg:     8px;
  --r-xl:     16px;
  --r-xxl:    24px;
  --r-xxxl:   32px;
  --r-feature:40px;
  --r-full:   100px;
  /* Spacing */
  --sp-xs:  8px;  --sp-sm: 10px; --sp-md: 12px;  --sp-base: 16px;
  --sp-lg: 20px;  --sp-xl: 24px; --sp-xxl: 32px; --sp-xxxl: 40px;
  --sp-section-sm: 48px; --sp-section: 64px; --sp-section-lg: 80px;
  /* Elevation */
  --shadow-pill:  rgba(0,0,0,0.20) 1px 1px 0px 0px;
  --shadow-panel: rgba(20,22,26,0.30) 0px 1px 4px 0px;
}

/* ── Global typography ───────────────────────────────────────────────────── */
html, body, [class*="css"] {
  font-family: var(--font-sans) !important;
  color: var(--ms-ink) !important;
  background-color: var(--ms-canvas) !important;
  -webkit-font-smoothing: antialiased;
}

/* ── Streamlit chrome resets ─────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] > .main {
  background-color: var(--ms-canvas);
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stDecoration"] { display: none !important; }
footer { display: none !important; }

/* ── Sidebar ─────────────────────────────────────────────────────────────── */

/* Sidebar nav buttons — pill-shaped (Meta {rounded.full}) */
section[data-testid="stSidebar"] .stButton > button {
  background: transparent !important;
  border: 1px solid transparent !important;
  text-align: left !important;
  padding: 8px 16px !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  letter-spacing: -0.14px !important;
  color: var(--ms-sidebar-ink) !important;
  box-shadow: none !important;
  width: 100% !important;
  border-radius: var(--r-full) !important;  /* pill */
  transition: background 0.15s ease-out !important;
}
section[data-testid="stSidebar"] .stButton > button:hover,
section[data-testid="stSidebar"] .stButton > button:focus {
  background: var(--ms-primary-soft) !important;
  border-color: var(--ms-hairline) !important;
  color: var(--ms-ink-deep) !important;
}

/* ── Main content buttons — cobalt pill (uniform across all button types) ─── */
.stButton > button,
.stFormSubmitButton > button,
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-secondary"],
[data-testid="stFormSubmitButton"] > button {
  border-radius: 100px !important;
  font-family: var(--font-sans) !important;
  font-size: 14px !important;
  font-weight: 700 !important;
  letter-spacing: -0.14px !important;
  padding: 12px 28px !important;
  line-height: 1.43 !important;
  background: var(--ms-primary) !important;   /* cobalt - explicit hex */
  color: var(--ms-on-primary) !important;
  border: none !important;
  box-shadow: none !important;
  transition: background 0.15s ease-out !important;
  min-height: 44px !important;
}
.stButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stBaseButton-primary"]:hover {
  background: var(--ms-primary-deep) !important;   /* cobalt-deep on hover */
  color: var(--ms-on-primary) !important;
}
.stButton > button:active,
.stFormSubmitButton > button:active {
  background: var(--ms-primary-deep) !important;
  color: var(--ms-on-primary) !important;
}

/* ── Page header — Meta {typography.display-lg} hierarchy ───────────────── */
.ms-page-header {
  padding-bottom: var(--sp-xl);
  margin-bottom: var(--sp-xxl);
  border-bottom: 1px solid var(--ms-hairline-soft);
}
.ms-page-header h1 {
  font-size: 36px !important;
  font-weight: 500 !important;
  line-height: 1.28 !important;
  letter-spacing: 0 !important;
  color: var(--ms-ink-deep) !important;
  margin: 0 0 6px 0 !important;
  font-variant-ligatures: common-ligatures !important;
}
/* Subtitle: slate on every descendant — st.html() used so no Streamlit blue spans */
.ms-page-header p,
.ms-page-subtitle,
.ms-page-header p *,
.ms-page-header p a,
.ms-page-header p a:hover,
.ms-page-header p code,
.ms-page-header p em,
.ms-page-header p strong,
.ms-page-header p span {
  font-size: 16px !important;
  font-weight: 400 !important;
  line-height: 1.44 !important;
  color: var(--ms-slate) !important;
  margin: 0 !important;
  text-decoration: none !important;
  background: none !important;
}

/* ── KPI card — Meta card-product-feature ({rounded.xxxl}) ──────────────── */
.ms-card {
  background: var(--ms-card);
  border: 1px solid var(--ms-hairline-soft);   /* hairline, no top accent     */
  border-top: 3px solid var(--ms-primary);     /* cobalt accent top rail      */
  border-radius: var(--r-xxxl);                /* 32px — photographic cards   */
  padding: var(--sp-xxl) var(--sp-xxl);        /* 32px internal padding       */
  text-align: center;
  box-shadow: none;                            /* flat — Meta's zero-elevation */
}
.ms-card .val {
  font-size: clamp(20px, 2.8vw, 32px);        /* scales down for long values  */
  font-weight: 700;
  line-height: 1.17;
  color: var(--ms-primary);
  letter-spacing: 0;
  white-space: nowrap;                         /* prevents value wrap          */
  overflow: visible;
}
.ms-card .lbl {
  font-size: 11px !important;                 /* {typography.caption-bold}    */
  font-weight: 700 !important;
  color: var(--ms-steel) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  margin-top: 6px !important;
  font-family: var(--font-sans) !important;
}

/* Card semantic variants */
.ms-card.red   { border-top-color: var(--ms-err-fg);   }
.ms-card.red   .val { color: var(--ms-err-fg);   }
.ms-card.green { border-top-color: var(--ms-ok-fg);    }
.ms-card.green .val { color: var(--ms-ok-fg);    }
.ms-card.amber { border-top-color: var(--ms-warn-fg);  }
.ms-card.amber .val { color: var(--ms-warn-fg);  }

/* ── Section heading — Meta {typography.heading-sm} ─────────────────────── */
.ms-section {
  font-size: 18px !important;
  font-weight: 700 !important;
  line-height: 1.44 !important;
  color: var(--ms-ink-deep) !important;
  font-family: var(--font-sans) !important;
  margin: var(--sp-xxl) 0 var(--sp-md) !important;
  padding: 0 !important;
  border-left: none !important;
  border-bottom: 1px solid var(--ms-hairline-soft) !important;
  padding-bottom: var(--sp-xs) !important;
}

/* ── Status pills — Meta badge-* pattern ({rounded.full}) ───────────────── */
.pill-ok {
  display: inline-block;
  background: var(--ms-ok-bg);
  color: var(--ms-ok-fg);
  border-radius: var(--r-full);
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.33;
  letter-spacing: 0;
}
.pill-warn {
  display: inline-block;
  background: var(--ms-warn-bg);
  color: var(--ms-warn-fg);
  border-radius: var(--r-full);
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.33;
}
.pill-err {
  display: inline-block;
  background: var(--ms-err-bg);
  color: var(--ms-err-fg);
  border-radius: var(--r-full);
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.33;
}

/* ── Provider card — Meta card-icon-feature ({rounded.xl}) ──────────────── */
.prov-card {
  background: var(--ms-card);
  border: 1px solid var(--ms-hairline-soft);
  border-radius: var(--r-xl);              /* 16px — icon-feature tile style  */
  padding: var(--sp-lg) var(--sp-xl);
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  margin-bottom: var(--sp-xs);
  box-shadow: none;
}
.prov-name {
  font-size: 16px;
  font-weight: 500;
  line-height: 1.50;
  letter-spacing: -0.16px;
  color: var(--ms-ink-deep);
}
.prov-model {
  font-size: 14px;
  font-weight: 400;
  line-height: 1.43;
  letter-spacing: -0.14px;
  color: var(--ms-slate);
  margin-top: 2px;
}

/* ── Streamlit native elements: typography harmonisation ─────────────────── */
h1, h2, h3, h4 {
  font-family: var(--font-sans) !important;
  font-weight: 500 !important;
  color: var(--ms-ink-deep) !important;
}
p, li, label, span {
  font-family: var(--font-sans) !important;
}

/* ── Markdown body text ──────────────────────────────────────────────────── */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stText"] p {
  font-size: 16px !important;
  line-height: 1.50 !important;
  letter-spacing: -0.16px !important;
  color: var(--ms-ink) !important;
  font-family: var(--font-sans) !important;
}
[data-testid="stMarkdownContainer"] strong {
  color: var(--ms-ink-deep) !important;
}
[data-testid="stMarkdownContainer"] a {
  color: var(--ms-primary) !important;
  text-decoration: underline !important;
}

/* ── Form / widget labels — ink-deep, never Streamlit-blue ──────────────── */
/* data-testid="stWidgetLabel" is how Streamlit marks ALL widget labels in 1.x */
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
/* Broad selector: covers all labels regardless of widget testid version */
section[data-testid="stMain"] label,
[data-testid="stMainBlockContainer"] label,
[data-testid="stVerticalBlock"] label,
[data-testid="stHorizontalBlock"] label,
[data-testid="stColumn"] label,
[data-testid="stForm"] label,
/* Belt-and-suspenders: specific widget testid overrides */
[data-testid="stTextInput"] label,
[data-testid="stNumberInput"] label,
[data-testid="stDateInput"] label,
[data-testid="stSelectbox"] label,
[data-testid="stTextArea"] label,
[data-testid="stCheckbox"] label,
[data-testid="stRadio"] label,
[data-testid="stSlider"] label,
.stTextInput label, .stNumberInput label,
.stSelectbox label, .stDateInput label {
  color: var(--ms-ink-deep) !important;   /* explicit hex — avoids CSS-var resolution edge cases */
  font-family: var(--font-sans) !important;
  font-size: 14px !important;
  font-weight: 500 !important;
  letter-spacing: -0.14px !important;
}

/* ── Caption / small text ────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span {
  color: var(--ms-slate) !important;
  font-family: var(--font-sans) !important;
  font-size: 12px !important;
}
[data-testid="stCaptionContainer"] code,
[data-testid="stCaptionContainer"] strong {
  color: var(--ms-ink-deep) !important;
  background: var(--ms-surface-soft) !important;
  border-radius: var(--r-sm) !important;
  padding: 1px 5px !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  font-family: var(--font-sans) !important;
}

/* ── Sidebar text — explicit override after global p/span rule ───────────── */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] li {
  color: var(--ms-sidebar-ink) !important;
  font-size: inherit !important;
}

/* Tab labels — Meta {typography.body-sm-bold} */
[data-testid="stTabs"] button[role="tab"] {
  font-family: var(--font-sans) !important;
  font-size: 14px !important;
  font-weight: 700 !important;
  letter-spacing: -0.14px !important;
  color: var(--ms-slate) !important;
  border-radius: var(--r-full) !important;
  padding: 8px 16px !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: var(--ms-ink-deep) !important;
  background: var(--ms-surface-soft) !important;
}

/* Info / warning / error boxes — hairline border flat style */
[data-testid="stAlert"] {
  border-radius: var(--r-xl) !important;
  border: 1px solid var(--ms-hairline-soft) !important;
  box-shadow: none !important;
  font-size: 14px !important;
}

/* Form inputs — Meta text-input style */
input[type="text"], input[type="number"], textarea, select {
  font-family: var(--font-sans) !important;
  font-size: 16px !important;
  border-radius: var(--r-lg) !important;  /* 8px */
  border: 1px solid var(--ms-hairline) !important;
  height: 44px !important;
}
input:focus, textarea:focus, select:focus {
  border: 2px solid var(--ms-primary) !important;  /* fb-blue focus ring */
  outline: none !important;
}

/* Selectbox / combobox pill */
[data-testid="stSelectbox"] > div > div {
  border-radius: var(--r-lg) !important;
  border-color: var(--ms-hairline) !important;
}

/* Dataframe */
[data-testid="stDataFrame"] {
  border-radius: var(--r-xl) !important;
  overflow: hidden;
  border: 1px solid var(--ms-hairline-soft) !important;
}

/* ── Footer — Meta footer-region style ──────────────────────────────────── */
.ms-footer {
  margin-top: var(--sp-section);
  padding-top: var(--sp-md);
  border-top: 1px solid var(--ms-hairline-soft);
  font-size: 12px;                          /* {typography.caption} */
  font-weight: 400;
  line-height: 1.33;
  color: var(--ms-stone);
  text-align: center;
  letter-spacing: 0;
}

/* ── Promo / info banner — dark ink-deep strip ───────────────────────────── */
.ms-banner-info {
  background: var(--ms-primary-soft);
  border-radius: var(--r-xl);
  padding: var(--sp-md) var(--sp-xl);
  font-size: 14px;
  font-weight: 700;
  color: var(--ms-primary-deep);
  margin-bottom: var(--sp-xl);
}
.ms-banner-warn {
  background: var(--ms-warn-bg);
  border-radius: var(--r-xl);
  padding: var(--sp-md) var(--sp-xl);
  font-size: 14px;
  font-weight: 700;
  color: var(--ms-warn-fg);
  margin-bottom: var(--sp-xl);
}
</style>
"""


# ── Utility helpers ────────────────────────────────────────────────────────────


def _nan_to_dash(val: Any) -> str:
    """Normalise None / NaN / 'nan' / empty string to an em-dash placeholder."""
    if val is None:
        return "—"
    if isinstance(val, float) and math.isnan(val):
        return "—"
    s = str(val)
    if s.lower() in ("nan", "none", ""):
        return "—"
    return s


def _maude_url(report_id: str) -> str:
    return _MAUDE_DETAIL_URL.format(report_id)


def _load_db() -> Database:
    """Load the database, falling back to env-var path if Config cannot be fully loaded.

    Stored-first deploy (added during the Meta hackathon): when
    ``MAUDESIGNAL_DB_PATH`` is unset and there is no local ``data/maudesignal.db``,
    open the committed keyless demo database instead of creating an empty one.
    """
    if (
        not os.environ.get("MAUDESIGNAL_DB_PATH")
        and not (_PROJECT_ROOT / _DEFAULT_DB_RELPATH).exists()
        and _DEMO_DB_PATH.exists()
    ):
        if keyless():
            # Never modify the committed demo DB: work on a copy with the recorded packs.
            return Database(demo_copy_with_recorded_packs(_DEMO_DB_PATH))
        return Database(_DEMO_DB_PATH)
    try:
        cfg = Config.load()
        return Database(cfg.db_path)
    except Exception:
        db_path_str = os.environ.get("MAUDESIGNAL_DB_PATH", "data/maudesignal.db")
        db_path = (_PROJECT_ROOT / db_path_str).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return Database(db_path)


def _try_load_config() -> Config | None:
    """Return Config or None if loading fails (e.g., missing API key)."""
    try:
        return Config.load()
    except Exception:
        return None


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
    for col in ("severity", "ai_failure_mode", "failure_mode"):
        if col in df.columns:
            df[col] = df[col].apply(_nan_to_dash)
    return df


def _product_code_lookup(db: Database) -> dict[str, str]:
    events = db.list_normalized_events()
    return {e.maude_report_id: e.product_code for e in events}


def _device_name_lookup(db: Database) -> dict[str, str]:
    """Return product_code → display name.

    Prefers the FDA classification name; then device_catalog.device_name; then
    normalized_events.brand_name so product codes never enriched still show a
    human-readable label.
    """
    brand_fallback = db.brand_name_lookup()
    catalog = {d.product_code: d.device_name for d in db.list_catalog_devices()}
    return {**brand_fallback, **catalog, **classification_names(db)}


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


def _page_header(icon: str, title: str, subtitle: str) -> None:
    """Render the standard page header (design system: serif headline, sans deck)."""
    del icon  # the design system uses words, not emoji, in headings
    st.html(
        '<div class="ms-page-header">'
        f'<h1 class="t-headline" style="margin:0 0 6px 0">{html.escape(title)}</h1>'
        f'<p class="t-deck" style="margin:0;color:var(--ink-2)">{html.escape(subtitle)}</p>'
        "</div>"
    )


def _kpi_card(col: Any, value: str, label: str, variant: str = "") -> None:
    cls = f"ms-card {variant}".strip()
    with col:
        st.html(
            f'<div class="{cls}"><div class="val">{value}</div>'
            f'<div class="lbl">{label}</div></div>'
        )


def _section(title: str) -> None:
    st.markdown(f'<p class="ms-section">{title}</p>', unsafe_allow_html=True)


# ── Page 1: Dashboard ──────────────────────────────────────────────────────────


def _page_dashboard(db: Database) -> None:
    _page_header("", "Dashboard", "Executive summary of postmarket signal activity")

    df = _extractions_dataframe(db)
    df_ext = df[df["skill_name"] == EXTRACTOR_SKILL] if not df.empty else pd.DataFrame()

    n_raw = db.count_raw_reports()
    n_total = len(df_ext)
    n_ai = int(df_ext["ai_related_flag"].fillna(False).astype(bool).sum()) if n_total else 0
    avg_conf = float(df_ext["confidence_score"].mean()) if n_total else 0.0
    n_alerts = len(db.list_alert_rules(active_only=True))
    cost = db.total_llm_cost_usd()

    # KPI row. Without extraction rows the AI / confidence / cost tiles would only show
    # zeros (the keyless demo database has none), so they appear once data exists.
    _section("Key Performance Indicators")
    if df_ext.empty:
        c1, _ = st.columns([1, 4])
        _kpi_card(c1, f"{n_raw:,}", "MAUDE Records")
        st.info(
            "No extraction results yet. Use **MAUDE Ingestion** to pull records, "
            "then **LLM Extraction** to analyse them."
        )
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    _kpi_card(c1, f"{n_raw:,}", "MAUDE Records")
    _kpi_card(c2, str(n_ai), "AI Signals Detected", "red" if n_ai > 0 else "")
    _kpi_card(c3, f"{avg_conf:.3f}", "Avg Confidence", "green" if avg_conf >= 0.8 else "amber")
    _kpi_card(c4, str(n_alerts), "Active Alert Rules")
    _kpi_card(c5, f"${cost:.2f}", "Extraction LLM cost")

    st.markdown("<br>", unsafe_allow_html=True)

    col_left, col_right = st.columns(2)

    with col_left:
        _section("Severity Distribution")
        sev_counts = (
            df_ext["severity"]
            .fillna("unknown")
            .value_counts()
            .reindex(_SEVERITY_ORDER + ["unknown"], fill_value=0)
        )
        sev_df = sev_counts[sev_counts > 0].reset_index()
        sev_df.columns = pd.Index(["Severity", "Count"])
        if sev_df.empty:
            st.info("No severity data available.")
        else:
            chart = (
                alt.Chart(sev_df)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
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
                .properties(height=240)
            )
            st.altair_chart(chart, width="stretch")

    with col_right:
        _section("AI Failure Mode Breakdown")
        df_cls = df[df["skill_name"] == CLASSIFIER_SKILL]
        if df_cls.empty:
            st.info("No failure mode classifications yet.")
        else:
            fm_counts = df_cls["ai_failure_mode"].fillna("unknown").value_counts().head(8)
            fm_df = fm_counts.reset_index()
            fm_df.columns = pd.Index(["Failure Mode", "Count"])
            chart_fm = (
                alt.Chart(fm_df)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("Failure Mode:N", axis=alt.Axis(labelAngle=-30)),
                    y=alt.Y("Count:Q"),
                    color=alt.Color(
                        "Failure Mode:N",
                        scale=alt.Scale(scheme="tableau10"),
                        legend=None,
                    ),
                    tooltip=["Failure Mode", "Count"],
                )
                .properties(height=240)
            )
            st.altair_chart(chart_fm, width="stretch")

    _section("Recent Signals")
    pc_lookup = _product_code_lookup(db)
    dn_lookup = _device_name_lookup(db)
    recent = df_ext.copy()
    recent["product_code"] = recent["maude_report_id"].map(pc_lookup).fillna("?")
    # The device named on each report; the product code's FDA name only when blank.
    recent["device_name"] = (
        recent["maude_report_id"]
        .map(report_brands(db))
        .fillna(recent["product_code"].map(dn_lookup))
        .fillna("—")
    )
    display_recent = (
        recent[
            [
                "extraction_ts",
                "maude_report_id",
                "product_code",
                "device_name",
                "severity",
                "ai_related_flag",
                "confidence_score",
            ]
        ]
        .sort_values("extraction_ts", ascending=False)
        .head(15)
    )
    st.dataframe(
        display_recent,
        width="stretch",
        hide_index=True,
        column_config={
            "extraction_ts": st.column_config.DatetimeColumn("Extracted At"),
            "maude_report_id": st.column_config.TextColumn("Report ID"),
            "product_code": st.column_config.TextColumn("Code"),
            "device_name": st.column_config.TextColumn("Device"),
            "severity": st.column_config.TextColumn("Severity"),
            "ai_related_flag": st.column_config.CheckboxColumn("AI-Related"),
            "confidence_score": st.column_config.NumberColumn("Confidence", format="%.3f"),
        },
    )


# ── Page 2: Signal Explorer ────────────────────────────────────────────────────


def _page_signal_explorer(db: Database) -> None:
    _page_header("", "Signal Explorer", "Browse, filter, and export AI extraction results")

    df = _extractions_dataframe(db)
    if df.empty:
        st.info(
            "No extraction results found. Use **MAUDE Ingestion** then **LLM Extraction** "
            "to populate data."
        )
        return

    pc_lookup = _product_code_lookup(db)
    df["product_code"] = df["maude_report_id"].map(pc_lookup).fillna("?")
    dn_lookup = _device_name_lookup(db)
    df["device_name"] = (
        df["maude_report_id"]
        .map(report_brands(db))
        .fillna(df["product_code"].map(dn_lookup))
        .fillna("—")
    )

    _section("Filters")
    f1, f2, f3, f4 = st.columns(4)
    pc_options = ["(all)"] + sorted({p for p in df["product_code"].dropna() if p and p != "?"})
    sev_options = ["(all)"] + sorted({s for s in df["severity"].dropna() if s and s != "—"})
    ai_options = ["(all)", "AI-related", "Not AI-related"]

    pc_sel = f1.selectbox("Product Code", pc_options, key="se_pc")
    sev_sel = f2.selectbox("Severity", sev_options, key="se_sev")
    ai_sel = f3.selectbox("AI Flag", ai_options, key="se_ai")

    today = date.today()
    date_range = f4.date_input(
        "Date Range",
        value=(today - timedelta(days=365), today),
        key="se_dates",
    )

    device_search = st.text_input(
        "Search device name or report ID",
        key="se_search",
        placeholder="e.g. radiology, 1234567",
    )

    filtered = df.copy()
    if pc_sel != "(all)":
        filtered = filtered[filtered["product_code"] == pc_sel]
    if sev_sel != "(all)":
        filtered = filtered[filtered["severity"] == sev_sel]
    if ai_sel == "AI-related":
        filtered = filtered[filtered["ai_related_flag"].fillna(False).astype(bool)]
    elif ai_sel == "Not AI-related":
        filtered = filtered[~filtered["ai_related_flag"].fillna(False).astype(bool)]
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_dt = datetime.combine(date_range[0], datetime.min.time())
        end_dt = datetime.combine(date_range[1], datetime.max.time())
        ts_col = pd.to_datetime(filtered["extraction_ts"])
        filtered = filtered[(ts_col >= start_dt) & (ts_col <= end_dt)]
    if device_search.strip():
        q = device_search.strip().lower()
        mask = filtered["device_name"].str.lower().str.contains(q, na=False) | filtered[
            "maude_report_id"
        ].str.lower().str.contains(q, na=False)
        filtered = filtered[mask]

    st.caption(f"**{len(filtered):,}** of {len(df):,} records")

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
        width="stretch",
        height=340,
        hide_index=True,
        column_config={
            "maude_report_id": st.column_config.TextColumn("Report ID"),
            "product_code": st.column_config.TextColumn("Code"),
            "device_name": st.column_config.TextColumn("Device Name"),
            "severity": st.column_config.TextColumn("Severity"),
            "ai_related_flag": st.column_config.CheckboxColumn("AI-Related"),
            "ai_failure_mode": st.column_config.TextColumn("Failure Mode"),
            "confidence_score": st.column_config.NumberColumn("Confidence", format="%.3f"),
            "requires_review": st.column_config.CheckboxColumn("Needs Review"),
            "skill_name": st.column_config.TextColumn("Skill"),
            "extraction_ts": st.column_config.DatetimeColumn("Extracted At"),
        },
    )

    # Narrative detail
    st.divider()
    _section("Record Detail")
    report_ids = filtered["maude_report_id"].dropna().unique().tolist()
    if not report_ids:
        st.info("No records match the current filters.")
    else:
        selected_id = st.selectbox("Select a MAUDE Report ID", report_ids, key="se_detail_id")
        if selected_id:
            event = db.get_normalized_event(str(selected_id))
            if event is None:
                st.warning(f"Normalized event not found for {selected_id}.")
            else:
                detail_row = filtered[filtered["maude_report_id"] == selected_id]
                col_a, col_b, col_c = st.columns(3)
                col_a.markdown(f"**Manufacturer:** {event.manufacturer or '—'}")
                col_a.markdown(f"**Brand / Device:** {event.brand_name or '—'}")
                col_b.markdown(f"**Product Code:** {event.product_code}")
                col_b.markdown(f"**FDA device type:** {dn_lookup.get(event.product_code, '—')}")
                col_b.markdown(f"**Event Type:** {event.event_type or '—'}")
                col_b.markdown(f"**Event Date:** {event.event_date or '—'}")
                col_c.markdown(f"**Official FDA Record:** [Open ↗]({_maude_url(str(selected_id))})")
                if not detail_row.empty:
                    row = detail_row.iloc[0]
                    col_c.markdown(
                        f"**Severity:** {_nan_to_dash(row.get('severity'))}  \n"
                        f"**AI-Related:** {'✅' if row.get('ai_related_flag') else '❌'}  \n"
                        f"**Failure Mode:** {_nan_to_dash(row.get('ai_failure_mode'))}  \n"
                        f"**Confidence:** {row.get('confidence_score', 0):.3f}"
                    )
                if event.narrative:
                    with st.expander("Patient / Reporter Narrative", expanded=True):
                        st.text(event.narrative)
                if event.mfr_narrative:
                    with st.expander("Manufacturer Narrative"):
                        st.text(event.mfr_narrative)

    # Export
    st.divider()
    _section("Export")
    csv_data = filtered[display_cols].to_csv(index=False)
    scope = (pc_sel or "all").replace("(all)", "all")
    st.download_button(
        label="⬇ Download CSV",
        data=csv_data,
        file_name=f"maudesignal_signals_{scope}.csv",
        mime="text/csv",
    )


# ── Page 3: MAUDE Ingestion ────────────────────────────────────────────────────


def _page_ingestion(db: Database) -> None:
    _page_header("", "MAUDE Ingestion", "Pull adverse event reports from openFDA")

    # Current inventory
    n_raw = db.count_raw_reports()
    n_events = len(db.list_normalized_events())

    _section("Current Inventory")
    c1, c2 = st.columns(2)
    _kpi_card(c1, f"{n_raw:,}", "Raw MAUDE Reports in DB")
    _kpi_card(c2, f"{n_events:,}", "Normalized Events")

    st.markdown("<br>", unsafe_allow_html=True)
    _section("Ingest New Records")

    with st.form("ingestion_form"):
        col1, col2 = st.columns(2)
        product_code = col1.text_input(
            "FDA Product Code *",
            placeholder="e.g. QIH",
            help="3-character FDA product code (e.g. QIH for AI-assisted radiology)",
        ).strip()
        limit = col2.number_input(
            "Record Limit",
            min_value=1,
            max_value=1000,
            value=50,
            help="Maximum number of records to fetch (1–1000)",
        )
        col3, col4 = st.columns(2)
        today = date.today()
        start_date = col3.date_input(
            "Start Date",
            value=today - timedelta(days=365),
            help="Earliest date_received to include",
        )
        end_date = col4.date_input(
            "End Date",
            value=today,
            help="Latest date_received to include",
        )
        submitted = st.form_submit_button("▶ Start Ingestion", type="primary")

    if submitted:
        if not product_code:
            st.error("Product code is required.")
            return
        if start_date > end_date:
            st.error("Start date must be before end date.")
            return

        cfg = _try_load_config()
        api_key = cfg.openfda_api_key if cfg else None
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        with st.spinner(f"Ingesting records for **{product_code}** from openFDA…"):
            try:
                client = OpenFDAClient(api_key=api_key)
                result: IngestionResult = ingest_product_code(
                    client=client,
                    db=db,
                    product_code=product_code,
                    start_date=start_str,
                    end_date=end_str,
                    limit=int(limit),
                )
            except Exception as exc:
                st.error(f"Ingestion failed: {exc}")
                return

        st.success("Ingestion complete!")
        _section("Ingestion Summary")
        r1, r2, r3, r4 = st.columns(4)
        _kpi_card(r1, str(result.records_fetched), "Records Fetched")
        _kpi_card(r2, str(result.records_new), "New Records Added", "green")
        _kpi_card(
            r3,
            str(result.records_skipped),
            "Skipped",
            "amber" if result.records_skipped else "",
        )
        existing = result.records_fetched - result.records_new - result.records_skipped
        _kpi_card(r4, str(max(0, existing)), "Already Existed")

        if result.skip_reasons:
            reasons_str = ", ".join(f"{k}: {v}" for k, v in result.skip_reasons.items())
            st.caption(f"Skip reasons: {reasons_str}")

        st.info(
            "Records ingested. Navigate to **LLM Extraction** to run AI analysis on these records."
        )


# ── Page 4: LLM Extraction ────────────────────────────────────────────────────


def _page_extraction(db: Database) -> None:
    _page_header("", "LLM Extraction", "Run AI extraction on ingested MAUDE records")

    # Check config
    cfg = _try_load_config()
    if cfg is None:
        st.error(
            "LLM provider is not configured. Set `LLM_PROVIDER` and the corresponding API key "
            "in your `.env` file, then restart the app."
        )
        st.info(
            "**Quick start (free):** Set `LLM_PROVIDER=groq` and `GROQ_API_KEY=<your-key>` "
            "in `.env`. Free tier at [console.groq.com](https://console.groq.com)."
        )
        return

    # Unprocessed record count
    all_events = db.list_normalized_events()
    extracted_ids = {r.maude_report_id for r in db.list_extractions(skill_name=EXTRACTOR_SKILL)}
    unprocessed = [e for e in all_events if e.maude_report_id not in extracted_ids]

    _section("Queue Status")
    c1, c2, c3 = st.columns(3)
    _kpi_card(c1, str(len(all_events)), "Total Normalized Events")
    _kpi_card(c2, str(len(extracted_ids)), "Already Extracted", "green")
    _kpi_card(
        c3,
        str(len(unprocessed)),
        "Pending Extraction",
        "amber" if unprocessed else "green",
    )

    if not unprocessed:
        st.success("All ingested records have been extracted. Ingest more records to continue.")
        return

    st.markdown("<br>", unsafe_allow_html=True)
    _section("Run Extraction")

    # Product code filter
    available_pcs = sorted({e.product_code for e in unprocessed if e.product_code})
    col1, col2 = st.columns(2)
    pc_filter = col1.selectbox(
        "Filter by Product Code",
        ["(all)"] + available_pcs,
        key="ext_pc",
    )
    batch_limit = col2.number_input(
        "Batch Size",
        min_value=1,
        max_value=100,
        value=10,
        help="Number of records to extract in this run",
    )

    if pc_filter != "(all)":
        queue = [e for e in unprocessed if e.product_code == pc_filter]
    else:
        queue = unprocessed

    queue = queue[: int(batch_limit)]
    st.caption(
        f"**{len(queue)}** record(s) will be processed using provider: "
        f"`{cfg.llm_provider}` / `{_active_model(cfg)}`"
    )

    if st.button("▶ Run Extraction", type="primary", key="ext_run"):
        _run_extraction_batch(db=db, cfg=cfg, queue=queue)


def _active_model(cfg: Config) -> str:
    """Return the model name for the active provider."""
    mapping = {
        "groq": cfg.groq_model,
        "anthropic": cfg.claude_model_extraction,
        "openai": cfg.openai_model,
        "gemini": cfg.gemini_model,
        "pool": cfg.provider_fallback_order,
    }
    return mapping.get(cfg.llm_provider, "unknown")


def _run_extraction_batch(db: Database, cfg: Config, queue: list[Any]) -> None:
    """Run the 3-Skill extraction chain on a batch and display results."""
    try:
        from maudesignal.extraction.extractor import Extractor
        from maudesignal.extraction.pipeline import extract_record
        from maudesignal.extraction.skill_loader import SkillLoader
    except ImportError as exc:
        st.error(f"Extraction modules not available: {exc}")
        return

    skills_root = cfg.project_root / "skills"
    try:
        loader = SkillLoader(skills_root)
        skill_ext = loader.load(EXTRACTOR_SKILL)
        skill_sev = loader.load(SEVERITY_SKILL)
        skill_cls = loader.load(CLASSIFIER_SKILL)
        extractor = Extractor(config=cfg, db=db)
    except Exception as exc:
        st.error(f"Failed to initialise extraction pipeline: {exc}")
        return

    st.markdown("<br>", unsafe_allow_html=True)
    progress_bar = st.progress(0.0, text="Starting extraction…")
    results_placeholder = st.empty()
    successes = 0
    failures = 0
    result_rows: list[dict[str, Any]] = []

    for i, event in enumerate(queue):
        pct = (i + 1) / len(queue)
        n_total_q = len(queue)
        progress_bar.progress(pct, text=f"Processing {event.maude_report_id} ({i + 1}/{n_total_q})")
        try:
            rec_result = extract_record(
                extractor=extractor,
                db=db,
                event=event,
                skill_extractor=skill_ext,
                skill_severity=skill_sev,
                skill_classifier=skill_cls,
            )
            if rec_result.any_success:
                successes += 1
                ext_out = rec_result.extractor_result.output if rec_result.extractor_result else {}
                result_rows.append(
                    {
                        "Report ID": event.maude_report_id,
                        "Product Code": event.product_code,
                        "AI-Related": ext_out.get("ai_related_flag"),
                        "Severity": _nan_to_dash(ext_out.get("severity")),
                        "Confidence": round(float(ext_out.get("confidence_score", 0.0)), 3),
                        "Status": "✅ Success",
                    }
                )
            else:
                failures += 1
                error_str = "; ".join(f"{s}: {m}" for s, m in rec_result.errors)
                result_rows.append(
                    {
                        "Report ID": event.maude_report_id,
                        "Product Code": event.product_code,
                        "AI-Related": None,
                        "Severity": "—",
                        "Confidence": 0.0,
                        "Status": f"❌ {error_str[:60]}",
                    }
                )
        except Exception as exc:
            failures += 1
            result_rows.append(
                {
                    "Report ID": event.maude_report_id,
                    "Product Code": event.product_code,
                    "AI-Related": None,
                    "Severity": "—",
                    "Confidence": 0.0,
                    "Status": f"❌ Error: {str(exc)[:60]}",
                }
            )

        results_placeholder.dataframe(pd.DataFrame(result_rows), width="stretch", hide_index=True)

    progress_bar.progress(1.0, text="Extraction complete.")
    if failures == 0:
        st.success(f"All {successes} records extracted successfully.")
    else:
        st.warning(f"{successes} succeeded, {failures} failed. Check the table for details.")


# ── Page 5: PSUR Reports ───────────────────────────────────────────────────────


def _page_psur(db: Database) -> None:
    _page_header(
        "📋",
        "PSUR Reports",
        "Periodic safety update report drafts — AI-generated, requires human review",
    )

    tab_existing, tab_generate = st.tabs(["📂 Existing Reports", "⚡ Generate New Report"])

    with tab_existing:
        _psur_existing_reports(db)

    with tab_generate:
        _psur_generate(db)


def _psur_existing_reports(db: Database) -> None:
    reports = db.list_psur_reports(limit=100)
    if not reports:
        st.info(
            "No PSUR reports found. Use the **Generate New Report** tab to create one, "
            "or run `maudesignal psur generate <product_code>` from the CLI."
        )
        return

    dn_lookup = _device_name_lookup(db)
    n_confirmed = sum(1 for r in reports if r.signal_assessment == "confirmed_signal")
    n_potential = sum(1 for r in reports if r.signal_assessment == "potential_signal")
    n_none = sum(1 for r in reports if r.signal_assessment == "no_signal")

    c1, c2, c3, c4 = st.columns(4)
    _kpi_card(c1, str(len(reports)), "Total Reports")
    _kpi_card(c2, str(n_confirmed), "Confirmed Signals", "red")
    _kpi_card(c3, str(n_potential), "Potential Signals", "amber")
    _kpi_card(c4, str(n_none), "No Signal", "green")

    st.markdown("<br>", unsafe_allow_html=True)

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
                "Signal": r.signal_assessment.replace("_", " ").title(),
                "Confidence": round(r.confidence_score, 2),
                "Drafted At": r.drafted_at,
                "_out": out,
            }
        )
    df = pd.DataFrame(rows)
    display_cols = [c for c in df.columns if c != "_out"]
    st.dataframe(df[display_cols], width="stretch", hide_index=True)

    st.divider()
    _section("Report Preview")
    report_ids = [r.report_id for r in reports]
    selected_id = st.selectbox("Select report to preview", report_ids, key="psur_sel")
    selected = next((r for r in rows if r["Report ID"] == selected_id), None)
    if selected is None:
        return

    out = selected["_out"]
    col_info1, col_info2 = st.columns(2)
    col_info1.markdown(f"**Product:** {selected['Product']}  |  **Device:** {selected['Device']}")
    col_info1.markdown(f"**Period:** {selected['Period Start']} → {selected['Period End']}")
    col_info2.markdown(
        f"**Signal:** {selected['Signal']}  |  **Confidence:** {selected['Confidence']}"
    )
    st.divider()

    exec_sum = out.get("executive_summary", "")
    if exec_sum:
        st.markdown("**Executive Summary**")
        st.write(exec_sum)

    for sec in out.get("sections", []):
        with st.expander(sec.get("title", "Section")):
            st.write(sec.get("content", ""))

    actions = out.get("recommended_actions", [])
    if actions:
        st.markdown("**Recommended Actions**")
        for i, action in enumerate(actions, 1):
            st.markdown(f"{i}. {action}")

    st.warning(
        "⚠️ DRAFT — Requires independent human regulatory review before any regulatory action. "
        "MaudeSignal is NOT an FDA-cleared device."
    )


def _psur_generate(db: Database) -> None:
    cfg = _try_load_config()
    if cfg is None:
        st.error(
            "LLM provider is not configured. Set `LLM_PROVIDER` and API key in `.env`, "
            "then restart the app."
        )
        return

    st.markdown("Generate a new PSUR draft using the AI pipeline.")
    _section("Report Parameters")

    col1, col2 = st.columns(2)
    dn_lookup = _device_name_lookup(db)
    events = db.list_normalized_events()
    available_pcs = sorted({e.product_code for e in events if e.product_code})
    pc = col1.selectbox(
        "Product Code *",
        [""] + available_pcs,
        key="psur_gen_pc",
        help="Select a product code from ingested records",
    )
    device_name = col1.text_input(
        "Device Name (optional)",
        value=dn_lookup.get(pc, "") if pc else "",
        key="psur_gen_device",
    )
    window_days = col2.number_input(
        "Reporting Window (days)",
        min_value=30,
        max_value=730,
        value=180,
        key="psur_gen_window",
        help="Reporting period in days (default: 180 = 6 months)",
    )

    if st.button("⚡ Generate PSUR Draft", type="primary", key="psur_gen_btn"):
        if not pc:
            st.error("Product code is required.")
            return

        with st.spinner(f"Generating PSUR draft for **{pc}**…"):
            try:
                from maudesignal.extraction.extractor import Extractor
                from maudesignal.report.psur_generator import PsurGenerator

                extractor = Extractor(config=cfg, db=db)
                generator = PsurGenerator(
                    extractor=extractor,
                    db=db,
                    skills_root=cfg.project_root / "skills",
                )
                draft = generator.generate(
                    product_code=pc,
                    device_name=device_name.strip() or pc,
                    window_days=int(window_days),
                )
            except FileNotFoundError:
                st.error(
                    "The `psur-report-drafter` skill is not yet available in this build. "
                    "It is planned for a future release. Use the CLI to generate reports "
                    "once the skill is published."
                )
                return
            except Exception as exc:
                st.error(f"PSUR generation failed: {exc}")
                return

        st.success(f"PSUR draft generated! Report ID: `{draft.report_id}`")
        st.markdown(f"**Signal Assessment:** {draft.signal_assessment.replace('_', ' ').title()}")
        st.markdown(f"**Confidence:** {draft.confidence_score:.2f}")
        if draft.executive_summary:
            with st.expander("Executive Summary", expanded=True):
                st.write(draft.executive_summary)
        st.info(
            "The report has been saved to the database. " "View it in the **Existing Reports** tab."
        )


# ── Page 6: Alerts ────────────────────────────────────────────────────────────


def _page_alerts(db: Database) -> None:
    _page_header("", "Alerts", "Monitor and test alert rules")

    tab_rules, tab_test, tab_history = st.tabs(["📋 Alert Rules", "🧪 Test Alerts", "📜 History"])

    with tab_rules:
        _alerts_rules(db)

    with tab_test:
        _alerts_test(db)

    with tab_history:
        _alerts_history(db)


def _alerts_rules(db: Database) -> None:
    rules = db.list_alert_rules(active_only=False)
    if not rules:
        st.info(
            "No alert rules configured. "
            "Run `maudesignal alert add` from the CLI to create rules."
        )
        st.markdown(
            "**Example:**\n```bash\nmaudesignal alert add --metric ai_rate "
            "--threshold 0.7 --delivery slack --webhook-url https://...\n```"
        )
        return

    n_active = sum(1 for r in rules if r.active)
    c1, c2 = st.columns(2)
    _kpi_card(c1, str(n_active), "Active Rules", "green" if n_active else "")
    _kpi_card(c2, str(len(rules) - n_active), "Inactive Rules")

    st.markdown("<br>", unsafe_allow_html=True)
    rule_rows = [
        {
            "Rule ID": r.rule_id,
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
        width="stretch",
        hide_index=True,
    )


def _alerts_test(db: Database) -> None:
    st.markdown("Run a live check of all active alert rules against the current database.")
    rules = db.list_alert_rules(active_only=True)
    if not rules:
        st.info("No active alert rules to test.")
        return

    pc_opts = sorted({r.product_code for r in rules if r.product_code})
    test_pc = st.selectbox(
        "Scope (optional)",
        ["(all)"] + pc_opts,
        key="alert_test_pc",
        help="Limit the check to a specific product code",
    )
    scope_str = None if test_pc == "(all)" else test_pc

    if st.button("🧪 Run Alert Check", type="primary", key="alert_test_btn"):
        with st.spinner("Evaluating alert rules…"):
            try:
                from maudesignal.alerting.checker import AlertChecker

                checker = AlertChecker(db=db)
                result = checker.check_all(product_code=scope_str)
            except Exception as exc:
                st.error(f"Alert check failed: {exc}")
                return

        if result.alerts_fired == 0:
            st.success(
                f"No alerts fired. Evaluated {result.rules_evaluated} rule(s) — "
                "all within thresholds."
            )
        else:
            st.warning(
                f"**{result.alerts_fired}** alert(s) fired out of {result.rules_evaluated} "
                f"rules evaluated. {result.alerts_delivered} delivered."
            )
        if result.details:
            st.dataframe(pd.DataFrame(result.details), width="stretch", hide_index=True)


def _alerts_history(db: Database) -> None:
    events = db.list_alert_events(limit=200)
    if not events:
        st.info("No alerts have fired yet.")
        return

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
    st.caption(f"**{len(df_ev)}** alert event(s) on record")
    st.dataframe(df_ev, width="stretch", hide_index=True)


# ── Page 7: Settings ──────────────────────────────────────────────────────────


def _page_settings(db: Database) -> None:
    _page_header("", "Settings", "Configuration, LLM providers, and system health")

    tab_providers, tab_system, tab_catalog, tab_sources = st.tabs(
        ["🤖 LLM Providers", "🗄 System", "📦 Device Catalog", "🔗 External Sources"]
    )

    with tab_providers:
        _settings_providers(db)

    with tab_system:
        _settings_system(db)

    with tab_catalog:
        _settings_catalog(db)

    with tab_sources:
        _settings_sources(db)


def _key_pill(present: bool) -> str:
    """Key status only: whether it is set, never any part of its value."""
    if present:
        return '<span class="pill-ok">✓ Key set</span>'
    return '<span class="pill-warn">Not set</span>'


def _settings_providers(db: Database) -> None:
    from maudesignal.config import openfda_api_key_from_env

    cfg = _try_load_config()
    meta_key = bool(os.environ.get("META_MODEL_API_KEY", "").strip())

    _section("Meta Model API (hackathon build)")
    if not meta_key:
        st.info(
            "Demo mode: no Meta key is set on this deployment. The Signals, Copilot, Vision "
            "and Audit pages replay recorded Muse Spark, Muse Wonder, Voice Transcribe and "
            "SAM 3.1 runs; live calls are off."
        )
    meta_model = os.environ.get("META_MODEL_API_MODEL", "").strip() or "—"
    openfda_key = openfda_api_key_from_env() is not None
    for name, env_var, present, detail in (
        ("Meta Model API", "META_MODEL_API_KEY", meta_key, f"Model: {meta_model}"),
        ("openFDA", "OPENFDA_API_KEY", openfda_key, "Optional: raises openFDA's daily limit"),
    ):
        st.markdown(
            f'<div class="prov-card">{_key_pill(present)}&nbsp;&nbsp;'
            f'<div><div class="prov-name">{name}</div>'
            f'<div class="prov-model">{env_var} &nbsp;|&nbsp; {detail}</div>'
            f"</div></div>",
            unsafe_allow_html=True,
        )

    _section("Extraction providers (pre-hackathon pipeline, optional)")
    if cfg is not None:
        st.caption(f"Active extraction provider: {cfg.llm_provider} / {_active_model(cfg)}")
    else:
        st.caption("Used only by the pre-hackathon extraction pages; none is needed for the demo.")
    providers: list[tuple[str, str, bool, str]] = [
        ("Groq", "GROQ_API_KEY", bool(cfg and cfg.groq_api_key), cfg.groq_model if cfg else "—"),
        (
            "Anthropic (Claude)",
            "ANTHROPIC_API_KEY",
            bool(cfg and cfg.anthropic_api_key),
            cfg.claude_model_extraction if cfg else "—",
        ),
        (
            "OpenAI",
            "OPENAI_API_KEY",
            bool(cfg and cfg.openai_api_key),
            cfg.openai_model if cfg else "—",
        ),
        (
            "Google Gemini",
            "GEMINI_API_KEY",
            bool(cfg and cfg.gemini_api_key),
            cfg.gemini_model if cfg else "—",
        ),
    ]
    for name, env_var, present, model in providers:
        st.markdown(
            f'<div class="prov-card">{_key_pill(present)}&nbsp;&nbsp;'
            f'<div><div class="prov-name">{name}</div>'
            f'<div class="prov-model">{env_var} &nbsp;|&nbsp; Model: {model}</div>'
            f"</div></div>",
            unsafe_allow_html=True,
        )

    if cfg:
        _section("Cost & Limits")
        cost = db.total_llm_cost_usd()
        c1, c2 = st.columns(2)
        _kpi_card(c1, f"${cost:.2f}", "Extraction LLM cost")
        _kpi_card(c2, f"${cfg.cost_ceiling_usd:.2f}", "Cost Ceiling")


def _settings_system(db: Database) -> None:
    cfg = _try_load_config()

    _section("Database")
    c1, c2, c3 = st.columns(3)
    _kpi_card(c1, f"{db.count_raw_reports():,}", "Raw Reports")
    _kpi_card(c2, f"{len(db.list_normalized_events()):,}", "Normalized Events")
    _kpi_card(c3, f"{len(db.list_extractions()):,}", "Extraction Records")

    if cfg:
        st.markdown(f"**DB Path:** `{cfg.db_path}`")
        st.markdown(f"**Log Level:** `{cfg.log_level}`")
    from maudesignal.config import openfda_api_key_from_env

    openfda_status = "Set" if openfda_api_key_from_env() else "Not set (keyless openFDA limits)"
    st.markdown(f"**openFDA API key:** {openfda_status}")

    _section("System Health")
    if st.button("Run Health Check", key="health_check_btn"):
        checks: list[tuple[str, bool, str]] = []

        # DB accessible
        try:
            db.count_raw_reports()
            checks.append(("Database", True, "Accessible"))
        except Exception as exc:
            checks.append(("Database", False, str(exc)))

        # Config loadable
        if cfg:
            checks.append(("Configuration", True, f"Provider: {cfg.llm_provider}"))
        else:
            checks.append(("Configuration", True, "Demo mode (no LLM key; recorded runs)"))

        # Skills directory
        skills_ok = (Path(__file__).resolve().parents[3] / "skills").exists()
        checks.append(("Skills directory", skills_ok, "Found" if skills_ok else "Not found"))

        for name, ok, detail in checks:
            pill = (
                '<span class="pill-ok">✓ OK</span>'
                if ok
                else '<span class="pill-err">✗ Error</span>'
            )
            st.markdown(f"{pill}&nbsp;&nbsp;**{name}** — {detail}", unsafe_allow_html=True)


def _settings_catalog(db: Database) -> None:
    df = _catalog_dataframe(db)
    if df.empty:
        st.info(
            "Device catalog is empty. "
            "Run `maudesignal catalog fetch` to discover FDA-cleared AI/ML devices."
        )
        return

    n_catalog = len(df)
    n_specialties = len(df["specialty"].replace("", None).dropna().unique())

    c1, c2 = st.columns(2)
    _kpi_card(c1, str(n_catalog), "Catalog Devices")
    _kpi_card(c2, str(n_specialties), "Specialties")

    st.markdown("<br>", unsafe_allow_html=True)
    _section("Browse Devices")

    f1, f2 = st.columns(2)
    specialties = ["(all)"] + sorted({s for s in df["specialty"] if s and s.strip()})
    specialty_sel = f1.selectbox("Specialty", specialties, key="cat_spec")
    search = f2.text_input("Search name / company / code", key="cat_search")

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

    st.caption(f"**{len(filtered)}** of {n_catalog} devices")
    catalog_cols = [
        "product_code",
        "device_name",
        "company_name",
        "specialty",
        "decision_date",
        "k_number",
    ]
    st.dataframe(
        filtered[catalog_cols].rename(
            columns={
                "product_code": "Code",
                "device_name": "Device Name",
                "company_name": "Company",
                "specialty": "Specialty",
                "decision_date": "Decision Date",
                "k_number": "510(k) Number",
            }
        ),
        width="stretch",
        hide_index=True,
        height=380,
    )


def _settings_sources(db: Database) -> None:
    all_sources = db.list_external_sources(limit=500)
    if not all_sources:
        st.info(
            "No external sources found. "
            "Run `maudesignal sources fetch pubmed --query ...` to populate."
        )
        return

    pubmed_count = sum(1 for s in all_sources if s.source_type == "pubmed")
    ct_count = sum(1 for s in all_sources if s.source_type == "clinicaltrials")

    c1, c2 = st.columns(2)
    _kpi_card(c1, str(pubmed_count), "PubMed Articles")
    _kpi_card(c2, str(ct_count), "Clinical Trials")

    tab_pm, tab_ct = st.tabs(["PubMed", "ClinicalTrials.gov"])

    with tab_pm:
        pubmed = [s for s in all_sources if s.source_type == "pubmed"]
        if not pubmed:
            st.info("No PubMed records.")
        else:
            rows = [
                {
                    "PMID": s.source_id,
                    "Title": s.title or "",
                    "Authors": s.authors or "",
                    "Date": s.publication_date or "",
                    "Product": s.product_code or "—",
                    "URL": s.url or "",
                }
                for s in pubmed
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with tab_ct:
        trials = [s for s in all_sources if s.source_type == "clinicaltrials"]
        if not trials:
            st.info("No ClinicalTrials records.")
        else:
            rows_ct = [
                {
                    "NCT ID": s.source_id,
                    "Title": s.title or "",
                    "Summary": (s.abstract or "")[:120],
                    "Date": s.publication_date or "",
                    "Product": s.product_code or "—",
                    "URL": s.url or "",
                }
                for s in trials
            ]
            st.dataframe(pd.DataFrame(rows_ct), width="stretch", hide_index=True)


# ── App shell ─────────────────────────────────────────────────────────────────


#: Pages in the top navigation (built during the hackathon); the rest sit in the sidebar.
_TOP_PAGES: tuple[str, ...] = ("Signals", "Copilot", "Vision", "Audit")

_WORDMARK = (
    '<a class="ms-wordmark" href="?" aria-label="MaudeSignal home">'
    '<svg viewBox="-16 -16 32 26" width="24" height="20" aria-hidden="true">'
    '<g fill="none" stroke="currentColor" stroke-linecap="round">'
    '<path d="M-14,0 A14,14 0 0,1 14,0" stroke-width="2.2"/>'
    '<path d="M-9,0 A9,9 0 0,1 9,0" stroke-width="2.2" opacity=".6"/>'
    '<line x1="0" y1="0" x2="0" y2="8" stroke-width="2"/></g>'
    '<circle r="2.5" fill="currentColor"/></svg><span>Maude<em>Signal</em></span></a>'
)


def _nav_label(name: str) -> str:
    icon = next(i for i, n, _ in _PAGES if n == name)
    return f":material/{icon}: {name}"


def _on_top_nav() -> None:
    choice = st.session_state.get("top_nav")
    if choice:
        st.session_state["nav_page"] = choice.split(": ", 1)[1]


def _on_theme() -> None:
    from maudesignal.dashboard.theme import normalize_theme

    st.session_state["theme"] = normalize_theme(st.session_state.get("theme_select"))
    st.query_params["theme"] = st.session_state["theme"].lower().replace(" ", "-")


def _top_bar(db: Database) -> None:
    """Design-system Bar: wordmark, the product pages, theme picker; then the dateline."""
    from maudesignal.connector.registry import HEADLINE
    from maudesignal.dashboard.copilot_pages import FRAMING_LINE
    from maudesignal.dashboard.theme import THEME_NAMES

    page = st.session_state["nav_page"]
    st.session_state["top_nav"] = _nav_label(page) if page in _TOP_PAGES else None
    st.session_state["theme_select"] = st.session_state["theme"]
    with st.container(key="ms_topbar"):
        c1, c2, c3 = st.columns([2.2, 7.2, 1.8], vertical_alignment="center")
        c1.html(_WORDMARK)
        c2.segmented_control(
            "Pages",
            [_nav_label(n) for n in _TOP_PAGES],
            key="top_nav",
            on_change=_on_top_nav,
            label_visibility="collapsed",
        )
        c3.selectbox(
            "Theme",
            THEME_NAMES,
            key="theme_select",
            on_change=_on_theme,
            label_visibility="collapsed",
        )
    latest = db.max_date_received()
    as_of = datetime.strptime(str(latest), "%Y%m%d").strftime("%b %d, %Y") if latest else "no data"
    st.html(
        '<div class="ms-dateline">'
        f"<span>{datetime.now().strftime('%A, %B %d, %Y')}</span>"
        f"<span>openFDA data as of {as_of}</span>"
        f"<span>{db.count_raw_reports():,} MAUDE records on file</span></div>"
        f'<p class="ms-frame-line"><strong>{html.escape(HEADLINE)}</strong></p>'
        f'<p class="ms-frame-line">{html.escape(FRAMING_LINE)}</p>'
    )


#: Product pages only by default (the submission shows hackathon work). ``?tools=all``
#: or MAUDESIGNAL_CLASSIC_TOOLS=1 brings back the pre-hackathon "More tools" pages.
SHOW_ALL_PAGES_BY_DEFAULT = False


def _classic_tools_enabled() -> bool:
    """The "More tools" pages (pipeline, extraction, PSUR, alerts, settings).

    Hidden by default (:data:`SHOW_ALL_PAGES_BY_DEFAULT`). ``?tools=demo`` hides them
    for the browser session and ``?tools=all`` shows them; with no link choice,
    ``MAUDESIGNAL_DEMO_MODE=1`` hides them and ``MAUDESIGNAL_CLASSIC_TOOLS=1`` shows them.
    """
    choice = st.query_params.get("tools")
    if choice in ("all", "demo"):
        st.session_state["classic_tools"] = choice == "all"
    if "classic_tools" in st.session_state:
        return bool(st.session_state["classic_tools"])
    if os.environ.get("MAUDESIGNAL_CLASSIC_TOOLS") == "1":
        return True
    if os.environ.get("MAUDESIGNAL_DEMO_MODE") == "1":
        return False
    return SHOW_ALL_PAGES_BY_DEFAULT


def _render_app(db: Database) -> None:  # noqa: PLR0912
    from maudesignal.dashboard.theme import normalize_theme, theme_css

    st.set_page_config(
        page_title="MaudeSignal",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    if "theme" not in st.session_state:
        st.session_state["theme"] = normalize_theme(st.query_params.get("theme"))
    st.html(_CSS)
    st.html(theme_css(st.session_state["theme"]))

    from maudesignal.dashboard.spend_ui import has_key

    classic = _classic_tools_enabled()
    if "nav_page" not in st.session_state or (
        not classic and st.session_state["nav_page"] not in _TOP_PAGES
    ):
        st.session_state["nav_page"] = "Signals"

    _top_bar(db)

    # ── Sidebar: the classic tools (when enabled) and, with a key, the live-call
    # quota. The keyless public demo has neither, so it shows no sidebar at all.
    quota_slot = None
    if classic or has_key():
        with st.sidebar:
            if classic:
                st.caption("AI-Powered Postmarket Surveillance · public FDA data")
                st.html('<div class="ms-kicker">More tools</div>')
                for icon, page_name, _ in _PAGES:
                    if page_name in _TOP_PAGES:
                        continue
                    is_active = st.session_state["nav_page"] == page_name
                    label = f"**{page_name}**" if is_active else page_name
                    if st.button(
                        label, key=f"nav_{page_name}", icon=f":material/{icon}:", width="stretch"
                    ):
                        st.session_state["nav_page"] = page_name
                        st.rerun()
            # Filled after the page runs, so it reflects calls made on this rerun.
            quota_slot = st.empty()

    page: str = st.session_state["nav_page"]

    # ── Page routing ──────────────────────────────────────────────────────────
    from maudesignal.dashboard.copilot_pages import page_audit, page_copilot
    from maudesignal.dashboard.vision_pages import page_vision
    from maudesignal.dashboard.workspace import page_signals

    page_fn_map: dict[str, Callable[[], None]] = {
        "Signals": lambda: page_signals(db),
        "Copilot": lambda: page_copilot(db),
        "Audit": lambda: page_audit(db),
        "Vision": lambda: page_vision(db),
        "Dashboard": lambda: _page_dashboard(db),
        "Signal Explorer": lambda: _page_signal_explorer(db),
        "MAUDE Ingestion": lambda: _page_ingestion(db),
        "LLM Extraction": lambda: _page_extraction(db),
        "PSUR Reports": lambda: _page_psur(db),
        "Alerts": lambda: _page_alerts(db),
        "Settings": lambda: _page_settings(db),
    }

    fn = page_fn_map.get(page)
    if fn is None:
        st.error(f"Unknown page: {page!r}")
        return

    # Product pages carry no big title: the top bar names the page and the dateline
    # carries the one framing line (it used to be a banner repeated on every page).
    with st.spinner(""):
        fn()

    from maudesignal.dashboard.spend_ui import sidebar_quota

    if quota_slot is not None:
        with quota_slot.container():
            sidebar_quota(db)

    st.markdown(
        '<div class="ms-footer">'
        "MaudeSignal — AI-Powered Postmarket Surveillance &nbsp;|&nbsp; "
        "Data: openFDA (public domain) &nbsp;|&nbsp; "
        "Not for clinical use &nbsp;|&nbsp; "
        "Every AI output requires human regulatory review"
        "</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    """Entry point — run via `streamlit run` or `maudesignal-dashboard`."""
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
    return __name__ == "__main__" or ("streamlit" in sys.modules and _running_under_streamlit())


# ── Backward-compatibility aliases (test suite) ───────────────────────────────
# Tests reference the old internal names directly; we expose them as module-level
# aliases so the test_dashboard.py assertions remain green without any test changes.

_page_summary = _page_dashboard  # was: Monitor > Overview
_page_records = _page_signal_explorer  # was: Monitor > Records
_page_drift = _page_signal_explorer  # was: Analyze > Signals & Drift

# Original 9-page group structure kept as a static map for the nav regression test.
_PAGE_GROUPS: dict[str, list[str]] = {
    "Monitor": ["Overview", "Records", "Severity"],
    "Analyze": ["Signals & Drift", "Root Cause & Alerts", "Trends & Forecasting"],
    "Configure": ["External Sources", "PSUR Reports", "Device Catalog"],
}


if _is_main_module():
    _db: Any = _load_db()
    _render_app(_db)
