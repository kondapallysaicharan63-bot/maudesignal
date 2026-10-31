"""Contrast and text-size audit for the B7 views (table, device with evidence, device without, bell list, drawer).

    cd web && npm run build && python3 qa/contrast_b7.py

Uses the same measurement as ``contrast_b6b.py`` (computed text colour over the first opaque background).
Reports, for light and dark at 1440 and 390: the lowest ratio, any text under 4.5:1 (3:1 for large text), and
any text under 15px. Also prints the exact ratios for the chips and the "Chain ok" pill.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from contrast_b6b import JS, audit
from playwright.sync_api import Page, sync_playwright
from shoot_b1 import local_only, serve
from shoot_b6a import go_workflow

TITLE = "Our devices (simulated)"

PAIR = """(sel) => { const el = document.querySelector(sel); if (!el) return null;
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 } };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b) };
  const cs = getComputedStyle(el); const fg = parse(cs.color); const bg = parse(cs.backgroundColor);
  const l1 = lum(fg), l2 = lum(bg); return { text: el.innerText.slice(0, 30), ratio: Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100, px: cs.fontSize } }"""


def pairs(page: Page, report: dict[str, object], tag: str) -> None:
    """Exact ratios of the pills on the current screen."""
    report[f"{tag} pills"] = {
        "status_chip": page.evaluate(PAIR, "[data-testid=status-chip]"),
        "chain_ok": page.evaluate(PAIR, ".ws-pill--ring.text-success"),
        "badge": page.evaluate(PAIR, "[data-testid=alert-badge]"),
    }


def main() -> None:
    """Run the audit."""
    _ = JS
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            phone = width < 700
            for scheme in ("light", "dark"):
                tag = f"{width}-{scheme}"
                ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)  # type: ignore[arg-type]
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                go_workflow(page, phone, TITLE)
                audit(page, f"{tag} table", report)
                pairs(page, report, f"{tag} table")
                if phone:
                    page.get_by_test_id("mini-toggle").click()
                    audit(page, f"{tag} drawer open", report)
                    page.get_by_test_id("mini-toggle").click()
                page.locator("main tbody tr").first.get_by_role("button").click()
                page.wait_for_timeout(300)
                audit(page, f"{tag} device with evidence", report)
                pairs(page, report, f"{tag} detail")
                page.get_by_role("button", name="All devices").first.click()
                page.get_by_test_id("filter-chips").get_by_role("button", name="Monitoring").click()
                page.locator("main tbody tr").first.get_by_role("button").click()
                page.wait_for_timeout(300)
                audit(page, f"{tag} device without evidence or quiet", report)
                page.get_by_test_id("alert-bell").click()
                page.wait_for_selector("#alert-list")
                audit(page, f"{tag} bell list", report)
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
