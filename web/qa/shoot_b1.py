"""B1 screenshots of the empty shell at 1440 and 390, light and dark.

    cd web && npm run build && python3 qa/shoot_b1.py

Serves ``dist/`` on a local port, blocks every non-local request (no network needed) and
writes ``qa/screenshots/B1-<width>-<theme>.png``. Also checks, and prints, that there is no
horizontal scroll and that the phone drawer, bottom sheet and Ctrl+K palette open.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import Page, Route, sync_playwright

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "qa" / "screenshots"
SCRATCH = Path("/tmp/claude-0/-home-user-maudesignal/e8f516e9-363c-5cd6-b49e-957804d514a6/scratchpad")


def serve() -> tuple[socketserver.TCPServer, int]:

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    handler = partial(Quiet, directory=str(WEB / "dist"))
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def local_only(route: Route) -> None:
    if route.request.url.startswith("http://127.0.0.1"):
        route.continue_()
    else:
        route.abort()


def open_page(page: Page, url: str) -> None:
    page.route("**/*", local_only)
    page.goto(url, wait_until="load")
    page.wait_for_selector("text=claims verified")
    page.evaluate("document.fonts.ready")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((WEB / "public/data/manifest.json").read_text())["header"]
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {"header": manifest}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            for scheme in ("light", "dark"):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=scheme  # type: ignore[arg-type]
                )
                page = ctx.new_page()
                open_page(page, url)
                strip = page.locator("[role=status]").inner_text()
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
                report[f"{width}-{scheme}"] = {"strip": strip, "x_overflow_px": overflow, "bg": bg}
                page.screenshot(path=str(OUT / f"B1-{width}-{scheme}.png"))
                if width == 390:
                    page.get_by_label("Toggle sidebar").click()
                    page.wait_for_timeout(300)
                    page.screenshot(path=str(SCRATCH / f"drawer-{scheme}.png"))
                    report[f"drawer-{scheme}-visible"] = page.locator("#sidebar").is_visible()
                    page.get_by_label("Close menu").click()
                    page.get_by_label("Toggle artifacts").click()
                    page.wait_for_timeout(300)
                    page.screenshot(path=str(SCRATCH / f"sheet-{scheme}.png"))
                    report[f"sheet-{scheme}-visible"] = page.locator("#artifacts").is_visible()
                else:
                    page.keyboard.press("Control+k")
                    page.wait_for_selector("[role=dialog]")
                    page.screenshot(path=str(SCRATCH / f"palette-{scheme}.png"))
                    report[f"palette-{scheme}-items"] = page.locator("[role=option]").count()
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
