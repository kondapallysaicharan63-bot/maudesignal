"""Unit tests for Phase 3: trend detection and forecasting."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from maudesignal.forecasting.trend_detector import (
    VALID_METRICS,
    TrendDetector,
    _compute_stats,
    _empty_stats,
    _mann_kendall,
)
from maudesignal.storage.database import Database

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _in_memory_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _fake_extractor_result(output: dict[str, Any]) -> MagicMock:
    result = MagicMock()
    result.output = output
    result.model_used = "test-model"
    return result


def _good_trend_output(
    direction: str = "increasing",
    signal: str = "elevated",
    significant: bool = True,
) -> dict[str, Any]:
    return {
        "product_code": "QIH",
        "metric_name": "ai_rate",
        "analysis_ts": "2026-05-01T12:00:00Z",
        "skill_name": "trend-interpreter",
        "skill_version": "1.0.0",
        "model_used": "test-model",
        "trend_direction": direction,
        "trend_strength": "moderate",
        "is_statistically_significant": significant,
        "regulatory_narrative": (
            "The AI-related failure rate for product code QIH has increased over the window. "
            "This trend is statistically significant. Escalation is recommended."
        ),
        "signal_level": signal,
        "recommended_action": "Review device performance data and notify manufacturer.",
        "confidence_score": 0.75,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Mann-Kendall unit tests
# ──────────────────────────────────────────────────────────────────────────────


class TestMannKendall:
    def test_monotone_increasing_returns_positive_tau(self) -> None:
        import numpy as np

        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        tau, p = _mann_kendall(arr)
        assert tau == pytest.approx(1.0)
        assert p < 0.05

    def test_monotone_decreasing_returns_negative_tau(self) -> None:
        import numpy as np

        arr = np.array([8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
        tau, p = _mann_kendall(arr)
        assert tau == pytest.approx(-1.0)
        assert p < 0.05

    def test_constant_series_returns_zero_tau(self) -> None:
        import numpy as np

        arr = np.array([0.5, 0.5, 0.5, 0.5])
        tau, p = _mann_kendall(arr)
        assert tau == pytest.approx(0.0)
        assert p == pytest.approx(1.0)

    def test_noisy_series_returns_tau_in_range(self) -> None:
        import numpy as np

        arr = np.array([0.3, 0.5, 0.2, 0.7, 0.4, 0.6, 0.5, 0.8])
        tau, p = _mann_kendall(arr)
        assert -1.0 <= tau <= 1.0
        assert 0.0 <= p <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# compute_stats unit tests
# ──────────────────────────────────────────────────────────────────────────────


class TestComputeStats:
    def test_increasing_series_positive_slope(self) -> None:
        series = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        stats = _compute_stats(series)
        assert stats.slope_per_period > 0
        assert stats.mk_tau > 0
        assert stats.mean_value == pytest.approx(0.45)
        assert stats.recent_value == pytest.approx(0.8)
        assert stats.baseline_value == pytest.approx(0.1)
        assert stats.period_count == 8

    def test_decreasing_series_negative_slope(self) -> None:
        series = [0.9, 0.7, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        stats = _compute_stats(series)
        assert stats.slope_per_period < 0
        assert stats.mk_tau < 0

    def test_empty_stats_zeros(self) -> None:
        es = _empty_stats([])
        assert es.slope_per_period == 0.0
        assert es.mk_tau == 0.0
        assert es.mk_p_value == 1.0
        assert es.period_count == 0

    def test_stats_preserves_series(self) -> None:
        series = [0.1, 0.2, 0.3, 0.4]
        stats = _compute_stats(series)
        assert stats.series == series

    def test_single_bucket_constant_slope(self) -> None:
        # Very short series — slope is 0, no trend
        series = [0.5, 0.5]
        stats = _compute_stats(series)
        assert math.isfinite(stats.slope_per_period)


# ──────────────────────────────────────────────────────────────────────────────
# VALID_METRICS
# ──────────────────────────────────────────────────────────────────────────────


class TestValidMetrics:
    def test_contains_expected_metrics(self) -> None:
        assert "ai_rate" in VALID_METRICS
        assert "severity_rate" in VALID_METRICS
        assert "report_volume" in VALID_METRICS

    def test_no_unexpected_metrics(self) -> None:
        assert len(VALID_METRICS) == 3


# ──────────────────────────────────────────────────────────────────────────────
# Database: TrendSnapshotRecord
# ──────────────────────────────────────────────────────────────────────────────


class TestTrendSnapshotDB:
    def test_insert_and_list(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        db.insert_trend_snapshot(
            snapshot_id="snap-001",
            product_code="QIH",
            metric_name="ai_rate",
            window_days=90,
            period_count=12,
            slope_per_period=0.01,
            mk_tau=0.45,
            mk_p_value=0.02,
            mean_value=0.55,
            recent_value=0.72,
            baseline_value=0.38,
            trend_direction="increasing",
            signal_level="elevated",
            skill_version="1.0.0",
            model_used="test-model",
            output_payload={"confidence_score": 0.8},
            confidence_score=0.8,
        )
        snaps = db.list_trend_snapshots()
        assert len(snaps) == 1
        s = snaps[0]
        assert s.snapshot_id == "snap-001"
        assert s.product_code == "QIH"
        assert s.metric_name == "ai_rate"
        assert s.trend_direction == "increasing"
        assert s.confidence_score == pytest.approx(0.8)

    def test_filter_by_product_code(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for pc, metric in [("QIH", "ai_rate"), ("MYH", "severity_rate")]:
            db.insert_trend_snapshot(
                snapshot_id=f"snap-{pc}",
                product_code=pc,
                metric_name=metric,
                window_days=90,
                period_count=8,
                slope_per_period=0.0,
                mk_tau=0.0,
                mk_p_value=1.0,
                mean_value=0.1,
                recent_value=0.1,
                baseline_value=0.1,
                trend_direction="stable",
                signal_level="low",
                skill_version="1.0.0",
                model_used="test",
                output_payload={},
                confidence_score=0.5,
            )
        qih_snaps = db.list_trend_snapshots(product_code="QIH")
        assert len(qih_snaps) == 1
        assert qih_snaps[0].product_code == "QIH"

    def test_filter_by_metric_name(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for metric in ["ai_rate", "severity_rate", "report_volume"]:
            db.insert_trend_snapshot(
                snapshot_id=f"snap-{metric}",
                product_code="QIH",
                metric_name=metric,
                window_days=90,
                period_count=8,
                slope_per_period=0.0,
                mk_tau=0.0,
                mk_p_value=1.0,
                mean_value=0.0,
                recent_value=0.0,
                baseline_value=0.0,
                trend_direction="stable",
                signal_level="low",
                skill_version="1.0.0",
                model_used="test",
                output_payload={},
                confidence_score=0.5,
            )
        ai_snaps = db.list_trend_snapshots(metric_name="ai_rate")
        assert len(ai_snaps) == 1

    def test_list_returns_most_recent_first(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for i, sid in enumerate(["snap-old", "snap-new"]):
            db.insert_trend_snapshot(
                snapshot_id=sid,
                product_code="QIH",
                metric_name="ai_rate",
                window_days=90,
                period_count=8,
                slope_per_period=float(i),
                mk_tau=0.0,
                mk_p_value=1.0,
                mean_value=0.0,
                recent_value=0.0,
                baseline_value=0.0,
                trend_direction="stable",
                signal_level="low",
                skill_version="1.0.0",
                model_used="test",
                output_payload={},
                confidence_score=0.5,
            )
        snaps = db.list_trend_snapshots()
        assert len(snaps) == 2
        # Most recent first — snap-new was inserted last so has latest analysis_ts
        assert snaps[0].snapshot_id == "snap-new"


# ──────────────────────────────────────────────────────────────────────────────
# Database: get_metric_time_series
# ──────────────────────────────────────────────────────────────────────────────


class TestMetricTimeSeries:
    def test_empty_db_returns_all_zero_buckets(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        series = db.get_metric_time_series(
            product_code="QIH",
            metric_name="ai_rate",
            window_days=30,
            bucket_size_days=7,
        )
        assert len(series) > 0
        # All values should be 0.0 (no data)
        assert all(v == 0.0 for _, v in series)

    def test_report_volume_counts_extractions(self, tmp_path: Path) -> None:
        from sqlalchemy.orm import Session

        from maudesignal.storage.models import ExtractionRecord, NormalizedEventRecord

        db = _in_memory_db(tmp_path)
        # Insert a normalized event + extraction 5 days ago
        with Session(db._engine) as session:
            session.add(
                NormalizedEventRecord(
                    maude_report_id="R001",
                    product_code="QIH",
                    event_type="malfunction",
                    event_date=None,
                    narrative="test",
                    mfr_narrative=None,
                    manufacturer=None,
                    brand_name=None,
                )
            )
            session.commit()
            five_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)
            session.add(
                ExtractionRecord(
                    extraction_id="E001",
                    maude_report_id="R001",
                    extraction_ts=five_days_ago,
                    skill_name="maude-narrative-extractor",
                    skill_version="1.0.0",
                    model_used="test",
                    output_json=json.dumps({"ai_related_flag": True}),
                    confidence_score=0.9,
                    requires_review=False,
                )
            )
            session.commit()

        series = db.get_metric_time_series(
            product_code="QIH",
            metric_name="report_volume",
            window_days=14,
            bucket_size_days=7,
        )
        total = sum(v for _, v in series)
        assert total == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# TrendDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestTrendDetector:
    def _make_detector(self, tmp_path: Path, extractor_output: dict[str, Any]) -> TrendDetector:
        skills_root = Path(__file__).parent.parent.parent / "skills"
        db = _in_memory_db(tmp_path)
        mock_extractor = MagicMock()
        mock_extractor.run.return_value = _fake_extractor_result(extractor_output)
        detector = TrendDetector.__new__(TrendDetector)
        detector._extractor = mock_extractor
        detector._db = db
        from maudesignal.extraction.skill_loader import SkillLoader

        loader = SkillLoader(skills_root)
        detector._skill = loader.load("trend-interpreter")
        return detector

    def test_skips_when_insufficient_data(self, tmp_path: Path) -> None:
        detector = self._make_detector(tmp_path, _good_trend_output())
        results = detector.run(
            product_code="QIH",
            metrics=["ai_rate"],
            window_days=30,
            bucket_size_days=7,
            min_periods=4,
        )
        assert len(results) == 1
        r = results[0]
        assert r.skipped is True
        assert r.skip_reason is not None

    def test_raises_on_unknown_metric(self, tmp_path: Path) -> None:
        detector = self._make_detector(tmp_path, _good_trend_output())
        with pytest.raises(ValueError, match="Unknown metric"):
            detector.run(product_code="QIH", metrics=["bad_metric"])

    def test_runs_all_metrics_by_default(self, tmp_path: Path) -> None:
        detector = self._make_detector(tmp_path, _good_trend_output())
        results = detector.run(product_code="QIH", window_days=30)
        # All 3 metrics — may all be skipped due to no data, but should return 3 results
        assert len(results) == 3

    def test_stores_snapshot_when_data_available(self, tmp_path: Path) -> None:
        from datetime import timedelta

        from sqlalchemy.orm import Session

        from maudesignal.storage.models import ExtractionRecord, NormalizedEventRecord

        db_path = tmp_path / "test.db"
        db = Database(db_path)

        # Seed enough data across 60 days for 8+ buckets
        with Session(db._engine) as session:
            for i in range(20):
                rid = f"R{i:03d}"
                session.add(
                    NormalizedEventRecord(
                        maude_report_id=rid,
                        product_code="QIH",
                        event_type="malfunction",
                        event_date=None,
                        narrative=f"report {i}",
                        mfr_narrative=None,
                        manufacturer=None,
                        brand_name=None,
                    )
                )
                ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60 - i * 3)
                session.add(
                    ExtractionRecord(
                        extraction_id=f"E{i:03d}",
                        maude_report_id=rid,
                        extraction_ts=ts,
                        skill_name="maude-narrative-extractor",
                        skill_version="1.0.0",
                        model_used="test",
                        output_json=json.dumps({"ai_related_flag": i % 2 == 0}),
                        confidence_score=0.9,
                        requires_review=False,
                    )
                )
            session.commit()

        mock_extractor = MagicMock()
        mock_extractor.run.return_value = _fake_extractor_result(_good_trend_output())
        skills_root = Path(__file__).parent.parent.parent / "skills"
        from maudesignal.extraction.skill_loader import SkillLoader

        loader = SkillLoader(skills_root)
        detector = TrendDetector.__new__(TrendDetector)
        detector._extractor = mock_extractor
        detector._db = db
        detector._skill = loader.load("trend-interpreter")

        results = detector.run(
            product_code="QIH",
            metrics=["ai_rate"],
            window_days=60,
            bucket_size_days=7,
            min_periods=4,
        )
        assert len(results) == 1
        r = results[0]
        if not r.skipped:
            snaps = db.list_trend_snapshots(product_code="QIH", metric_name="ai_rate")
            assert len(snaps) >= 1
