"""Pure statistical functions for drift detection (FR-19)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy import stats


def ks_test(baseline: Sequence[float], current: Sequence[float]) -> tuple[float, float]:
    """Two-sample Kolmogorov–Smirnov test. Returns (statistic, p_value)."""
    if len(baseline) < 2 or len(current) < 2:
        return (0.0, 1.0)
    result = stats.ks_2samp(list(baseline), list(current))
    return (float(result.statistic), float(result.pvalue))


def psi_calculator(
    baseline: Sequence[float],
    current: Sequence[float],
    bins: int = 10,
) -> float:
    """Population Stability Index over equal-width bins of the baseline range."""
    if not baseline or not current:
        return 0.0
    b = np.asarray(baseline, dtype=float)
    c = np.asarray(current, dtype=float)
    lo, hi = float(np.min(b)), float(np.max(b))
    if lo == hi:
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    b_counts, _ = np.histogram(b, bins=edges)
    c_counts, _ = np.histogram(c, bins=edges)
    eps = 1e-6
    b_pct = (b_counts / max(b_counts.sum(), 1)) + eps
    c_pct = (c_counts / max(c_counts.sum(), 1)) + eps
    return float(np.sum((c_pct - b_pct) * np.log(c_pct / b_pct)))


def delta_pct(baseline: float, current: float) -> float:
    """Percent change from baseline to current. Returns 0.0 if baseline == 0."""
    if baseline == 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0
