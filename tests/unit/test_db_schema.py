"""Tests for the database schema, table structure, and integrity constraints.

Verifies that all 11 expected tables exist, primary keys enforce uniqueness,
and the brand_name_lookup + upsert operations behave correctly.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


EXPECTED_TABLES = {
    "raw_reports",
    "normalized_events",
    "extractions",
    "device_catalog",
    "llm_audit_log",
    "root_cause_reports",
    "alert_rules",
    "alert_events",
    "trend_snapshots",
    "external_sources",
    "psur_reports",
}


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------


class TestTableExistence:
    def test_all_11_tables_exist(self, tmp_path: Path) -> None:
        """All 11 MaudeSignal tables are created on first DB init."""
        db = _make_db(tmp_path)
        inspector = inspect(db._engine)
        actual = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(actual), f"Missing tables: {EXPECTED_TABLES - actual}"

    def test_raw_reports_columns(self, tmp_path: Path) -> None:
        """raw_reports table has the expected columns."""
        db = _make_db(tmp_path)
        inspector = inspect(db._engine)
        cols = {c["name"] for c in inspector.get_columns("raw_reports")}
        assert {"maude_report_id", "product_code", "raw_json", "fetched_at"}.issubset(cols)

    def test_normalized_events_has_brand_name(self, tmp_path: Path) -> None:
        """normalized_events table exposes the brand_name column (required for Bug 3 fix)."""
        db = _make_db(tmp_path)
        inspector = inspect(db._engine)
        cols = {c["name"] for c in inspector.get_columns("normalized_events")}
        assert "brand_name" in cols

    def test_extractions_has_no_device_name_column(self, tmp_path: Path) -> None:
        """extractions table does NOT have a device_name column (Bug 3 root cause awareness)."""
        db = _make_db(tmp_path)
        inspector = inspect(db._engine)
        cols = {c["name"] for c in inspector.get_columns("extractions")}
        assert "device_name" not in cols


# ---------------------------------------------------------------------------
# Primary-key uniqueness
# ---------------------------------------------------------------------------


class TestPrimaryKeyConstraints:
    def test_raw_report_pk_prevents_duplicate(self, tmp_path: Path) -> None:
        """Inserting the same maude_report_id twice is a no-op, not an error."""
        db = _make_db(tmp_path)
        payload = {"k": "v"}
        db.upsert_raw_report(
            maude_report_id="DUP001",
            product_code="QIH",
            date_received="20250101",
            date_of_event=None,
            raw_payload=payload,
        )
        db.upsert_raw_report(
            maude_report_id="DUP001",
            product_code="QIH",
            date_received="20250101",
            date_of_event=None,
            raw_payload=payload,
        )
        assert db.count_raw_reports() == 1

    def test_device_catalog_upsert_updates_existing(self, tmp_path: Path) -> None:
        """Upserting same product_code with new device_name updates the row."""
        db = _make_db(tmp_path)
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
            company_name=None,
            specialty=None,
            decision_date=None,
            k_number=None,
            source_keyword=None,
        )
        devices = db.list_catalog_devices()
        assert len(devices) == 1
        assert devices[0].device_name == "New Name"


# ---------------------------------------------------------------------------
# brand_name_lookup (new method added for Bug 3)
# ---------------------------------------------------------------------------


class TestBrandNameLookup:
    def test_empty_table_returns_empty_dict(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        assert db.brand_name_lookup() == {}

    def test_multiple_product_codes_mapped_correctly(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        for rid, pc, brand in [
            ("R1", "QIH", "StrokeAI"),
            ("R2", "LLZ", "RetinalAI"),
            ("R3", "QFM", None),
        ]:
            db.upsert_normalized_event(
                maude_report_id=rid,
                product_code=pc,
                event_type=None,
                event_date=None,
                narrative=None,
                mfr_narrative=None,
                manufacturer=None,
                brand_name=brand,
            )
        lookup = db.brand_name_lookup()
        assert lookup == {"QIH": "StrokeAI", "LLZ": "RetinalAI"}

    def test_normalized_event_update_reflects_in_lookup(self, tmp_path: Path) -> None:
        """Upserting normalized event with new brand_name updates lookup."""
        db = _make_db(tmp_path)
        db.upsert_normalized_event(
            maude_report_id="R1",
            product_code="QIH",
            event_type=None,
            event_date=None,
            narrative=None,
            mfr_narrative=None,
            manufacturer=None,
            brand_name="OldBrand",
        )
        db.upsert_normalized_event(
            maude_report_id="R1",
            product_code="QIH",
            event_type=None,
            event_date=None,
            narrative=None,
            mfr_narrative=None,
            manufacturer=None,
            brand_name="NewBrand",
        )
        lookup = db.brand_name_lookup()
        assert lookup["QIH"] == "NewBrand"
