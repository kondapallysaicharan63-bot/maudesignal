"""Fetch a 510(k) summary PDF with a headless browser (Playwright + Chromium).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

accessdata.fda.gov answers plain HTTP clients from cloud runners with an
"apology" (access-denied) page. A real browser that first opens the public
510(k) database page for the K-number picks up the cookies that page sets and
can then request the PDF the way a person clicking the summary link would.

This is only the download route; the PDF is validated exactly like a plain
download (``store_pdf``: magic bytes, size limit). If Playwright or Chromium
is missing, or FDA still refuses, the caller gets a ``BrowserFetchError`` and
decides what to do (the recorder skips that K-number).

Install for the recorder: ``pip install playwright && python -m playwright
install --with-deps chromium``. It is not a runtime dependency of the app.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from maudesignal.vision.fda_pdf import (
    FdaPdfError,
    is_cached_pdf,
    normalize_k_number,
    pdf_url,
    store_pdf,
)

PMN_PAGE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}"
DEFAULT_TIMEOUT_MS = 60_000
SETTLE_MS = 3_000  # let the database page's scripts set their cookies


class BrowserFetchError(FdaPdfError):
    """The headless browser could not get the PDF (or is not installed)."""


def _sync_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserFetchError(
            "Playwright is not installed (pip install playwright && "
            "python -m playwright install --with-deps chromium)"
        ) from exc
    return sync_playwright


def browser_download_510k_pdf(
    k_number: str,
    cache_dir: Path,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Path:
    """Download one 510(k) summary PDF through headless Chromium.

    Args:
        k_number: 510(k) number.
        cache_dir: Cache folder (the file is written as ``<K>.pdf``).
        timeout_ms: Per-navigation / per-request timeout.

    Returns:
        Path of the cached PDF.

    Raises:
        BrowserFetchError: Playwright/Chromium missing, a navigation failed, or
            FDA still served something other than the PDF.
    """
    k = normalize_k_number(k_number)
    path = cache_dir / f"{k}.pdf"
    if is_cached_pdf(path):
        return path
    url = pdf_url(k)
    sync_playwright = _sync_playwright()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                page.goto(PMN_PAGE_URL.format(k=k), timeout=timeout_ms)
                page.wait_for_timeout(SETTLE_MS)
                # Same cookies as the page: the request a click on the summary link makes.
                resp = context.request.get(url, timeout=timeout_ms)
                body = resp.body()
                if resp.ok and body[:5] == b"%PDF-" and "apology" not in resp.url:
                    return store_pdf(body, path, url)
                # Some PDFs are only handed over as a browser download.
                with (
                    page.expect_download(timeout=timeout_ms) as dl,
                    contextlib.suppress(Exception),  # "Download is starting" aborts goto
                ):
                    page.goto(url, timeout=timeout_ms)
                tmp = path.with_suffix(".download")
                path.parent.mkdir(parents=True, exist_ok=True)
                dl.value.save_as(str(tmp))
                data = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                return store_pdf(data, path, url)
            finally:
                browser.close()
    except FdaPdfError as exc:
        raise BrowserFetchError(f"{k}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - Playwright raises its own error types
        raise BrowserFetchError(f"{k}: {type(exc).__name__}: {str(exc)[:200]}") from exc
