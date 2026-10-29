"""B2 screenshots of the chat pane: each workflow's thread plus a repaired and a voice thread.

    cd web/qa && python3 shoot_b2.py     (after ``npm run build`` in web/)

Serves ``dist/`` locally, blocks every non-local request and writes
``qa/screenshots/B2-<thread>-<width>-<theme>.png`` with reduced motion on, so the stored
answer is shown in full. Prints the checks (chip count, no sideways scroll) as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import WEB, local_only, serve

OUT = WEB / "qa" / "screenshots"
DATA = WEB / "public" / "data"

# (thread id, workflow title in the sidebar, id of the thread that workflow opens first)
CASES = [
    ("01-what-changed", "What changed this week", "01-what-changed"),
    ("03-quote", "Ask the copilot", "03-quote"),
    ("05-capa-need-evidence", "CAPA-need evidence", "05-capa-need-evidence"),
    ("06-trap", "Ask the copilot", "03-quote"),
    ("00-voice-c", "Ask the copilot", "03-quote"),
]


def open_thread(page: Page, tid: str, wf: str, first: str, question: str, phone: bool) -> None:
    """Open the workflow in the sidebar, then switch to the wanted thread if it is not the first."""
    if phone:
        page.get_by_label("Toggle sidebar").click()
        page.wait_for_timeout(200)
    page.locator("#sidebar").get_by_role("button", name=wf).first.click()
    page.wait_for_selector("main .ws-pill")
    if tid != first:
        page.locator("main details summary").first.click()
        page.locator("main details button", has_text=question[:30]).first.click()
        page.wait_for_selector("main .ws-pill")


def main() -> None:
    """Take the B2 screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    threads = {t["id"]: t for t in json.loads(Path(DATA / "threads.json").read_text())["threads"]}
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            for scheme in ("light", "dark"):
                for tid, wf, first in CASES:
                    ctx = browser.new_context(
                        viewport={"width": width, "height": height},
                        color_scheme=scheme,  # type: ignore[arg-type]
                        reduced_motion="reduce",
                    )
                    page = ctx.new_page()
                    page.route("**/*", local_only)
                    page.goto(url, wait_until="load")
                    page.wait_for_selector("text=claims verified")
                    t = threads[tid]
                    q = t["voice"]["transcript_text"] if t["voice"] else t["question"]
                    open_thread(page, tid, wf, first, q, width < 700)
                    if tid in ("03-quote", "06-trap"):
                        chip = 1 if tid == "06-trap" else 0
                        page.locator("main li button.ws-pill").nth(chip).click()
                    page.evaluate("document.fonts.ready")
                    chips = page.locator("main li button.ws-pill").count()
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth"
                        " - document.documentElement.clientWidth"
                    )
                    report[f"{tid}-{width}-{scheme}"] = {"chips": chips, "x_overflow_px": overflow}
                    page.screenshot(path=str(OUT / f"B2-{tid}-{width}-{scheme}.png"))
                    ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
