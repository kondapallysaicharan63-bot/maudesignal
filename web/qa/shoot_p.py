"""P run (task O-web): alert detail panel, outside mentions, "Connect to Muse", header at 390 px.

    cd web && python3 qa/shoot_p.py

Builds the site twice (with the live stub's address, and without any API address), serves both, and drives Chromium.
Checks every way into the alert panel (bell, home dashboard, Signals list, Our devices), its sections, Esc, the focus
trap and focus return, "Open in chat" (live and recorded), the mentions box (stored, live, 429, personal details,
Official source only for fda.gov), the Connect page (key handed out, no key, no API, 404), the header at 390 and sideways
scroll. Screenshots: qa/screenshots/P-<view>-<width>-<theme>.png at 390 and 1440, light and dark. Prints one JSON
report; exits 1 if any check failed.
"""

# ruff: noqa: E501, T201
from __future__ import annotations

import json
import re
import sys

import e2e_live as e
from live_stub import Stub
from playwright.sync_api import Browser, Page, sync_playwright

results = e.results
check = e.check

# Sections the panel must print, in order.
SECTIONS = ["What changed", "Reports behind it", "Recalls and 510(k)", "Who filed", "Next steps"]
FORBIDDEN = re.compile(
    r"\b(safe|unsafe|compliant|validated|overnight)\b|fda[- ]approved|part 11 compliant|worsening signals?|citation-checked|complaint data",
    re.I,
)


def page_for(browser: Browser, width: int, height: int, scheme: str) -> Page:
    """A page with clipboard access."""
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=scheme,  # type: ignore[arg-type]
        permissions=["clipboard-read", "clipboard-write"],
    )
    return ctx.new_page()


def open_site(page: Page, url: str) -> None:
    """Open the app and wait for the dashboard."""
    page.goto(url, wait_until="load")
    page.wait_for_selector("text=Dashboard")
    page.evaluate("document.fonts.ready")


def snap(page: Page, name: str, w: int, scheme: str, report: dict[str, object]) -> None:
    """Screenshot P-<name>-<w>-<scheme>.png and record the overflow."""
    page.wait_for_timeout(250)
    report[f"overflow_{name}_{w}_{scheme}"] = e.overflow(page)
    page.screenshot(path=str(e.OUT / f"P-{name}-{w}-{scheme}.png"))


def ratio(page: Page, selector: str) -> float:
    """WCAG contrast ratio of the first match's text colour against its nearest opaque background."""
    return float(
        page.evaluate(
            """(sel) => {
          const el = document.querySelector(sel); if (!el) return 0;
          const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
          const lum = (c) => { const f = (v) => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4) }; return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b) };
          let bg = null; let n = el;
          while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a === 1) { bg = c; break } n = n.parentElement }
          if (!bg) bg = {r:255,g:255,b:255,a:1};
          const fg = parse(getComputedStyle(el).color);
          const a = lum(fg), b = lum(bg); return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
        }""",
            selector,
        )
    )


def focus_is(page: Page, selector: str) -> bool:
    """True when the first match has focus."""
    return bool(page.evaluate("(s) => document.activeElement === document.querySelector(s)", selector))


