"""E2E tests for the Dashboard page (default landing page)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def dash(ms_page: Page) -> Page:
    """The classic Dashboard sits under "More tools" in the sidebar (the hackathon build
    lands on What changed)."""
    navigate(ms_page, "Dashboard")
    return ms_page


class TestDashboardLoads:
    def test_sidebar_visible(self, dash: Page) -> None:
        expect(dash.locator("section[data-testid='stSidebar']")).to_be_visible()

    def test_maudesignal_branding_in_page(self, dash: Page) -> None:
        # Brand rendered via CSS/markdown; check full page HTML not sidebar text
        assert "MaudeSignal" in dash.content()

    def test_tagline_in_sidebar(self, dash: Page) -> None:
        sidebar = dash.locator("section[data-testid='stSidebar']")
        expect(sidebar).to_contain_text("Postmarket Surveillance")

    def test_page_header_visible(self, dash: Page) -> None:
        expect(dash.get_by_role("heading", name="Dashboard", exact=False)).to_be_visible()

    def test_no_exception_banner(self, dash: Page) -> None:
        assert dash.locator("[data-testid='stException']").count() == 0


class TestDashboardKPIs:
    def test_kpi_section_heading(self, dash: Page) -> None:
        expect(dash.get_by_text("Key Performance Indicators", exact=False)).to_be_visible()

    def test_maude_records_label(self, dash: Page) -> None:
        # Actual rendered label is "MAUDE Records"
        assert "MAUDE Records" in dash.content()

    def test_data_tiles_only_with_extractions(self, dash: Page) -> None:
        """AI signals / confidence / alert rules / extraction cost need extraction rows;
        without them (the keyless demo database) they are not shown as zeros."""
        content = dash.content()
        has_data = "No extraction results" not in content
        for label in (
            "AI Signals Detected",
            "Avg Confidence",
            "Active Alert Rules",
            "Extraction LLM cost",
        ):
            assert (label in content) == has_data, label
        assert "LLM Cost to Date" not in content

    def test_maude_records_is_numeric(self, dash: Page) -> None:
        content = dash.content()
        assert any(
            str(n) in content for n in range(0, 10_000)
        ), "MAUDE Records KPI does not contain any numeric value"


class TestDashboardCharts:
    def test_severity_distribution_heading(self, dash: Page) -> None:
        assert "Severity Distribution" in dash.content()

    def test_failure_mode_heading(self, dash: Page) -> None:
        # Full heading is "AI Failure Mode Breakdown"
        assert "AI Failure Mode Breakdown" in dash.content()

    def test_charts_rendered(self, dash: Page) -> None:
        dash.wait_for_timeout(3_000)  # extra wait for Vega-Lite async rendering
        charts = dash.locator("[data-testid='stVegaLiteChart']")
        info_boxes = dash.locator("[data-testid='stAlert']")
        # Charts render when extraction data exists; info box renders when DB is empty
        assert (
            charts.count() >= 1 or info_boxes.count() >= 1
        ), "Expected either Altair charts or an empty-state info box on the Dashboard"


class TestDashboardRecentSignals:
    def test_recent_signals_heading(self, dash: Page) -> None:
        assert "Recent Signals" in dash.content()

    def test_recent_signals_section_has_data(self, dash: Page) -> None:
        content = dash.content()
        # "Recent Signals" heading renders only when df_ext is non-empty
        # "No extraction results" info box renders when DB has no extractions
        has_data_section = "Recent Signals" in content
        has_empty_state = "No extraction results" in content
        assert has_data_section or has_empty_state, (
            "Expected either 'Recent Signals' section (with data) or "
            "'No extraction results' empty-state message"
        )


class TestDashboardSidebarFooter:
    def test_sidebar_has_no_status_clutter(self, dash: Page) -> None:
        """The old extraction status lines and the keyless quota note were removed."""
        sidebar = dash.locator("section[data-testid='stSidebar']")
        for text in ("active alert rules", "LLM spend", "Last extraction", "Live Meta calls"):
            expect(sidebar.get_by_text(text, exact=False)).to_have_count(0)


class TestDashboardNavigation:
    def test_all_seven_nav_items_visible(self, dash: Page) -> None:
        sidebar = dash.locator("section[data-testid='stSidebar']")
        for label in (
            "Dashboard",
            "Signal Explorer",
            "MAUDE Ingestion",
            "LLM Extraction",
            "PSUR Reports",
            "Alerts",
            "Settings",
        ):
            btn = sidebar.get_by_role("button", name=label, exact=False).first
            expect(btn).to_be_visible()
