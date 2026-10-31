"""E2E tests for the connector's /privacy and /terms pages (HACKATHON-BUILT).

The API app is started in-process on a free local port (no Streamlit server needed) and the
pages are opened in Chromium at phone and desktop width, light and dark. Covers compatibility
(390 and 1440 px, both colour schemes, no sideways scroll), accessibility basics (language,
landmark, heading, named links, contrast between text and background), and that nothing is
loaded from outside the page.

    pytest tests/e2e/test_09_connector_pages.py -m e2e --no-cov -v
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")
from playwright.sync_api import Page  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    import uvicorn

    work = tmp_path_factory.mktemp("pages")
    app = create_app(
        Settings(
            keys=KeyStore([]),
            limiter=RateLimiter(10),
            data=ConnectorData(work_dir=Path(work)),
            feedback_store=MemoryStore(),
        )
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _luminance(rgb: str) -> float:
    nums = [int(x) for x in rgb[rgb.index("(") + 1 : rgb.index(")")].split(",")[:3]]
    lin = [(c / 255) ** 2.2 for c in nums]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


@pytest.mark.parametrize("path", ["/privacy", "/terms"])
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_page_fits_the_screen_and_follows_the_colour_scheme(
    page: Page, site: str, path: str, width: int, scheme: str
) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto(site + path)
    assert page.locator("h1").count() == 1 and page.locator("main").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    fg = page.evaluate("getComputedStyle(document.body).color")
    assert (_luminance(bg) > _luminance(fg)) == (scheme == "light")
    assert all(u.startswith(site) for u in requests), requests  # nothing from outside


@pytest.mark.parametrize("path", ["/privacy", "/terms"])
def test_accessibility_basics(page: Page, site: str, path: str) -> None:
    page.goto(site + path)
    assert page.evaluate("document.documentElement.lang") == "en"
    assert "MaudeSignal" in page.title()
    names = page.evaluate(
        "Array.from(document.querySelectorAll('a')).map(a => a.textContent.trim())"
    )
    assert names and all(names)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.tagName") == "A"  # reachable by keyboard
    if path == "/privacy":
        assert page.locator("h2").count() >= 5  # sectioned by headings (the page has no table)
