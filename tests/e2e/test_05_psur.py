"""E2E tests for the PSUR Reports page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import click_tab, navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def psur(ms_page: Page) -> Page:
    navigate(ms_page, "PSUR Reports")
    return ms_page


class TestPsurPageLoads:
    def test_page_header(self, psur: Page) -> None:
        expect(psur.get_by_role("heading", name="PSUR", exact=False)).to_be_visible()

    def test_no_exception_banner(self, psur: Page) -> None:
        assert psur.locator("[data-testid='stException']").count() == 0


class TestPsurTabs:
    def test_at_least_two_tabs(self, psur: Page) -> None:
        tabs = psur.get_by_role("tab")
        assert (
            tabs.count() >= 2
        ), "Expected at least 2 tabs on PSUR page (existing reports + generate)"

    def test_generate_tab_label_present(self, psur: Page) -> None:
        content = psur.content()
        assert "Generate" in content, "Expected a 'Generate' tab on PSUR page"


class TestPsurReportsTab:
    def test_empty_state_or_table(self, psur: Page) -> None:
        content = psur.content()
        has_empty = any(kw in content.lower() for kw in ("no psur", "no reports"))
        has_table = psur.locator("table, [data-testid='stDataFrame']").count() > 0
        assert (
            has_empty or has_table
        ), "PSUR Reports tab should show empty-state message or a reports table"

    def test_empty_state_is_actionable(self, psur: Page) -> None:
        content = psur.content()
        if any(kw in content.lower() for kw in ("no psur", "no reports")):
            assert any(
                kw in content.lower() for kw in ("generate", "tab", "use", "click")
            ), "Empty state for PSUR reports should guide user toward generating one"


class TestPsurGenerateTab:
    def test_generate_tab_loads(self, psur: Page) -> None:
        click_tab(psur, "Generate")
        expect(psur.get_by_role("heading", name="PSUR", exact=False)).to_be_visible()

    def test_generate_tab_no_crash(self, psur: Page) -> None:
        click_tab(psur, "Generate")
        assert psur.locator("[data-testid='stException']").count() == 0

    def test_product_code_field_in_generate(self, psur: Page) -> None:
        click_tab(psur, "Generate")
        # Generating needs an LLM provider key; the keyless demo says so instead of a form.
        keyless = psur.get_by_text("LLM provider is not configured", exact=False)
        if keyless.count():
            expect(keyless.first).to_be_visible()
            return
        expect(psur.get_by_text("Product Code", exact=False)).to_be_visible()

    def test_generate_action_present(self, psur: Page) -> None:
        click_tab(psur, "Generate")
        content = psur.content()
        assert any(
            kw in content for kw in ("Generate", "Draft", "Create")
        ), "Expected a Generate/Draft action button on Generate tab"
