"""SQLAlchemy 2.0 models for MaudeSignal.

Implements the database schema defined in Document 5 §8.
Phase 2 adds: root_cause_reports, alert_rules, alert_events.
Phase 3 adds: trend_snapshots.
Phase 4 adds: external_sources.
Phase 5 adds: psur_reports.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all MaudeSignal SQLAlchemy models."""


class RawReportRecord(Base):
    """Immutable raw MAUDE report as fetched from openFDA.

    Per Doc 5 §8 this table is append-only. Re-running ingestion with
    the same parameters is idempotent (NFR-05) — existing rows are not
    modified.
    """

    __tablename__ = "raw_reports"

    maude_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str] = mapped_column(String, index=True)
    date_received: Mapped[str | None] = mapped_column(String, index=True)
    date_of_event: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[str] = mapped_column(Text)  # full openFDA JSON payload
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class NormalizedEventRecord(Base):
    """Cleaned, queryable subset of a MAUDE report.

    Derived from ``raw_reports`` at ingestion time. Can be safely
    regenerated from raw data without losing information.
    """

    __tablename__ = "normalized_events"

    maude_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str | None] = mapped_column(String, index=True)
    event_date: Mapped[str | None] = mapped_column(String)
    narrative: Mapped[str | None] = mapped_column(Text)
    mfr_narrative: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(String)
    brand_name: Mapped[str | None] = mapped_column(String)


class ExtractionRecord(Base):
    """Structured LLM extraction output for a MAUDE report.

    One row per (maude_report_id, skill_version) pair — re-extractions
    with newer Skill versions coexist with old ones for auditability.
    """

    __tablename__ = "extractions"

    extraction_id: Mapped[str] = mapped_column(String, primary_key=True)
    maude_report_id: Mapped[str] = mapped_column(String, index=True)
    extraction_ts: Mapped[datetime] = mapped_column(DateTime)
    skill_name: Mapped[str] = mapped_column(String)
    skill_version: Mapped[str] = mapped_column(String)
    model_used: Mapped[str] = mapped_column(String)
    output_json: Mapped[str] = mapped_column(Text)  # full validated JSON
    confidence_score: Mapped[float] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Boolean, index=True)


class DeviceCatalogRecord(Base):
    """FDA-cleared AI/ML device registry.

    Populated by ``maudesignal catalog update`` from the openFDA 510k API.
    One row per unique product_code; re-running update is idempotent.
    """

    __tablename__ = "device_catalog"

    product_code: Mapped[str] = mapped_column(String, primary_key=True)
    device_name: Mapped[str] = mapped_column(String)
    company_name: Mapped[str | None] = mapped_column(String)
    specialty: Mapped[str | None] = mapped_column(String)
    decision_date: Mapped[str | None] = mapped_column(String)
    k_number: Mapped[str | None] = mapped_column(String)
    source_keyword: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class LLMAuditLogRecord(Base):
    """ALCOA+ audit trail: one row per LLM API call.

    Per FR-12 every LLM call is logged with Skill version, hashes, tokens,
    and cost. This table is the source of truth for reproducibility and
    spend tracking.
    """

    __tablename__ = "llm_audit_log"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    skill_name: Mapped[str] = mapped_column(String, index=True)
    skill_version: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    output_hash: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_estimate_usd: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------------------
# Phase 2: root cause analysis + alerting
# ---------------------------------------------------------------------------


class RootCauseReportRecord(Base):
    """Root-cause analysis output for a cluster of extractions.

    One row per (product_code, failure_mode_category, analysis run).
    Multiple runs for the same cluster coexist (new run = new report_id).
    """

    __tablename__ = "root_cause_reports"

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str] = mapped_column(String, index=True)
    failure_mode_category: Mapped[str] = mapped_column(String)
    analysis_ts: Mapped[datetime] = mapped_column(DateTime)
    cluster_size: Mapped[int] = mapped_column(Integer)
    skill_version: Mapped[str] = mapped_column(String)
    model_used: Mapped[str] = mapped_column(String)
    output_json: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Boolean, index=True)


