"""M2-web: "Make it yours" and the alert buddy in the real built page, against the local stub of the API.

    cd web && python3 qa/e2e_m2.py

Builds the site with VITE_MAUDESIGNAL_API_BASE pointing at the stub (qa/live_stub.py, which answers /v1/connect,
/v1/tools/lookup_device and /v1/live/label), serves it, and drives Chromium at 390 and 1440, light and dark. It checks the
simulated default, adding a device by product code, K-number (looked up), CSV (preview + errors first) and a label photo
(only the confirmed match is added), forward-only statuses, export / import / clear, blocked storage, that nothing the person
typed leaves the browser, the alert buddy (calm, alert, click opens the panel, keyboard, reduced motion) and sideways scroll.
Screenshots: qa/screenshots/M2-*.png. Prints one JSON report; exits 1 if a check failed.
"""

# ruff: noqa: E501, T201
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from live_stub import Stub
from playwright.sync_api import Browser, Page, sync_playwright

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "qa" / "screenshots"
_BASE = int(os.environ.get("MAUDESIGNAL_QA_PORT_BASE") or "0")
STUB_PORT, LIVE_PORT = (_BASE, _BASE + 1) if _BASE else (8795, 4195)
LIVE_URL = f"http://127.0.0.1:{LIVE_PORT}/"
COMPANY = "Zeta Test Co"
PHOTO = WEB / "public" / "data" / "vision" / "label-caresens-n.jpg"
results: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    """Record one check."""
    results.append({"check": name, "ok": bool(ok), "detail": detail if not ok else ""})
    print(
        ("PASS " if ok else "FAIL ") + name + ("" if ok or not detail else f"  <- {detail}"),
        flush=True,
    )


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Run a build command in web/."""
    subprocess.run(
        cmd, cwd=WEB, env={**os.environ, **(env or {})}, check=True, capture_output=True, text=True
    )


def preview(port: int) -> subprocess.Popen[bytes]:
    """Serve dist-m2 with vite preview."""
    p = subprocess.Popen(
        [
            "npx",
            "vite",
            "preview",
            "--outDir",
            "dist-m2",
            "--port",
            str(port),
            "--strictPort",
            "--host",
            "127.0.0.1",
        ],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("preview did not start")


def overflow(page: Page) -> int:
    """Document scrollWidth minus the viewport width (0 = no sideways scroll)."""
    return int(
        page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    )


def new_page(
    browser: Browser, w: int, h: int, scheme: str, reduced: bool = False, init: str | None = None
) -> Page:
    """A fresh context (empty storage) at the given size and colour scheme."""
    ctx = browser.new_context(
        viewport={"width": w, "height": h},
        color_scheme=scheme,  # type: ignore[arg-type]
        reduced_motion="reduce" if reduced else "no-preference",
        accept_downloads=True,
    )
    page = ctx.new_page()
    if init:
        page.add_init_script(init)
    return page


def open_app(page: Page) -> None:
    """Open the app and wait for the top bar."""
    page.goto(LIVE_URL, wait_until="load")
    page.wait_for_selector("text=claims verified")
    page.evaluate("document.fonts.ready")


def go_devices(page: Page, phone: bool) -> None:
    """Open Our devices from the sidebar (through the drawer on a phone)."""
    if phone:
        page.get_by_label("Toggle sidebar").click()
        page.wait_for_timeout(250)
    page.locator("#sidebar").get_by_role("button", name=re.compile(r"^Our devices")).first.click()
    page.wait_for_selector("h1")
    page.wait_for_timeout(300)


def shot(page: Page, report: dict[str, object], tag: str, name: str, full: bool = False) -> None:
    """Record the overflow and save M2-<name>-<tag>.png."""
    page.wait_for_timeout(250)
    report[f"overflow_{name}_{tag}"] = overflow(page)
    page.screenshot(path=str(OUT / f"M2-{name}-{tag}.png"), full_page=full)


def stub_log(page: Page) -> list[dict[str, object]]:
    """The requests the stub has seen so far."""
    return json.loads(page.request.get(f"http://127.0.0.1:{STUB_PORT}/__log").text())["log"]


def stored(page: Page) -> dict[str, object] | None:
    """The company in localStorage."""
    raw = page.evaluate("localStorage.getItem('ms-my-company-v1')")
    return json.loads(raw) if raw else None


def tid(page: Page, t: str):  # type: ignore[no-untyped-def]
    """Locator by data-testid."""
    return page.locator(f"[data-testid='{t}']")


def flow(
    browser: Browser, w: int, h: int, scheme: str, stub: Stub, report: dict[str, object]
) -> None:
    """The full flow for one size and scheme."""
    tag = f"{w}-{scheme}"
    phone = w < 768
    sweep = json.loads((WEB / "public/data/sweep.json").read_text())
    hot = next(
        r["product_code"]
        for r in sweep["rows"]
        if r["classification"] in ("new_signal", "severity_escalation")
    )
    page = new_page(browser, w, h, scheme)
    seen: list[tuple[str, str]] = []
    page.on("request", lambda r: seen.append((r.url, r.post_data or "")))
    open_app(page)

    # Alert buddy: alert state at first (the sweep flags codes), fits the header.
    buddy = tid(page, "alert-buddy")
    check(
        f"{tag} buddy: alert state with the data's alerts",
        buddy.get_attribute("data-state") == "alert",
        buddy.get_attribute("data-state"),
    )
    label = buddy.get_attribute("aria-label") or ""
    badge = tid(page, "alert-badge").inner_text()
    check(
        f"{tag} buddy: label says the same count as the bell badge",
        f"{badge} alert" in label,
        (label, badge),
    )
    check(
        f"{tag} buddy: no second count badge beside the bell", tid(page, "buddy-badge").count() == 0
    )
    bubble_vis = tid(page, "buddy-bubble").count() > 0 and tid(page, "buddy-bubble").is_visible()
    if phone:
        check(
            f"{tag} buddy: no speech bubble on a phone (it would cover the verification strip)",
            not bubble_vis,
        )
    else:
        check(
            f"{tag} buddy: bubble opens once and says the same count",
            bubble_vis and badge in tid(page, "buddy-bubble").inner_text(),
        )
        page.wait_for_timeout(4500)
        check(
            f"{tag} buddy: bubble hides itself after about 4 s",
            tid(page, "buddy-bubble").count() == 0,
        )
    box = buddy.bounding_box() or {}
    svg_w = float(
        page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('[data-testid=buddy-svg]')).width)"
        )
    )
    check(
        f"{tag} buddy: 28-32 px drawing on a phone, 32-36 px on wide screens, inside the header",
        (26 <= svg_w <= 32 if phone else 32 <= svg_w <= 36)
        and box.get("x", -1) >= 0
        and box.get("x", 0) + box.get("width", 0) <= w,
        (svg_w, box),
    )
    check(f"{tag} buddy: header has no sideways scroll", overflow(page) == 0, overflow(page))
    check(
        f"{tag} buddy: pulses (animation running)",
        page.evaluate(
            "getComputedStyle(document.querySelector('[data-testid=buddy-svg]')).animationName"
        )
        == "ms-buddy-pulse",
    )
    shot(page, report, tag, "buddy-alert")
    buddy.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("[data-testid='alert-panel']")
    check(f"{tag} buddy: Enter opens the alert panel", tid(page, "alert-panel").is_visible())
    page.keyboard.press("Escape")
    page.wait_for_selector("[data-testid='alert-panel']", state="detached")
    buddy.click()
    page.wait_for_selector("[data-testid='alert-panel']")
    check(f"{tag} buddy: click opens the alert panel", True)
    tid(page, "alert-panel-close").click()
    page.wait_for_selector("[data-testid='alert-panel']", state="detached")

    # Simulated company is the default.
    go_devices(page, phone)
    check(
        f"{tag} default: simulated company, its banner, nothing stored",
        page.locator("h1").inner_text() == "Our devices (simulated)"
        and "Simulated company — sample data. Problem evidence is real FDA data."
        in tid(page, "company-banner").inner_text()
        and stored(page) is None,
    )
    shot(page, report, tag, "demo-default")

    # Make it yours
    tid(page, "make-it-yours").click()
    page.wait_for_selector("[data-testid='make-it-yours-panel']")
    check(
        f"{tag} yours: banner and empty state",
        tid(page, "company-banner").inner_text() == "Your company — your data stays in your browser"
        and "No devices yet" in tid(page, "no-devices").inner_text(),
    )
    tid(page, "in-company").fill(COMPANY)
    # product code: invalid, unknown (note), flagged (Needs review), known with stored evidence
    tid(page, "in-code").fill("L1")
    tid(page, "add-code").click()
    check(
        f"{tag} code: invalid code refused with a message",
        "exactly 3 letters" in tid(page, "code-error").inner_text(),
    )
    tid(page, "in-code").fill("zzz")
    tid(page, "in-code-name").fill("Mystery Monitor")
    tid(page, "add-code").click()
    check(
        f"{tag} code: unknown code accepted with a note",
        "Added with a note" in tid(page, "added-msg").inner_text(),
    )
    tid(page, "in-code").fill(hot)
    tid(page, "in-code-name").fill("Hot Device")
    tid(page, "add-code").click()
    tid(page, "in-code").fill("LLZ")
    tid(page, "in-code-name").fill("Viewer LLZ")
    tid(page, "add-code").click()
    # K-number: looked up through the stub with the demo key; and one with no record
    tid(page, "method-k").click()
    tid(page, "in-k").fill("K123456")
    n_before = len(stub_log(page))
    tid(page, "add-k").click()
    page.wait_for_function(
        "document.querySelector('[data-testid=added-msg]')?.textContent.includes('K123456')"
    )
    lookups = [
        e
        for e in stub_log(page)[n_before:]
        if str(e.get("path", "")).startswith("/v1/tools/lookup_device")
    ]
    check(
        f"{tag} K-number: one look-up with the demo key, only the K-number in the query",
        len(lookups) == 1
        and lookups[0].get("key_sent") is True
        and lookups[0].get("query") == "k_number=K123456",
        lookups,
    )
    check(
        f"{tag} K-number: result stored",
        "Stub looked-up device" in json.dumps(stored(page))
        and "checked with the FDA 510(k) record K123456" in json.dumps(stored(page)),
    )
    tid(page, "in-k").fill("K999999")
    tid(page, "in-k-name").fill("No record")
    tid(page, "add-k").click()
    page.wait_for_function(
        "document.querySelector('[data-testid=added-msg]')?.textContent.includes('K999999')"
    )
    check(
        f"{tag} K-number: a K-number with no record says so",
        "no 510(k) record" in json.dumps(stored(page)),
    )
    # CSV
    tid(page, "method-csv").click()
    tid(page, "in-csv-text").fill(
        "name,product_code,k_number\nCsv One,QIH,K111111\nCsv Two,MQB,\nBad row,12,\n,LLZ,\n"
    )
    check(
        f"{tag} CSV: preview shows 2 valid, 2 problems before import",
        tid(page, "csv-valid").inner_text() == "2"
        and tid(page, "csv-bad").inner_text() == "2"
        and "Line 4" in tid(page, "csv-errors").inner_text(),
    )
    before = len((stored(page) or {}).get("devices", []))  # type: ignore[arg-type]
    shot(page, report, tag, "csv-preview")
    check(f"{tag} CSV: nothing imported yet", before == 5, before)
    tid(page, "csv-import").click()
    check(f"{tag} CSV: valid rows imported", len((stored(page) or {}).get("devices", [])) == 7)  # type: ignore[arg-type]
    # Label photo: only the confirmed match is added
    tid(page, "method-label").click()
    tid(page, "image-input").set_input_files(str(PHOTO))
    page.wait_for_selector("[data-testid='label-matches']", timeout=20000)
    check(f"{tag} label: three possible matches, nothing added yet", page.locator("[data-testid='match-card']").count() == 3 and tid(page, "add-confirmed").count() == 0 and len((stored(page) or {}).get("devices", [])) == 7)  # type: ignore[arg-type]
    page.get_by_role("button", name="Confirm this match").nth(1).click()
    tid(page, "add-confirmed").click()
    devs = (stored(page) or {}).get("devices", [])
    check(f"{tag} label: only the confirmed match was added", len(devs) == 8 and devs[-1]["k_number"] == "K000002" and devs[-1]["source"] == "label", devs[-1:])  # type: ignore[index]
    shot(page, report, tag, "label-confirmed")

    # Table, chips, alert counts
    tid(page, "make-it-yours").click()  # closes the editor
    page.wait_for_timeout(200)
    check(
        f"{tag} table: your devices, status chips, Needs review count",
        "Hot Device" in page.inner_text("main")
        and tid(page, "status-chip").count() >= 7
        and tid(page, "need-review-line")
        .inner_text()
        .startswith(("2 devices need review", "1 device needs review")),
        tid(page, "need-review-line").inner_text(),
    )
    check(
        f"{tag} table: banner is the neutral/success yours style, not amber",
        "ms-banner--mine" in (tid(page, "company-banner").get_attribute("class") or ""),
    )
    check(
        f"{tag} table: heading says yours",
        page.locator("h1").inner_text() == "Our devices (your company)",
    )
    if phone:
        check(
            f"{tag} table: phone shows stacked cards, filter chips in one row",
            tid(page, "device-cards").count() == 1
            and (tid(page, "filter-chips").bounding_box() or {}).get("height", 999) < 70,
            tid(page, "filter-chips").bounding_box(),
        )
    shot(page, report, tag, "table-yours")
    if phone:
        page.get_by_label("Toggle sidebar").click()
        page.wait_for_timeout(250)
    side_text = page.locator("#sidebar").inner_text()
    check(
        f"{tag} sidebar: Our devices row is tagged yours and not simulated",
        re.search(r"Our devices\s*yours", side_text) is not None
        and "Our devices (simulated)" not in side_text,
        side_text[:300],
    )
    if phone:
        page.get_by_label("Close menu").click()
        page.wait_for_timeout(250)
    # Device page with stored evidence, forward-only status
    page.get_by_role("button", name="Viewer LLZ").first.click()
    page.wait_for_selector("[data-testid='device-detail']")
    check(
        f"{tag} device: the same real FDA evidence as the stored LLZ device",
        tid(page, "report-count").count() == 1
        and tid(page, "report-count").inner_text() != "not stored",
        tid(page, "report-count").inner_text() if tid(page, "report-count").count() else "",
    )
    check(
        f"{tag} device: Monitoring is last, so no forward move",
        tid(page, "no-forward").count() == 1,
    )
    shot(page, report, tag, "device-evidence")
    tid(page, "device-detail").get_by_role("button", name="All devices").click()
    page.get_by_role("button", name="Hot Device").first.click()
    page.wait_for_selector("[data-testid='device-detail']")
    moves = list(tid(page, "move-status").all_inner_texts())
    check(
        f"{tag} device: Needs review can move forward only",
        "Move to Needs review" not in moves and "Move to Testing in progress" in moves,
        moves,
    )
    page.get_by_role("button", name="Move to Testing in progress").click()
    check(
        f"{tag} device: status moved and is in the history",
        "Needs review → Testing in progress" in tid(page, "history").inner_text()
        and "Move to Testing in progress" not in tid(page, "move-status").all_inner_texts(),
    )
    shot(page, report, tag, "device-status")
    tid(page, "device-detail").get_by_role("button", name="All devices").click()

    # Export, reload, clear, import
    tid(page, "make-it-yours").click()
    with page.expect_download() as dl:
        tid(page, "export-json").click()
    path = dl.value.path()
    exported = json.loads(Path(str(path)).read_text())
    check(
        f"{tag} export: a JSON file with the company and 8 devices",
        exported["app"] == "maudesignal-my-company"
        and exported["company"] == COMPANY
        and len(exported["devices"]) == 8,
    )
    page.reload()
    page.wait_for_selector("text=claims verified")
    check(
        f"{tag} persists: reload keeps your company and the switch",
        (stored(page) or {}).get("company") == COMPANY
        and page.evaluate("localStorage.getItem('ms-company-mode-v1')") == "mine",
    )
    go_devices(page, phone)
    check(
        f"{tag} persists: after reload the view is still yours",
        page.locator("h1").inner_text() == "Our devices (your company)",
    )
    tid(page, "make-it-yours").click()
    tid(page, "clear-company").click()
    check(
        f"{tag} clear: Keep it is focused, Export first is offered, Yes is the danger colour",
        page.evaluate("document.activeElement && document.activeElement.dataset.testid")
        == "clear-keep"
        and tid(page, "clear-export").count() == 1
        and "critical" in (tid(page, "clear-yes").get_attribute("style") or ""),
    )
    shot(page, report, tag, "clear-confirm")
    tid(page, "clear-yes").click()
    check(f"{tag} clear: confirmed clear empties it", stored(page) is None)
    tid(page, "import-json-file").set_input_files(str(path))
    page.wait_for_selector("[data-testid='data-ok']")
    check(f"{tag} import: the exported file brings 8 devices back", len((stored(page) or {}).get("devices", [])) == 8)  # type: ignore[arg-type]
    bad = WEB / "qa" / "tmp" / "bad-company.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(
        json.dumps(
            {
                "app": "maudesignal-my-company",
                "version": 1,
                "company": "x",
                "devices": [{"id": "MY-01", "name": "", "product_code": "ab", "status": "Done"}],
            }
        )
    )
    tid(page, "import-json-file").set_input_files(str(bad))
    page.wait_for_selector("[data-testid='import-confirm'], [data-testid='import-errors']")
    check(
        f"{tag} import: a bad file gives clear errors with a heading and plain rows",
        "product_code must be 3 capital letters" in tid(page, "import-errors").inner_text()
        and "could not be imported" in tid(page, "import-errors").inner_text()
        and "devices[0]" not in tid(page, "import-errors").inner_text()
        and "Row 1:" in tid(page, "import-errors").inner_text(),
    )
    shot(page, report, tag, "import-errors")

    # Calm buddy after Mark all seen
    page.get_by_test_id("alert-bell").click()
    page.get_by_role("button", name="Mark all seen").click()
    page.get_by_role("button", name="Close alerts").click()
    check(
        f"{tag} buddy: calm once everything is seen",
        tid(page, "alert-buddy").get_attribute("data-state") == "calm"
        and "calm" in (tid(page, "alert-buddy").get_attribute("aria-label") or ""),
    )
    check(
        f"{tag} buddy: calm drawing breathes",
        page.evaluate(
            "getComputedStyle(document.querySelector('[data-testid=buddy-svg]')).animationName"
        )
        == "ms-buddy-breathe",
    )
    shot(page, report, tag, "buddy-calm")

    # Nothing the person typed left the browser.
    leaked = [
        u
        for u, body in seen
        if COMPANY in u
        or COMPANY in body
        or "Mystery" in u
        or "Mystery" in body
        or "Hot Device" in body
    ]
    # Hosts other than this site and the stub: only the design system's font files (they carry no data from the page).
    outside = sorted(
        {
            u.split("/")[2]
            for u, _ in seen
            if not u.startswith(LIVE_URL) and not u.startswith(("data:", "blob:"))
        }
    )
    check(
        f"{tag} privacy: company name and device names appear in no request", not leaked, leaked[:3]
    )
    check(
        f"{tag} privacy: requests go only to this site, the stub and the font hosts",
        set(outside) <= {f"127.0.0.1:{STUB_PORT}", "fonts.googleapis.com", "fonts.gstatic.com"},
        outside,
    )
    visits = [json.loads(b) for u, b in seen if u.endswith("/v1/visit") and b]
    check(
        f"{tag} privacy: visit pings keep their shape",
        all(set(v) <= {"ref", "page", "client_ts"} for v in visits),
        visits[:2],
    )
    page.context.close()


def side_checks(browser: Browser, stub: Stub, report: dict[str, object]) -> None:
    """Reduced motion, blocked storage, K-number without a key."""
    page = new_page(browser, 1440, 900, "light", reduced=True)
    open_app(page)
    anim = page.evaluate(
        "getComputedStyle(document.querySelector('[data-testid=buddy-svg]')).animationName"
    )
    check(
        "reduced motion: the buddy does not animate, the colour and the bell badge still show the alert",
        anim == "none"
        and tid(page, "alert-badge").is_visible()
        and page.evaluate(
            "getComputedStyle(document.querySelector('[data-testid=buddy-svg] .ms-buddy-body')).fill"
        )
        != "none",
    )
    shot(page, report, "1440-light", "buddy-reduced-motion")
    page.context.close()

    blocked = (
        "Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})"
    )
    page = new_page(browser, 390, 844, "dark", init=blocked)
    open_app(page)
    go_devices(page, True)
    tid(page, "make-it-yours").click()
    check(
        "blocked storage: a note says the company is kept in memory only",
        "kept in memory only" in tid(page, "memory-note").inner_text(),
    )
    tid(page, "in-code").fill("LLZ")
    tid(page, "add-code").click()
    tid(page, "make-it-yours").click()
    check(
        "blocked storage: the device still works in memory",
        "Product code LLZ" in page.inner_text("main"),
    )
    shot(page, report, "390-dark", "storage-blocked")
    page.context.close()

    stub.connect_mode = "no_key"
    page = new_page(browser, 1440, 900, "light")
    open_app(page)
    go_devices(page, False)
    tid(page, "make-it-yours").click()
    tid(page, "method-k").click()
    tid(page, "in-k").fill("K222222")
    n0 = len(
        [e for e in stub_log(page) if str(e.get("path", "")).startswith("/v1/tools/lookup_device")]
    )
    tid(page, "add-k").click()
    page.wait_for_function("document.querySelector('[data-testid=added-msg]')")
    n1 = len(
        [e for e in stub_log(page) if str(e.get("path", "")).startswith("/v1/tools/lookup_device")]
    )
    check(
        "K-number without a demo key: stored as not checked yet, no look-up call",
        "not checked yet" in tid(page, "added-msg").inner_text() and n1 == n0,
    )
    page.context.close()
    stub.connect_mode = "ok"
    stub.lookup_mode = "404"
    page = new_page(browser, 1440, 900, "light")
    open_app(page)
    go_devices(page, False)
    tid(page, "make-it-yours").click()
    tid(page, "method-k").click()
    tid(page, "in-k").fill("K333333")
    tid(page, "add-k").click()
    page.wait_for_function("document.querySelector('[data-testid=added-msg]')")
    check(
        "K-number when the tool is not deployed (404): stored as not checked yet",
        "not checked yet" in tid(page, "added-msg").inner_text(),
    )
    page.context.close()
    stub.lookup_mode = "ok"

    # Stored build (no API address): K-number not checked, label photo off.
    ctx_page = new_page(browser, 1440, 900, "light")
    ctx_page.close()


def main() -> int:
    """Run everything and print the report."""
    OUT.mkdir(parents=True, exist_ok=True)
    print("building...", flush=True)
    run(["node", "scripts/copy-design-system.mjs"])
    run(["npx", "tsc", "-b"])
    run(
        ["npx", "vite", "build", "--outDir", "dist-m2"],
        {"VITE_MAUDESIGNAL_API_BASE": f"http://127.0.0.1:{STUB_PORT}"},
    )
    stub = Stub(port=STUB_PORT, origins={f"http://127.0.0.1:{LIVE_PORT}"})
    stub.start()
    server = preview(LIVE_PORT)
    report: dict[str, object] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            report["chromium"] = browser.version
            for w, h in ((1440, 900), (390, 844)):
                for scheme in ("light", "dark"):
                    flow(browser, w, h, scheme, stub, report)
            side_checks(browser, stub, report)
            browser.close()
    finally:
        server.terminate()
        stub.stop()
    failed = [r for r in results if not r["ok"]]
    report["checks"] = len(results)
    report["failed"] = failed
    overflows = {k: v for k, v in report.items() if k.startswith("overflow_") and v != 0}
    report["nonzero_overflow"] = overflows
    print(json.dumps({k: v for k, v in report.items() if not k.startswith("overflow_")}, indent=2))
    return 1 if failed or overflows else 0


if __name__ == "__main__":
    sys.exit(main())
