"""Trend detection pipeline for MaudeSignal (Phase 3).

Computes Mann-Kendall test + linear regression on time-bucketed metrics,
then calls Skill trend-interpreter to produce a regulatory narrative.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.storage.database import Database

VALID_METRICS: frozenset[str] = frozenset({"ai_rate", "severity_rate", "report_volume"})
_DEFAULT_WINDOW_DAYS = 90
_DEFAULT_BUCKET_DAYS = 7


@dataclass(frozen=True)
class TrendStats:
    """Raw statistical outputs from Mann-Kendall + linear regression."""

    slope_per_period: float
    intercept: float
    mk_tau: float
    mk_p_value: float
    mean_value: float
    recent_value: float
    baseline_value: float
    series: list[float]
    period_count: int


@dataclass(frozen=True)
class TrendResult:
    """Complete result of one trend detection run."""

    product_code: str
    metric_name: str
    stats: TrendStats
    snapshot_id: str
    output: dict[str, Any]
    skipped: bool = False
    skip_reason: str | None = None


class TrendDetector:
    """Compute trends for a product code across multiple metrics."""

    def __init__(
        self,
        *,
        extractor: Extractor,
        db: Database,
        skills_root: Path,
    ) -> None:
        """Initialize with extractor, database, and skills directory."""
        self._extractor = extractor
        self._db = db
        loader = SkillLoader(skills_root)
        self._skill = loader.load("trend-interpreter")

    def run(
        self,
        *,
        product_code: str,
        metrics: list[str] | None = None,
        window_days: int = _DEFAULT_WINDOW_DAYS,
        bucket_size_days: int = _DEFAULT_BUCKET_DAYS,
        min_periods: int = 4,
    ) -> list[TrendResult]:
        """Run trend detection for each metric; return one TrendResult per metric.

        Args:
            product_code: FDA product code to analyze.
            metrics: Subset of VALID_METRICS to run. Defaults to all three.
            window_days: Lookback window in days.
            bucket_size_days: Size of each time bucket.
            min_periods: Minimum number of non-zero buckets required; skip otherwise.
        """
        if metrics is None:
            metrics = sorted(VALID_METRICS)
        results: list[TrendResult] = []
        for metric in metrics:
            if metric not in VALID_METRICS:
                raise ValueError(f"Unknown metric {metric!r}. Valid: {sorted(VALID_METRICS)}")
            result = self._detect_one(
                product_code=product_code,
                metric_name=metric,
                window_days=window_days,
                bucket_size_days=bucket_size_days,
                min_periods=min_periods,
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_one(
        self,
        *,
        product_code: str,
        metric_name: str,
        window_days: int,
        bucket_size_days: int,
        min_periods: int,
    ) -> TrendResult:
        """Run trend detection for one (product_code, metric_name) pair."""
        time_series = self._db.get_metric_time_series(
            product_code=product_code,
            metric_name=metric_name,
            window_days=window_days,
            bucket_size_days=bucket_size_days,
        )
        series = [v for _, v in time_series]
        nonzero = sum(1 for v in series if v > 0)
        snapshot_id = f"ts-{uuid.uuid4().hex[:12]}"

        if len(series) < min_periods or nonzero < min_periods // 2:
            return TrendResult(
                product_code=product_code,
                metric_name=metric_name,
                stats=_empty_stats(series),
                snapshot_id=snapshot_id,
                output={},
                skipped=True,
                skip_reason=f"Insufficient data: {len(series)} buckets, {nonzero} non-zero",
            )

        trend_stats = _compute_stats(series)
        skill_input = _build_skill_input(
            product_code=product_code,
            metric_name=metric_name,
            window_days=window_days,
            trend_stats=trend_stats,
        )
        result = self._extractor.run(self._skill, skill_input)

        self._db.insert_trend_snapshot(
            snapshot_id=snapshot_id,
            product_code=product_code,
            metric_name=metric_name,
            window_days=window_days,
            period_count=trend_stats.period_count,
            slope_per_period=trend_stats.slope_per_period,
            mk_tau=trend_stats.mk_tau,
            mk_p_value=trend_stats.mk_p_value,
            mean_value=trend_stats.mean_value,
            recent_value=trend_stats.recent_value,
            baseline_value=trend_stats.baseline_value,
            trend_direction=result.output.get("trend_direction", "stable"),
            signal_level=result.output.get("signal_level", "routine"),
            skill_version=self._skill.version,
            model_used=result.model_used,
            output_payload=result.output,
            confidence_score=result.output.get("confidence_score", 0.0),
        )
        return TrendResult(
            product_code=product_code,
            metric_name=metric_name,
            stats=trend_stats,
            snapshot_id=snapshot_id,
            output=result.output,
        )


def _compute_stats(series: list[float]) -> TrendStats:
    """Compute Mann-Kendall + linear regression statistics for a series."""
    arr = np.array(series, dtype=float)
    x = np.arange(len(arr), dtype=float)

    # Linear regression for slope
    slope, intercept, _r, _p, _se = stats.linregress(x, arr)

    # Mann-Kendall trend test
    mk_tau, mk_p = _mann_kendall(arr)

    return TrendStats(
        slope_per_period=float(slope),
        intercept=float(intercept),
        mk_tau=float(mk_tau),
        mk_p_value=float(mk_p),
        mean_value=float(np.mean(arr)),
        recent_value=float(arr[-1]),
        baseline_value=float(arr[0]),
        series=series,
        period_count=len(series),
    )


def _empty_stats(series: list[float]) -> TrendStats:
    """Return zero-valued stats for a skipped series."""
    return TrendStats(
        slope_per_period=0.0,
        intercept=0.0,
        mk_tau=0.0,
        mk_p_value=1.0,
        mean_value=0.0,
        recent_value=0.0,
        baseline_value=0.0,
        series=series,
        period_count=len(series),
    )


def _mann_kendall(arr: np.ndarray[Any, np.dtype[np.float64]]) -> tuple[float, float]:
    """Compute Mann-Kendall tau and two-tailed p-value.

    Uses the normal approximation (valid for n >= 8; acceptable for smaller n).
    """
    n = len(arr)
    s = 0.0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = arr[j] - arr[i]
            if diff > 0:
                s += 1.0
            elif diff < 0:
                s -= 1.0

    # Variance of S under H0 (no ties assumed for simplicity)
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if var_s == 0:
        return 0.0, 1.0

    # Continuity-corrected z-score
    if s > 0:
        z = (s - 1.0) / (var_s**0.5)
    elif s < 0:
        z = (s + 1.0) / (var_s**0.5)
    else:
        z = 0.0

    p_value = 2.0 * (1.0 - float(stats.norm.cdf(abs(z))))

    # tau = S / (n*(n-1)/2)
    tau = s / (n * (n - 1) / 2.0)
    return tau, p_value


def _build_skill_input(
    *,
    product_code: str,
    metric_name: str,
    window_days: int,
    trend_stats: TrendStats,
) -> dict[str, Any]:
    """Build the input dict for the trend-interpreter Skill."""
    return {
        "product_code": product_code,
        "metric_name": metric_name,
        "window_days": window_days,
        "period_count": trend_stats.period_count,
        "slope_per_period": trend_stats.slope_per_period,
        "mk_tau": trend_stats.mk_tau,
        "mk_p_value": trend_stats.mk_p_value,
        "mean_value": trend_stats.mean_value,
        "recent_value": trend_stats.recent_value,
        "baseline_value": trend_stats.baseline_value,
        "series": trend_stats.series,
    }
