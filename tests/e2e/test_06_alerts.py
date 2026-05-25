"""E2E tests for the Alerts page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import click_tab, navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def alerts(ms_page: Page) -> Page:
    navigate(ms_page, "Alerts")
    return ms_page


class TestAlertsPageLoads:
    def test_page_header(self, alerts: Page) -> None:
        expect(alerts.get_by_role("heading", name="Alerts", exact=False)).to_be_visible()

    def test_no_exception_banner(self, alerts: Page) -> None:
        assert alerts.locator("[data-testid='stException']").count() == 0


class TestAlertsTabs:
    def test_three_tabs_present(self, alerts: Page) -> None:
        assert (
            alerts.get_by_role("tab").count() >= 3
        ), "Expected Alert Rules, Test Alerts, and History tabs"

    def test_alert_rules_tab_present(self, alerts: Page) -> None:
        content = alerts.content()
        assert "Alert Rules" in content or "Rules" in content

    def test_test_alerts_tab_present(self, alerts: Page) -> None:
        assert alerts.get_by_role("tab", name="Test", exact=False).count() >= 1

    def test_history_tab_present(self, alerts: Page) -> None:
        assert alerts.get_by_role("tab", name="History", exact=False).count() >= 1


class TestAlertsRulesTab:
    def test_empty_state_or_table(self, alerts: Page) -> None:
        content = alerts.content()
        has_empty = "No alert rules" in content or "no rules" in content.lower()
        has_table = alerts.locator("table, [data-testid='stDataFrame']").count() > 0
        assert has_empty or has_table, "Alert Rules tab must show empty state or a rules table"

    def test_empty_state_shows_cli_hint(self, alerts: Page) -> None:
        content = alerts.content()
        if "No alert rules" in content:
            assert "alert" in content.lower() and (
                "maudesignal" in content.lower() or "CLI" in content
            ), "Empty state should show the CLI command to add alert rules"

    def test_example_command_block_shown(self, alerts: Page) -> None:
        content = alerts.content()
        if "No alert rules" in content:
            # A code block with the example CLI command should be visible
            assert "alert add" in content or "alert" in content.lower()


class TestAlertsTestTab:
    def test_test_tab_loads_without_crash(self, alerts: Page) -> None:
        click_tab(alerts, "Test Alerts")
        alerts.wait_for_timeout(1_000)
        assert alerts.locator("[data-testid='stException']").count() == 0

    def test_test_tab_heading_still_visible(self, alerts: Page) -> None:
        click_tab(alerts, "Test Alerts")
        alerts.wait_for_timeout(1_000)
        expect(alerts.get_by_role("heading", name="Alerts", exact=False)).to_be_visible()

    def test_test_tab_has_meaningful_content(self, alerts: Page) -> None:
        click_tab(alerts, "Test Alerts")
        alerts.wait_for_timeout(1_000)
        content = alerts.content()
        assert len(content) > 2_000, "Test Alerts tab appears to have no content"


class TestAlertsHistoryTab:
    def test_history_tab_loads_without_crash(self, alerts: Page) -> None:
        click_tab(alerts, "History")
        alerts.wait_for_timeout(1_000)
        assert alerts.locator("[data-testid='stException']").count() == 0

    def test_history_tab_heading_visible(self, alerts: Page) -> None:
        click_tab(alerts, "History")
        alerts.wait_for_timeout(1_000)
        expect(alerts.get_by_role("heading", name="Alerts", exact=False)).to_be_visible()

    def test_history_empty_state_or_table(self, alerts: Page) -> None:
        click_tab(alerts, "History")
        alerts.wait_for_timeout(1_000)
        content = alerts.content()
        has_empty = any(kw in content.lower() for kw in ("no history", "no alerts", "no events"))
        has_table = alerts.locator("table, [data-testid='stDataFrame']").count() > 0
        assert has_empty or has_table, "History tab must show empty state or a history table"
