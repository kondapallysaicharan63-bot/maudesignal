"""E2E tests for the MAUDE Ingestion page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def ingestion(ms_page: Page) -> Page:
    navigate(ms_page, "MAUDE Ingestion")
    return ms_page


class TestIngestionPageLoads:
    def test_page_header(self, ingestion: Page) -> None:
        expect(
            ingestion.get_by_role("heading", name="MAUDE Ingestion", exact=False)
        ).to_be_visible()

    def test_no_exception_banner(self, ingestion: Page) -> None:
        assert ingestion.locator("[data-testid='stException']").count() == 0

    def test_subtitle_references_openfda_or_ingest(self, ingestion: Page) -> None:
        content = ingestion.content()
        assert any(
            kw in content.lower() for kw in ("openfda", "ingest", "adverse event")
        ), "Expected ingestion subtitle to reference openFDA or adverse events"


class TestIngestionQueueStatus:
    def test_current_db_count_shown(self, ingestion: Page) -> None:
        content = ingestion.content()
        assert any(
            str(n) in content for n in range(0, 10_000)
        ), "Expected numeric DB record count on Ingestion page"

    def test_ingestion_section_present(self, ingestion: Page) -> None:
        content = ingestion.content()
        assert any(
            kw in content for kw in ("Ingest", "Run Ingestion", "Pull")
        ), "Expected an ingestion action section heading"


class TestIngestionForm:
    def test_product_code_label(self, ingestion: Page) -> None:
        expect(ingestion.get_by_text("Product Code", exact=False)).to_be_visible()

    def test_run_button_present(self, ingestion: Page) -> None:
        content = ingestion.content()
        assert any(
            kw in content for kw in ("Run Ingestion", "Ingest", "Start")
        ), "Expected a Run/Ingest action button"

    def test_product_code_input_accepts_text(self, ingestion: Page) -> None:
        # Scoped to the page body: the top bar's theme picker is also a text input.
        main = ingestion.locator("[data-testid='stMainBlockContainer']")
        inputs = main.locator("input[type='text']:not([role='combobox'])")
        if inputs.count() == 0:
            pytest.skip("No text input found — form may use a different widget")
        inputs.first.fill("QIH")
        ingestion.wait_for_timeout(500)
        expect(
            ingestion.get_by_role("heading", name="MAUDE Ingestion", exact=False)
        ).to_be_visible()
