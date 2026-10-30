"""F screenshots: the feedback panel at 1440 and 390, light and dark.

    cd web && VITE_MAUDESIGNAL_API_BASE=https://qa-api.example npm run build && python3 qa/shoot_f.py

Serves ``dist/`` locally and blocks every other request. Opens the app with ``?r=qa-code``, opens the
panel, checks there is no horizontal scroll, that Esc closes it, and writes
``qa/screenshots/F-feedback-<width>-<theme>.png``. Prints the checks as JSON.
"""

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright
from shoot_b1 import OUT, local_only, serve

SCROLL = "[document.documentElement.scrollWidth, document.documentElement.clientWidth]"


def main() -> None:
    """Take the four screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    srv, port = serve()
    checks: list[dict[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            for theme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": width, "height": height})
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.add_init_script(f"localStorage.setItem('ms-theme','{theme}')")
                page.goto(f"http://127.0.0.1:{port}/?r=qa-code", wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                row: dict[str, object] = {"width": width, "theme": theme}
                row["scroll_before"] = page.evaluate(SCROLL)
                page.get_by_role("button", name="Give feedback").click()
                page.wait_for_selector("[role=dialog]")
                row["scroll_open"] = page.evaluate(SCROLL)
                row["focus_in_dialog"] = page.evaluate("!!document.activeElement.closest('[role=dialog]')")
                page.screenshot(path=str(OUT / f"F-feedback-{width}-{theme}.png"))
                page.keyboard.press("Escape")
                row["esc_closes"] = page.locator("[role=dialog]").count() == 0
                checks.append(row)
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
