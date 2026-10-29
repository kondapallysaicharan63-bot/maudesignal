"""B5 screenshots (check workflow through the MaudeSignal API, CAPA-need evidence tab).

    cd web && VITE_MAUDESIGNAL_API_BASE=https://qa-api.example npm run build && python3 qa/shoot_b5.py api
    cd web && npm run build && python3 qa/shoot_b5.py unset

Serves ``dist/`` locally and blocks every other request. In ``api`` mode the one allowed
extra host, ``qa-api.example``, is answered by this script: a mock "check" built from the counts
stored in ``sweep.json`` for IYN, shown with a red "QA MOCK" banner, then a 429. It proves the
layout and the fallback, not a live call. Prints the checks as JSON.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import re
import sys

from playwright.sync_api import Route, sync_playwright
from shoot_b1 import OUT, local_only, serve
from shoot_b4 import (
    DATA,
    MOCK_BANNER,
    STREAMLIT,
    close_artifacts,
    go_workflow,
    open_artifacts_tab,
    xo,
)

BASE = "https://qa-api.example"


def main(mode: str) -> None:
    """Take the B5 screenshots for one build mode."""
    OUT.mkdir(parents=True, exist_ok=True)
    row = next(
        r
        for r in json.loads((DATA / "sweep.json").read_text())["rows"]
        if r["product_code"] == "IYN"
    )
    check = {**row, "change": "reports suddenly increased"}
    answer = {
        "speakable": "QA mock",
        "facts": [],
        "advisory": "QA mock answer.",
        "provenance": "QA mock",
        "check": check,
    }
    state: dict[str, object] = {"next": "ok"}
    calls: list[str] = []
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    cors = {"access-control-allow-origin": "*"}

    def router(route: Route) -> None:
        u = route.request.url
        if u.startswith(BASE):
            calls.append(u)
            if state["next"] == "ok":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(answer),
                    headers=cors,
                )
            else:
                route.fulfill(status=429, content_type="application/json", body="{}", headers=cors)
        else:
            local_only(route)

    banner = MOCK_BANNER.replace(
        "counts from sweep.json, not a live openFDA call",
        "mock API answer built from stored sweep.json counts, not a live call",
    )
    report: dict[str, object] = {"mode": mode}
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
                page.route("**/*", router)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                r: dict[str, object] = {}
                go_workflow(page, phone, "Check any device type")
                state["next"] = "ok"
                page.get_by_label("Any FDA product code").fill("iyn")
                page.get_by_role("button", name="Check device type").click()
                if mode == "api":
                    page.wait_for_selector("main article")
                    r["success_text"] = " ".join(
                        page.locator("main article").first.inner_text().split()
                    )[:240]
                    r["success_links"] = page.locator("main details a").count()
                    r["success_first_link"] = page.locator("main details a").first.get_attribute(
                        "href"
                    )
                    page.locator("main article").first.scroll_into_view_if_needed()
                    page.evaluate(banner)
                    page.screenshot(path=str(OUT / f"B5-check-success-qa-mock-{tag}.png"))
                    page.evaluate("document.getElementById('qa-mock-banner')?.remove()")
                    state["next"] = "429"
                    page.get_by_label("Any FDA product code").fill("llz")
                    page.get_by_role("button", name="Check device type").click()
                    page.wait_for_selector("[role=alert]")
                    r["rate_limited_message"] = " ".join(
                        page.locator("main [role=alert]").inner_text().split()
                    )[:220]
                    r["rate_limited_streamlit_link"] = (
                        page.locator("main [role=alert] a").get_attribute("href") == STREAMLIT
                    )
                    r["rate_limited_no_result"] = page.locator("main article").count() == 0
                    page.locator("main [role=alert]").scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT / f"B5-check-429-fallback-{tag}.png"))
                    r["api_calls_so_far"] = len(calls)
                else:
                    page.wait_for_selector("[role=alert]")
                    r["unset_message"] = " ".join(
                        page.locator("main [role=alert]").inner_text().split()
                    )[:220]
                    r["unset_streamlit_link"] = (
                        page.locator("main [role=alert] a").get_attribute("href") == STREAMLIT
                    )
                    r["unset_no_result"] = page.locator("main article").count() == 0
                    page.locator("main [role=alert]").scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT / f"B5-check-unset-base-{tag}.png"))
                r["x_overflow"] = xo(page)
                go_workflow(page, phone, "CAPA-need evidence")
                open_artifacts_tab(page, phone, "CAPA-need evidence")
                r["capa_tab_has_label"] = (
                    "capa-need evidence" in page.locator("#artifact-panel").inner_text().lower()
                )
                r["capa_draft_text_on_page"] = bool(
                    re.search("CAPA draft", page.evaluate("document.body.innerText"))
                )
                page.screenshot(path=str(OUT / f"B5-capa-need-evidence-{tag}.png"))
                close_artifacts(page, phone)
                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=1))  # noqa: T201


if __name__ == "__main__":
    main(sys.argv[1])
