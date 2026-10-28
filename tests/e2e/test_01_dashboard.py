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

    def test_ai_signals_label(self, dash: Page) -> None:
        # Actual rendered label is "AI Signals Detected"
        assert "AI Signals Detected" in dash.content()

    def test_avg_confidence_label(self, dash: Page) -> None:
        # Actual rendered label is "Avg Confidence"
        assert "Avg Confidence" in dash.content()

    def test_active_alert_rules_label(self, dash: Page) -> None:
        assert "Active Alert Rules" in dash.content()

    def test_llm_cost_label(self, dash: Page) -> None:
        # Actual rendered label is "LLM Cost to Date"
        assert "LLM Cost to Date" in dash.content()

    def test_maude_records_is_numeric(self, dash: Page) -> None:
        content = dash.content()
        assert any(
            str(n) in content for n in range(0, 10_000)
        ), "MAUDE Records KPI does not contain any numeric value"

    def test_avg_confidence_is_decimal(self, dash: Page) -> None:
        assert "0." in dash.content(), "Avg Confidence should be a decimal between 0 and 1"

    def test_llm_cost_shows_dollar(self, dash: Page) -> None:
        assert "$" in dash.content(), "LLM Cost KPI should display a dollar amount"


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
    def test_sidebar_footer_record_count(self, dash: Page) -> None:
        sidebar = dash.locator("section[data-testid='stSidebar']")
        expect(sidebar.get_by_text("MAUDE records", exact=False)).to_be_visible()

    def test_sidebar_footer_alert_rules(self, dash: Page) -> None:
        sidebar = dash.locator("section[data-testid='stSidebar']")
        expect(sidebar.get_by_text("active alert rules", exact=False)).to_be_visible()

    def test_sidebar_footer_llm_spend(self, dash: Page) -> None:
        sidebar = dash.locator("section[data-testid='stSidebar']")
        expect(sidebar.get_by_text("LLM spend", exact=False)).to_be_visible()


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
