"""E2E tests for the "Our devices" page (simulated company, real FDA evidence).

Run against the keyless public-demo setup (no ``META_MODEL_API_KEY``):

    streamlit run streamlit_app.py --server.headless true
    pytest tests/e2e/test_09_company.py -m e2e --no-cov -v

Expected values are computed here from the same files with the package's own loader, so a
test fails only when the page disagrees with the data.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Locator, Page, expect

from maudesignal.company import BANNER, load_company
from maudesignal.company.constants import FORBIDDEN, STATUSES
from tests.e2e.conftest import TOPBAR_SELECTOR, navigate

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        bool(os.environ.get("META_MODEL_API_KEY")),
        reason="stored-first checks assume the keyless public-demo setup",
    ),
]

EXCEPTION = "[data-testid='stException']"


def _main(page: Page) -> Locator:
    return page.locator("[data-testid='stMainBlockContainer']").first


def _open(page: Page) -> Locator:
    navigate(page, "Our devices")
    return _main(page)


def _pick(page: Page, device_id: str) -> None:
    box = page.get_by_label("Open a device")
    box.scroll_into_view_if_needed()
    box.click()
    page.wait_for_timeout(500)
    page.locator("[role=option]", has_text=device_id).first.click()
    page.wait_for_timeout(3_500)


def test_our_devices_is_a_top_bar_page(ms_page: Page) -> None:
    expect(
        ms_page.locator(TOPBAR_SELECTOR).get_by_role("radio", name="Our devices", exact=False)
    ).to_have_count(1)


def test_banner_and_table_show_every_device_and_status(ms_page: Page) -> None:
    main = _open(ms_page)
    expect(main).to_contain_text(BANNER)
    expect(main.locator("#company-banner")).to_be_visible()
    view = load_company()
    text = main.inner_text().lower()
    for d in view.devices:
        assert d.device_id.lower() in text and d.name.lower() in text, d.name
        assert d.status is not None and d.status.to_status.lower() in text
    for status in STATUSES:
        assert status.lower() in text, status
    assert main.locator(EXCEPTION).count() == 0


def test_banner_comes_before_the_table(ms_page: Page) -> None:
    main = _open(ms_page)
    banner_y = main.locator("#company-banner").bounding_box()
    table_y = main.locator(".ms-company-table").first.bounding_box()
    assert banner_y is not None and table_y is not None
    assert banner_y["y"] < table_y["y"]


def test_device_with_real_patterns_shows_evidence_quotes_and_history(ms_page: Page) -> None:
    main = _open(ms_page)
    view = load_company()
    dev = view.device("DMC-03")
    assert dev is not None and dev.patterns
    _pick(ms_page, "DMC-03")
    expect(main).to_contain_text(f"Product code {dev.product_code}")
    for p in dev.patterns:
        expect(main).to_contain_text(p.label)
        expect(main).to_contain_text(f"{p.count} real reports")
    quote = dev.patterns[0].quotes[0]
    expect(main).to_contain_text(quote.text)
    assert main.locator(f"a[href='{quote.url}']").count() >= 1
    expect(main).to_contain_text("Status history")
    expect(main).to_contain_text("Chain re-verified now")
    expect(main).to_contain_text("intact")
    expect(main).to_contain_text("Recalls on file for this code")
    assert main.locator(EXCEPTION).count() == 0


def test_investigator_groups_are_reused_for_llz(ms_page: Page) -> None:
    main = _open(ms_page)
    dev = load_company().device("DMC-01")
    assert dev is not None
    _pick(ms_page, "DMC-01")
    for p in dev.patterns:
        expect(main).to_contain_text(p.label)
    expect(main).to_contain_text("weekly investigator group")
    expect(main).to_contain_text("Testing in progress", ignore_case=True)


def test_device_without_stored_evidence_says_so_and_shows_no_numbers(ms_page: Page) -> None:
    main = _open(ms_page)
    _pick(ms_page, "DMC-06")
    expect(main).to_contain_text("evidence not fetched yet", ignore_case=True)
    expect(main).to_contain_text("No count, pattern or quote is shown")
    expect(main).not_to_contain_text("real reports")
    assert main.locator(EXCEPTION).count() == 0


def test_no_forbidden_words_on_the_page(ms_page: Page) -> None:
    main = _open(ms_page)
    for did in ("DMC-01", "DMC-03", "DMC-06"):
        _pick(ms_page, did)
        assert not FORBIDDEN.search(main.inner_text()), did
