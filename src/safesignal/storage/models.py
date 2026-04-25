"""SQLAlchemy 2.0 models for SafeSignal.

Implements the database schema defined in Document 5 §8. These models are
intentionally minimal — just enough to demonstrate the data flow end-to-end.
Additional tables (classifications, drift_alerts) will be added in Phase 2.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SafeSignal SQLAlchemy models."""


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
