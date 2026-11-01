"""Live check of the typed ask on the deployed API and web app (a few cents of Meta credit).

HACKATHON-BUILT - Meta Global AI Developer Hackathon (Oct 26 - Nov 4, 2026).

Why: on Nov 1 two long, multi-tool questions showed "The live service could not be reached" on
the live site. This script asks those two questions (and a third) the way a visitor does, then
runs one browser question, and prints what happened: HTTP status, latency, mode and tier,
model, trace steps, tool calls, and the answer text. It never prints a key.

Spend: one shared ``Budget`` (``budget.py``, the same class ``smoke.py`` uses) limited to
``--max-usd`` (default $0.40, every call held at the deployed API's $0.25 per-request cap until
its real ``cost_usd`` is known; a call with no usable reply is settled at the full hold). A call
that does not fit is reported as ``skipped: budget``, never sent.

Run:
    MAUDESIGNAL_ADMIN_KEY_SMOKE=... python scripts/release/live_check.py \
        --api https://maudesignal-api.vercel.app --web https://maudesignal-app.vercel.app \
        --out-dir live-check-out

``/v1/live/ask`` needs no key. ``MAUDESIGNAL_ADMIN_KEY_SMOKE`` (optional) is used only to delete
the TEST entries the browser pass writes, exactly as ``smoke.py`` does.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from budget import HOLD_USD, SKIPPED_BUDGET, Budget  # noqa: E402
from leaks import find_key_shapes  # noqa: E402
from netutil import request  # noqa: E402

QUESTIONS = (
    "For LLZ, compare reports from Aug 25 to Aug 31, 2026 with the 4 weeks before, "
    "and what kinds of problems were reported?",
    "What problems were reported for LLZ devices in August 2026?",
    "Why did reports for LLZ jump in the last week of August?",
)
BROWSER_QUESTION = "What problems were reported for LLZ devices in August 2026?"
CHIP_TEXT = "Muse Spark 1.3 · Live"
TEST_REF = "TEST-9"  # matches /v1/admin/delete-test (TEST[0-9._~-]*)
ASK_TIMEOUT_S = 75.0
COMPOSER = "textarea[aria-label='Ask a question']"
TOOL_CALLS = re.compile(r"(\d+) tool call")


def cost_of(body: dict[str, Any]) -> float | None:
    """A non-negative numeric ``cost_usd``, else None (then the full hold counts as spent)."""
    c = body.get("cost_usd")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or c != c or c < 0:
        return None
    return float(c)


def describe(i: int, question: str, budget: Budget) -> dict[str, Any]:
    """Send one ask (if the budget allows), print the facts, return them."""
    print(f"\n=== ask {i}: {question}", flush=True)
    if not budget.reserve("ask"):
        print(f"  {SKIPPED_BUDGET}", flush=True)
        return {"question": question, "skipped": SKIPPED_BUDGET}
    r = request(
        "POST",
        _API + "/v1/live/ask",
        json_body={"question": question, "ref": TEST_REF},
        headers={"Origin": _WEB},
        timeout=ASK_TIMEOUT_S,
    )
    body = r.json() if isinstance(r.json(), dict) else {}
    got = cost_of(body) if r.status == 200 else None
    budget.settle("ask", got)
    trace = body.get("trace") if isinstance(body.get("trace"), list) else []
    models = sorted({str(s.get("model")) for s in trace if isinstance(s, dict) and s.get("model")})
    tool_calls = 0
    for s in trace:
        m = TOOL_CALLS.search(str(s.get("note", ""))) if isinstance(s, dict) else None
        tool_calls += int(m.group(1)) if m else 0
    answer = body.get("answer") if isinstance(body.get("answer"), dict) else {}
    text = str(answer.get("spoken_text", "")) or str(body.get("message", ""))
    acao = r.headers.get("access-control-allow-origin", "")
    row = {
        "question": question,
        "http_status": r.status,
        "latency_ms": r.elapsed_ms,
        "mode": body.get("mode"),
        "tier": body.get("tier"),
        "error_code": (
            (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
        ),
        "models": models,
        "trace_steps": [
            f"{s.get('step')} [{s.get('status')}] {s.get('ms')} ms"
            for s in trace
            if isinstance(s, dict)
        ],
        "tool_calls": tool_calls,
        "cors_header_present": bool(acao),
        "cost_usd": got,
        "answer_text": text,
        "transport_error": r.error if hasattr(r, "error") else "",
    }
    for k, v in row.items():
        if k == "answer_text":
            print(f"  answer_text: {v}", flush=True)
        elif k == "trace_steps":
            for step in v:
                print(f"  trace: {step}", flush=True)
        else:
            print(f"  {k}: {v}", flush=True)
    note = "  (tool rounds are not reported by the API: tool_calls is the count in the trace note)"
    print(note, flush=True)
    if find_key_shapes(json.dumps(row)):
        row["answer_text"] = "[withheld: key-shaped text in the response]"
        print("  WARNING: a key-shaped string appeared in the response; text withheld", flush=True)
    return row


def browser_pass(web: str, out_dir: Path, budget: Budget) -> dict[str, Any]:
    """One question in a real browser; screenshots at 1440 and 390 wide; chip assertion."""
    from playwright.sync_api import sync_playwright

    result: dict[str, Any] = {"url": f"{web}/?layout=v2&r={TEST_REF}"}
    print(f"\n=== browser: {result['url']}", flush=True)
    if not budget.reserve("ask"):
        print(f"  {SKIPPED_BUDGET}", flush=True)
        result["skipped"] = SKIPPED_BUDGET
        return result
    seen: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()

            def on_response(resp: Any) -> None:
                if resp.url.endswith("/v1/live/ask"):
                    try:
                        seen.append({"status": resp.status, "body": resp.json()})
                    except Exception:  # noqa: BLE001 - an unreadable body is just not recorded
                        seen.append({"status": resp.status, "body": {}})

            page.on("response", on_response)
            page.goto(result["url"], wait_until="networkidle")
            box = page.locator(COMPOSER)
            box.click()
            box.fill(BROWSER_QUESTION)
            box.press("Enter")
            with contextlib.suppress(Exception):  # a missing chip is reported below
                page.wait_for_selector(
                    "[data-testid=model-chip], [data-testid=turn-error]", timeout=90_000
                )
            chip = page.locator("[data-testid=model-chip]").first
            err = page.locator("[data-testid=turn-error]").first
            result["chip_text"] = chip.inner_text() if chip.count() else None
            result["error_text"] = err.inner_text() if err.count() else None
            result["chip_ok"] = result["chip_text"] == CHIP_TEXT
            result["page_has_unreachable"] = "could not be reached" in page.inner_text("body")
            print(f"  chip: {result['chip_text']!r}  error: {result['error_text']!r}", flush=True)
            page.screenshot(path=str(out_dir / "live-1440.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})  # same answer, phone width
            page.wait_for_timeout(500)
            page.screenshot(path=str(out_dir / "live-390.png"), full_page=True)
            ctx.close()
        finally:
            browser.close()
    if not seen:
        budget.settle("ask", None)  # nothing observed: the full hold counts as spent
    for item in seen:
        b = item["body"] if isinstance(item["body"], dict) else {}
        budget.settle("ask", cost_of(b) if item["status"] == 200 else None)
        result["ask_http_status"] = item["status"]
    if len(seen) > 1:
        print(f"  note: the page sent {len(seen)} asks; one hold was reserved", flush=True)
    return result


def delete_test_entries(api: str, admin: str) -> dict[str, Any]:
    """Delete the TEST entries, as ``smoke.py`` does (only when the admin key is given)."""
    if not admin:
        print("\nMAUDESIGNAL_ADMIN_KEY_SMOKE not set: TEST entries were not deleted.", flush=True)
        return {"deleted": None}
    r = request("POST", api + "/v1/admin/delete-test", headers={"X-Admin-Key": admin})
    print(f"\n/v1/admin/delete-test: HTTP {r.status} {r.text[:120]}", flush=True)
    s = request("GET", api + "/v1/admin/summary", headers={"X-Admin-Key": admin})
    codes = (s.json() or {}).get("codes") if isinstance(s.json(), dict) else None
    left = [c for c in (codes or []) if isinstance(c, dict) and c.get("code") == TEST_REF]
    print(f"{TEST_REF} entries still listed after the delete: {len(left)}", flush=True)
    if r.status != 200 or left:
        print(
            f"FAIL: TEST entries remain after the delete (HTTP {r.status}, {len(left)} left)",
            flush=True,
        )
    return {"delete_status": r.status, "left": len(left)}


_API = ""
_WEB = ""


def main(argv: list[str] | None = None) -> int:
    """Run the check; write ``live-check.json``; exit 1 on a failed ask or a missing chip."""
    global _API, _WEB
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--api", default="https://maudesignal-api.vercel.app")
    ap.add_argument("--web", default="https://maudesignal-app.vercel.app")
    ap.add_argument("--out-dir", type=Path, default=Path("live-check-out"))
    ap.add_argument("--max-usd", type=float, default=0.40)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    _API, _WEB = args.api.rstrip("/"), args.web.rstrip("/")
    admin = os.environ.get("MAUDESIGNAL_ADMIN_KEY_SMOKE", "").strip()
    if admin and not _API.startswith("https://maudesignal-api"):
        print("refusing to send the admin key to an unexpected API host", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(
        max_usd=args.max_usd, limits={"ask": len(QUESTIONS) + 1, "photo": 0, "voice": 0}
    )
    rows = [describe(i + 1, q, budget) for i, q in enumerate(QUESTIONS)]
    browser: dict[str, Any] = {}
    if not args.no_browser:
        browser = browser_pass(_WEB, args.out_dir, budget)
    cleanup = delete_test_entries(_API, admin)
    snap = budget.snapshot()
    print(f"\nbudget: {snap} (hold per ask ${HOLD_USD['ask']})", flush=True)
    report = {"asks": rows, "browser": browser, "cleanup": cleanup, "budget": snap}
    (args.out_dir / "live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok_asks = all(r.get("http_status") == 200 or r.get("skipped") for r in rows)
    ok_browser = args.no_browser or bool(browser.get("chip_ok")) or "skipped" in browser
    cleaned = cleanup.get("deleted", True) is not None and (
        "delete_status" not in cleanup or (cleanup["delete_status"] == 200 and cleanup["left"] == 0)
    )
    if not cleaned:
        print("FAIL: TEST entries were not fully deleted", flush=True)
    return 0 if cleaned and ok_asks and ok_browser and snap["spent_usd"] <= args.max_usd + 1e-9 else 1  # type: ignore[operator]


if __name__ == "__main__":
    sys.exit(main())
