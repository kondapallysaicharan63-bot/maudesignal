"""B7 screenshots: "Our devices (simulated)" (table, mini-dashboard, device detail, alert bell).

    cd web && npm run build && python3 qa/shoot_b7.py

Serves ``dist/`` locally with the network blocked and writes ``qa/screenshots/B7-<view>-<width>-<theme>.png``.
Prints, as JSON, the overflow numbers of every shot (scrollWidth must equal the viewport width) and the checks.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from playwright.sync_api import Page, Route, sync_playwright
from shoot_b1 import OUT, local_only, serve
from shoot_b6a import go_workflow, overflow

PUBLIC = OUT.parents[1] / "public" / "data"
BANNER = "Simulated company \u2014 sample data. Problem evidence is real FDA data."
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


def with_one_device_missing(code_device_id: str):  # type: ignore[no-untyped-def]
    """A route handler that serves company.json with one device's evidence emptied.

    No device in the shipped file is missing (every code is backed by the demo database or a fetched
    file), so the missing-evidence screen is shot on a test copy of the real file: one real device,
    its evidence written the way the exporter writes a missing code. Nothing else is changed.
    """

    def handler(route: Route) -> None:
        doc = json.loads((PUBLIC / "company.json").read_text())
        for d in doc["devices"]:
            if d["id"] == code_device_id:
                d["evidence"] = {
                    "origin": "missing",
                    "available": False,
                    "note": "evidence not fetched yet",
                    "report_count": None,
                    "window": None,
                    "queries": [],
                    "recalls": None,
                }
                d["patterns"] = []
        route.fulfill(status=200, content_type="application/json", body=json.dumps(doc))

    return handler


def main() -> None:
    """Take the B7 screenshots and print the checks."""
    company = json.loads((PUBLIC / "company.json").read_text())
    fetched = next(d for d in company["devices"] if d["evidence"]["available"] and d["patterns"])
    assert all(d["evidence"]["available"] for d in company["devices"]), "a device is missing"
    missing = company["devices"][-1]  # shot on a test copy where its evidence is emptied
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {
        "detail_with_evidence": fetched["name"],
        "detail_without_evidence_test_copy": missing["name"],
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
                # default state: on a phone the stats drawer is folded to one line ("6 need review")
                r["mini_text"] = page.locator("aside[aria-label$='dashboard']").inner_text()
                r["first_rows"] = page.locator("main tbody tr").evaluate_all(
                    "rows => rows.map(r => [r.innerText.split('\\n')[0], r.getBoundingClientRect().bottom, innerHeight])"
                )[:3]
                shot(page, r, tag, "table")
                r["overflowing_in_main"] = inner_x_overflow(page)
                if phone:
                    page.get_by_test_id("mini-toggle").click()
                    page.wait_for_timeout(250)
                    r["mini_open_text"] = page.locator(
                        "aside[aria-label$='dashboard']"
                    ).inner_text()
                    shot(page, r, tag, "table-drawer-open")
                    page.get_by_test_id("mini-toggle").click()
                # scrolled: the composer folds to its input row
                page.locator("main .overflow-y-auto").first.evaluate(
                    "e => { e.scrollTop = e.scrollHeight }"
                )
                page.wait_for_timeout(250)
                r["composer_height_scrolled"] = page.get_by_test_id("composer").evaluate(
                    "e => e.getBoundingClientRect().height"
                )
                shot(page, r, tag, "table-scrolled")
                page.locator("main .overflow-y-auto").first.evaluate("e => { e.scrollTop = 0 }")
                # filter chip
                page.get_by_test_id("filter-chips").get_by_role(
                    "button", name="Needs review"
                ).click()
                page.wait_for_timeout(250)
                r["filtered_rows"] = page.locator("main tbody tr").count()
                shot(page, r, tag, "table-filtered")
                page.get_by_test_id("filter-chips").get_by_role("button", name="All").click()

                # expanded mini-dashboard
                (
                    page.get_by_label("Expand").first.click()
                    if page.get_by_label("Expand").count()
                    else None
                )
                page.wait_for_timeout(300)
                if page.get_by_test_id("status-bars").count():
                    r["mini_expanded_banner"] = page.get_by_test_id("status-bars").inner_text()
                    assert BANNER in r["mini_expanded_banner"], "no banner in the expanded view"
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

                # device without evidence: a test copy of the real file (see with_one_device_missing)
                page2 = ctx.new_page()
                page2.route("**/*", local_only)
                page2.route("**/data/company.json", with_one_device_missing(missing["id"]))
                page2.goto(url, wait_until="load")
                page2.wait_for_selector("text=claims verified")
                page2.evaluate("document.fonts.ready")
                go_workflow(page2, phone, TITLE)
                page2.get_by_role("button", name=f"{missing['name']} {missing['model']}").click()
                page2.wait_for_timeout(400)
                r["missing_text"] = page2.get_by_test_id("evidence-missing").inner_text()
                shot(page2, r, tag, "missing-evidence")
                page2.close()

                # alert bell
                page.get_by_test_id("alert-bell").click()
                page.wait_for_timeout(300)
                r["bell_list"] = page.locator("#alert-list").inner_text()[:600]
                assert BANNER in page.locator("#alert-list").inner_text(), "no banner in the bell"
                shot(page, r, tag, "bell")
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2, ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    main()
