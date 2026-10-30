"""B6a screenshots: home dashboard, workflow with mini-dashboard, expanded panel, bell list, artifacts tabs.

    cd web && npm run build && python3 qa/shoot_b6a.py

Serves ``dist/`` locally with the network blocked and writes ``qa/screenshots/B6-<view>-<width>-<theme>.png``.
Prints, as JSON, the horizontal-scroll check (scrollWidth - clientWidth) for every shot and the
expand/collapse, Esc, bell and sidebar checks.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import OUT, local_only, serve


def overflow(page: Page) -> dict[str, int]:
    """Horizontal overflow of the page, the body and the widest element."""
    return page.evaluate("""() => ({
          doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          body: document.body.scrollWidth - document.body.clientWidth,
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
        })""")


def sidebar_visible(page: Page) -> bool:
    """True when the sidebar is on screen."""
    box = page.locator("#sidebar").bounding_box()
    return bool(box) and page.locator("#sidebar").is_visible()


def go_workflow(page: Page, phone: bool, title: str) -> None:
    """Open a workflow from the sidebar (through the drawer on a phone)."""
    if phone:
        page.get_by_label("Toggle sidebar").click()
        page.wait_for_timeout(250)
    page.locator("#sidebar").get_by_role("button", name=title).first.click()
    page.wait_for_timeout(400)


def shot(page: Page, r: dict[str, object], tag: str, name: str, full: bool = False) -> None:
    """Record the overflow numbers of the page and save ``B6-<name>-<tag>.png``."""
    page.wait_for_timeout(250)
    r[f"overflow_{name}"] = overflow(page)
    page.screenshot(path=str(OUT / f"B6-{name}-{tag}.png"), full_page=full)


def inner_overflow(page: Page, selector: str) -> list[str]:
    """Descendants of ``selector`` that scroll sideways (scrollWidth > clientWidth)."""
    return page.evaluate(
        """(sel) => [...document.querySelectorAll(sel + ' *')]
          .filter(e => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
          .map(e => e.tagName + '.' + String(e.className).slice(0, 40) + ' ' + e.scrollWidth + '/' + e.clientWidth)""",
        selector,
    )


def tabs_check(page: Page) -> dict[str, object]:
    """The artifacts tablist must not scroll sideways, and every tab must lie inside the pane."""
    return page.evaluate("""() => {
          const l = document.querySelector('[role=tablist]');
          const pane = document.querySelector('#artifacts').getBoundingClientRect();
          const tabs = [...l.querySelectorAll('[role=tab]')];
          const inside = tabs.every(t => { const b = t.getBoundingClientRect(); return b.left >= pane.left - 1 && b.right <= pane.right + 1 });
          const ys = new Set(tabs.map(t => Math.round(t.getBoundingClientRect().y)));
          return { scrollWidth: l.scrollWidth, clientWidth: l.clientWidth, tabs: tabs.length, rows: ys.size, all_inside_pane: inside,
                   no_sideways_scroll: l.scrollWidth <= l.clientWidth }
        }""")


def main() -> None:
    """Take the B6a screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {}
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

                # 1. home
                shot(page, r, tag, "home")
                # scroll home to show charts
                page.locator("main [aria-label='Recorded runs']").scroll_into_view_if_needed()
                shot(page, r, tag, "home-charts")
                page.locator("main").locator("div.overflow-y-auto").first.evaluate(
                    "e => e.scrollTo(0, e.scrollHeight)"
                )
                shot(page, r, tag, "home-bottom")
                r["badge"] = (
                    page.get_by_test_id("alert-badge").inner_text()
                    if page.get_by_test_id("alert-badge").count()
                    else None
                )
                r["bell_label"] = page.get_by_test_id("alert-bell").get_attribute("aria-label")

                # 2. bell list
                page.get_by_test_id("alert-bell").click()
                page.wait_for_selector("#alert-list")
                r["bell_items"] = page.locator("#alert-list ul button").count()
                shot(page, r, tag, "bell")
                page.keyboard.press("Escape")
                r["bell_closed_on_esc"] = page.locator("#alert-list").count() == 0
                # click an item -> view
                page.get_by_test_id("alert-bell").click()
                page.locator("#alert-list ul button").first.click()
                page.wait_for_timeout(300)
                r["after_bell_click_focused_row"] = page.locator(
                    "[data-focused=true]"
                ).evaluate_all("els => els.map(e => e.id)")
                shot(page, r, tag, "bell-target-row")
                r["bell_target_inner_overflow"] = inner_overflow(
                    page, "aside[aria-label$='dashboard']"
                )
                page.keyboard.press("Escape")

                # 3. workflow with mini-dashboard
                go_workflow(page, phone, "Ask the copilot")
                r["mini_title"] = page.locator(
                    "aside[aria-label$='dashboard'] h2"
                ).first.inner_text()
                shot(page, r, tag, "workflow-mini")
                if phone:
                    page.get_by_role("button", name="Show numbers").click()
                r["mini_inner_overflow"] = inner_overflow(page, "aside[aria-label$='dashboard']")

                # 4. expanded mini-dashboard, Esc collapses
                page.get_by_test_id("expand-mini").click()
                page.wait_for_timeout(250)
                r["mini_expanded_inner_overflow"] = inner_overflow(
                    page, "aside[aria-label$='dashboard']"
                )
                r["mini_expanded_attr"] = page.locator(
                    "aside[aria-label$='dashboard']"
                ).get_attribute("data-expanded")
                shot(page, r, tag, "expanded-mini")
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                r["mini_after_esc"] = page.locator("aside[aria-label$='dashboard']").get_attribute(
                    "data-expanded"
                )
                # expand chat via button, collapse via button
                page.get_by_test_id("expand-main").click()
                page.wait_for_timeout(200)
                r["main_expanded_attr"] = page.locator("main").get_attribute("data-expanded")
                shot(page, r, tag, "expanded-chat")
                page.get_by_test_id("expand-main").click()
                r["main_after_button"] = page.locator("main").get_attribute("data-expanded")

                # 5. AI sweep workflow (rules + stats)
                go_workflow(page, phone, "AI device sweep")
                page.locator("main [data-testid=sweep-rules]").scroll_into_view_if_needed()
                r["sweep_rules_text"] = page.locator("main [data-testid=sweep-rules]").inner_text()
                shot(page, r, tag, "sweep-rules")

                # 6. artifacts tabs (+ expand)
                if not page.locator("#artifacts").is_visible():
                    page.get_by_label("Toggle artifacts").click()
                page.wait_for_timeout(450)
                r["tabs_ai_sweep"] = tabs_check(page)
                shot(page, r, tag, "artifacts-tabs")
                # the thread with the most produced tabs (CAPA-need evidence)
                if phone:
                    page.get_by_label("Close artifacts").click()
                go_workflow(page, phone, "CAPA-need evidence")
                if not page.locator("#artifacts").is_visible():
                    page.get_by_label("Toggle artifacts").click()
                page.wait_for_timeout(450)
                r["tabs_capa_thread"] = tabs_check(page)
                r["tabs_new_dots"] = page.locator("[role=tab] .bg-accent").count()
                shot(page, r, tag, "artifacts-tabs-thread")
                for key in ("tabs_ai_sweep", "tabs_capa_thread"):
                    chk = r[key]
                    assert (
                        isinstance(chk, dict)
                        and chk["no_sideways_scroll"]
                        and chk["all_inside_pane"]
                    ), (tag, key, chk)
                page.get_by_test_id("expand-artifacts").click()
                page.wait_for_timeout(250)
                shot(page, r, tag, "expanded-artifacts")
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                r["artifacts_after_esc"] = page.locator("#artifacts").get_attribute("data-expanded")

                # 7. sidebar collapse/expand
                if not phone:
                    r["sidebar_before"] = sidebar_visible(page)
                    page.get_by_label("Toggle sidebar").click()
                    page.wait_for_timeout(250)
                    r["sidebar_after_collapse"] = sidebar_visible(page)
                    shot(page, r, tag, "sidebar-collapsed")
                    page.get_by_label("Toggle sidebar").click()
                    page.wait_for_timeout(250)
                    r["sidebar_after_expand"] = sidebar_visible(page)
                else:
                    page.get_by_label("Close artifacts").click()
                    page.wait_for_timeout(250)
                    r["sidebar_before"] = sidebar_visible(page)
                    page.get_by_label("Toggle sidebar").click()
                    page.wait_for_timeout(300)
                    r["sidebar_after_open"] = sidebar_visible(page)
                    shot(page, r, tag, "sidebar-drawer")
                    page.get_by_label("Close menu").click()
                    page.wait_for_timeout(300)
                    r["sidebar_after_close"] = sidebar_visible(page)
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
