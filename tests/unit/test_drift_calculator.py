"""Drift calculator math tests."""

from __future__ import annotations

import numpy as np

from maudesignal.drift.calculator import delta_pct, ks_test, psi_calculator


def test_ks_identical_distributions_high_p() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 500).tolist()
    b = rng.normal(0, 1, 500).tolist()
    stat, p = ks_test(a, b)
    assert 0.0 <= stat <= 1.0
    assert p > 0.05


def test_ks_shifted_distribution_low_p() -> None:
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 500).tolist()
    b = rng.normal(2, 1, 500).tolist()
    _, p = ks_test(a, b)
    assert p < 0.001


def test_ks_short_input_returns_neutral() -> None:
    stat, p = ks_test([1.0], [2.0, 3.0])
    assert stat == 0.0 and p == 1.0


def test_psi_identical_returns_near_zero() -> None:
    rng = np.random.default_rng(2)
    a = rng.normal(0, 1, 1000).tolist()
    b = rng.normal(0, 1, 1000).tolist()
    assert psi_calculator(a, b) < 0.1  # below standard "stable" threshold


def test_psi_shifted_returns_above_threshold() -> None:
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, 1000).tolist()
    b = rng.normal(2, 1, 1000).tolist()
    assert psi_calculator(a, b) > 0.2


def test_delta_pct_zero_baseline_safe() -> None:
    assert delta_pct(0.0, 5.0) == 0.0
    assert delta_pct(100.0, 110.0) == 10.0
    assert delta_pct(100.0, 90.0) == -10.0
