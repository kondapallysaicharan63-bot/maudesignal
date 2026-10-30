"""N screenshots: header fit with bell + feedback button, feedback dialog open/Esc.

    cd web && npm run build && python3 qa/shoot_n.py

Starts ``npx vite preview``, opens it at 390 and 1440 in light and dark, checks there is no horizontal
scroll, that the alert bell and "Give feedback" button are visible, that the dialog opens and Esc closes
it, and writes ``qa/screenshots/N-header-<width>-<theme>.png``. Prints the checks as JSON.
"""

# ruff: noqa: E501, T201
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from shoot_b1 import OUT

PORT = 4179


def wait_up() -> None:
    """Wait until the preview server answers."""
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("preview did not start")


def main() -> None:
    """Run the checks and print them."""
    OUT.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen(
        ["npx", "vite", "preview", "--port", str(PORT), "--strictPort", "--host", "127.0.0.1"],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rows: list[dict[str, object]] = []
    try:
        wait_up()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in ((390, 844), (1440, 900)):
                for theme in ("light", "dark"):
                    ctx = browser.new_context(viewport={"width": width, "height": height})
                    page = ctx.new_page()
                    page.add_init_script(f"localStorage.setItem('ms-theme','{theme}')")
                    page.goto(f"http://127.0.0.1:{PORT}/")
                    page.wait_for_timeout(800)
                    fb = page.get_by_role("button", name="Give feedback")
                    bell = page.locator("button[aria-label^='Alerts:']").first
                    dims = page.evaluate(
                        "[document.documentElement.scrollWidth, document.documentElement.clientWidth]"
                    )
                    row: dict[str, object] = {
                        "width": width,
                        "theme": theme,
                        "scrollWidth": dims[0],
                        "clientWidth": dims[1],
                        "no_hscroll": dims[0] == width == dims[1],
                        "feedback_visible": fb.is_visible(),
                        "bell_visible": bell.is_visible(),
                    }
                    page.screenshot(path=str(OUT / f"N-header-{width}-{theme}.png"))
                    fb.click()
                    page.wait_for_timeout(300)
                    row["dialog_opens"] = page.get_by_role("dialog").is_visible()
                    page.screenshot(path=str(OUT / f"N-dialog-{width}-{theme}.png"))
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    row["esc_closes"] = page.get_by_role("dialog").count() == 0
                    rows.append(row)
                    ctx.close()
            browser.close()
    finally:
        srv.terminate()
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
