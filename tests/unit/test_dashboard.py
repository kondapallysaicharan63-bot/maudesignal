"""Smoke tests for the Streamlit dashboard module."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import maudesignal.dashboard.app as app
from maudesignal.storage.database import Database
from maudesignal.storage.models import ExtractionRecord


def test_dashboard_module_importable() -> None:
    importlib.reload(app)
    assert hasattr(app, "main")
    assert callable(app.main)
    for name in ("_page_records", "_page_drift", "_page_summary"):
        assert callable(getattr(app, name))


def test_extractions_dataframe_has_expected_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    db = Database(db_path)

    with db._session() as session:  # noqa: SLF001 — direct session use is fine in tests
        session.add(
            ExtractionRecord(
                extraction_id="e1",
                maude_report_id="MW-1",
                extraction_ts=datetime.now(UTC),
                skill_name="maude-narrative-extractor",
                skill_version="1.0.0",
                model_used="fake-model",
                output_json=json.dumps(
                    {
                        "severity": "malfunction",
                        "ai_related_flag": True,
                        "failure_mode": "fm",
                    }
                ),
                confidence_score=0.85,
                requires_review=False,
            )
        )
        session.commit()

    df = app._extractions_dataframe(db)  # noqa: SLF001
    assert not df.empty
    for col in (
        "extraction_ts",
        "maude_report_id",
        "skill_name",
        "confidence_score",
        "severity",
        "ai_related_flag",
        "failure_mode",
    ):
        assert col in df.columns
    assert df.iloc[0]["severity"] == "malfunction"
    assert bool(df.iloc[0]["ai_related_flag"]) is True


def test_maude_url_format() -> None:
    url = app._maude_url("1234567")  # noqa: SLF001
    assert url == (
        "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm"
        "?mdrfoi__id=1234567"
    )
    assert app._maude_url("0000001").endswith("mdrfoi__id=0000001")  # noqa: SLF001


def test_page_groups_contain_all_nine_pages() -> None:
    """_PAGE_GROUPS must cover every routable page — regression guard for nav crashes."""
    all_pages = [p for pages in app._PAGE_GROUPS.values() for p in pages]  # noqa: SLF001
    assert len(all_pages) == 9
    assert "Overview" in all_pages
    assert "Trends & Forecasting" in all_pages
    assert "External Sources" in all_pages
    assert "Device Catalog" in all_pages
    # No duplicates
    assert len(all_pages) == len(set(all_pages))


def test_failure_mode_chart_data_non_empty(tmp_path: Path) -> None:
    """Regression: failure-mode bar chart must get non-empty data when classifier records exist."""
    db_path = tmp_path / "fm_test.db"
    db = Database(db_path)

    payload = json.dumps(
        {
            "failure_mode_category": "software_bug",
            "failure_mode": "software bug",
            "ai_related_flag": True,
            "severity": "malfunction",
        }
    )
    with db._session() as session:  # noqa: SLF001
        for i in range(3):
            session.add(
                ExtractionRecord(
                    extraction_id=f"cls{i}",
                    maude_report_id=f"MW-{i}",
                    extraction_ts=datetime.now(UTC),
                    skill_name="ai-failure-mode-classifier",
                    skill_version="1.0.0",
                    model_used="fake",
                    output_json=payload,
                    confidence_score=0.9,
                    requires_review=False,
                )
            )
        session.commit()

    df = app._extractions_dataframe(db)  # noqa: SLF001
    df_cls = df[df["skill_name"] == "ai-failure-mode-classifier"]
    assert not df_cls.empty, "classifier records must appear in the extractions frame"
    fm_counts = df_cls["ai_failure_mode"].value_counts()
    assert fm_counts.sum() > 0, "failure mode chart data must be non-empty when records exist"
    # The value must survive the nan-to-dash normalisation unchanged
    assert "software_bug" in fm_counts.index, "actual DB values must pass through unchanged"


@pytest.fixture(autouse=True)
def _no_streamlit_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no test accidentally triggers a streamlit render."""
    monkeypatch.setattr(app, "_render_app", lambda db: None)
