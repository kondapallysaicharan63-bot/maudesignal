"""Unit tests for the ingestion pipeline and openFDA client helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from maudesignal.ingestion.pipeline import (
    IngestionResult,
    _extract_report_id,
    _normalize,
    ingest_product_code,
)
from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SENTINEL: list[str] = ["Malfunction"]


def _raw_event(
    report_id: str = "12345678",
    *,
    narrative: str | None = "Patient reported pain.",
    mfr_narrative: str | None = "Device examined; no defect found.",
    event_type: list[str] | None = _SENTINEL,
    brand: str = "TestDevice",
    mfr: str = "Acme Corp",
) -> dict:
    """Return a minimal openFDA device event payload."""
    mdr_text = []
    if narrative:
        mdr_text.append({"text_type_code": "Description of Event", "text": narrative})
    if mfr_narrative:
        mdr_text.append({"text_type_code": "Manufacturer Narrative", "text": mfr_narrative})

    return {
        "mdr_report_key": report_id,
        "event_type": event_type if event_type is not _SENTINEL else ["Malfunction"],
        "date_received": "20240601",
        "date_of_event": "20240530",
        "mdr_text": mdr_text,
        "device": [{"brand_name": brand, "manufacturer_d_name": mfr}],
    }


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# _extract_report_id
# ---------------------------------------------------------------------------


class TestExtractReportId:
    def test_uses_mdr_report_key(self) -> None:
        raw = {"mdr_report_key": "9876543", "other": "x"}
        assert _extract_report_id(raw) == "9876543"

    def test_falls_back_to_report_number(self) -> None:
        raw = {"report_number": "ABCD-001"}
        assert _extract_report_id(raw) == "ABCD-001"

    def test_returns_none_when_both_missing(self) -> None:
        assert _extract_report_id({}) is None

    def test_prefers_mdr_report_key_over_report_number(self) -> None:
        raw = {"mdr_report_key": "AAA", "report_number": "BBB"}
        assert _extract_report_id(raw) == "AAA"


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_extracts_narrative(self) -> None:
        raw = _raw_event(narrative="Device failed during scan.")
        result = _normalize(raw, "QIH")
        assert result["narrative"] == "Device failed during scan."

    def test_extracts_mfr_narrative(self) -> None:
        raw = _raw_event(mfr_narrative="Root cause: hardware fault.")
        result = _normalize(raw, "QIH")
        assert result["mfr_narrative"] == "Root cause: hardware fault."

    def test_event_type_lowercased(self) -> None:
        raw = _raw_event(event_type=["Injury"])
        result = _normalize(raw, "QIH")
        assert result["event_type"] == "injury"

    def test_missing_narratives_return_none(self) -> None:
        raw = _raw_event(narrative=None, mfr_narrative=None)
        result = _normalize(raw, "QIH")
        assert result["narrative"] is None
        assert result["mfr_narrative"] is None

    def test_extracts_brand_and_manufacturer(self) -> None:
        raw = _raw_event(brand="MyDevice", mfr="BigMed Inc")
        result = _normalize(raw, "QIH")
        assert result["brand_name"] == "MyDevice"
        assert result["manufacturer"] == "BigMed Inc"

    def test_empty_device_list_does_not_crash(self) -> None:
        raw = _raw_event()
        raw["device"] = []
        result = _normalize(raw, "QIH")
        assert result["brand_name"] is None
        assert result["manufacturer"] is None

    def test_empty_event_type_list(self) -> None:
        raw = _raw_event(event_type=[])
        result = _normalize(raw, "QIH")
        assert result["event_type"] is None


# ---------------------------------------------------------------------------
# ingest_product_code
# ---------------------------------------------------------------------------


class TestIngestProductCode:
    def _mock_client(self, records: list[dict]) -> MagicMock:
        client = MagicMock()
        client.iter_reports.return_value = iter(records)
        return client

    def test_new_records_are_counted(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        client = self._mock_client([_raw_event("R001"), _raw_event("R002")])
        result = ingest_product_code(client=client, db=db, product_code="QIH")

        assert result.records_fetched == 2
        assert result.records_new == 2
        assert result.records_skipped == 0

    def test_duplicate_records_not_counted_as_new(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        client1 = self._mock_client([_raw_event("R001")])
        ingest_product_code(client=client1, db=db, product_code="QIH")

        client2 = self._mock_client([_raw_event("R001")])
        result = ingest_product_code(client=client2, db=db, product_code="QIH")
        assert result.records_new == 0
        assert result.records_fetched == 1

    def test_missing_report_id_is_skipped(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        bad_record = _raw_event()
        del bad_record["mdr_report_key"]  # no ID at all
        client = self._mock_client([bad_record])
        result = ingest_product_code(client=client, db=db, product_code="QIH")

        assert result.records_fetched == 1
        assert result.records_new == 0
        assert result.skip_reasons.get("missing_report_id", 0) == 1

    def test_missing_narrative_flagged_in_skip_reasons(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        rec = _raw_event("R999", narrative=None, mfr_narrative=None)
        client = self._mock_client([rec])
        result = ingest_product_code(client=client, db=db, product_code="QIH")

        # Record still fetched and stored (raw + normalized), but flagged
        assert result.records_fetched == 1
        assert result.skip_reasons.get("missing_narrative", 0) == 1
        # Raw report IS stored even when narrative is empty
        assert db.count_raw_reports(product_code="QIH") == 1

    def test_result_product_code_matches_input(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        client = self._mock_client([])
        result = ingest_product_code(client=client, db=db, product_code="QFM")
        assert result.product_code == "QFM"

    def test_records_persisted_to_normalized_events(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        client = self._mock_client([_raw_event("R100", narrative="Scan failed.")])
        ingest_product_code(client=client, db=db, product_code="QIH")

        event = db.get_normalized_event("R100")
        assert event is not None
        assert event.narrative == "Scan failed."
        assert event.product_code == "QIH"


# ---------------------------------------------------------------------------
# IngestionResult dataclass
# ---------------------------------------------------------------------------


def test_ingestion_result_frozen() -> None:
    r = IngestionResult(
        product_code="QIH",
        records_fetched=10,
        records_new=8,
        records_skipped=2,
        skip_reasons={"missing_narrative": 2},
    )
    with pytest.raises((AttributeError, TypeError)):
        r.records_fetched = 99  # type: ignore[misc]
