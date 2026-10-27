"""510(k) PDF fetch: plain HTTP, then headless browser, then skip. No network."""

from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from maudesignal.vision import browser_fetch, fda_pdf
from maudesignal.vision.fda_pdf import PdfUnavailableError

PDF = b"%PDF-1.4\n% fake summary\n"
ROOT = Path(__file__).resolve().parents[2]


def _apology() -> httpx.MockTransport:
    def handler(r: httpx.Request) -> httpx.Response:
        if "apology" in str(r.url):
            return httpx.Response(200, text="<html>sorry</html>")
        return httpx.Response(302, headers={"location": "/apology_objects/abuse.html"})

    return httpx.MockTransport(handler)


def test_browser_fallback_used_only_when_plain_download_refused(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_browser(k: str, cache: Path) -> Path:
        calls.append(k)
        return fda_pdf.store_pdf(PDF, cache / f"{k}.pdf", "u")

    p = fda_pdf.fetch_510k_pdf(
        "k210666", tmp_path, transport=_apology(), browser_fallback=True, browser_fetch=fake_browser
    )
    assert p.read_bytes() == PDF and calls == ["K210666"]
    # Cached now: neither route is tried again.
    fda_pdf.fetch_510k_pdf(
        "K210666", tmp_path, transport=_apology(), browser_fallback=True, browser_fetch=fake_browser
    )
    assert calls == ["K210666"]


def test_no_fallback_by_default_and_both_reasons_reported(tmp_path: Path) -> None:
    def never(k: str, cache: Path) -> Path:
        raise AssertionError("browser must not be used by default")

    with pytest.raises(PdfUnavailableError, match="access-denied"):
        fda_pdf.fetch_510k_pdf("K190442", tmp_path, transport=_apology(), browser_fetch=never)

    def blocked(k: str, cache: Path) -> Path:
        raise browser_fetch.BrowserFetchError("still the apology page")

    with pytest.raises(PdfUnavailableError) as info:
        fda_pdf.fetch_510k_pdf(
            "K190442", tmp_path, transport=_apology(), browser_fallback=True, browser_fetch=blocked
        )
    msg = str(info.value)
    assert "plain download failed" in msg and "browser fetch failed (still the apology page)" in msg
    assert not (tmp_path / "K190442.pdf").exists()


def test_store_pdf_rejects_non_pdf_and_oversize(tmp_path: Path, monkeypatch: Any) -> None:
    with pytest.raises(PdfUnavailableError, match="did not return a PDF"):
        fda_pdf.store_pdf(b"<html>", tmp_path / "K1.pdf", "u")
    monkeypatch.setattr(fda_pdf, "MAX_PDF_BYTES", 4)
    with pytest.raises(PdfUnavailableError, match="limit"):
        fda_pdf.store_pdf(PDF, tmp_path / "K1.pdf", "u")


def test_missing_playwright_is_a_browser_fetch_error(tmp_path: Path, monkeypatch: Any) -> None:
    real_import = builtins.__import__

    def no_playwright(name: str, *a: Any, **kw: Any) -> Any:
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    with pytest.raises(browser_fetch.BrowserFetchError, match="Playwright is not installed"):
        browser_fetch.browser_download_510k_pdf("K210666", tmp_path)


class _FakeDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def save_as(self, path: str) -> None:
        Path(path).write_bytes(self._data)


class _Expect:
    def __init__(self, data: bytes) -> None:
        self.value = _FakeDownload(data)

    def __enter__(self) -> _Expect:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _fake_playwright(request_body: bytes, request_url: str, download: bytes, log: list[str]) -> Any:
    class Page:
        def goto(self, url: str, timeout: int) -> None:
            log.append(f"goto {url}")
            if url.endswith(".pdf"):
                raise RuntimeError("Download is starting")

        def wait_for_timeout(self, ms: int) -> None:
            log.append("settle")

        def expect_download(self, timeout: int) -> _Expect:
            return _Expect(download)

    class Context:
        request = SimpleNamespace(
            get=lambda url, timeout: (
                log.append(f"request {url}")
                or SimpleNamespace(ok=True, url=request_url, body=lambda: request_body)
            )
        )

        def new_page(self) -> Page:
            return Page()

    class Browser:
        def new_context(self, accept_downloads: bool) -> Context:
            return Context()

        def close(self) -> None:
            log.append("close")

    class PW:
        chromium = SimpleNamespace(launch=lambda headless: Browser())

        def __enter__(self) -> PW:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    return lambda: PW()


def test_browser_gets_pdf_via_page_cookies(tmp_path: Path, monkeypatch: Any) -> None:
    log: list[str] = []
    url = fda_pdf.pdf_url("K210666")
    monkeypatch.setattr(
        browser_fetch, "_sync_playwright", lambda: _fake_playwright(PDF, url, b"", log)
    )
    p = browser_fetch.browser_download_510k_pdf("K210666", tmp_path)
    assert p.read_bytes() == PDF
    assert log[0] == "goto " + browser_fetch.PMN_PAGE_URL.format(k="K210666")
    assert log[1:] == ["settle", f"request {url}", "close"]


def test_browser_falls_back_to_download_event(tmp_path: Path, monkeypatch: Any) -> None:
    log: list[str] = []
    apology = "https://www.accessdata.fda.gov/apology_objects/abuse.html"
    monkeypatch.setattr(
        browser_fetch, "_sync_playwright", lambda: _fake_playwright(b"<html>", apology, PDF, log)
    )
    p = browser_fetch.browser_download_510k_pdf("K210666", tmp_path)
    assert p.read_bytes() == PDF and not (tmp_path / "K210666.download").exists()
    assert log[-1] == "close"


def test_browser_non_pdf_download_raises(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        browser_fetch, "_sync_playwright", lambda: _fake_playwright(b"x", "u", b"<html>", [])
    )
    with pytest.raises(browser_fetch.BrowserFetchError, match="did not return a PDF"):
        browser_fetch.browser_download_510k_pdf("K210666", tmp_path)
    assert not (tmp_path / "K210666.pdf").exists()


def test_recorder_skips_unavailable_pdf(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    spec = importlib.util.spec_from_file_location(
        "record_vision_runs", ROOT / "scripts" / "record_vision_runs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen: dict[str, Any] = {}

    def unavailable(k: str, **kw: Any) -> Any:
        seen.update(kw)
        raise PdfUnavailableError("plain download failed; browser fetch failed")

    monkeypatch.setattr(mod, "read_and_verify_510k", unavailable)
    monkeypatch.setenv("META_MODEL_API_KEY", "test-key-not-real")
    (tmp_path / "510k-K210666.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["x", "--k", "K210666", "K190442", "--skip-labels", "--out", str(tmp_path)],
    )
    assert mod.main() == 0  # skips are not failures
    out = capsys.readouterr().out
    assert "[510k] K210666: SKIPPED — PDF unavailable (earlier recorded reading kept)" in out
    assert "[510k] K190442: SKIPPED — PDF unavailable:" in out
    assert "failures: 0; skipped (PDF unavailable): 2 K210666, K190442" in out
    assert seen["browser_fallback"] is True
    assert (tmp_path / "510k-K210666.json").read_text(encoding="utf-8") == "{}"
