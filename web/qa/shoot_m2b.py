"""M2b screenshots: the Connect page with copy-paste config snippets.

    cd web && npm run build && python3 qa/shoot_m2b.py

Serves ``dist/`` locally with the network blocked (so the page shows the fixed addresses and the key placeholder),
checks the snippets, the Copy buttons and sideways scroll, and writes ``qa/screenshots/M2b-connect-<width>-<theme>.png``.
Prints one JSON report; exits 1 if any check failed.
"""

# ruff: noqa: E501, T201
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright
from shoot_b1 import OUT, local_only, serve


def main() -> int:
    """Open the Connect page at 390 and 1440, light and dark, and check it."""
    OUT.mkdir(parents=True, exist_ok=True)
    srv, port = serve()
    report: dict[str, object] = {}
    failed: list[str] = []

    def check(name: str, ok: bool) -> None:
        report[name] = ok
        if not ok:
            failed.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for w, h in ((1440, 900), (390, 844)):
            for scheme in ("light", "dark"):
                ctx = browser.new_context(
                    viewport={"width": w, "height": h},
                    color_scheme=scheme,  # type: ignore[arg-type]
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
                page.wait_for_selector("text=claims verified")
                if w == 390:
                    page.get_by_test_id("more-menu-button").click()
                    page.get_by_test_id("more-connect").click()
                else:
                    page.get_by_test_id("connect-button").click()
                page.wait_for_selector("[data-testid=config-snippets]")
                page.evaluate("document.fonts.ready")
                tag = f"{w}-{scheme}"
                d = json.loads(page.get_by_test_id("code-claude-desktop").inner_text())
                c = json.loads(page.get_by_test_id("code-cursor").inner_text())
                muse = page.get_by_test_id("code-muse").inner_text()
                url = "https://maudesignal-api.vercel.app/mcp"
                check(
                    f"{tag}: claude desktop json has url and header",
                    url in d["mcpServers"]["maudesignal"]["args"]
                    and any(
                        a.startswith("X-API-Key:") for a in d["mcpServers"]["maudesignal"]["args"]
                    ),
                )
                check(
                    f"{tag}: cursor json has url and header",
                    c["mcpServers"]["maudesignal"]["url"] == url
                    and "X-API-Key" in c["mcpServers"]["maudesignal"]["headers"],
                )
                check(f"{tag}: muse has url and header", url in muse and "X-API-Key" in muse)
                page.get_by_test_id("copy-cursor-config").click()
                clip = page.evaluate("navigator.clipboard.readText()")
                check(
                    f"{tag}: copy puts the cursor snippet on the clipboard",
                    clip == page.get_by_test_id("code-cursor").inner_text(),
                )
                check(
                    f"{tag}: three prompts listed",
                    page.locator("[data-testid=example-questions] li").count() == 3,
                )
                check(
                    f"{tag}: status line",
                    "pending review." in page.get_by_test_id("connect-status").inner_text(),
                )
                over = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                report[f"{tag}: x_overflow_px"] = over
                check(f"{tag}: no sideways scroll", over == 0)
                # Strong check: no element inside the chat pane, and no <pre> anywhere, is wider than its box.
                wide = page.evaluate("""() => {
                        const bad = [];
                        const pane = document.querySelector('main[aria-label=Chat], main[aria-label=Home]');
                        const els = new Set([...(pane ? pane.querySelectorAll('*') : []), ...document.querySelectorAll('pre')]);
                        if (pane) els.add(pane);
                        els.forEach((e) => { if (e.classList.contains('sr-only')) return; /* 1px clipped screen-reader text, hidden on purpose */ if (e.scrollWidth > e.clientWidth + 1) bad.push(e.tagName + '.' + String(e.className).slice(0, 40) + ' ' + e.scrollWidth + '>' + e.clientWidth); });
                        return { n: els.size, bad };
                    }""")
                report[f"{tag}: elements_checked"] = wide["n"]
                report[f"{tag}: wide_elements"] = wide["bad"]
                check(
                    f"{tag}: no element in the chat pane or pre has scrollWidth > clientWidth + 1",
                    not wide["bad"] and wide["n"] > 10,
                )
                # The Connect view scrolls inside the chat pane, so scroll each section into view and shoot it.
                for sec in (
                    "connect-status",
                    "connect-steps",
                    "demo-key-block",
                    "snippet-claude-desktop",
                    "snippet-cursor",
                    "snippet-muse",
                    "example-questions",
                    "link-privacy",
                ):
                    page.get_by_test_id(sec).scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT / f"M2b-connect-{tag}-{sec}.png"))
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
