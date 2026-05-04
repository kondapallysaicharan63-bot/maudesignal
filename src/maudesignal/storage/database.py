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
    AlertEventRecord,
    AlertRuleRecord,
    Base,
    DeviceCatalogRecord,
    ExternalSourceRecord,
    ExtractionRecord,
    LLMAuditLogRecord,
    NormalizedEventRecord,
    PsurReportRecord,
    RawReportRecord,
    RootCauseReportRecord,
    TrendSnapshotRecord,
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
            return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

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

    def get_normalized_event(self, maude_report_id: str) -> NormalizedEventRecord | None:
        """Return a single normalized event by report ID, or None if not found."""
        with self._session() as session:
            stmt = select(NormalizedEventRecord).where(
                NormalizedEventRecord.maude_report_id == maude_report_id
            )
            return session.execute(stmt).scalars().first()

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

    def list_extractions(
        self,
        *,
        product_code: str | None = None,
        skill_name: str | None = None,
    ) -> list[ExtractionRecord]:
        """Return extraction rows, optionally filtered by product_code/skill."""
        with self._session() as session:
            stmt = select(ExtractionRecord)
            if skill_name:
                stmt = stmt.where(ExtractionRecord.skill_name == skill_name)
            if product_code:
                ids = (
                    session.execute(
                        select(NormalizedEventRecord.maude_report_id).where(
                            NormalizedEventRecord.product_code == product_code
                        )
                    )
                    .scalars()
                    .all()
                )
                if not ids:
                    return []
                stmt = stmt.where(ExtractionRecord.maude_report_id.in_(ids))
            stmt = stmt.order_by(ExtractionRecord.extraction_ts)
            return list(session.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # Device catalog
    # ------------------------------------------------------------------

    def upsert_catalog_device(
        self,
        *,
        product_code: str,
        device_name: str,
        company_name: str | None,
        specialty: str | None,
        decision_date: str | None,
        k_number: str | None,
        source_keyword: str | None,
    ) -> bool:
        """Insert or update a device catalog entry.

        Returns True if a new row was inserted, False if updated.
        """
        with self._session() as session:
            # Pre-check for existence: SQLite's on_conflict_do_update always
            # returns rowcount=1 regardless of insert vs update, so we detect
            # new rows with a SELECT before the upsert.
            existing = (
                session.execute(
                    select(DeviceCatalogRecord).where(
                        DeviceCatalogRecord.product_code == product_code
                    )
                )
                .scalars()
                .first()
            )
            is_new = existing is None

            stmt = sqlite_insert(DeviceCatalogRecord).values(
                product_code=product_code,
                device_name=device_name,
                company_name=company_name,
                specialty=specialty,
                decision_date=decision_date,
                k_number=k_number,
                source_keyword=source_keyword,
                fetched_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["product_code"],
                set_={
                    "device_name": stmt.excluded.device_name,
                    "company_name": stmt.excluded.company_name,
                    "specialty": stmt.excluded.specialty,
                    "decision_date": stmt.excluded.decision_date,
                    "k_number": stmt.excluded.k_number,
                    "source_keyword": stmt.excluded.source_keyword,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            session.execute(stmt)
            session.commit()
            return is_new

    def list_catalog_devices(self) -> list[DeviceCatalogRecord]:
        """Return all devices in the catalog, ordered by product_code."""
        with self._session() as session:
            stmt = select(DeviceCatalogRecord).order_by(DeviceCatalogRecord.product_code)
            return list(session.execute(stmt).scalars().all())

    def count_catalog_devices(self) -> int:
        """Return count of unique product codes in the catalog."""
        with self._session() as session:
            return len(session.execute(select(DeviceCatalogRecord)).scalars().all())

    # ------------------------------------------------------------------
    # Root cause reports  (Phase 2)
    # ------------------------------------------------------------------

    def insert_root_cause_report(
        self,
        *,
        report_id: str,
        product_code: str,
        failure_mode_category: str,
        cluster_size: int,
        skill_version: str,
        model_used: str,
        output_payload: dict[str, Any],
        confidence_score: float,
        requires_review: bool,
    ) -> None:
        """Append a root-cause analysis result (append-only)."""
        with self._session() as session:
            record = RootCauseReportRecord(
                report_id=report_id,
                product_code=product_code,
                failure_mode_category=failure_mode_category,
                analysis_ts=datetime.now(UTC),
                cluster_size=cluster_size,
                skill_version=skill_version,
                model_used=model_used,
                output_json=json.dumps(output_payload),
                confidence_score=confidence_score,
                requires_review=requires_review,
            )
            session.add(record)
            session.commit()

    def list_root_cause_reports(
        self,
        product_code: str | None = None,
    ) -> list[RootCauseReportRecord]:
        """Return root cause reports, newest first."""
        with self._session() as session:
            stmt = select(RootCauseReportRecord)
            if product_code:
                stmt = stmt.where(RootCauseReportRecord.product_code == product_code)
            stmt = stmt.order_by(RootCauseReportRecord.analysis_ts.desc())
            return list(session.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # Alert rules  (Phase 2)
    # ------------------------------------------------------------------

    def insert_alert_rule(
        self,
        *,
        rule_id: str,
        product_code: str | None,
        metric: str,
        threshold: float,
        window_days: int,
        delivery: str,
        delivery_config: dict[str, Any] | None,
        description: str | None,
    ) -> None:
        """Insert a new alert rule."""
        with self._session() as session:
            record = AlertRuleRecord(
                rule_id=rule_id,
                product_code=product_code,
                metric=metric,
                threshold=threshold,
                window_days=window_days,
                delivery=delivery,
                delivery_config=json.dumps(delivery_config) if delivery_config else None,
                description=description,
                created_at=datetime.now(UTC),
                active=True,
            )
            session.add(record)
            session.commit()

    def list_alert_rules(self, active_only: bool = True) -> list[AlertRuleRecord]:
        """Return alert rules, optionally filtered to active ones."""
        with self._session() as session:
            stmt = select(AlertRuleRecord)
            if active_only:
                stmt = stmt.where(AlertRuleRecord.active == True)  # noqa: E712
            stmt = stmt.order_by(AlertRuleRecord.created_at)
            return list(session.execute(stmt).scalars().all())

    def deactivate_alert_rule(self, rule_id: str) -> bool:
        """Mark a rule as inactive. Returns True if found and updated."""
        with self._session() as session:
            record = (
                session.execute(select(AlertRuleRecord).where(AlertRuleRecord.rule_id == rule_id))
                .scalars()
                .first()
            )
            if record is None:
                return False
            record.active = False
            session.commit()
            return True

    # ------------------------------------------------------------------
    # Alert events  (Phase 2)
    # ------------------------------------------------------------------

    def insert_alert_event(
        self,
        *,
        event_id: str,
        rule_id: str,
        product_code: str | None,
        metric: str,
        metric_value: float,
        threshold: float,
        message: str,
        delivered: bool,
    ) -> None:
        """Append a fired alert event (append-only)."""
        with self._session() as session:
            record = AlertEventRecord(
                event_id=event_id,
                rule_id=rule_id,
                fired_at=datetime.now(UTC),
                product_code=product_code,
                metric=metric,
                metric_value=metric_value,
                threshold=threshold,
                message=message,
                delivered=delivered,
            )
            session.add(record)
            session.commit()

    def list_alert_events(
        self,
        rule_id: str | None = None,
        limit: int = 100,
    ) -> list[AlertEventRecord]:
        """Return alert events, newest first."""
        with self._session() as session:
            stmt = select(AlertEventRecord)
            if rule_id:
                stmt = stmt.where(AlertEventRecord.rule_id == rule_id)
            stmt = stmt.order_by(AlertEventRecord.fired_at.desc()).limit(limit)
            return list(session.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # Metric queries for alerting  (Phase 2)
    # ------------------------------------------------------------------

    def count_extractions_in_window(
        self,
        *,
        product_code: str | None,
        skill_name: str,
        since: datetime,
    ) -> int:
        """Count extractions for a product code after `since`."""
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since
        with self._session() as session:
            stmt = select(ExtractionRecord).where(
                ExtractionRecord.skill_name == skill_name,
                ExtractionRecord.extraction_ts >= since_naive,
            )
            if product_code:
                ids = (
                    session.execute(
                        select(NormalizedEventRecord.maude_report_id).where(
                            NormalizedEventRecord.product_code == product_code
                        )
                    )
                    .scalars()
                    .all()
                )
                if not ids:
                    return 0
                stmt = stmt.where(ExtractionRecord.maude_report_id.in_(ids))
            return len(session.execute(stmt).scalars().all())

    def ai_rate_in_window(
        self,
        *,
        product_code: str | None,
        since: datetime,
    ) -> float:
        """Return fraction of extractor outputs flagged ai_related_flag=true since `since`.

        Returns 0.0 if no records in window.
        """
        # SQLite stores datetimes without timezone; strip tzinfo for comparison.
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since
        rows = self.list_extractions(
            product_code=product_code,
            skill_name="maude-narrative-extractor",
        )
        in_window = [r for r in rows if r.extraction_ts >= since_naive]
        if not in_window:
            return 0.0
        ai_count = sum(
            1 for r in in_window if json.loads(r.output_json).get("ai_related_flag") is True
        )
        return ai_count / len(in_window)

    def severity_rate_in_window(
        self,
        *,
        product_code: str | None,
        since: datetime,
        severity_levels: list[str] | None = None,
    ) -> float:
        """Return fraction of severity-triage outputs at or above given levels.

        Defaults to counting death + serious_injury.
        """
        if severity_levels is None:
            severity_levels = ["death", "serious_injury"]
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since
        rows = self.list_extractions(
            product_code=product_code,
            skill_name="severity-triage",
        )
        in_window = [r for r in rows if r.extraction_ts >= since_naive]
        if not in_window:
            return 0.0
        count = sum(
            1 for r in in_window if json.loads(r.output_json).get("severity") in severity_levels
        )
        return count / len(in_window)

    # ------------------------------------------------------------------
    # Trend snapshots  (Phase 3)
    # ------------------------------------------------------------------

    def insert_trend_snapshot(
        self,
        *,
        snapshot_id: str,
        product_code: str,
        metric_name: str,
        window_days: int,
        period_count: int,
        slope_per_period: float,
        mk_tau: float,
        mk_p_value: float,
        mean_value: float,
        recent_value: float,
        baseline_value: float,
        trend_direction: str,
        signal_level: str,
        skill_version: str,
        model_used: str,
        output_payload: dict[str, Any],
        confidence_score: float,
    ) -> None:
        """Insert a trend snapshot record."""
        with self._session() as session:
            record = TrendSnapshotRecord(
                snapshot_id=snapshot_id,
                product_code=product_code,
                metric_name=metric_name,
                analysis_ts=datetime.now(UTC).replace(tzinfo=None),
                window_days=window_days,
                period_count=period_count,
                slope_per_period=slope_per_period,
                mk_tau=mk_tau,
                mk_p_value=mk_p_value,
                mean_value=mean_value,
                recent_value=recent_value,
                baseline_value=baseline_value,
                trend_direction=trend_direction,
                signal_level=signal_level,
                skill_version=skill_version,
                model_used=model_used,
                output_json=json.dumps(output_payload),
                confidence_score=confidence_score,
            )
            session.add(record)
            session.commit()
            logger.info(
                "trend_snapshot_inserted",
                snapshot_id=snapshot_id,
                product_code=product_code,
                metric_name=metric_name,
            )

    def list_trend_snapshots(
        self,
        *,
        product_code: str | None = None,
        metric_name: str | None = None,
        limit: int = 50,
    ) -> list[TrendSnapshotRecord]:
        """Return trend snapshots, most recent first."""
        with self._session() as session:
            stmt = select(TrendSnapshotRecord).order_by(TrendSnapshotRecord.analysis_ts.desc())
            if product_code:
                stmt = stmt.where(TrendSnapshotRecord.product_code == product_code)
            if metric_name:
                stmt = stmt.where(TrendSnapshotRecord.metric_name == metric_name)
            stmt = stmt.limit(limit)
            return list(session.execute(stmt).scalars().all())

    def get_metric_time_series(
        self,
        *,
        product_code: str | None,
        metric_name: str,
        window_days: int,
        bucket_size_days: int = 7,
    ) -> list[tuple[datetime, float]]:
        """Return (bucket_start, metric_value) pairs for the given window.

        Buckets are aligned to calendar weeks (or `bucket_size_days`).
        metric_name: "ai_rate" | "severity_rate" | "report_volume"
        """
        from datetime import timedelta

        since = datetime.now(UTC) - timedelta(days=window_days)
        since_naive = since.replace(tzinfo=None)
        now_naive = datetime.now(UTC).replace(tzinfo=None)

        buckets: list[tuple[datetime, float]] = []
        cursor = since_naive
        while cursor < now_naive:
            bucket_end = min(cursor + timedelta(days=bucket_size_days), now_naive)
            value = self._compute_metric_in_range(
                product_code=product_code,
                metric_name=metric_name,
                start=cursor,
                end=bucket_end,
            )
            buckets.append((cursor, value))
            cursor = bucket_end
        return buckets

    def _compute_metric_in_range(
        self,
        *,
        product_code: str | None,
        metric_name: str,
        start: datetime,
        end: datetime,
    ) -> float:
        """Compute a single metric value for a time range."""
        if metric_name == "report_volume":
            rows = self.list_extractions(
                product_code=product_code,
                skill_name="maude-narrative-extractor",
            )
            return float(sum(1 for r in rows if start <= r.extraction_ts < end))

        if metric_name == "ai_rate":
            rows = self.list_extractions(
                product_code=product_code,
                skill_name="maude-narrative-extractor",
            )
            in_range = [r for r in rows if start <= r.extraction_ts < end]
            if not in_range:
                return 0.0
            ai_count = sum(
                1 for r in in_range if json.loads(r.output_json).get("ai_related_flag") is True
            )
            return ai_count / len(in_range)

        if metric_name == "severity_rate":
            rows = self.list_extractions(
                product_code=product_code,
                skill_name="severity-triage",
            )
            in_range = [r for r in rows if start <= r.extraction_ts < end]
            if not in_range:
                return 0.0
            count = sum(
                1
                for r in in_range
                if json.loads(r.output_json).get("severity") in ("death", "serious_injury")
            )
            return count / len(in_range)

        return 0.0

    # ------------------------------------------------------------------
    # External sources  (Phase 4)
    # ------------------------------------------------------------------

    def upsert_external_source(
        self,
        *,
        record_id: str,
        source_type: str,
        source_id: str,
        product_code: str | None,
        title: str | None,
        authors: str | None,
        publication_date: str | None,
        abstract: str | None,
        url: str | None,
        raw_payload: dict[str, Any],
    ) -> None:
        """Insert or replace an external source record (idempotent by record_id)."""
        with self._session() as session:
            existing = session.get(ExternalSourceRecord, record_id)
            if existing:
                existing.fetched_at = datetime.now(UTC).replace(tzinfo=None)
                existing.title = title
                existing.authors = authors
                existing.publication_date = publication_date
                existing.abstract = abstract
                existing.url = url
                existing.raw_json = json.dumps(raw_payload)
            else:
                session.add(
                    ExternalSourceRecord(
                        record_id=record_id,
                        source_type=source_type,
                        source_id=source_id,
                        product_code=product_code,
                        fetched_at=datetime.now(UTC).replace(tzinfo=None),
                        title=title,
                        authors=authors,
                        publication_date=publication_date,
                        abstract=abstract,
                        url=url,
                        raw_json=json.dumps(raw_payload),
                    )
                )
            session.commit()
            logger.info(
                "external_source_upserted",
                record_id=record_id,
                source_type=source_type,
                source_id=source_id,
            )

    def list_external_sources(
        self,
        *,
        source_type: str | None = None,
        product_code: str | None = None,
        limit: int = 100,
    ) -> list[ExternalSourceRecord]:
        """Return external source records, most recent first."""
        with self._session() as session:
            stmt = select(ExternalSourceRecord).order_by(ExternalSourceRecord.fetched_at.desc())
            if source_type:
                stmt = stmt.where(ExternalSourceRecord.source_type == source_type)
            if product_code:
                stmt = stmt.where(ExternalSourceRecord.product_code == product_code)
            stmt = stmt.limit(limit)
            return list(session.execute(stmt).scalars().all())

    def count_external_sources(self, *, source_type: str | None = None) -> int:
        """Return count of external source records."""
        return len(self.list_external_sources(source_type=source_type, limit=100_000))

    # ------------------------------------------------------------------
    # PSUR reports  (Phase 5)
    # ------------------------------------------------------------------

    def insert_psur_report(
        self,
        *,
        report_id: str,
        product_code: str,
        reporting_period_start: str,
        reporting_period_end: str,
        signal_assessment: str,
        skill_version: str,
        model_used: str,
        output_payload: dict[str, Any],
        confidence_score: float,
    ) -> None:
        """Insert a new PSUR report draft."""
        with self._session() as session:
            session.add(
                PsurReportRecord(
                    report_id=report_id,
                    product_code=product_code,
                    reporting_period_start=reporting_period_start,
                    reporting_period_end=reporting_period_end,
                    drafted_at=datetime.now(UTC).replace(tzinfo=None),
                    signal_assessment=signal_assessment,
                    skill_version=skill_version,
                    model_used=model_used,
                    output_json=json.dumps(output_payload),
                    confidence_score=confidence_score,
                )
            )
            session.commit()
            logger.info(
                "psur_report_inserted",
                report_id=report_id,
                product_code=product_code,
                signal_assessment=signal_assessment,
            )

    def list_psur_reports(
        self,
        *,
        product_code: str | None = None,
        limit: int = 20,
    ) -> list[PsurReportRecord]:
        """Return PSUR reports, most recent first."""
        with self._session() as session:
            stmt = select(PsurReportRecord).order_by(PsurReportRecord.drafted_at.desc())
            if product_code:
                stmt = stmt.where(PsurReportRecord.product_code == product_code)
            stmt = stmt.limit(limit)
            return list(session.execute(stmt).scalars().all())
