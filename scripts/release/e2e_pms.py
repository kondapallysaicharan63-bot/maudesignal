"""Real-browser run of the 2026-11-03 P0 path (Playwright, Python, Chromium, local only).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

Serves ``web/dist`` (and ``web/dist-live`` for the forced-failure test) on 127.0.0.1 and clicks through:
every product page loads; complaint investigation -> evidence pack -> accept -> audit row ->
Note to File export (Markdown + PDF + CSV + audit) -> Board status change -> chain re-verified;
a tampered copy of the audit trail breaks at that entry; a forced 504 / 500 / cap shows the
recorded answer + four no-model lookups + Retry; button target sizes. Expected values are
computed from ``data/demo/maudesignal_demo.db`` and ``web/public/data/*.json``, never typed in.

    python scripts/release/e2e_pms.py --out-dir release-out/2026-11-03

Exit 0 only when every check passed. A check that cannot run is reported SKIPPED with why.
"""

# ruff: noqa: E501, D102, D103, D101, D107, B023
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"
CHROMIUM = "/opt/pw-browsers/chromium"

PAGES = [
    ("Home", "/"),
    ("Signals", "/signals/ranked"),
    ("Copilot", "/chat"),
    ("Vision", "/workflow/vision"),
    ("Audit", "/evidence/audit"),
    ("Board", "/board"),
    ("Validation", "/validation"),
    ("Investigate", "/investigate"),
    ("PMS workflow", "/pms-workflow"),
    ("ROI", "/roi"),
]


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files with a single-page-app fallback (what vercel.json rewrites do)."""

    def log_message(self, *a: Any) -> None:  # silence
        return

    def send_head(self) -> Any:
        if self.path.startswith("/_vercel/"):  # Vercel injects these; locally they do not exist
            self.send_error(404)
            return None
        path = self.translate_path(self.path.split("?", 1)[0])
        if not Path(path).exists() or Path(path).is_dir() and not Path(path, "index.html").exists():
            self.path = "/index.html"
        return super().send_head()


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    h = functools.partial(Handler, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Run:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))

    def skip(self, name: str, why: str) -> None:
        self.results.append({"name": name, "status": "SKIPPED", "detail": why})
        print(f"SKIP {name} — {why}")


def expected() -> dict[str, Any]:
    alerts = json.loads((DATA / "alerts.json").read_text("utf-8"))["alerts"]
    real = [a for a in alerts if a["source"]["kind"] != "company" and a["rule"]]
    codes: list[str] = []
    for a in real:
        if a["product_code"] not in codes:
            codes.append(a["product_code"])
    mix = next(a for a in real if a["rule"] == "report mix changed")
    con = sqlite3.connect(f"file:{ROOT / 'data/demo/maudesignal_demo.db'}?mode=ro", uri=True)
    n, lo, hi = con.execute(
        "select count(*), min(date_received), max(date_received) from raw_reports"
    ).fetchone()
    con.close()
    manifest = json.loads((DATA / "manifest.json").read_text("utf-8"))
    return {
        "flagged": codes,
        "mix": mix,
        "db": {"n": n, "lo": lo, "hi": hi},
        "manifest": manifest,
        "invest": json.loads(
            (ROOT / "web/src/fixtures/investigateExample.json").read_text("utf-8")
        ),
    }


def human_wait(page: Page, ms: int = 250) -> None:
    page.wait_for_timeout(ms)


def run(out: Path, shots: Path) -> int:
    exp = expected()
    r = Run()
    shots.mkdir(parents=True, exist_ok=True)
    m0 = exp["manifest"]["data_as_of"]
    latest_stored = max(x for x in [m0["stored"]["latest"], m0["sweep"]["week_end"]] if x)
    srv, base = serve(ROOT / "web" / "dist")
    srv2, base_live = serve(ROOT / "web" / "dist-live")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on(
            "console",
            lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None,
        )

        # ---- D1: every product page loads
        for name, path in PAGES:
            errors.clear()
            page.goto(base + path, wait_until="networkidle")
            human_wait(page, 300)
            h1 = page.locator("h1:visible").first
            ok = h1.count() > 0 and len(h1.inner_text().strip()) > 0
            r.check(
                f"D page loads: {name} ({path})",
                ok and not [e for e in errors if "pageerror" in e],
                "; ".join(errors)[:200],
            )
            blocking = [e for e in errors if "pageerror" in e]
            if blocking:
                r.check(f"D no blocking JS error on {name}", False, "; ".join(blocking)[:200])
            if name in {"Home", "Board", "Validation", "Investigate"}:
                page.screenshot(path=str(shots / f"{name.lower()}.png"))

        # ---- A1/A2: Home order + pitch + links
        page.goto(base + "/", wait_until="networkidle")
        order = page.evaluate(
            "() => ['home-investigate','home-board','home-alerts','home-sweep'].map(id => { const e=document.querySelector(`[data-testid=${id}]`); return e? e.getBoundingClientRect().top + window.scrollY : null })"
        )
        r.check(
            "A Home order: complaint < board < weekly sweep",
            all(x is not None for x in order) and order[0] < order[1] < order[2],
            str(order),
        )
        pitch = page.locator("[data-testid=home-pitch]").inner_text()
        r.check(
            "A pitch is the reviewer wording",
            pitch.startswith("Companies know their competitors. What they cannot see is:")
            and "never reached their complaint team" in pitch,
        )
        body = page.inner_text("body")
        r.check(
            "A no 'pharmacovigilance' / old label on Home",
            "pharmacovigilance" not in body.lower()
            and ("more serious " + "than usual") not in body.lower(),
        )
        r.check(
            "A Home links to /pms-workflow and /validation",
            page.locator("[data-testid=home-hero-pms]").count() == 1
            and page.locator("[data-testid=trust-validation-link]").count() == 1,
        )
        r.check(
            "A footer links to Validation",
            page.locator("[data-testid=footer-validation]").count() == 1,
        )
        count = int(page.locator("[data-testid=home-board-count]").inner_text())
        r.check(
            "A Home board count = flagged real codes from alerts.json",
            count == len(exp["flagged"]),
            f"{count} vs {len(exp['flagged'])}",
        )

        # ---- H: data-as-of banner values match the stored data
        m = exp["manifest"]["data_as_of"]
        page.goto(base + "/signals/ranked", wait_until="networkidle")
        banner = page.locator("[data-testid=signals-asof]").inner_text()
        latest = max(x for x in [m["stored"]["latest"], m["sweep"]["week_end"]] if x)
        r.check(
            "H Signals banner: 'Data as of' = later of DB newest report and sweep week end",
            f"Data as of: {latest}." in banner,
            banner[:160],
        )
        r.check("H banner has the reporting-delay sentence", "not because risk is zero" in banner)
        db_hi = exp["db"]["hi"]
        r.check(
            "H banner stored window equals the demo DB",
            f"{db_hi[:4]}-{db_hi[4:6]}-{db_hi[6:]}" in banner and str(exp["db"]["n"]) in banner,
            f"db {exp['db']}",
        )
        page.goto(base + "/signals/alerts", wait_until="networkidle")
        r.check(
            "H sweep banner on All alerts", page.locator("[data-testid=sweep-asof]").count() == 1
        )
        sweep = json.loads((DATA / "sweep.json").read_text("utf-8"))["meta"]
        r.check(
            "H sweep banner date = sweep file week end",
            sweep["window"]["current_end"] in page.locator("[data-testid=sweep-asof]").inner_text(),
        )

        # ---- P0 path: Investigate (recorded example) -> pack -> accept -> audit -> note -> exports -> board
        page.goto(base + "/investigate", wait_until="networkidle")
        sections = page.eval_on_selector_all(
            "[data-testid=inv-results] > section",
            "els => els.map(e => e.getAttribute('data-testid'))",
        )
        r.check(
            "A Investigate: non-manufacturer section is first",
            sections[:1] == ["inv-sources"],
            str(sections),
        )
        ihead = page.locator("#inv-sources h2").inner_text()
        r.check(
            "A section title is the reviewer wording",
            ihead == "Reports NOT filed by a manufacturer — check these against your complaint log",
            ihead,
        )
        r.check(
            "H Investigate banner present",
            "Data as of:" in page.locator("[data-testid=inv-asof]").inner_text(),
        )
        r.check(
            "A Investigate links /pms-workflow",
            page.locator("[data-testid=inv-pms-link]").count() == 1,
        )
        inv = exp["invest"]["answer"]
        n_total = inv["total_code_wide"]["value"]
        r.check(
            "D Investigate total equals the stored example",
            page.locator("[data-testid=inv-total-code]")
            .inner_text()
            .replace(",", "")
            .find(str(n_total))
            >= 0,
            str(n_total),
        )

        page.locator("[data-testid=pack-reviewer]").fill("Ana Ruiz")
        page.locator("[data-testid=pack-reason]").fill("Complete for this complaint")
        page.locator("[data-testid=pack-accept]").click()
        human_wait(page)
        decided = page.locator("[data-testid=pack-decided]").inner_text()
        r.check(
            "D accept -> 'Evidence accepted by Ana Ruiz · audit entry #1'",
            "Evidence accepted by Ana Ruiz" in decided and "#1" in decided,
            decided,
        )
        page.locator("[data-testid=note-rationale]").fill("No new failure mode; file a note.")
        page.locator("[data-testid=note-approver]").fill("Ana Ruiz")
        page.locator("[data-testid=note-decision-capa]").check()
        page.locator("[data-testid=note-record]").click()
        page.wait_for_selector("[data-testid=note-export]")
        r.check(
            "D Note to File export opens with the label",
            "Draft note to file for your QMS; not filed with FDA."
            in page.locator("[data-testid=note-preview]").inner_text(),
        )
        preview = page.locator("[data-testid=note-preview]").inner_text()
        for must in [
            "Decision: Open a CAPA (in your QMS)",
            "Approver: Ana Ruiz",
            "Company complaint / CAPA number: ____________________",
            "Build: MaudeSignal 0.1.0 · commit ",
            "Data as of:",
            "Does this meet your recall procedure?",
        ]:
            r.check(f"D note contains: {must[:48]}", must in preview)
        r.check(
            "D note has no tool-made decision sentence",
            not re.search(
                r"recall (is )?(needed|required)|is reportable|must be reported|capa is (required|needed)",
                preview,
                re.I,
            ),
        )
        got: dict[str, bytes] = {}
        buttons = page.locator("[data-testid=note-export] button")
        for i in range(buttons.count()):
            with page.expect_download() as dl:
                buttons.nth(i).click()
            d = dl.value
            got[d.suggested_filename] = Path(d.path()).read_bytes()
        names = sorted(got)
        r.check(
            "D four exports downloaded (md, pdf, csv, audit json)",
            len(names) == 4
            and {n.rsplit(".", 1)[1] for n in names} == {"md", "pdf", "csv", "json"},
            str(names),
        )
        pdf = next((v for k, v in got.items() if k.endswith(".pdf")), b"")
        r.check(
            "D PDF is a PDF and prints the approver",
            pdf.startswith(b"%PDF-1.4") and b"Approver: Ana Ruiz" in pdf,
        )
        csv_text = next((v.decode() for k, v in got.items() if k.endswith(".csv")), "")
        r.check(
            "D CSV prints version, commit, data-as-of and a blank CAPA number field",
            all(
                s in csv_text
                for s in [
                    "# Build: MaudeSignal 0.1.0 · commit ",
                    "# Data as of:",
                    "# Company complaint / CAPA number: ____________________",
                ]
            ),
        )
        audit_json = json.loads(next((v for k, v in got.items() if k.endswith(".json")), b"{}"))
        actions = [e["action"] for e in audit_json.get("entries", [])]
        r.check(
            "J export audit lists pack_accept then note_to_file",
            actions == ["pack_accept", "note_to_file"],
            str(actions),
        )
        r.check(
            "D audit export has build + blank company number",
            audit_json.get("build", {}).get("version") == "0.1.0"
            and audit_json.get("company_complaint_or_capa_number") == "",
        )
        md_text = next((v.decode() for k, v in got.items() if k.endswith(".md")), "")
        e_note = next(e for e in audit_json["entries"] if e["action"] == "note_to_file")
        r.check(
            "D note decision + approver match the audit row",
            json.loads(e_note["payload_json"])["decision"] == "capa"
            and e_note["actor"] == "Ana Ruiz"
            and "Approver: Ana Ruiz" in md_text
            and f"audit entry #{e_note['seq']}" in md_text,
        )
        page.screenshot(path=str(shots / "note-export.png"), full_page=True)

        # ---- Board status change
        flagged = exp["flagged"]
        code = exp["mix"]["product_code"]
        page.goto(base + "/board", wait_until="networkidle")
        rows = page.locator("[data-testid=board-row]")
        r.check(
            "D Board rows = flagged real codes from alerts.json (exact set)",
            sorted(rows.evaluate_all("els => els.map(e => e.dataset.code)")) == sorted(flagged),
            str(flagged),
        )
        r.check(
            "D Board says 'This is not a QMS'",
            "This is not a QMS" in page.locator("[data-testid=board-not-qms]").inner_text(),
        )
        r.check(
            "D Board header columns",
            page.eval_on_selector_all(
                "[data-testid=board-table] thead th", "els => els.map(e => e.innerText.trim())"
            )[:6]
            == [
                "Flagged code",
                "Why flagged",
                "Status",
                "Owner",
                "Due date (MDR clock, advisory)",
                "Decision / audit",
            ],
        )
        r.check(
            "A Board 'why flagged' for the mix code uses the new sentence",
            exp["mix"]["mix_sentence"]
            in page.locator(f"[data-testid=board-row][data-code={code}]").inner_text(),
        )
        r.check(
            "J earlier audit rows are listed on the Board page",
            page.locator("[data-testid=local-audit-row]").count() == 2,
        )
        page.locator(f"[data-testid=board-open-{code}]").click()
        page.locator(f"[data-testid=board-submit-{code}]").click()
        r.check(
            "D status change without a name is refused",
            "named person" in page.locator(f"[data-testid=board-error-{code}]").inner_text(),
        )
        page.locator(f"[data-testid=board-actor-{code}]").fill("Ana Ruiz")
        page.locator(f"[data-testid=board-owner-{code}]").fill("Ben Okafor")
        page.locator(f"[data-testid=board-aware-{code}]").fill("2026-11-03")
        page.locator(f"[data-testid=board-submit-{code}]").click()
        human_wait(page, 400)
        r.check(
            "D Board: New -> Under review",
            page.locator(f"[data-testid=board-status-{code}]").inner_text() == "Under review",
        )
        due = page.locator(f"[data-testid=board-row][data-code={code}]").inner_text()
        r.check(
            "D Board: owner + advisory due date 2026-12-03 (30 days, 21 CFR 803.50)",
            "Ben Okafor" in due and "2026-12-03" in due and "803.50" in due,
            due[:200],
        )
        r.check(
            "J Board change is in the audit table with name",
            page.locator("[data-testid=local-audit-row][data-action=board_status]").count() == 1
            and "Ana Ruiz"
            in page.locator("[data-testid=local-audit-row][data-action=board_status]").inner_text(),
        )
        r.check(
            "J chain re-verifies on display (3 entries)",
            "Chain verified: 3 entries"
            in page.locator("[data-testid=local-audit-status]").inner_text(),
        )
        page.reload(wait_until="networkidle")
        r.check(
            "D status persists after reload",
            page.locator(f"[data-testid=board-status-{code}]").inner_text() == "Under review",
        )
        page.locator(f"[data-testid=board-open-{code}]").click()
        page.locator(f"[data-testid=board-to-{code}]").select_option("note_to_file")
        page.locator(f"[data-testid=board-actor-{code}]").fill("Ana Ruiz")
        page.locator(f"[data-testid=board-submit-{code}]").click()
        human_wait(page, 400)
        r.check(
            "D Board: Under review -> Note to file",
            page.locator(f"[data-testid=board-status-{code}]").inner_text() == "Note to file",
        )
        page.screenshot(path=str(shots / "board-after.png"), full_page=True)

        # ---- J tamper test, on a copy in a separate context
        stored = page.evaluate("() => window.localStorage.getItem('ms-pms-audit-v1')")
        entries = json.loads(stored)
        ctx2 = browser.new_context(viewport={"width": 1440, "height": 900})
        p2 = ctx2.new_page()
        tampered = [dict(e) for e in entries]
        tampered[1]["actor"] = "Someone Else"
        p2.add_init_script(
            "window.localStorage.setItem('ms-pms-audit-v1', "
            + json.dumps(json.dumps(tampered))
            + ")"
        )
        p2.goto(base + "/board", wait_until="networkidle")
        human_wait(p2, 400)
        status = p2.locator("[data-testid=local-audit-status]").inner_text()
        r.check(
            "J tampered copy: chain breaks at entry #2 and is shown",
            "Chain broken at entry #2" in status,
            status,
        )
        ctx2.close()

        # ---- Validation page
        page.goto(base + "/validation", wait_until="networkidle")
        human_wait(page, 400)
        vt = page.inner_text("[data-testid=validation-page]")
        r.check("D Validation: says not validated", "This build is not validated" in vt)
        r.check(
            "D Validation: never says FDA validated / approved / AI validated",
            not re.search(r"FDA validated|FDA approved|AI validated", vt),
        )
        life = json.loads((DATA / "lifecycle.json").read_text("utf-8"))
        r.check(
            "D Validation lifecycle lists every Skill version from lifecycle.json",
            all(
                f"{k} {v}" in page.inner_text("[data-testid=validation-skills]")
                for k, v in life["skills"].items()
            ),
        )
        r.check(
            "D Validation shows the sweep date from the sweep file",
            sweep["generated_utc"][:10] in page.inner_text("[data-testid=validation-sweep]"),
        )
        r.check(
            "D Validation not hidden behind sweep/profile (sidebar entry)",
            page.locator("[data-testid=sidebar-v2]").get_by_text("Validation").count() >= 1,
        )

        # ---- M: target sizes and keyboard on P0 controls
        small: list[str] = []
        for path in ["/board", "/validation", "/investigate"]:
            page.goto(base + path, wait_until="networkidle")
            if path == "/board":
                page.locator(f"[data-testid=board-open-{code}]").click()
            sizes = page.evaluate(
                "() => [...document.querySelectorAll('main button, main select, main input:not([type=hidden]), main textarea, main a.ms-btn')].filter(e => e.offsetParent !== null && !e.closest('details:not([open])')).map(e => { const b=e.getBoundingClientRect(); return [e.tagName, (e.getAttribute('data-testid')||e.textContent||'').trim().slice(0,30), Math.round(b.height*10)/10, e.type||''] })"
            )
            small += [
                f"{path} {s[0]} {s[1]} h={s[2]}"
                for s in sizes
                if s[2] < 43.9 and s[3] != "radio" and s[3] != "checkbox"
            ]
        r.check(
            "M no P0 control below 44px on Board / Validation / Investigate",
            not small,
            "; ".join(small[:6]),
        )
        page.goto(base + "/board", wait_until="networkidle")
        page.keyboard.press("Tab")
        reached = {
            page.evaluate(
                "document.activeElement && (document.activeElement.getAttribute('data-testid')||document.activeElement.tagName)"
            )
        }
        for _ in range(40):
            page.keyboard.press("Tab")
            reached.add(
                page.evaluate(
                    "document.activeElement && (document.activeElement.getAttribute('data-testid')||document.activeElement.tagName)"
                )
            )
        r.check(
            "M Board controls reachable by keyboard (Review button)",
            f"board-open-{code}" in reached
            or any(str(x).startswith("board-open-") for x in reached),
        )
        r.skip(
            "M themes / AA contrast for all six themes",
            "not run in this pass; existing contrast scripts (web/qa/contrast_*.py) not re-run against the new pages",
        )

        # ---- H: banner over a recorded Copilot answer (thread page)
        threads = json.loads((DATA / "threads.json").read_text("utf-8"))["threads"]
        t0 = next(t for t in threads if t["id"] == "01-what-changed")
        page.goto(base + "/thread/01-what-changed", wait_until="networkidle")
        human_wait(page, 500)
        tb = page.locator("[data-testid=thread-asof]").inner_text()
        r.check(
            "H recorded answer: banner shows the data date and the recording date",
            f"Data as of: {latest}." in tb
            and f"recorded answer of {t0['recorded_at_utc'][:10]}" in tb,
            tb[:160],
        )

        # ---- F: forced live failures (separate bundle with an API address; routes mocked)
        for kind, status, body in [
            (
                "timeout",
                504,
                {
                    "code": "live_timeout",
                    "message": "x",
                    "error": {"code": "live_timeout", "message": "x"},
                },
            ),
            ("failure", 500, {"code": "server", "message": "boom"}),
            ("cap", 429, {"code": "rate_limited", "message": "limit"}),
        ]:
            c3 = browser.new_context(viewport={"width": 1440, "height": 900})
            p3 = c3.new_page()
            calls: list[str] = []

            def make(status: int, body: dict[str, Any], calls: list[str] = calls) -> Any:
                def handle(route: Any) -> None:
                    calls.append(route.request.url)
                    route.fulfill(
                        status=status, content_type="application/json", body=json.dumps(body)
                    )

                return handle

            handle = make(status, body)

            p3.route("**/v1/live/ask", handle)  # noqa: B023
            p3.route(
                "**/v1/**",
                lambda route: (
                    route.fulfill(status=204, body="")
                    if "live/ask" not in route.request.url
                    else route.fallback()
                ),
            )
            p3.goto(base_live + "/chat", wait_until="networkidle")
            q = f"What changed for {exp['mix']['product_code']} this week?"
            p3.locator("textarea").first.fill(q)
            p3.keyboard.press("Enter")
            try:
                p3.wait_for_selector("[data-testid=fallback]", timeout=8000)
            except Exception:
                r.check(f"F {kind}: fallback screen appears", False, "no fallback panel")
                c3.close()
                continue
            asof = (
                p3.locator("[data-testid=chat-asof]").inner_text()
                if p3.locator("[data-testid=chat-asof]").count()
                else ""
            )
            r.check(
                f"H {kind}: banner over the Copilot answer = stored dates",
                f"Data as of: {latest_stored}." in asof and "not because risk is zero" in asof,
                asof[:120],
            )
            fb = p3.locator("[data-testid=fallback]")
            r.check(
                f"F {kind}: panel kind",
                fb.get_attribute("data-kind") == ("cap" if kind == "cap" else kind),
                str(fb.get_attribute("data-kind")),
            )
            modes = p3.eval_on_selector_all(
                "[data-testid=live-answer]", "els => els.map(e => e.getAttribute('data-mode'))"
            )
            r.check(
                f"F {kind}: no live answer was invented (any answer shown is mode=recorded)",
                all(x == "recorded" for x in modes),
                str(modes),
            )
            r.check(
                f"F {kind}: four lookups + retry present",
                all(
                    p3.locator(f"[data-testid=fallback-{i}]").count() == 1
                    for i in ["live", "reports", "recalls", "summary", "retry"]
                ),
            )
            r.check(
                f"F {kind}: cost shown",
                "$0.25" in p3.locator("[data-testid=fallback-cost]").inner_text() or kind == "cap",
            )
            (
                p3.select_option("[data-testid=fallback-code]", exp["mix"]["product_code"])
                if p3.locator("[data-testid=fallback-code]").count()
                else None
            )
            n_before = len(calls)
            p3.locator("[data-testid=fallback-recalls]").click()
            rt = p3.locator("[data-testid=fallback-out-recalls]").inner_text()
            r.check(
                f"F {kind}: Show recalls returns the stored total ({exp['mix']['recalls_total']})",
                str(exp["mix"]["recalls_total"]) in rt,
                rt[:80],
            )
            p3.locator("[data-testid=fallback-summary]").click()
            r.check(
                f"F {kind}: Show product summary returns stored data",
                "stored reports" in p3.locator("[data-testid=fallback-out-summary]").inner_text(),
            )
            ev = json.loads((DATA / "evidence.json").read_text("utf-8"))["reports"]
            llz = [v for v in ev.values() if v["product_code"] == "LLZ"]
            p3.select_option("[data-testid=fallback-code]", "LLZ")
            p3.locator("[data-testid=fallback-reports]").click()
            matched = sum(1 for v in llz if "changed" in v["excerpt"].lower())
            rep = p3.locator("[data-testid=fallback-out-reports]").inner_text()
            r.check(
                f"F {kind}: Search stored reports counts match evidence.json ({matched} of {len(llz)} for LLZ)",
                re.search(
                    rf"\b{matched} of {len(llz)} stored reports for LLZ", rep.replace("\n", " ")
                )
                is not None,
                rep[:120],
            )
            r.check(
                f"F {kind}: lookups made no model call",
                len(calls) == n_before,
                f"{n_before} -> {len(calls)}",
            )
            if kind != "cap":
                p3.locator("[data-testid=fallback-retry]").click()
                human_wait(p3, 600)
                r.check(
                    f"F {kind}: Retry live re-asks",
                    len(calls) == n_before + 1,
                    f"calls {len(calls)}",
                )
            else:
                r.check(
                    "F cap: Retry is disabled while the cap is reached",
                    p3.locator("[data-testid=fallback-retry]").is_disabled(),
                )
            log = json.loads(
                p3.evaluate("() => window.localStorage.getItem('ms-pms-audit-v1')") or "[]"
            )
            acts = [e["action"] for e in log]
            r.check(
                f"F {kind}: failure + fallback choices are in the audit",
                acts[:1] == ["live_failure"] and acts.count("fallback_choice") >= 3,
                str(acts),
            )
            if kind == "timeout":
                p3.screenshot(path=str(shots / "fallback-timeout.png"), full_page=True)
            c3.close()

        browser.close()
    srv.shutdown()
    srv2.shutdown()
    out.mkdir(parents=True, exist_ok=True)
    (out / "e2e-pms.json").write_text(json.dumps(r.results, indent=2), "utf-8")
    fails = [x for x in r.results if x["status"] == "FAIL"]
    lines = [
        "# P0 browser run (Chromium, local)",
        "",
        f"{sum(x['status'] == 'PASS' for x in r.results)} passed, {len(fails)} failed, {sum(x['status'] == 'SKIPPED' for x in r.results)} skipped",
        "",
    ]
    lines += [
        f"- {x['status']} {x['name']}"
        + (f" — {x['detail']}" if x["status"] != "PASS" and x["detail"] else "")
        for x in r.results
    ]
    (out / "e2e-pms.md").write_text("\n".join(lines) + "\n", "utf-8")
    print(lines[2])
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", type=Path, default=ROOT / "release-out" / "2026-11-03")
    a = ap.parse_args()
    return run(a.out_dir, a.out_dir / "shots")


if __name__ == "__main__":
    raise SystemExit(main())
