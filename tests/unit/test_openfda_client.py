"""Unit tests for openFDA client helpers (no network)."""

from __future__ import annotations

from safesignal.ingestion.openfda_client import _build_query


def test_build_query_product_only() -> None:
    """Product code alone produces a clean query."""
    q = _build_query("QIH", start_date=None, end_date=None)
    assert q == "device.openfda.product_code:QIH"


def test_build_query_full_range() -> None:
    """Both dates produce a bracketed date_received clause."""
    q = _build_query("QAS", start_date="20240101", end_date="20241231")
    assert "device.openfda.product_code:QAS" in q
    assert "date_received:[20240101+TO+20241231]" in q
    assert q.count("+AND+") == 1


def test_build_query_start_only() -> None:
    """Start date alone uses an open-ended upper bound."""
    q = _build_query("QFM", start_date="20250101", end_date=None)
    assert "date_received:[20250101+TO+99991231]" in q


def test_build_query_end_only() -> None:
    """End date alone uses an open-ended lower bound."""
    q = _build_query("QFM", start_date=None, end_date="20251231")
    assert "date_received:[19900101+TO+20251231]" in q
