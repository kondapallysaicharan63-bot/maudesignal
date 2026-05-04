"""Unit tests for the MaudeSignal CLI (typer commands)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from maudesignal.cli import app
from maudesignal.config import Config
from maudesignal.storage.database import Database

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config(tmp_path: Path) -> Config:
    """Minimal Config pointing at a temp SQLite database."""
    return Config(
        llm_provider="groq",
        groq_api_key="gsk_fake",
        groq_model="llama-3.3-70b-versatile",
        anthropic_api_key=None,
        claude_model_extraction="claude-sonnet-4-6",
        claude_model_reasoning="claude-opus-4-7",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        gemini_api_key=None,
        gemini_model="gemini-2.5-flash",
        provider_fallback_order="groq",
        openfda_api_key=None,
        db_path=tmp_path / "test.db",
        log_level="WARNING",
        cost_ceiling_usd=150.0,
        project_root=Path(__file__).resolve().parents[2],
    )


@pytest.fixture()
def tmp_db(tmp_config: Config) -> Database:
    return Database(tmp_config.db_path)


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def test_help_flag_shows_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "extract" in result.output
    assert "catalog" in result.output
    assert "status" in result.output


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_shows_db_info(tmp_config: Config, tmp_db: Database) -> None:
    with patch("maudesignal.cli.Config.load", return_value=tmp_config):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Raw reports" in result.output
    assert "LLM spend" in result.output


def test_status_config_error_exits_2() -> None:
    from maudesignal.config import ConfigError

    with patch("maudesignal.cli.Config.load", side_effect=ConfigError("bad config")):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 2
    assert "bad config" in result.output


# ---------------------------------------------------------------------------
# ingest command
# ---------------------------------------------------------------------------


def test_ingest_no_flags_exits_2(tmp_config: Config) -> None:
    """ingest without --product-code or --all-ai must exit 2."""
    with patch("maudesignal.cli.Config.load", return_value=tmp_config):
        result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 2
    assert "--product-code" in result.output or "Provide" in result.output


def test_ingest_product_code_happy_path(tmp_config: Config) -> None:
    from maudesignal.ingestion.pipeline import IngestionResult as IngestResult

    fake_result = IngestResult(
        product_code="QIH",
        records_fetched=5,
        records_new=5,
        records_skipped=0,
        skip_reasons={},
    )
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("maudesignal.cli.Config.load", return_value=tmp_config),
        patch("maudesignal.cli.OpenFDAClient", return_value=mock_client),
        patch("maudesignal.cli.ingest_product_code", return_value=fake_result),
    ):
        result = runner.invoke(app, ["ingest", "--product-code", "QIH", "--limit", "5"])

    assert result.exit_code == 0
    assert "5" in result.output  # records_fetched


def test_ingest_maude_error_exits_1(tmp_config: Config) -> None:
    from maudesignal.common.exceptions import MaudeSignalError

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("maudesignal.cli.Config.load", return_value=tmp_config),
        patch("maudesignal.cli.OpenFDAClient", return_value=mock_client),
        patch("maudesignal.cli.ingest_product_code", side_effect=MaudeSignalError("API down")),
    ):
        result = runner.invoke(app, ["ingest", "--product-code", "QIH"])

    assert result.exit_code == 1
    assert "API down" in result.output


# ---------------------------------------------------------------------------
# ingest --all-ai
# ---------------------------------------------------------------------------


def test_ingest_all_ai_empty_catalog(tmp_config: Config, tmp_db: Database) -> None:
    """--all-ai with no catalog entries prints a warning and returns 0."""
    with patch("maudesignal.cli.Config.load", return_value=tmp_config):
        result = runner.invoke(app, ["ingest", "--all-ai"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "catalog" in result.output.lower()


def test_ingest_all_ai_iterates_catalog(tmp_config: Config, tmp_db: Database) -> None:
    from maudesignal.ingestion.pipeline import IngestionResult as IngestResult

    tmp_db.upsert_catalog_device(
        product_code="QIH",
        device_name="Radiology CAD",
        company_name=None,
        specialty="Radiology",
        decision_date=None,
        k_number=None,
        source_keyword="seed_list",
    )
    fake_result = IngestResult(
        product_code="QIH",
        records_fetched=3,
        records_new=3,
        records_skipped=0,
        skip_reasons={},
    )
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("maudesignal.cli.Config.load", return_value=tmp_config),
        patch("maudesignal.cli.OpenFDAClient", return_value=mock_client),
        patch("maudesignal.cli.ingest_product_code", return_value=fake_result),
    ):
        result = runner.invoke(app, ["ingest", "--all-ai", "--limit", "5"])

    assert result.exit_code == 0
    assert "QIH" in result.output or "Bulk" in result.output


# ---------------------------------------------------------------------------
# catalog update
# ---------------------------------------------------------------------------


def test_catalog_update_runs(tmp_config: Config) -> None:
    from maudesignal.catalog.fetcher import CatalogUpdateResult

    fake_result = CatalogUpdateResult(
        devices_found=18,
        product_codes_new=18,
        product_codes_updated=0,
        keywords_searched=12,
        errors=[],
    )
    with (
        patch("maudesignal.cli.Config.load", return_value=tmp_config),
        patch("maudesignal.catalog.fetcher.CatalogFetcher.update", return_value=fake_result),
        patch("maudesignal.catalog.fetcher.httpx.get"),
        patch("maudesignal.catalog.fetcher.time.sleep"),
    ):
        result = runner.invoke(app, ["catalog", "update"])
    assert result.exit_code == 0
    assert "12" in result.output or "18" in result.output or "Keywords" in result.output


def test_catalog_update_shows_errors(tmp_config: Config) -> None:
    from maudesignal.catalog.fetcher import CatalogUpdateResult

    fake_result = CatalogUpdateResult(
        devices_found=5,
        product_codes_new=5,
        product_codes_updated=0,
        keywords_searched=12,
        errors=["keyword=foo: timeout"],
    )
    with (
        patch("maudesignal.cli.Config.load", return_value=tmp_config),
        patch("maudesignal.catalog.fetcher.CatalogFetcher.update", return_value=fake_result),
    ):
        result = runner.invoke(app, ["catalog", "update"])
    assert result.exit_code == 0
    assert "timeout" in result.output


# ---------------------------------------------------------------------------
# catalog list
# ---------------------------------------------------------------------------


def test_catalog_list_empty(tmp_config: Config, tmp_db: Database) -> None:
    with patch("maudesignal.cli.Config.load", return_value=tmp_config):
        result = runner.invoke(app, ["catalog", "list"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower()


def test_catalog_list_shows_devices(tmp_config: Config, tmp_db: Database) -> None:
    tmp_db.upsert_catalog_device(
        product_code="QIH",
        device_name="Radiology CAD Software",
        company_name="AcmeMed",
        specialty="Radiology",
        decision_date="20240101",
        k_number="K240001",
        source_keyword="machine learning",
    )
    with patch("maudesignal.cli.Config.load", return_value=tmp_config):
        result = runner.invoke(app, ["catalog", "list"])
    assert result.exit_code == 0
    assert "QIH" in result.output
    assert "Radiology" in result.output