def panel_checks(page: Page, label: str, *, company: bool, phone: bool) -> None:
    """Sections, rule words, showing line, gate line, banner, widths, forbidden words."""
    panel = page.get_by_test_id("alert-panel")
    text = panel.inner_text()
    low = text.lower()  # the kickers are upper-cased by CSS
    check(f"{label}: panel has its sections in order", all(s.lower() in low for s in SECTIONS) and [low.index(s.lower()) for s in SECTIONS] == sorted(low.index(s.lower()) for s in SECTIONS))
    check(f"{label}: rule in plain words", page.get_by_test_id("alert-rule-words").inner_text().strip() != "")
    check(f"{label}: numbers each have an openFDA link", page.get_by_test_id("alert-number").count() >= 3 and page.locator("[data-testid=alert-number] a[href^='https://api.fda.gov']").count() == page.get_by_test_id("alert-number").count())
    has_reports = page.get_by_test_id("alert-report").count() > 0
    check(
        f"{label}: reports show 'showing N of M' or say none are stored",
        (has_reports and re.search(r"showing \d+ of \d+", page.get_by_test_id("alert-showing").inner_text()) is not None) or page.get_by_test_id("alert-no-reports").count() == 1,
    )
    check(f"{label}: gate line", re.fullmatch(r"\s*(\d+) facts? checked, (\d+) passed, (\d+) held back\s*", page.get_by_test_id("alert-gate").inner_text()) is not None, page.get_by_test_id("alert-gate").inner_text())
    check(f"{label}: next steps say a person decides", "A person decides" in text)
    check(f"{label}: no forbidden words", FORBIDDEN.search(text) is None, FORBIDDEN.search(text))
    banner = page.get_by_test_id("alert-simulated-banner")
    owner_shown = page.get_by_test_id("alert-owner").count() == 1
    check(f"{label}: the simulated banner is printed with the owner section and only then", (banner.count() == 1 and "Simulated company — sample data. Problem evidence is real FDA data." in banner.inner_text()) == owner_shown)
    if company:
        check(f"{label}: a device alert always has an owner section", owner_shown)
    vw = page.viewport_size["width"] if page.viewport_size else 0
    box = panel.bounding_box() or {"width": 0, "x": 0}
    check(f"{label}: {'full screen on a phone' if phone else 'side sheet on desktop'}", (abs(box["width"] - vw) < 2) if phone else (box["width"] < vw - 100 and box["x"] > 100), box)
    check(f"{label}: panel text contrast is at least 4.5", ratio(page, "[data-testid=alert-rule-words]") >= 4.5, ratio(page, "[data-testid=alert-rule-words]"))
    for q in page.locator("[data-testid=alert-report] blockquote").all():
        check(f"{label}: quote has no personal details", re.search(r"\b(Dr|Mr|Mrs|Ms)\.? [A-Z]|@|\d{3}[ -.]\d{3}[ -.]\d{4}|\d+[- ]year[- ]old", q.inner_text()) is None)


