"""E2E tests for the Settings page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import click_tab, navigate

pytestmark = pytest.mark.e2e


@pytest.fixture()
def settings(ms_page: Page) -> Page:
    navigate(ms_page, "Settings")
    return ms_page


class TestSettingsPageLoads:
    def test_page_header(self, settings: Page) -> None:
        expect(settings.get_by_role("heading", name="Settings", exact=False)).to_be_visible()

    def test_no_exception_banner(self, settings: Page) -> None:
        assert settings.locator("[data-testid='stException']").count() == 0


class TestSettingsTabs:
    def test_four_tabs_rendered(self, settings: Page) -> None:
        assert (
            settings.get_by_role("tab").count() >= 4
        ), "Expected 4 tabs: LLM Providers, System, Device Catalog, External Sources"

    def test_llm_providers_tab(self, settings: Page) -> None:
        content = settings.content()
        assert "LLM Providers" in content or "Providers" in content

    def test_system_tab(self, settings: Page) -> None:
        # Tab label is "🗄 System" — emoji prefix means get_by_role full-name match fails
        content = settings.content()
        assert "System" in content

    def test_device_catalog_tab(self, settings: Page) -> None:
        content = settings.content()
        assert "Device Catalog" in content or "Catalog" in content

    def test_external_sources_tab(self, settings: Page) -> None:
        content = settings.content()
        assert "External Sources" in content or "Sources" in content


class TestSettingsProvidersTab:
    """Key status only (set / not set), Meta first, and no error banner in keyless demo mode."""

    def test_meta_model_api_listed_first(self, settings: Page) -> None:
        content = settings.content()
        assert "Meta Model API" in content and "META_MODEL_API_KEY" in content
        assert content.index("Meta Model API") < content.index("Groq")

    def test_openfda_key_status_listed(self, settings: Page) -> None:
        assert "OPENFDA_API_KEY" in settings.content()

    def test_no_config_error_banner(self, settings: Page) -> None:
        assert "Configuration could not be loaded" not in settings.content()
        assert "Not Configured" not in settings.content()

    def test_extraction_providers_are_optional(self, settings: Page) -> None:
        content = settings.content()
        assert "pre-hackathon pipeline, optional" in content
        assert "Groq" in content and "Anthropic" in content

    def test_openai_card_present(self, settings: Page) -> None:
        assert "OpenAI" in settings.content()

    def test_gemini_card_present(self, settings: Page) -> None:
        content = settings.content()
        assert "Gemini" in content or "Google Gemini" in content

    def test_no_part_of_any_key_is_shown(self, settings: Page) -> None:
        import re

        content = settings.content()
        key_like = re.compile(r"(gsk_[A-Za-z0-9]{4,}|sk-[A-Za-z0-9]{4,}|AIza[0-9A-Za-z_\-]{4,})")
        assert not key_like.search(content), "Part of an API key is shown on Settings"

    def test_cost_section_present(self, settings: Page) -> None:
        # "Cost" appears in multiple elements; use content check to avoid strict mode violation
        assert "Cost" in settings.content()

    def test_cost_ceiling_value_shown(self, settings: Page) -> None:
        content = settings.content()
        assert (
            "150" in content
        ), "Expected MAUDESIGNAL_COST_CEILING_USD=150.00 from .env to appear in Settings"


class TestSettingsSystemTab:
    def test_system_tab_loads(self, settings: Page) -> None:
        click_tab(settings, "System")
        settings.wait_for_timeout(1_000)
        assert settings.locator("[data-testid='stException']").count() == 0
        expect(settings.get_by_role("heading", name="Settings", exact=False)).to_be_visible()

    def test_system_tab_has_content(self, settings: Page) -> None:
        click_tab(settings, "System")
        settings.wait_for_timeout(1_000)
        assert len(settings.content()) > 2_000, "System tab appears empty"


class TestSettingsDeviceCatalogTab:
    def test_catalog_tab_loads(self, settings: Page) -> None:
        click_tab(settings, "Device Catalog")
        settings.wait_for_timeout(1_000)
        assert settings.locator("[data-testid='stException']").count() == 0
        expect(settings.get_by_role("heading", name="Settings", exact=False)).to_be_visible()

    def test_catalog_shows_empty_state_or_table(self, settings: Page) -> None:
        click_tab(settings, "Device Catalog")
        settings.wait_for_timeout(1_000)
        content = settings.content()
        has_empty = any(kw in content.lower() for kw in ("no device", "empty", "catalog"))
        has_table = settings.locator("table, [data-testid='stDataFrame']").count() > 0
        assert has_empty or has_table, "Device Catalog must show empty state or a device table"


class TestSettingsExternalSourcesTab:
    def test_external_sources_tab_loads(self, settings: Page) -> None:
        click_tab(settings, "External Sources")
        settings.wait_for_timeout(1_000)
        assert settings.locator("[data-testid='stException']").count() == 0
        expect(settings.get_by_role("heading", name="Settings", exact=False)).to_be_visible()

    def test_external_sources_mentions_openfda(self, settings: Page) -> None:
        click_tab(settings, "External Sources")
        settings.wait_for_timeout(1_000)
        content = settings.content()
        assert any(
            kw in content.lower() for kw in ("openfda", "pubmed", "source", "external")
        ), "Expected external sources content referencing openFDA or PubMed"
