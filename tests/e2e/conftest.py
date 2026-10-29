"""Shared fixtures and helpers for MaudeSignal e2e tests.

All tests in this package require the Streamlit app running at localhost:8501.
Start it first:
    python3.12 -m streamlit run src/maudesignal/dashboard/app.py --server.headless true

Run the e2e suite (no coverage — tests hit a live server, not source imports):
    pytest tests/e2e -m e2e --no-cov -v
"""

from __future__ import annotations

import urllib.request

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:8501"
SIDEBAR_SELECTOR = "section[data-testid='stSidebar']"
TOPBAR_SELECTOR = ".st-key-ms_topbar"
LOAD_TIMEOUT = 20_000
NAV_SETTLE = 4_500


def _server_reachable() -> bool:
    try:
        urllib.request.urlopen(BASE_URL, timeout=3)  # noqa: S310
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def _require_server() -> None:
    """Skip the entire e2e session if the Streamlit server is not reachable."""
    if not _server_reachable():
        pytest.skip(
            "MaudeSignal dashboard not running at localhost:8501. "
            "Start it with: python3.12 -m streamlit run "
            "src/maudesignal/dashboard/app.py --server.headless true"
        )


@pytest.fixture()
def ms_page(page: Page, _require_server: None) -> Page:  # type: ignore[misc]
    """Open the app with every tool shown and wait for Streamlit to fully hydrate."""
    page.set_default_timeout(LOAD_TIMEOUT)
    # ?tools=all shows the sidebar's "More tools", hidden in the public demo.
    page.goto(f"{BASE_URL}/?tools=all", wait_until="networkidle", timeout=LOAD_TIMEOUT)
    page.wait_for_selector(SIDEBAR_SELECTOR, timeout=LOAD_TIMEOUT)
    page.wait_for_timeout(NAV_SETTLE)
    return page


def navigate(page: Page, nav_text: str) -> None:
    """Click a top-bar page (or a sidebar "More tools" button) and wait for it to settle."""
    top = page.locator(TOPBAR_SELECTOR).get_by_role("radio", name=nav_text, exact=False)
    if top.count():
        top.first.click()
    else:
        sidebar = page.locator(SIDEBAR_SELECTOR)
        sidebar.get_by_role("button", name=nav_text, exact=False).first.click()
    page.wait_for_timeout(NAV_SETTLE)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    page.wait_for_timeout(1_000)


def click_tab(page: Page, tab_name: str) -> None:
    """Click a Streamlit tab by visible label and wait for content to settle."""
    page.get_by_role("tab", name=tab_name, exact=False).first.click()
    page.wait_for_timeout(1_500)
