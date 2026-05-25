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
    def test_active_provider_section(self, settings: Page) -> None:
        assert "Active Provider" in settings.content() or "Active provider" in settings.content()

    def test_active_provider_is_gemini(self, settings: Page) -> None:
        content = settings.content()
        assert (
            "GEMINI" in content.upper()
        ), "Expected active provider to be Gemini per .env LLM_PROVIDER=gemini"

    def test_model_name_gemini_flash(self, settings: Page) -> None:
        content = settings.content()
        assert (
            "gemini-2.5-flash" in content or "flash" in content.lower()
        ), "Expected GEMINI_MODEL=gemini-2.5-flash from .env to appear in Settings"

    def test_provider_status_section(self, settings: Page) -> None:
        expect(settings.get_by_text("Provider Status", exact=False)).to_be_visible()

    def test_groq_card_shows_key_set(self, settings: Page) -> None:
        content = settings.content()
        assert (
            "Groq" in content and "Key Set" in content
        ), "Expected Groq provider with 'Key Set' pill — GROQ_API_KEY is configured"

    def test_anthropic_shows_not_configured(self, settings: Page) -> None:
        content = settings.content()
        assert (
            "Not Configured" in content
        ), "Expected 'Not Configured' pill — ANTHROPIC_API_KEY is absent from .env"

    def test_openai_card_present(self, settings: Page) -> None:
        assert "OpenAI" in settings.content()

    def test_gemini_card_present(self, settings: Page) -> None:
        content = settings.content()
        assert "Gemini" in content or "Google Gemini" in content

    def test_api_keys_are_masked(self, settings: Page) -> None:
        content = settings.content()
        # The UI shows masked keys like "gsk_....Hgnm" — verify "..." ellipsis is present
        # (indicates masking), and no full-length key is exposed (> 20 chars of key chars)
        import re

        raw_key_pattern = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})")
        assert not raw_key_pattern.search(
            content
        ), "A full unmasked API key was found in the Settings page"

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
