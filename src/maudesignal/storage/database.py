"""Database facade for MaudeSignal.

Exposes a small, typed API for persistence. Callers never see SQLAlchemy
sessions or SQL directly.

Design rule (Doc 5 §3.2): storage/ is the hub. Every module reads and
writes through this class — no module executes raw SQL elsewhere.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from maudesignal.common.logging import get_logger
from maudesignal.storage.models import (
    Base,
    ExtractionRecord,
    LLMAuditLogRecord,
    NormalizedEventRecord,
    RawReportRecord,
)

logger = get_logger(__name__)


class Database:
    """Thin facade over SQLAlchemy for MaudeSignal's SQLite backend.

    All writes are idempotent where the domain allows (raw_reports and
    normalized_events use INSERT OR IGNORE; extractions append new rows
    keyed by extraction_id; audit log is append-only).
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the database, creating tables if they don't exist.

        Args:
            db_path: Path to the SQLite file. Parent directory must exist.
        """
        self._db_path = db_path
        # check_same_thread=False lets Streamlit's threadpool share the DB later.
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)
        logger.info("database_initialized", db_path=str(db_path))

    @property
    def path(self) -> Path:
        """Path to the SQLite file, for diagnostics."""
        return self._db_path

    def _session(self) -> Session:
        """Return a new SQLAlchemy session."""
        return self._session_factory()

    # ------------------------------------------------------------------
    # Raw reports
    # ------------------------------------------------------------------

    def upsert_raw_report(
        self,
        *,
        maude_report_id: str,
        product_code: str,
        date_received: str | None,
        date_of_event: str | None,
        raw_payload: dict[str, Any],
    ) -> bool:
        """Insert a raw MAUDE report, skipping if it already exists.

        Returns:
            True if a new row was inserted, False if it already existed.
        """
        with self._session() as session:
            stmt = sqlite_insert(RawReportRecord).values(
                maude_report_id=maude_report_id,
                product_code=product_code,
                date_received=date_received,
                date_of_event=date_of_event,
                raw_json=json.dumps(raw_payload),
                fetched_at=datetime.now(UTC),
            )
            # ON CONFLICT DO NOTHING = idempotent ingestion (NFR-05, FR-05)
            stmt = stmt.on_conflict_do_nothing(index_elements=["maude_report_id"])
            result = session.execute(stmt)
            session.commit()
            return (result.rowcount or 0) > 0

    def upsert_normalized_event(
        self,
        *,
        maude_report_id: str,
        product_code: str,
        event_type: str | None,
        event_date: str | None,
        narrative: str | None,
        mfr_narrative: str | None,
        manufacturer: str | None,
        brand_name: str | None,
    ) -> None:
        """Insert or replace a normalized event row.

        Normalized rows can be regenerated from raw, so replacement is fine.
        """
        with self._session() as session:
            stmt = sqlite_insert(NormalizedEventRecord).values(
                maude_report_id=maude_report_id,
                product_code=product_code,
                event_type=event_type,
                event_date=event_date,
                narrative=narrative,
                mfr_narrative=mfr_narrative,
                manufacturer=manufacturer,
                brand_name=brand_name,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["maude_report_id"],
                set_={
                    "product_code": stmt.excluded.product_code,
                    "event_type": stmt.excluded.event_type,
                    "event_date": stmt.excluded.event_date,
                    "narrative": stmt.excluded.narrative,
                    "mfr_narrative": stmt.excluded.mfr_narrative,
                    "manufacturer": stmt.excluded.manufacturer,
                    "brand_name": stmt.excluded.brand_name,
                },
            )
            session.execute(stmt)
            session.commit()

    def count_raw_reports(self, product_code: str | None = None) -> int:
        """Return the number of stored raw reports, optionally filtered by code."""
        with self._session() as session:
            stmt = select(RawReportRecord)
            if product_code:
                stmt = stmt.where(RawReportRecord.product_code == product_code)
            return len(session.execute(stmt).scalars().all())

    def list_normalized_events(
        self,
        product_code: str | None = None,
        limit: int | None = None,
    ) -> list[NormalizedEventRecord]:
        """Return normalized events, optionally filtered/limited."""
        with self._session() as session:
            stmt = select(NormalizedEventRecord)
            if product_code:
                stmt = stmt.where(NormalizedEventRecord.product_code == product_code)
            if limit:
                stmt = stmt.limit(limit)
            return list(session.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # Extractions
    # ------------------------------------------------------------------

    def insert_extraction(
        self,
        *,
        extraction_id: str,
        maude_report_id: str,
        skill_name: str,
        skill_version: str,
        model_used: str,
        output_payload: dict[str, Any],
        confidence_score: float,
        requires_review: bool,
    ) -> None:
        """Insert a validated extraction result (append-only)."""
        with self._session() as session:
            record = ExtractionRecord(
                extraction_id=extraction_id,
                maude_report_id=maude_report_id,
                extraction_ts=datetime.now(UTC),
                skill_name=skill_name,
                skill_version=skill_version,
                model_used=model_used,
                output_json=json.dumps(output_payload),
                confidence_score=confidence_score,
                requires_review=requires_review,
            )
            session.add(record)
            session.commit()

    # ------------------------------------------------------------------
    # LLM audit log
    # ------------------------------------------------------------------

    def insert_audit_log(
        self,
        *,
        call_id: str,
        skill_name: str,
        skill_version: str,
        model: str,
        input_hash: str,
        output_hash: str,
        input_tokens: int,
        output_tokens: int,
        cost_estimate_usd: float,
    ) -> None:
        """Append a row to the LLM audit log (FR-12, ALCOA+)."""
        with self._session() as session:
            record = LLMAuditLogRecord(
                call_id=call_id,
                ts=datetime.now(UTC),
                skill_name=skill_name,
                skill_version=skill_version,
                model=model,
                input_hash=input_hash,
                output_hash=output_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_estimate_usd=cost_estimate_usd,
            )
            session.add(record)
            session.commit()

    def total_llm_cost_usd(self) -> float:
        """Return cumulative Claude API spend across all audit log rows."""
        with self._session() as session:
            records = session.execute(select(LLMAuditLogRecord)).scalars().all()
            return sum(r.cost_estimate_usd for r in records)
