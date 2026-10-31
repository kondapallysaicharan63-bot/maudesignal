"""B6c screenshots: the label possible-matches screen (Vision > Device labels).

    cd web && npm run build && python3 qa/shoot_b6c.py

Serves ``dist/`` locally with the network blocked and writes ``qa/screenshots/B6c-<view>-<width>-<theme>.png``.
Prints, as JSON, the overflow numbers of every shot (scrollWidth must equal the viewport width) and the checks.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import OUT, local_only, serve
from shoot_b6a import go_workflow, overflow

PUBLIC = OUT.parents[1] / "public" / "data"

# Scroll only the Artifacts panel (never the page or chat behind it), leaving a little room above the element.
PANEL_SCROLL = """e => {
  const p = document.getElementById('artifact-panel');
  const top = e.getBoundingClientRect().top - p.getBoundingClientRect().top + p.scrollTop;
  p.scrollTo({top: Math.max(0, top - 8)});
}"""


def shot(page: Page, r: dict[str, object], tag: str, name: str) -> None:
    """Record the overflow numbers and save ``B6c-<name>-<tag>.png``."""
    page.wait_for_timeout(250)
    r[f"overflow_{name}"] = overflow(page)
    page.screenshot(path=str(OUT / f"B6c-{name}-{tag}.png"))


def scroll_to(page: Page, test_id: str) -> None:
    """Bring a test-id element to the top of its scroll container."""
    page.get_by_test_id(test_id).first.evaluate(PANEL_SCROLL)
    page.wait_for_timeout(200)


def main() -> None:
    """Take the B6c screenshots and print the checks."""
    vision = json.loads((PUBLIC / "vision.json").read_text())
    names = [lab["image"] for lab in vision["labels"]]
    with_matches = next(
        i for i, lab in enumerate(vision["labels"]) if lab["matches"] and lab["matches"]["matches"]
    )
    no_match = next(
        i
        for i, lab in enumerate(vision["labels"])
        if lab["matches"]
        and not lab["matches"]["matches"]
        and lab["matches"]["label"]["overall_legibility"] == "illegible"
    )
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {
        "label_with_matches": names[with_matches],
        "label_without": names[no_match],
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

                go_workflow(page, phone, "Label & 510(k) vision")
                r["list_text"] = page.locator("main").inner_text()
                shot(page, r, tag, "list")
                r["last_label_row_clear_of_composer"] = page.evaluate("""(() => {
                      const sc = document.querySelector('main .overflow-y-auto'); sc.scrollTop = sc.scrollHeight;
                      const rows = [...document.querySelectorAll('main li button')]; const last = rows[rows.length - 1].getBoundingClientRect();
                      const comp = document.querySelector('main form, main [data-testid=composer]');
                      const top = comp ? comp.getBoundingClientRect().top : sc.getBoundingClientRect().bottom;
                      sc.scrollTop = 0; return last.bottom <= top + 1 })()""")
                page.locator("main").get_by_role("button").filter(
                    has_text="possible match"
                ).first.click()
                page.wait_for_timeout(400)
                if (
                    phone
                    and page.locator("#artifacts").evaluate("e => getComputedStyle(e).visibility")
                    == "hidden"
                ):
                    page.get_by_label("Toggle artifacts").click()
                    page.wait_for_timeout(300)
                page.locator("#label-pick").select_option(str(with_matches))
                page.wait_for_timeout(300)
                shot(page, r, tag, "photo-fields")
                scroll_to(page, "label-matches")
                r["tabs_right_edges"] = page.evaluate(
                    "[...document.querySelectorAll('#artifacts [role=tab]')].map(t => Math.round(t.getBoundingClientRect().right))"
                )
                r["tabs_visible"] = page.evaluate(
                    "[...document.querySelectorAll('#artifacts [role=tab]')].every(t => t.getBoundingClientRect().right <= innerWidth)"
                )
                r["photo_height_vs_panel"] = page.evaluate(
                    "(() => { const i = document.querySelector('#artifact-panel figure img'); const p = document.getElementById('artifact-panel'); return Math.round(100 * i.getBoundingClientRect().height / p.getBoundingClientRect().height) })()"
                )
                r["cards_before_confirm"] = page.get_by_test_id("match-card").count()
                r["facts_before_confirm"] = page.get_by_test_id("match-facts").count()
                r["confirmed_before_click"] = page.get_by_test_id("confirmed-note").count()
                shot(page, r, tag, "matches")
                page.get_by_role("button", name="Confirm this match").first.click()
                page.wait_for_timeout(300)
                r["confirmed_note"] = page.get_by_test_id("confirmed-note").inner_text()
                r["confirmed_cards"] = page.get_by_test_id("confirmed-note").count()
                r["confirmed_in_view"] = page.evaluate(
                    "(() => { const c = document.querySelector('[data-confirmed=true]').getBoundingClientRect(); const p = document.getElementById('artifact-panel').getBoundingClientRect(); return c.top >= p.top - 1 && c.top < p.bottom })()"
                )
                shot(page, r, tag, "confirmed")
                scroll_to(page, "match-facts")
                shot(page, r, tag, "facts")
                page.get_by_test_id("label-matches").get_by_test_id("trace").locator(
                    "summary"
                ).click()
                page.wait_for_timeout(250)
                page.get_by_test_id("label-matches").get_by_test_id("trace").evaluate(PANEL_SCROLL)
                r["trace_text"] = (
                    page.get_by_test_id("label-matches").get_by_test_id("trace").inner_text()
                )
                shot(page, r, tag, "trace")
                scroll_to(page, "match-recorded-note")
                shot(page, r, tag, "recorded-note")

                # illegible reading with no match found
                page.locator("#label-pick").select_option(str(no_match))
                page.wait_for_timeout(300)
                page.get_by_test_id("legibility-banner").scroll_into_view_if_needed()
                r["banner"] = page.get_by_test_id("legibility-banner").inner_text()
                r["illegible_fields"] = page.get_by_test_id("label-fields").inner_text()
                shot(page, r, tag, "illegible")
                scroll_to(page, "no-match")
                r["no_match_text"] = page.get_by_test_id("no-match").inner_text()
                shot(page, r, tag, "no-match")
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
