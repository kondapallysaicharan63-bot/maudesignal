"""B7 screenshots: "Our devices (simulated)" (table, mini-dashboard, device detail, alert bell).

    cd web && npm run build && python3 qa/shoot_b7.py

Serves ``dist/`` locally with the network blocked and writes ``qa/screenshots/B7-<view>-<width>-<theme>.png``.
Prints, as JSON, the overflow numbers of every shot (scrollWidth must equal the viewport width) and the checks.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import OUT, local_only, serve
from shoot_b6a import go_workflow, overflow

PUBLIC = OUT.parents[1] / "public" / "data"
TITLE = "Our devices (simulated)"


def shot(page: Page, r: dict[str, object], tag: str, name: str) -> None:
    """Record the overflow numbers and save ``B7-<name>-<tag>.png``."""
    page.wait_for_timeout(250)
    r[f"overflow_{name}"] = overflow(page)
    page.screenshot(path=str(OUT / f"B7-{name}-{tag}.png"))


def inner_x_overflow(page: Page) -> list[str]:
    """Elements inside the main column that are wider than the column."""
    return page.evaluate(
        """() => { const m = document.querySelector('main'); const w = m.getBoundingClientRect().right;
          return [...m.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > w + 1 && e.getBoundingClientRect().width > 0)
            .map(e => e.tagName + '.' + String(e.className).slice(0, 30)).slice(0, 8) }"""
    )


def main() -> None:
    """Take the B7 screenshots and print the checks."""
    company = json.loads((PUBLIC / "company.json").read_text())
    fetched = next(d for d in company["devices"] if d["evidence"]["available"] and d["patterns"])
    missing = next(d for d in company["devices"] if not d["evidence"]["available"])
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {
        "detail_with_evidence": fetched["name"],
        "detail_without_evidence": missing["name"],
        "needs_review": sum(
            1 for d in company["devices"] if d["status"]["label"] == "Needs review"
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            phone = width < 700
            for scheme in ("light", "dark"):
                tag = f"{width}-{scheme}"
                r: dict[str, object] = {}
                ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)  # type: ignore[arg-type]
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)

                r["bell_badge"] = page.get_by_test_id("alert-badge").inner_text()
                go_workflow(page, phone, TITLE)
                r["banner"] = page.get_by_test_id("company-banner").first.inner_text()
                r["banners_on_list_view"] = page.get_by_test_id("company-banner").count()
                if phone:
                    page.get_by_test_id("mini-toggle").click()
                    page.wait_for_timeout(250)
                r["mini_text"] = page.locator("aside[aria-label$='dashboard']").inner_text()
                shot(page, r, tag, "table")
                r["overflowing_in_main"] = inner_x_overflow(page)
                if phone:
                    page.get_by_test_id("mini-toggle").click()

                # expanded mini-dashboard
                (
                    page.get_by_label("Expand").first.click()
                    if page.get_by_label("Expand").count()
                    else None
                )
                page.wait_for_timeout(300)
                if page.get_by_test_id("status-bars").count():
                    shot(page, r, tag, "mini-expanded")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)

                # device with evidence
                page.get_by_role("button", name=f"{fetched['name']} {fetched['model']}").click()
                page.wait_for_timeout(400)
                page.locator("main .overflow-y-auto").first.evaluate("e => { e.scrollTop = 0 }")
                r["detail_banner"] = page.get_by_test_id("company-banner").first.inner_text()
                shot(page, r, tag, "detail")
                r["detail_overflowing"] = inner_x_overflow(page)
                sc = page.locator("main .overflow-y-auto").first
                page.get_by_test_id("pattern").first.scroll_into_view_if_needed()
                shot(page, r, tag, "patterns")
                page.get_by_test_id("history").scroll_into_view_if_needed()
                sc.evaluate("e => { e.scrollTop = e.scrollHeight }")
                shot(page, r, tag, "history")
                r["history_text"] = page.get_by_test_id("history").inner_text()
                r["chain_ok_shown"] = page.get_by_text("Chain ok").count()

                # device without evidence
                page.get_by_role("button", name="All devices").first.click()
                page.wait_for_timeout(300)
                page.get_by_role("button", name=f"{missing['name']} {missing['model']}").click()
                page.wait_for_timeout(400)
                r["missing_text"] = page.get_by_test_id("evidence-missing").inner_text()
                shot(page, r, tag, "missing-evidence")

                # alert bell
                page.get_by_test_id("alert-bell").click()
                page.wait_for_timeout(300)
                r["bell_list"] = page.locator("#alert-list").inner_text()[:400]
                shot(page, r, tag, "bell")
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2, ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    main()
