"""Tests validating the three bug fixes applied in Phase 1.

Bug 1 — Icon text bleeding: confirmed N/A (emoji labels used, no raw icon text).
Bug 2 — openFDA HTTP 500 not retried: OpenFDAUnavailableError added; retry now covers 500/503.
Bug 3 — Device column shows '—': _device_name_lookup now falls back to normalized_events.brand_name.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from maudesignal.common.exceptions import (
    OpenFDAAPIError,
    OpenFDAUnavailableError,
)
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _seed_normalized_event(
    db: Database,
    *,
    maude_report_id: str = "MW001",
    product_code: str = "QIH",
    brand_name: str | None = "StrokeAI v2.1",
) -> None:
    db.upsert_normalized_event(
        maude_report_id=maude_report_id,
        product_code=product_code,
        event_type="malfunction",
        event_date=None,
        narrative="Test.",
        mfr_narrative=None,
        manufacturer=None,
        brand_name=brand_name,
    )


# ---------------------------------------------------------------------------
# Bug 2 — HTTP 500/503 retry
# ---------------------------------------------------------------------------


class TestBug2OpenFDA500Retry:
    """OpenFDAUnavailableError is raised for 500/503 and retried."""

    def test_openfda_unavailable_error_exists(self) -> None:
        """OpenFDAUnavailableError is importable from exceptions module."""
        err = OpenFDAUnavailableError("server error 503")
        assert isinstance(err, OpenFDAAPIError)
        assert "server error" in str(err)

    def test_500_raises_unavailable_not_generic_api_error(self) -> None:
        """HTTP 500 raises OpenFDAUnavailableError (retryable) not OpenFDAAPIError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        client = OpenFDAClient()
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(OpenFDAUnavailableError):
                client._fetch_page.__wrapped__(client, query="q", skip=0, limit=10)

    def test_503_raises_unavailable_error(self) -> None:
        """HTTP 503 raises OpenFDAUnavailableError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        client = OpenFDAClient()
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(OpenFDAUnavailableError):
                client._fetch_page.__wrapped__(client, query="q", skip=0, limit=10)

    def test_non_500_server_error_still_raises_api_error(self) -> None:
        """HTTP 502 (not explicitly retried) raises OpenFDAAPIError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 502

        client = OpenFDAClient()
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(OpenFDAAPIError):
                client._fetch_page.__wrapped__(client, query="q", skip=0, limit=10)

    def test_500_eventually_propagates_after_max_retries(self) -> None:
        """After MAX_RETRIES the exception is re-raised."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        client = OpenFDAClient()
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(OpenFDAUnavailableError):
                client._fetch_page(query="q", skip=0, limit=10)


# ---------------------------------------------------------------------------
# Bug 3 — Device column fallback to brand_name
# ---------------------------------------------------------------------------


class TestBug3DeviceNameFallback:
    """brand_name_lookup + _device_name_lookup fall back to normalized_events."""

    def test_brand_name_lookup_returns_mapping(self, tmp_path: Path) -> None:
        """brand_name_lookup returns product_code → brand_name from normalized_events."""
        db = _make_db(tmp_path)
        _seed_normalized_event(db, maude_report_id="R1", product_code="QIH", brand_name="StrokeAI")
        _seed_normalized_event(db, maude_report_id="R2", product_code="LLZ", brand_name="RetinalAI")

        lookup = db.brand_name_lookup()
        assert lookup["QIH"] == "StrokeAI"
        assert lookup["LLZ"] == "RetinalAI"

    def test_brand_name_lookup_skips_null_brand_names(self, tmp_path: Path) -> None:
        """Events with brand_name=None do not appear in the lookup."""
        db = _make_db(tmp_path)
        _seed_normalized_event(db, maude_report_id="R1", product_code="QIH", brand_name=None)

        lookup = db.brand_name_lookup()
        assert "QIH" not in lookup

    def test_brand_name_lookup_uses_first_non_null_per_code(self, tmp_path: Path) -> None:
        """Only the first brand_name per product_code is returned (stable)."""
        db = _make_db(tmp_path)
        _seed_normalized_event(db, maude_report_id="R1", product_code="QIH", brand_name="First")
        _seed_normalized_event(db, maude_report_id="R2", product_code="QIH", brand_name="Second")

        lookup = db.brand_name_lookup()
        assert lookup["QIH"] == "First"

    def test_device_name_lookup_falls_back_when_catalog_empty(self, tmp_path: Path) -> None:
        """When device_catalog has no entry, brand_name from normalized_events is used."""
        from maudesignal.dashboard.app import _device_name_lookup

        db = _make_db(tmp_path)
        _seed_normalized_event(db, product_code="QIH", brand_name="StrokeAI v2.1")

        lookup = _device_name_lookup(db)
        assert lookup.get("QIH") == "StrokeAI v2.1"

    def test_device_name_lookup_catalog_wins_over_brand_name(self, tmp_path: Path) -> None:
        """Catalog device_name takes precedence over brand_name from normalized_events."""

        from maudesignal.dashboard.app import _device_name_lookup

        db = _make_db(tmp_path)
        _seed_normalized_event(db, product_code="QIH", brand_name="BrandName from Event")
        db.upsert_catalog_device(
            product_code="QIH",
            device_name="Catalog Device Name",
            company_name=None,
            specialty=None,
            decision_date=None,
            k_number=None,
            source_keyword=None,
        )

        lookup = _device_name_lookup(db)
        assert lookup["QIH"] == "Catalog Device Name"

    def test_device_name_lookup_empty_db_returns_empty(self, tmp_path: Path) -> None:
        """Empty DB returns empty dict (no KeyError)."""
        from maudesignal.dashboard.app import _device_name_lookup

        db = _make_db(tmp_path)
        lookup = _device_name_lookup(db)
        assert isinstance(lookup, dict)
        assert len(lookup) == 0
