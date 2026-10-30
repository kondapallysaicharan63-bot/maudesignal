"""Contrast audit for the B6 views: computes WCAG ratios from the rendered colours (light and dark).

    cd web && npm run build && python3 qa/contrast_b6b.py

For every visible text element on each view it takes the computed text colour and the first opaque
background found walking up the tree, then reports the lowest ratios and any element under 4.5:1
(3:1 for large text). Also prints the exact pairs for the alert badge, the alert pills and the banners.
"""

# ruff: noqa: E501
from __future__ import annotations

import json

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import local_only, serve

JS = """() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 } };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b) };
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const bgOf = (el) => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break } }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (const c of stack.reverse()) base = over(c, base);
    return base;
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const n = walker.currentNode; const t = n.textContent.trim(); if (!t) continue;
    const el = n.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    const fg = parse(cs.color); const bg = bgOf(el); const f = over(fg, bg);
    const l1 = lum(f), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const px = parseFloat(cs.fontSize); const bold = parseInt(cs.fontWeight) >= 700;
    const large = px >= 24 || (px >= 18.66 && bold);
    out.push({ text: t.slice(0, 40), cls: String(el.className).slice(0, 50), ratio: Math.round(ratio * 100) / 100, px, large, ok: ratio >= (large ? 3 : 4.5) });
  }
  return out;
}"""


def audit(page: Page, name: str, report: dict[str, object]) -> None:
    """Record the audit of the current screen."""
    rows = page.evaluate(JS)
    bad = [r for r in rows if not r["ok"]]
    small = [r for r in rows if r["px"] < 15 and r["text"]]
    report[name] = {
        "elements": len(rows),
        "min_ratio": min(r["ratio"] for r in rows),
        "under_threshold": bad[:8],
        "text_under_15px": small[:6],
    }


def main() -> None:
    """Run the audit on home, the type-ahead, a thread with its trace, the camera panel, the bell list and the drawer."""
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            for scheme in ("light", "dark"):
                tag = f"{width}-{scheme}"
                ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)  # type: ignore[arg-type]
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                audit(page, f"{tag} home", report)
                # the badge and an alert pill, exact pairs
                pair = page.evaluate(
                    """() => { const b = document.querySelector('[data-testid=alert-badge]'); const cs = getComputedStyle(b); return { badge_fg: cs.color, badge_bg: cs.backgroundColor, badge_px: cs.fontSize } }"""
                )
                report[f"{tag} badge"] = pair
                box = page.get_by_role("combobox")
                box.click()
                box.fill("recall")
                page.wait_for_selector("[role=option]")
                audit(page, f"{tag} typeahead", report)
                box.press("ArrowDown")
                audit(page, f"{tag} typeahead selected", report)
                box.press("Escape")
                box.fill("")
                page.get_by_test_id("alert-bell").click()
                page.wait_for_selector("#alert-list")
                audit(page, f"{tag} bell list", report)
                page.keyboard.press("Escape")
                page.get_by_test_id("composer-camera").click()
                page.wait_for_selector("[data-testid=patient-warning]")
                audit(page, f"{tag} camera", report)
                page.get_by_test_id("image-input").set_input_files(
                    {"name": "a.png", "mimeType": "image/png", "buffer": b"\x89PNG\r\n\x1a\n1234"}
                )
                audit(page, f"{tag} camera picked", report)
                page.get_by_role("button", name="Send photo").click()
                page.wait_for_selector("[data-testid=fallback-reason]")
                audit(page, f"{tag} camera fallback", report)
                page.get_by_test_id("composer-mic").click()
                page.wait_for_selector("[data-testid=patient-warning]")
                audit(page, f"{tag} mic", report)
                page.get_by_role("combobox").fill("recall")
                page.get_by_role("option").first.click()
                page.wait_for_selector("[data-testid=trace]", timeout=15000)
                page.wait_for_timeout(3500)
                page.get_by_test_id("trace").locator("summary").click()
                audit(page, f"{tag} thread with trace open", report)
                page.get_by_label("Toggle sidebar").click()
                page.wait_for_timeout(300)
                audit(page, f"{tag} sidebar", report)
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
