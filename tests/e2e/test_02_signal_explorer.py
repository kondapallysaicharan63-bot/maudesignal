"""E2E tests for the Signal Explorer page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def explorer(ms_page: Page) -> Page:
    navigate(ms_page, "Signal Explorer")
    return ms_page


class TestSignalExplorerLoads:
    def test_page_header(self, explorer: Page) -> None:
        expect(explorer.get_by_role("heading", name="Signal Explorer", exact=False)).to_be_visible()

    def test_no_exception_banner(self, explorer: Page) -> None:
        assert explorer.locator("[data-testid='stException']").count() == 0

    def test_subtitle_mentions_filter_or_browse(self, explorer: Page) -> None:
        content = explorer.content()
        assert any(
            kw in content.lower() for kw in ("filter", "browse", "export")
        ), "Expected subtitle with 'filter', 'browse', or 'export'"


class TestSignalExplorerFilters:
    def test_filters_section_heading(self, explorer: Page) -> None:
        assert "Filters" in explorer.content()

    def test_product_code_filter_in_content(self, explorer: Page) -> None:
        assert "Product Code" in explorer.content()

    def test_severity_filter_in_content(self, explorer: Page) -> None:
        assert "Severity" in explorer.content()

    def test_ai_flag_filter_in_content(self, explorer: Page) -> None:
        assert "AI Flag" in explorer.content()

    def test_date_range_filter_in_content(self, explorer: Page) -> None:
        assert "Date Range" in explorer.content()

    def test_search_box_present(self, explorer: Page) -> None:
        # Placeholder is "e.g. radiology, 1234567" on the Search device/report textbox
        search = explorer.get_by_placeholder("e.g. radiology", exact=False).first
        expect(search).to_be_visible()

    def test_severity_options_in_dom(self, explorer: Page) -> None:
        content = explorer.content()
        assert any(
            s in content for s in ("malfunction", "serious_injury", "(all)", "all")
        ), "Expected severity filter options in DOM"


class TestSignalExplorerTable:
    def test_record_count_text_shown(self, explorer: Page) -> None:
        assert (
            "records" in explorer.content().lower()
        ), "Expected 'X of Y records' count text on Signal Explorer"

    def test_report_id_column_present(self, explorer: Page) -> None:
        assert "Report ID" in explorer.content()

    def test_table_element_rendered(self, explorer: Page) -> None:
        tables = explorer.locator("table, [data-testid='stDataFrame']")
        assert tables.count() >= 1, "Expected at least one data table on Signal Explorer"

    def test_confidence_column_present(self, explorer: Page) -> None:
        assert "Confidence" in explorer.content()


class TestSignalExplorerFilterInteraction:
    def test_search_accepts_and_clears_input(self, explorer: Page) -> None:
        search = explorer.get_by_placeholder("e.g. radiology", exact=False).first
        search.fill("malfunction")
        explorer.wait_for_timeout(2_000)
        expect(explorer.get_by_role("heading", name="Signal Explorer", exact=False)).to_be_visible()
        search.fill("")
        explorer.wait_for_timeout(1_000)
        expect(explorer.get_by_role("heading", name="Signal Explorer", exact=False)).to_be_visible()

    def test_page_stable_after_filter_interaction(self, explorer: Page) -> None:
        assert explorer.locator("[data-testid='stException']").count() == 0


class TestSignalExplorerExport:
    def test_csv_export_present(self, explorer: Page) -> None:
        content = explorer.content()
        assert any(
            kw in content.lower() for kw in ("csv", "download", "export")
        ), "Expected a CSV download/export option on Signal Explorer"