def main() -> int:
    """Run everything and print the report."""
    e.OUT.mkdir(parents=True, exist_ok=True)
    print("building...", flush=True)
    e.build()
    stub = Stub(port=e.STUB_PORT, origins={f"http://127.0.0.1:{e.LIVE_PORT}"})
    stub.start()
    servers = [e.preview("dist-live", e.LIVE_PORT), e.preview("dist-stored", e.STORED_PORT)]
    report: dict[str, object] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            report["chromium"] = browser.version

            # ---- 1. alert panel: every way in, desktop light (live build) -------------------------------------------
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.LIVE_URL)
            # 1a. home dashboard list
            row = page.locator("article[aria-label=Alerts] ul button").first
            row.focus()
            row.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            check("dashboard alert opens the panel", page.get_by_test_id("alert-panel").is_visible())
            panel_checks(page, "dashboard alert", company=False, phone=False)
            check("focus moves into the panel", bool(page.evaluate("document.querySelector('[data-testid=alert-panel]').contains(document.activeElement)")))
            for _ in range(60):
                page.keyboard.press("Tab")
            check("focus trap: after 60 Tab presses focus is still inside the panel", bool(page.evaluate("document.querySelector('[data-testid=alert-panel]').contains(document.activeElement)")))
            for _ in range(60):
                page.keyboard.press("Shift+Tab")
            check("focus trap: and after 60 Shift+Tab presses", bool(page.evaluate("document.querySelector('[data-testid=alert-panel]').contains(document.activeElement)")))
            snap(page, "alert-panel", 1440, "light", report)
            page.keyboard.press("Escape")
            page.wait_for_selector("[data-testid=alert-panel]", state="detached")
            check("Esc closes the panel and focus returns to the alert that was clicked", row.evaluate("el => el === document.activeElement"))

            # 1b. bell
            page.get_by_test_id("alert-bell").click()
            page.locator("#alert-list ul[aria-label=Alerts] button").first.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            check("bell alert opens the panel", True)
            page.get_by_test_id("alert-panel-close").click()
            page.wait_for_selector("[data-testid=alert-panel]", state="detached")
            page.wait_for_timeout(100)
            check("close button: focus returns to the bell (the list had closed)", focus_is(page, "[data-testid=alert-bell]"))

            # 1c. Signals list (flagged product codes)
            sig = page.get_by_test_id("sweep-alert-details").first
            sig.scroll_into_view_if_needed()
            sig.focus()
            sig.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            check("Signals list row opens the panel", page.get_by_test_id("alert-panel").is_visible())
            check("Signals list panel names the code of its row", re.search(r"[A-Z]{3}", page.locator("#alert-panel-title").inner_text()) is not None)
            page.keyboard.press("Escape")
            page.wait_for_selector("[data-testid=alert-panel]", state="detached")
            check("Signals list: focus returns to the row's button", sig.evaluate("el => el === document.activeElement"))

            # 1d. Our devices
            page.get_by_role("button", name=re.compile("Our devices")).first.click()
            page.wait_for_selector("[data-testid=device-alert-details]")
            dev = page.get_by_test_id("device-alert-details").first
            dev.focus()
            dev.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            check("Our devices row opens the panel", page.get_by_test_id("alert-panel").is_visible())
            panel_checks(page, "device alert", company=True, phone=False)
            check("device alert: owner and status are printed", page.get_by_test_id("alert-owner").inner_text().count("(simulated)") == 1, page.get_by_test_id("alert-owner").inner_text())
            page.keyboard.press("Escape")
            page.wait_for_selector("[data-testid=alert-panel]", state="detached")
            check("Our devices: focus returns to Alert details", dev.evaluate("el => el === document.activeElement"))
            page.close()

            # ---- 2. Open in chat: live (stub receives the code) and recorded ---------------------------------------
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.LIVE_URL)
            page.locator("article[aria-label=Alerts] ul button").first.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            code = page.locator("#alert-panel-title .ms-code").inner_text().strip()
            page.get_by_test_id("open-in-chat").click()
            page.wait_for_selector("[data-testid=live-turn]", timeout=20000)
            asks = [x for x in e.stub_log(page) if x["path"] == "/v1/live/ask"]
            body = asks[-1].get("body", {}) if asks else {}
            check("Open in chat (live): the stub got the product code and a question naming it", body.get("product_code") == code and code in str(body.get("question")), body)
            check("Open in chat: the panel is closed", page.get_by_test_id("alert-panel").count() == 0)
            page.close()
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.STORED_URL)
            page.locator("article[aria-label=Alerts] ul button").first.click()
            page.wait_for_selector("[data-testid=alert-panel]")
            page.get_by_test_id("open-in-chat").click()
            page.wait_for_function("document.body.innerText.includes('Stored run') || document.querySelector('main h1')", timeout=15000)
            check("Open in chat (no API): a stored run opens, no live turn", page.get_by_test_id("alert-panel").count() == 0 and page.locator("[data-testid=live-turn]").count() == 0)
            page.close()

            # ---- 3. mentions box -------------------------------------------------------------------------------------
            # 3a. no API: nothing stored -> "No stored search yet"; the button explains
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.STORED_URL)
            page.locator("article[aria-label=Alerts] ul button").first.click()
            page.wait_for_selector("[data-testid=mentions-box]")
            box = page.get_by_test_id("mentions-box")
            check("mentions box title and separate look", "News and public web (unverified)" in box.inner_text() and "border-dashed" in (box.get_attribute("class") or ""))
            check("no stored search: says 'No stored search yet', invents nothing", page.get_by_test_id("mentions-none").inner_text().strip() == "No stored search yet" and page.get_by_test_id("mention").count() == 0)
            page.get_by_test_id("search-outside").click()
            check("no API: the button says the live search is not connected", "not connected" in page.get_by_test_id("mentions-notice").inner_text())
            page.close()
            # 3b. live
            for scheme, w, h in (("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844)):
                stub.mode = "ok"
                page = page_for(browser, w, h, scheme)
                open_site(page, e.LIVE_URL)
                page.locator("article[aria-label=Alerts] ul button").first.click()
                page.wait_for_selector("[data-testid=alert-panel]")
                if w == 390:
                    panel_checks(page, f"alert panel {w} {scheme}", company=False, phone=True)
                page.get_by_test_id("search-outside").click()
                page.wait_for_selector("[data-testid=mentions-result][data-mode=live]", timeout=15000)
                dropped = page.get_by_test_id("mentions-dropped").inner_text()
                check(f"mentions {w} {scheme}: dropped line (the quote with a person's name is dropped and counted)", dropped == "2 found, 2 dropped because the quote was not on the page, 1 dropped for personal details", dropped)
                check(f"mentions {w} {scheme}: every mention carries the fixed Unverified badge", page.get_by_test_id("unverified-badge").count() == 2 and all(t == "Unverified — not checked against FDA records" for t in page.get_by_test_id("unverified-badge").all_inner_texts()))
                check(f"mentions {w} {scheme}: 'Official source' only on the fda.gov address", page.get_by_test_id("official-badge").count() == 1 and page.locator("[data-testid=mention][data-kind=web]").count() == 1)
                check(f"mentions {w} {scheme}: no personal details shown", "Dr. Smith" not in page.get_by_test_id("mentions-box").inner_text())
                check(f"mentions {w} {scheme}: each mention links out over https", page.locator("[data-testid=mention] a[href^='https://']").count() == 2)
                last = [x for x in e.stub_log(page) if x["path"] == "/v1/live/mentions"][-1]
                check(f"mentions {w} {scheme}: request is only the code and short terms; no cookies", set(last["body"]) <= {"product_code", "device_terms"} and len(last["body"]["product_code"]) == 3 and last["credentials_sent"] is False, last)
                badge_right = page.get_by_test_id("unverified-badge").first.evaluate("el => el.getBoundingClientRect().right")
                check(f"mentions {w} {scheme}: the Unverified badge stays inside the screen", badge_right <= w, badge_right)
                check(f"mentions {w} {scheme}: box contrast", ratio(page, "[data-testid=mentions-dropped]") >= 4.5, ratio(page, "[data-testid=mentions-dropped]"))
                page.get_by_test_id("mentions-box").scroll_into_view_if_needed()
                snap(page, "mentions", w, scheme, report)
                page.close()
            # 3c. 429 -> stored (none) message
            stub.mode = "429"
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.LIVE_URL)
            page.locator("article[aria-label=Alerts] ul button").first.click()
            page.get_by_test_id("search-outside").click()
            page.wait_for_selector("[data-testid=mentions-notice]")
            check("mentions 429: falls back to the stored search (none stored here) with the limit named", "Daily live limit reached" in page.get_by_test_id("mentions-notice").inner_text() and page.get_by_test_id("mentions-none").count() == 1)
            page.close()
            stub.mode = "ok"
            stub.mentions_mode = "empty"
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.LIVE_URL)
            page.locator("article[aria-label=Alerts] ul button").first.click()
            page.get_by_test_id("search-outside").click()
            page.wait_for_selector("[data-testid=mentions-result]")
            check("mentions: an empty result says nothing was kept", "Nothing was kept" in page.get_by_test_id("mentions-box").inner_text() and page.get_by_test_id("mention").count() == 0)
            page.close()
            stub.mentions_mode = "ok"

            # ---- 4. Connect to Muse ---------------------------------------------------------------------------------
            for scheme, w, h in (("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844)):
                stub.connect_mode = "ok"
                page = page_for(browser, w, h, scheme)
                open_site(page, e.LIVE_URL)
                if w == 390:
                    page.get_by_test_id("more-menu-button").click()
                    check("390: header menu lists Connect to Muse, search, feedback and theme", page.get_by_test_id("more-connect").is_visible() and page.get_by_test_id("more-search").is_visible() and page.get_by_test_id("more-feedback").is_visible() and page.get_by_test_id("more-theme").is_visible())
                    snap(page, "header-menu", w, scheme, report)
                    page.get_by_test_id("more-connect").click()
                else:
                    page.get_by_test_id("connect-button").click()
                page.wait_for_selector("[data-testid=connect-view] [data-testid=demo-key-block]")
                page.wait_for_selector("[data-testid=value-demo-key]")
                check(f"connect {w} {scheme}: MCP address, OpenAPI address and demo key are shown", page.get_by_test_id("value-mcp-address").inner_text() == "https://maudesignal-api.vercel.app/mcp" and page.get_by_test_id("value-openapi-address").inner_text().endswith("/openapi.json") and page.get_by_test_id("value-demo-key").inner_text().startswith("stub-demo-key"))
                check(f"connect {w} {scheme}: limits are stated (read-only, no live Spark, rate-limited)", "read-only" in page.get_by_test_id("demo-key-limits").inner_text() and "no live Spark" in page.get_by_test_id("demo-key-limits").inner_text())
                steps = page.locator("[data-testid=connect-steps] li").all_inner_texts()
                check(f"connect {w} {scheme}: three numbered steps", len(steps) == 3 and "connectors" in steps[0] and "https://maudesignal-api.vercel.app/mcp" in steps[1] and "X-API-Key" in steps[2], steps)
                check(f"connect {w} {scheme}: privacy and terms link to the API", page.get_by_test_id("link-privacy").get_attribute("href") == "https://maudesignal-api.vercel.app/privacy" and page.get_by_test_id("link-terms").get_attribute("href") == "https://maudesignal-api.vercel.app/terms")
                page.get_by_test_id("copy-demo-key").click()
                page.wait_for_timeout(200)
                clip = page.evaluate("navigator.clipboard.readText()")
                check(f"connect {w} {scheme}: one-click Copy puts the demo key on the clipboard", clip.startswith("stub-demo-key"), clip)
                check(f"connect {w} {scheme}: no OAuth button anywhere", "OAuth is not available" in page.get_by_test_id("connect-view").inner_text() and page.get_by_role("button", name=re.compile("sign in|log in|authorize", re.I)).count() == 0)
                get = [x for x in e.stub_log(page) if x["path"] == "/v1/connect"]
                check(f"connect {w} {scheme}: GET /v1/connect without cookies", len(get) >= 1 and get[-1]["credentials_sent"] is False)
                check(f"connect {w} {scheme}: contrast", ratio(page, "[data-testid=connect-view] p") >= 4.5)
                snap(page, "connect", w, scheme, report)
                page.close()
            # no key handed out, API 404, and no API at all
            for mode in ("no_key", "404"):
                stub.connect_mode = mode
                page = page_for(browser, 1440, 900, "light")
                open_site(page, e.LIVE_URL)
                page.get_by_test_id("connect-button").click()
                page.wait_for_selector("[data-testid=connect-view]")
                page.wait_for_function("!document.body.innerText.includes('Loading the connector')")
                txt = page.get_by_test_id("connect-view").inner_text()
                check(f"connect ({mode}): no key is shown and the page says to ask Charan", "Ask Charan for a key" in txt and page.get_by_test_id("value-demo-key").count() == 0 and "https://maudesignal-api.vercel.app/mcp" in txt)
                page.close()
            stub.connect_mode = "ok"
            page = page_for(browser, 1440, 900, "light")
            open_site(page, e.STORED_URL)
            page.get_by_test_id("connect-button").click()
            page.wait_for_selector("[data-testid=connect-view]")
            txt = page.get_by_test_id("connect-view").inner_text()
            check("connect (no API in this build): fixed text with the MCP URL, the OpenAPI URL and 'ask Charan for a key'", "https://maudesignal-api.vercel.app/mcp" in txt and "https://maudesignal-api.vercel.app/openapi.json" in txt and "Ask Charan for a key" in txt)
            page.close()

            # ---- 4b. the static privacy page (served at /privacy/) -------------------------------------------------------
            for scheme, w, h in (("light", 1440, 900), ("dark", 390, 844), ("light", 390, 844), ("dark", 1440, 900)):
                page = page_for(browser, w, h, scheme)
                page.goto(e.LIVE_URL + "privacy/", wait_until="load")
                txt = page.locator("main").inner_text()
                need = ["iad1", "Vercel", "Meta Model API", "openFDA", "kondapallysaicharan63@gmail.com", "No automatic deletion period", "not sold", "no name, no e-mail, no IP address", "is not kept"]
                missing = [n for n in need if n.lower() not in txt.lower()]
                check(f"privacy {w} {scheme}: answers the data questions (region, subprocessors, logs, retention, deletion contact, no sale)", not missing, missing)
                check(f"privacy {w} {scheme}: no forbidden words", FORBIDDEN.search(txt) is None, FORBIDDEN.search(txt))
                check(f"privacy {w} {scheme}: no sideways scroll and readable contrast", e.overflow(page) == 0 and ratio(page, "main p") >= 4.5, [e.overflow(page), ratio(page, "main p")])
                snap(page, "privacy", w, scheme, report)
                page.close()

            # ---- 5. header at 390 and 1440 -----------------------------------------------------------------------------
            for scheme in ("light", "dark"):
                for w, h in ((390, 844), (1440, 900)):
                    page = page_for(browser, w, h, scheme)
                    open_site(page, e.LIVE_URL)
                    hdr = page.locator("header > div").first
                    kids = hdr.evaluate("el => [...el.children].filter(c => c.offsetParent !== null).map(c => c.getBoundingClientRect().right)")
                    check(f"header {w} {scheme}: every control fits inside the viewport", max(kids) <= w + 0.5 and e.overflow(page) == 0, [max(kids), w])
                    tall = page.evaluate("[...document.querySelectorAll('header > div:first-child button')].filter(b => b.offsetParent !== null).every(b => b.getBoundingClientRect().height >= 40 && b.getBoundingClientRect().width >= 40)")
                    check(f"header {w} {scheme}: every header button is at least 40 px", tall)
                    if scheme == "dark" or w == 1440:
                        snap(page, "header", w, scheme, report)
                    page.close()
            # alert panel screenshots at 390 / dark
            for scheme, w, h in (("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844)):
                page = page_for(browser, w, h, scheme)
                open_site(page, e.LIVE_URL)
                page.locator("article[aria-label=Alerts] ul button").first.click()
                page.wait_for_selector("[data-testid=alert-panel]")
                snap(page, "alert-panel", w, scheme, report)
                page.close()
            # device panel (simulated banner) screenshots
            for scheme, w, h in (("light", 1440, 900), ("dark", 390, 844)):
                page = page_for(browser, w, h, scheme)
                open_site(page, e.LIVE_URL)
                page.get_by_role("button", name=re.compile("Our devices")).first.click() if w == 1440 else None
                if w == 390:
                    page.get_by_test_id("alert-bell").click()
                    page.locator("#alert-list [data-testid=alert-group]").nth(1).locator("ul button").first.click()
                else:
                    page.get_by_test_id("device-alert-details").first.click()
                page.wait_for_selector("[data-testid=alert-panel]")
                page.get_by_test_id("alert-simulated-banner").scroll_into_view_if_needed()
                snap(page, "alert-panel-device", w, scheme, report)
                page.close()
            browser.close()
    finally:
        for s in servers:
            s.terminate()
        stub.stop()
    failed = [r for r in results if not r["ok"]]
    report["checks"] = {"total": len(results), "failed": len(failed)}
    report["failed"] = failed
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
