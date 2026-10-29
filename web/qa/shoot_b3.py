"""B3 screenshots of every artifacts tab at 1440 and 390, light and dark.

    cd web/qa && python3 shoot_b3.py     (after ``npm run build`` in web/)

Serves ``dist/`` locally, blocks every non-local request, opens the CAPA-need evidence thread
(which must open the CAPA draft tab by itself on desktop), then writes
``qa/screenshots/B3-<tab>-<width>-<theme>.png`` for each tab. Prints the checks as JSON.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import WEB, local_only, serve

OUT = WEB / "qa" / "screenshots"

TABS = [
    ("brief", "Brief"),
    ("digest", "Digest"),
    ("dossier", "Dossier"),
    ("vision", "Vision"),
    ("audit", "Audit"),
    ("capa", "CAPA"),
    ("protocol", "Protocol"),
]


def select_tab(page: Page, label: str) -> None:
    """Click a tab in the artifacts pane and wait for its panel."""
    page.locator("#artifacts").get_by_role("tab", name=label).first.click()
    page.wait_for_timeout(150)


def main() -> None:
    """Take the B3 screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            phone = width < 700
            for scheme in ("light", "dark"):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    color_scheme=scheme,  # type: ignore[arg-type]
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: m.type == "error" and e.append(m.text))
                page.on("pageerror", lambda x, e=errors: e.append(str(x)))
                page.route("**/*", local_only)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                if phone:
                    page.get_by_label("Toggle sidebar").click()
                    page.wait_for_timeout(200)
                page.locator("#sidebar").get_by_role(
                    "button", name="CAPA-need evidence"
                ).first.click()
                page.wait_for_selector("main .ws-pill")
                if phone:
                    page.get_by_label("Toggle artifacts").click()
                    page.wait_for_timeout(250)
                auto = page.locator("#artifacts [role=tab][aria-selected=true]").inner_text()
                report[f"auto_open-{width}-{scheme}"] = auto.strip()
                for tid, label in TABS:
                    select_tab(page, label)
                    if tid == "dossier":
                        page.wait_for_selector("#artifact-panel canvas", timeout=15000)
                        report[f"dossier_canvases-{width}-{scheme}"] = page.locator(
                            "#artifact-panel canvas"
                        ).count()
                    if tid == "capa":
                        page.get_by_role("button", name="Human reviewer").click()
                        page.get_by_label("Your name (a named person approves)").fill(
                            "Example Reviewer"
                        )
                    page.evaluate("document.fonts.ready")
                    root = "document.documentElement"
                    overflow = page.evaluate(f"{root}.scrollWidth - {root}.clientWidth")
                    report[f"{tid}-{width}-{scheme}"] = {"x_overflow_px": overflow}
                    page.screenshot(path=str(OUT / f"B3-{tid}-{width}-{scheme}.png"))
                    if tid == "capa":
                        page.get_by_role("button", name="Approve (demo: not saved)").click()
                        page.wait_for_selector("text=Demo: not saved")
                        page.screenshot(path=str(OUT / f"B3-capa-approved-{width}-{scheme}.png"))
                    if tid == "vision":
                        page.get_by_role("button", name="510(k) summaries").click()
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(OUT / f"B3-vision-510k-{width}-{scheme}.png"))
                report[f"console_errors-{width}-{scheme}"] = errors
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
