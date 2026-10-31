"""R screenshots and ref-code checks: personal ?r=CODE kept for the session, no Name field.

    cd web && python3 qa/shoot_r.py

Starts a local stub API (logs POST bodies), builds the site with VITE_MAUDESIGNAL_API_BASE
pointing at it, serves it with ``vite preview`` and drives chromium. Checks no horizontal
scroll at 390 and 1440 in light and dark, opens ``/?r=TEST1``, moves to other views (also after
a reload without ``?r=``), shows that every /v1/visit body carries ref TEST1, opens the
feedback dialog, checks there is no Name field, submits and shows the body has ref TEST1 and no
name. Writes ``qa/screenshots/R-*.png`` and prints the checks as JSON.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, Route, sync_playwright

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "qa" / "screenshots"
STUB_PORT = 8765
PREVIEW_PORT = 4173
LOG: list[dict[str, object]] = []
SCROLL = "[document.documentElement.scrollWidth, document.documentElement.clientWidth]"


class Stub(http.server.BaseHTTPRequestHandler):
    """Accepts /v1/visit and /v1/feedback, logs each body, answers CORS."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002, D102
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self) -> None:  # noqa: N802, D102
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802, D102
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        LOG.append({"path": self.path, "body": json.loads(raw or b"{}")})
        self.send_response(201)
        self._cors()
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


def block_external(route: Route) -> None:
    """Allow local requests only."""
    if route.request.url.startswith("http://127.0.0.1"):
        route.continue_()
    else:
        route.abort()


def new_page(browser, width: int, height: int, theme: str) -> Page:  # type: ignore[no-untyped-def]
    """A fresh context (fresh sessionStorage) with the theme preset."""
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    page.route("**/*", block_external)
    page.add_init_script(f"localStorage.setItem('ms-theme','{theme}')")
    return page


def ready(page: Page) -> None:
    """Wait for the header strip and fonts."""
    page.wait_for_selector("text=claims verified")
    page.evaluate("document.fonts.ready")


def main() -> None:
    """Run the checks and print them."""
    OUT.mkdir(parents=True, exist_ok=True)
    stub = http.server.ThreadingHTTPServer(("127.0.0.1", STUB_PORT), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    env = {**os.environ, "VITE_MAUDESIGNAL_API_BASE": f"http://127.0.0.1:{STUB_PORT}"}
    subprocess.run(["npm", "run", "build"], cwd=WEB, env=env, check=True, capture_output=True)
    prev = subprocess.Popen(
        ["npx", "vite", "preview", "--host", "127.0.0.1", "--port", str(PREVIEW_PORT)],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{PREVIEW_PORT}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    result: dict[str, object] = {"scroll": []}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            scroll: list[dict[str, object]] = []
            for width, height in ((1440, 900), (390, 844)):
                for theme in ("light", "dark"):
                    page = new_page(browser, width, height, theme)
                    page.goto(f"{base}/?r=TEST1", wait_until="load")
                    ready(page)
                    sw, cw = page.evaluate(SCROLL)
                    row = {"width": width, "theme": theme, "scrollWidth": sw, "clientWidth": cw}
                    scroll.append({**row, "equal": sw == cw})
                    page.screenshot(path=str(OUT / f"R-home-{width}-{theme}.png"))
                    page.context.close()
            result["scroll"] = scroll

            # Session: open with ?r=TEST1, move to another view, reload without ?r=, move again.
            LOG.clear()
            page = new_page(browser, 1440, 900, "light")
            page.goto(f"{base}/?r=TEST1", wait_until="load")
            ready(page)
            page.wait_for_timeout(500)
            sidebar = page.locator("aside a, aside button, nav a, nav button")
            names = [t.strip() for t in sidebar.all_inner_texts() if t.strip()]
            result["sidebar_items"] = names[:12]
            clicked = []
            for label in ("Signals", "Audit", "Vision", "Copilot", "Dossier"):
                loc = page.get_by_role("button", name=label).first
                if loc.count() and loc.is_visible():
                    loc.click()
                    clicked.append(label)
                    page.wait_for_timeout(400)
                    break
            if not clicked:
                loc = sidebar.nth(3)
                clicked.append(loc.inner_text())
                loc.click()
                page.wait_for_timeout(400)
            result["clicked_before_reload"] = clicked
            # Same tab, URL without ?r=: the code must come from sessionStorage.
            page.goto(base + "/", wait_until="load")
            ready(page)
            page.wait_for_timeout(300)
            result["url_after_reload"] = page.url
            result["stored_ref"] = page.evaluate("sessionStorage.getItem('ms-ref')")
            # Open a different view than before the reload.
            page.keyboard.press("Control+k")
            page.wait_for_timeout(300)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)

            visits = [e for e in LOG if e["path"] == "/v1/visit"]
            result["visit_bodies"] = [e["body"] for e in visits]
            result["all_visits_have_ref_TEST1"] = bool(visits) and all(
                isinstance(e["body"], dict) and e["body"].get("ref") == "TEST1" for e in visits
            )

            page.get_by_role("button", name="Give feedback").click()
            page.wait_for_selector("[role=dialog]")
            labels = [t.strip() for t in page.locator("[role=dialog] label").all_inner_texts()]
            result["dialog_labels"] = labels
            result["no_name_field"] = not any(t.lower().startswith("name") for t in labels)
            result["note_shown"] = (
                page.get_by_text(
                    "We don't store your name or email. Please don't include patient details."
                ).count()
                == 1
            )
            page.screenshot(path=str(OUT / "R-dialog-1440-light.png"))
            page.get_by_role("radiogroup").get_by_text("4", exact=True).click()
            page.locator("[role=dialog] textarea").first.fill("TEST feedback from QA")
            page.get_by_label("Quote me anonymously").check()
            page.get_by_role("button", name="Send feedback").click()
            page.wait_for_selector("text=Your feedback was sent")
            fb = [e for e in LOG if e["path"] == "/v1/feedback"]
            result["feedback_bodies"] = [e["body"] for e in fb]
            result["feedback_ref_TEST1_no_name"] = bool(fb) and all(
                isinstance(e["body"], dict)
                and e["body"].get("ref") == "TEST1"
                and "name" not in e["body"]
                for e in fb
            )
            page.screenshot(path=str(OUT / "R-sent-1440-light.png"))
            page.context.close()

            # Phone dialog screenshot (light + dark) and no horizontal scroll with it open.
            for theme in ("light", "dark"):
                page = new_page(browser, 390, 844, theme)
                page.goto(f"{base}/?r=TEST1", wait_until="load")
                ready(page)
                page.get_by_role("button", name="Give feedback").click()
                page.wait_for_selector("[role=dialog]")
                sw, cw = page.evaluate(SCROLL)
                result[f"scroll_dialog_390_{theme}"] = [sw, cw]
                page.screenshot(path=str(OUT / f"R-dialog-390-{theme}.png"))
                page.context.close()
            browser.close()
    finally:
        prev.terminate()
        stub.shutdown()
    print(json.dumps(result, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