class AlertRuleRecord(Base):
    """User-configured alert rule (threshold + delivery).

    Metrics: new_reports | ai_rate | severity_rate | new_failure_mode
    Delivery: console | slack | email
    delivery_config stores JSON with delivery-specific fields (webhook_url, etc.).
    """

    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str | None] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String)
    threshold: Mapped[float] = mapped_column(Float)
    window_days: Mapped[int] = mapped_column(Integer)
    delivery: Mapped[str] = mapped_column(String)
    delivery_config: Mapped[str | None] = mapped_column(Text)  # JSON
    description: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, index=True)


class AlertEventRecord(Base):
    """Fired alert instance (one row per rule × fire time).

    Append-only. delivered=True when the notification was dispatched
    successfully; False means it fired but delivery failed.
    """

    __tablename__ = "alert_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String, index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime)
    product_code: Mapped[str | None] = mapped_column(String)
    metric: Mapped[str] = mapped_column(String)
    metric_value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean)


# ---------------------------------------------------------------------------
# Phase 3: trend detection + forecasting
# ---------------------------------------------------------------------------


class TrendSnapshotRecord(Base):
    """Point-in-time trend analysis for one (product_code, metric_name).

    One row per analysis run. Stores the raw stats and the Skill output JSON.
    Multiple snapshots coexist — the latest is retrieved by analysis_ts DESC.
    """

    __tablename__ = "trend_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str] = mapped_column(String, index=True)
    metric_name: Mapped[str] = mapped_column(String, index=True)
    analysis_ts: Mapped[datetime] = mapped_column(DateTime)
    window_days: Mapped[int] = mapped_column(Integer)
    period_count: Mapped[int] = mapped_column(Integer)
    slope_per_period: Mapped[float] = mapped_column(Float)
    mk_tau: Mapped[float] = mapped_column(Float)
    mk_p_value: Mapped[float] = mapped_column(Float)
    mean_value: Mapped[float] = mapped_column(Float)
    recent_value: Mapped[float] = mapped_column(Float)
    baseline_value: Mapped[float] = mapped_column(Float)
    trend_direction: Mapped[str] = mapped_column(String)
    signal_level: Mapped[str] = mapped_column(String)
    skill_version: Mapped[str] = mapped_column(String)
    model_used: Mapped[str] = mapped_column(String)
    output_json: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------------------
# Phase 4: multi-source integration
# ---------------------------------------------------------------------------


class ExternalSourceRecord(Base):
    """Publication or clinical trial record fetched from an external API.

    source_type: "pubmed" | "clinicaltrials"
    source_id: PubMed PMID or ClinicalTrials NCT number (unique per source_type)
    product_code: linked FDA product code (best-match, may be None)
    Idempotent: re-fetching the same source_id + source_type replaces the row.
    """

    __tablename__ = "external_sources"

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    product_code: Mapped[str | None] = mapped_column(String, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    title: Mapped[str | None] = mapped_column(String)
    authors: Mapped[str | None] = mapped_column(String)
    publication_date: Mapped[str | None] = mapped_column(String)
    abstract: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Phase 5: automated regulatory response (PSUR)
# ---------------------------------------------------------------------------


class PsurReportRecord(Base):
    """PSUR draft generated by the psur-report-drafter Skill.

    One row per generation run. Multiple drafts may coexist for the same
    product_code; the latest is queried by drafted_at DESC.
    """

    __tablename__ = "psur_reports"

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_code: Mapped[str] = mapped_column(String, index=True)
    reporting_period_start: Mapped[str] = mapped_column(String)
    reporting_period_end: Mapped[str] = mapped_column(String)
    drafted_at: Mapped[datetime] = mapped_column(DateTime)
    signal_assessment: Mapped[str] = mapped_column(String)
    skill_version: Mapped[str] = mapped_column(String)
    model_used: Mapped[str] = mapped_column(String)
    output_json: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)
