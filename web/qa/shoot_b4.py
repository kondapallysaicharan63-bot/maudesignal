"""B4 screenshots and checks (Charan's feedback round) at 1440 and 390, light and dark.

    cd web && npm run build && cd qa && python3 shoot_b4.py

Serves ``dist/`` locally and blocks every other request, except in one step: the "Check any device
type" result screenshot. openFDA cannot be reached from the build sandbox, so that step answers the
browser's openFDA requests with a mock built from the counts stored in ``sweep.json`` for IYN (this
week 21, 4 weeks before 42, 2727 before that). It proves the result layout, not a live call; the
file name says so (``B4-check-result-stored-counts``). The failure screen is the real behaviour of
a blocked request.

Checks printed as JSON: sweep card first on load, no "coming soon" on any screen, hidden workflows,
no overlap with a stand-in for the Vercel toolbar's round button (64 px, bottom right) once each
scroll area is scrolled to its end, chips wrap without a scrollbar, closest-answer and "Ask live"
messages, the withheld button opening the exact sentence, and no sideways page scroll.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import re

from playwright.sync_api import Page, Route, sync_playwright
from shoot_b1 import WEB, local_only, serve

OUT = WEB / "qa" / "screenshots"
DATA = WEB / "public" / "data"
STREAMLIT = "https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app/"
SOON = re.compile("coming" + r"\s+" + "soon", re.I)

STAND_IN = """
() => {
  let el = document.getElementById('toolbar-stand-in');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toolbar-stand-in';
    el.setAttribute('aria-hidden', 'true');
    el.style.cssText = 'position:fixed;right:12px;bottom:12px;width:64px;height:64px;border-radius:50%;' +
      'background:#6b6b6b;opacity:.85;z-index:2147483647;pointer-events:none';
    document.body.appendChild(el);
  }
  return true;
}
"""

# Text and controls under the stand-in, after every scroll area is scrolled to its end.
OVERLAP = """
() => {
  const s = document.getElementById('toolbar-stand-in').getBoundingClientRect();
  const hit = (r) => r.width > 0 && r.height > 0 &&
    r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top;
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || el.id === 'toolbar-stand-in') continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) if (hit(r)) {
      // Skip text that something else (such as the phone's bottom sheet) already covers.
      const cx = (Math.max(r.left, s.left) + Math.min(r.right, s.right)) / 2;
      const cy = (Math.max(r.top, s.top) + Math.min(r.bottom, s.bottom)) / 2;
      const top = document.elementFromPoint(cx, cy);
      if (top && (el.contains(top) || top.contains(el))) { out.push(n.textContent.trim().slice(0, 50)); break; }
    }
  }
  for (const el of document.querySelectorAll('button, a, input')) {
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const b = el.getBoundingClientRect();
    const cx = (Math.max(b.left, s.left) + Math.min(b.right, s.right)) / 2;
    const cy = (Math.max(b.top, s.top) + Math.min(b.bottom, s.bottom)) / 2;
    const top = document.elementFromPoint(cx, cy);
    if (hit(b) && top && (el.contains(top) || top.contains(el))) out.push('<' + el.tagName.toLowerCase() + '> ' + (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40));
  }
  return out;
}
"""

SCROLL_END = """
() => {
  for (const el of document.querySelectorAll('#artifact-panel, #sidebar nav, main > div:first-child'))
    el.scrollTop = el.scrollHeight;
}
"""


def mock_openfda(route: Route) -> None:
    """Answer openFDA requests from the counts stored in sweep.json for IYN (QA only)."""
    row = next(
        r
        for r in json.loads((DATA / "sweep.json").read_text())["rows"]
        if r["product_code"] == "IYN"
    )
    url = route.request.url
    cur, base, prior = row["current_count"], row["baseline_count"], row["prior_report_count"]
    ct = dict(row["current_event_type_counts"])
    body: dict[str, object]
    if "count=date_received" in url:
        body = {
            "results": [{"time": "20260910", "count": base}, {"time": "20260930", "count": cur}]
        }
    elif "count=event_type.exact" in url:
        if "19900101" in url:
            body = {
                "results": [
                    {"term": "Injury", "count": 700},
                    {"term": "Malfunction", "count": prior - 700},
                ]
            }
        elif "20260924" in url:
            body = {"results": [{"term": k.title(), "count": v} for k, v in ct.items()]}
        else:
            sev = row["baseline_severe_count"]
            body = {
                "results": [
                    {"term": "Injury", "count": sev},
                    {"term": "Malfunction", "count": base - sev},
                ]
            }
    else:
        body = {"meta": {"results": {"total": prior}}}
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(body),
        headers={"access-control-allow-origin": "*"},
    )


def open_sidebar(page: Page, phone: bool) -> None:
    """Open the phone drawer (the desktop sidebar is always open)."""
    if phone:
        page.get_by_label("Toggle sidebar").click()
        page.wait_for_timeout(200)


def go_workflow(page: Page, phone: bool, name: str) -> None:
    """Click a workflow in the sidebar."""
    open_sidebar(page, phone)
    page.locator("#sidebar").get_by_role(
        "button", name=re.compile(f"^{re.escape(name)}")
    ).first.click()
    page.wait_for_timeout(250)


def new_chat(page: Page, phone: bool) -> None:
    """Go back to the first screen."""
    open_sidebar(page, phone)
    page.locator("#sidebar").get_by_role("button", name="New chat").click()
    page.wait_for_timeout(200)


def open_artifacts_tab(page: Page, phone: bool, label: str) -> None:
    """Show the artifacts pane (phone: the sheet) on one tab."""
    if (
        phone
        and page.locator("#artifacts").evaluate("e => getComputedStyle(e).visibility") == "hidden"
    ):
        page.get_by_label("Toggle artifacts").click()
        page.wait_for_timeout(250)
    page.locator("#artifacts").get_by_role("tab", name=label).first.click()
    page.wait_for_timeout(150)


def close_artifacts(page: Page, phone: bool) -> None:
    """Close the phone bottom sheet if it is open."""
    if (
        phone
        and page.locator("#artifacts").evaluate("e => getComputedStyle(e).visibility") != "hidden"
    ):
        page.get_by_label("Close artifacts").click()
        page.wait_for_timeout(250)


def xo(page: Page) -> int:
    """Pixels of sideways page scroll."""
    return int(
        page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    )


def body_text(page: Page) -> str:
    """All visible text on the page."""
    return page.evaluate("document.body.innerText")


def main() -> None:
    """Take the B4 screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("B4-*.png"):
        old.unlink()
    threads = json.loads((DATA / "threads.json").read_text())["threads"]
    withheld = [(t, s) for t in threads for s in t["sentences"] if s["status"] == "block"]
    sweep = json.loads((DATA / "sweep.json").read_text())
    flagged = [r for r in sweep["rows"] if r["classification"] != "stable"]
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {
        "flagged_in_sweep_json": len(flagged),
        "codes": sweep["meta"]["codes_on_list"],
    }
    mock = {"on": False}

    def router(route: Route) -> None:
        if route.request.url.startswith("https://api.fda.gov/") and mock["on"]:
            mock_openfda(route)
        else:
            local_only(route)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            phone = width < 700
            for scheme in ("light", "dark"):
                tag = f"{width}-{scheme}"
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    color_scheme=scheme,  # type: ignore[arg-type]
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                errors: list[str] = []
                page.on(
                    "console",
                    lambda m, e=errors: m.type == "error"
                    and "Failed to load resource" not in m.text
                    and e.append(m.text),
                )
                page.on("pageerror", lambda x, e=errors: e.append(str(x)))
                page.route("**/*", router)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                r: dict[str, object] = {}

                # 1. First card on load is the AI device sweep (real data).
                lead = page.locator("main article").first.inner_text()
                r["first_card"] = " ".join(lead.split())[:140]
                r["first_card_ok"] = (
                    f"{len(flagged)} flagged of {sweep['meta']['codes_on_list']} product codes"
                    in " ".join(lead.split())
                )
                if not phone:
                    r["artifacts_default_tab"] = (
                        page.locator("#artifacts [role=tab][aria-selected=true]")
                        .inner_text()
                        .strip()
                    )
                r["no_soon_on_load"] = not SOON.search(body_text(page))
                r["x_overflow_load"] = xo(page)
                page.screenshot(path=str(OUT / f"B4-sweep-first-{tag}.png"))

                # 4. Chips: 3 + "more", wrapping, no scrollbar.
                chips = page.locator("ul[aria-label='Suggested prompts']")
                r["chips_visible_collapsed"] = chips.locator("li button").count()
                r["chips_scroll_collapsed"] = chips.evaluate("e => e.scrollWidth - e.clientWidth")
                page.get_by_role("button", name=re.compile(r"^\d+ more$")).click()
                page.wait_for_timeout(100)
                r["chips_visible_expanded"] = chips.locator("li button").count()
                r["chips_scroll_expanded"] = chips.evaluate("e => e.scrollWidth - e.clientWidth")
                r["x_overflow_chips"] = xo(page)
                page.screenshot(path=str(OUT / f"B4-chips-more-{tag}.png"))
                page.get_by_role("button", name="Show fewer").click()

                # 1b. Composer: closest recorded answer, and "Ask live" when nothing is close.
                box = page.get_by_label("Ask a question")
                box.fill("are there recalls for LLZ")
                box.press("Enter")
                page.wait_for_timeout(300)
                note = page.locator("main [role=status]").inner_text()
                r["composer_match_notice"] = " ".join(note.split())
                r["composer_match_opened"] = "recalls on file for LLZ" in body_text(page)
                page.screenshot(path=str(OUT / f"B4-composer-match-{tag}.png"))
                box.fill("what is the weather in Paris")
                box.press("Enter")
                page.wait_for_timeout(200)
                live = page.get_by_role("link", name="Ask live")
                r["ask_live_href"] = live.get_attribute("href")
                r["ask_live_target"] = live.get_attribute("target")
                r["ask_live_ok"] = (
                    r["ask_live_href"] == STREAMLIT and r["ask_live_target"] == "_blank"
                )
                page.screenshot(path=str(OUT / f"B4-composer-live-{tag}.png"))
                r["plus_menu_gone"] = page.get_by_label("Add").count() == 0

                # 5. The withheld button opens the exact sentence.
                new_chat(page, phone)
                btn = page.get_by_role("button", name=re.compile("withheld"))
                r["withheld_button_text"] = " ".join(btn.first.inner_text().split())
                btn.first.click()
                page.wait_for_timeout(500)
                focus = page.locator("[data-focus=true]")
                want = withheld[0][1]["text"]
                r["withheld_focus_text"] = " ".join(focus.first.inner_text().split())[:120]
                r["withheld_exact_sentence"] = want.split(" ")[
                    0
                ] in focus.first.inner_text() and want[:40] in " ".join(
                    focus.first.inner_text().split()
                )
                r["withheld_thread_is"] = withheld[0][0]["id"]
                r["withheld_bar"] = " ".join(
                    page.locator("main [role=status]").first.inner_text().split()
                )[:100]
                r["withheld_in_view"] = focus.first.evaluate(
                    "e => { const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }"
                )
                page.screenshot(path=str(OUT / f"B4-withheld-{tag}.png"))

                # 2/3. Demo snapshot labels, the Brief tab, and no overlap with the round button.
                open_artifacts_tab(page, phone, "Brief")
                r["brief_demo_label"] = (
                    "Demo snapshot" in page.locator("#artifact-panel").inner_text()
                )
                page.evaluate(STAND_IN)
                page.evaluate(SCROLL_END)
                page.wait_for_timeout(100)
                r["overlap_brief_end"] = page.evaluate(OVERLAP)
                page.screenshot(path=str(OUT / f"B4-brief-bottom-standin-{tag}.png"))
                page.evaluate("document.getElementById('toolbar-stand-in').remove()")
                page.evaluate("document.getElementById('artifact-panel').scrollTop = 0")
                page.screenshot(path=str(OUT / f"B4-brief-{tag}.png"))
                close_artifacts(page, phone)

                # Overlap on the chat pane and sidebar too, scrolled to their ends.
                new_chat(page, phone)
                page.evaluate(STAND_IN)
                page.evaluate(SCROLL_END)
                r["overlap_chat_end"] = page.evaluate(OVERLAP)
                if phone:
                    open_sidebar(page, phone)
                    page.evaluate(SCROLL_END)
                    r["overlap_sidebar_end"] = page.evaluate(OVERLAP)
                    page.keyboard.press("Escape")
                    page.locator("#sidebar").get_by_label("Close menu").click()
                else:
                    r["overlap_sidebar_end"] = page.evaluate(OVERLAP)
                page.evaluate("document.getElementById('toolbar-stand-in').remove()")

                # 6. Check any device type: real failure when the request cannot be made, then a layout
                #    proof with the stored sweep counts.
                go_workflow(page, phone, "Check any device type")
                page.get_by_label("Any FDA product code").fill("iyn")
                page.get_by_role("button", name="Check on openFDA").click()
                page.wait_for_selector("[role=alert]")
                alert = page.locator("main [role=alert]").inner_text()
                r["check_failure_message"] = " ".join(alert.split())[:200]
                r["check_failure_streamlit_link"] = (
                    page.locator("main [role=alert] a").get_attribute("href") == STREAMLIT
                )
                r["check_failure_shows_no_result"] = page.locator("main article").count() == 0
                page.screenshot(path=str(OUT / f"B4-check-device-error-{tag}.png"))
                mock["on"] = True
                page.get_by_role("button", name="Check on openFDA").click()
                page.wait_for_selector("main article")
                res = " ".join(page.locator("main article").first.inner_text().split())
                r["check_result_text"] = res[:260]
                links = page.locator("main details a")
                r["check_result_links"] = links.count()
                r["check_first_link"] = links.first.get_attribute("href")
                page.screenshot(path=str(OUT / f"B4-check-result-stored-counts-{tag}.png"))
                mock["on"] = False

                # 7. Every other visible workflow.
                go_workflow(page, phone, "AI device sweep")
                page.screenshot(path=str(OUT / f"B4-ai-sweep-{tag}.png"))
                go_workflow(page, phone, "Label & 510(k) vision")
                r["vision_page_text"] = " ".join(page.locator("main h1").inner_text().split())
                page.screenshot(path=str(OUT / f"B4-vision-{tag}.png"))
                page.locator("main").get_by_role("button", name=re.compile(r"^K\d+")).first.click()
                page.wait_for_timeout(300)
                if (
                    phone
                    and page.locator("#artifacts").evaluate("e => getComputedStyle(e).visibility")
                    == "hidden"
                ):
                    page.get_by_label("Toggle artifacts").click()
                    page.wait_for_timeout(250)
                r["vision_opens_in_artifacts"] = (
                    page.locator("#artifacts [role=tab][aria-selected=true]").inner_text().strip()
                )
                page.screenshot(path=str(OUT / f"B4-vision-510k-open-{tag}.png"))
                close_artifacts(page, phone)
                go_workflow(page, phone, "What changed this week")
                r["thread_demo_label"] = "Demo snapshot" in page.locator("main").inner_text()
                page.screenshot(path=str(OUT / f"B4-weekly-signals-{tag}.png"))
                go_workflow(page, phone, "CAPA-need evidence")
                page.screenshot(path=str(OUT / f"B4-capa-need-evidence-{tag}.png"))
                go_workflow(page, phone, "Ask the copilot")
                page.screenshot(path=str(OUT / f"B4-ask-copilot-{tag}.png"))

                # Hidden workflows: not in the sidebar, the palette, or anywhere on screen.
                open_sidebar(page, phone)
                side = page.locator("#sidebar").inner_text()
                r["sidebar_has_hidden"] = bool(
                    re.search("Weekly investigator|Recall sweep|Intake inbox", side)
                )
                r["sidebar_no_soon"] = not SOON.search(side)
                sched = page.locator("#sidebar").inner_text()
                r["sidebar_demo_labels"] = sched.count("emo snapshot")
                page.screenshot(path=str(OUT / f"B4-sidebar-{tag}.png"))
                if phone:
                    page.locator("#sidebar").get_by_label("Close menu").click()
                    page.wait_for_timeout(200)
                page.keyboard.press("Control+k")
                page.wait_for_selector("[role=dialog]")
                pal = page.locator("[role=dialog]").inner_text()
                r["palette_has_hidden"] = bool(
                    re.search("Weekly investigator|Recall sweep|Intake inbox", pal)
                )
                r["palette_no_soon"] = not SOON.search(pal)
                r["palette_items"] = [
                    x.strip() for x in page.locator("[role=dialog] [role=option]").all_inner_texts()
                ]
                page.screenshot(path=str(OUT / f"B4-palette-{tag}.png"))
                page.keyboard.press("Escape")
                r["x_overflow_end"] = xo(page)
                r["console_errors"] = errors
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
