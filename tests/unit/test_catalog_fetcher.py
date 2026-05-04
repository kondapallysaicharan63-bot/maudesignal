"""Unit tests for CatalogFetcher and catalog CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from maudesignal.catalog.fetcher import CatalogFetcher, CatalogUpdateResult
from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(results: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"results": results}
    resp.raise_for_status.return_value = None
    return resp


def _not_found_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status.return_value = None
    return resp


def _api_result(product_code: str, device_name: str = "Test Device") -> dict:
    return {
        "product_code": product_code,
        "device_name": device_name,
        "applicant": "Test Corp",
        "advisory_committee_description": "Radiology",
        "decision_date": "20240101",
        "k_number": "K240001",
    }


# ---------------------------------------------------------------------------
# CatalogFetcher tests
# ---------------------------------------------------------------------------


class TestCatalogFetcher:
    def test_update_deduplicates_by_product_code(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        # Two keywords both return the same product code QIH.
        dup_result = _api_result("QIH")
        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _fake_response([dup_result])
            result = fetcher.update()

        # Should deduplicate — QIH appears once in catalog regardless of keyword count.
        assert result.devices_found >= 1
        devices = db.list_catalog_devices()
        codes = [d.product_code for d in devices]
        assert codes.count("QIH") == 1

    def test_404_keyword_yields_empty_list(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _not_found_response()
            result = fetcher.update()

        # 404s produce no API devices; seed list still populates catalog.
        assert result.errors == []
        assert result.devices_found > 0  # seed list always adds entries

    def test_api_error_is_recorded_not_raised(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.side_effect = RuntimeError("network error")
            result = fetcher.update()

        assert len(result.errors) == result.keywords_searched
        # Seed list is still merged even when all API calls fail.
        assert result.devices_found > 0

    def test_seed_list_not_overwritten_by_api(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        # API returns QIH with rich data; seed list also has QIH but simpler.
        api_result = _api_result("QIH", "Radiology AI v2")
        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _fake_response([api_result])
            fetcher.update()

        devices = {d.product_code: d for d in db.list_catalog_devices()}
        # QIH came from the live API — its device_name is the API value.
        assert devices["QIH"].device_name == "Radiology AI v2"

    def test_new_vs_updated_counts(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _fake_response([_api_result("XYZ")])
            r1 = fetcher.update()

        # First run — XYZ is new; seed list is all new.
        assert r1.product_codes_new > 0

        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _fake_response([_api_result("XYZ")])
            r2 = fetcher.update()

        # Second run — everything is updated, nothing new.
        assert r2.product_codes_new == 0
        assert r2.product_codes_updated > 0

    def test_product_code_normalized_to_uppercase(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        fetcher = CatalogFetcher(db)

        lower_result = _api_result("qih")  # lowercase from API
        with (
            patch("maudesignal.catalog.fetcher.httpx.get") as mock_get,
            patch("maudesignal.catalog.fetcher.time.sleep"),
        ):
            mock_get.return_value = _fake_response([lower_result])
            fetcher.update()

        devices = {d.product_code: d for d in db.list_catalog_devices()}
        assert "QIH" in devices

    def test_result_dataclass_defaults(self) -> None:
        r = CatalogUpdateResult()
        assert r.devices_found == 0
        assert r.product_codes_new == 0
        assert r.errors == []


# ---------------------------------------------------------------------------
# Database catalog methods
# ---------------------------------------------------------------------------


class TestDatabaseCatalogMethods:
    def test_upsert_and_list(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        is_new = db.upsert_catalog_device(
            product_code="QIH",
            device_name="Radiology CAD",
            company_name="Acme",
            specialty="Radiology",
            decision_date="20240101",
            k_number="K240001",
            source_keyword="machine learning",
        )
        assert is_new is True
        devices = db.list_catalog_devices()
        assert len(devices) == 1
        assert devices[0].product_code == "QIH"

    def test_upsert_updates_existing(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        db.upsert_catalog_device(
            product_code="QIH",
            device_name="Old Name",
            company_name=None,
            specialty=None,
            decision_date=None,
            k_number=None,
            source_keyword=None,
        )
        db.upsert_catalog_device(
            product_code="QIH",
            device_name="New Name",
            company_name="Acme",
            specialty="Radiology",
            decision_date="20240101",
            k_number="K240001",
            source_keyword="machine learning",
        )
        devices = db.list_catalog_devices()
        assert len(devices) == 1
        assert devices[0].device_name == "New Name"

    def test_count_catalog_devices(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test.db")
        assert db.count_catalog_devices() == 0
        db.upsert_catalog_device(
            product_code="QIH",
            device_name="d",
            company_name=None,
            specialty=None,
            decision_date=None,
            k_number=None,
            source_keyword=None,
        )
        assert db.count_catalog_devices() == 1
