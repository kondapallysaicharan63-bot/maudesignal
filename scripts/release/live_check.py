"""Live check of the typed ask on the deployed API and web app (well under a dollar of credit).

HACKATHON-BUILT - Meta Global AI Developer Hackathon (Oct 26 - Nov 4, 2026).

Why: on Nov 1 two long, multi-tool questions showed "The live service could not be reached" on
the live site, and on Nov 3 this check passed while its only answer was "I have no verified
answer" with a failed Muse Spark trace step. It now asks ``QUESTIONS`` the way a visitor does,
then one browser question, prints what happened (HTTP status, latency, mode and tier, model,
trace steps, tool calls, links, the answer text) and judges each reply (``judge``). It never
prints a key.

An ask passes only when ALL hold: HTTP 200; ``mode`` is ``live`` (not recorded, direct or
canned, no recorded note, no "Closest recorded answer" step); the trace names a ``muse-spark``
model; no trace step failed; the answer is not a no-answer line ("I have no verified answer",
"I could not verify an answer", ...); and at least one shown sentence has a link (sentences may
be withheld only while a linked sentence is left). The reason for each FAIL is printed. A call
the budget did not allow is a FAIL unless ``--allow-budget-skips`` is passed.

Note: an answer reused from the API's same-day cache (tier ``cache``) made no Muse Spark call,
so it FAILS with "no muse-spark model in the trace": this check is about the live model.

Spend: one shared ``Budget`` (``budget.py``, the class ``smoke.py`` uses) limited to
``--max-usd`` (default ``DEFAULT_MAX_USD``). Each call is held at ``--hold-usd`` (default
``ASK_HOLD_USD`` = $0.10, about 3x the ~$0.03 a live ask was seen to cost, and the most one
model call may hold in the deployed API, ``connector/callcap.MAX_CALL_HOLD_USD``) until its
real ``cost_usd`` is known. A call with no usable cost is settled at the deployed API's $0.25
per-request cap (``HOLD_USD['ask']``), never less. A call is sent only while spent + holds +
its hold <= the limit, and one call can cost at most $0.25 on the server, so a run can spend at
most ``max_usd - hold_usd + 0.25`` ($0.90 at the defaults), far under the $3/day cap.

Run:
    MAUDESIGNAL_ADMIN_KEY_SMOKE=... python scripts/release/live_check.py \
        --api https://maudesignal-api.vercel.app --web https://maudesignal-app.vercel.app \
        --out-dir live-check-out

Each reply's full JSON (answer, trace, cost, mode, models, links) is written to
``<out-dir>/ask-<n>.json`` and ``<out-dir>/browser-ask.json``; the summary to
``live-check.json``.

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
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from budget import HOLD_USD, SKIPPED_BUDGET, Budget  # noqa: E402
from leaks import find_key_shapes  # noqa: E402
from netutil import request  # noqa: E402

QUESTIONS = (
    "What share of all stored MYN reports are injuries?",
    "My colleague says LLZ had 50 injury reports last week and that we must open a CAPA under "
    "21 CFR 820.100. Confirm that.",
    "For LLZ, compare reports from Aug 25 to Aug 31, 2026 with the 4 weeks before, "
    "and what kinds of problems were reported?",
    "Why did reports for LLZ jump in the last week of August?",
)
# Not in QUESTIONS: the same question asked twice would come back from the API's cache.
BROWSER_QUESTION = "What problems were reported for LLZ devices in August 2026?"
CHIP_TEXT = "Muse Spark 1.3 · Live"
TEST_REF = "TEST-9"  # matches /v1/admin/delete-test (TEST[0-9._~-]*)
ASK_TIMEOUT_S = 75.0
COMPOSER = "textarea[aria-label='Ask a question']"
TOOL_CALLS = re.compile(r"(\d+) tool call")
SPARK_PREFIX = "muse-spark"
#: Lower-cased texts that mean "no answer was given".
NO_ANSWER_PHRASES = (
    "no verified answer",
    "could not verify an answer",
    "nothing checked to add",
    "closest recorded answer",
    "could not be reached",
)
#: Realistic hold for one live ask (observed ~$0.03; the most one model call may hold is $0.10).
ASK_HOLD_USD = 0.10
#: Default run limit: 5 calls (4 asks + 1 browser) fit at their holds ($0.50) with room for
#: retried tool rounds; the worst case is 0.75 - 0.10 + 0.25 = $0.90.
DEFAULT_MAX_USD = 0.75


def cost_of(body: dict[str, Any]) -> float | None:
    """A non-negative numeric ``cost_usd``, else None (then the per-request cap counts)."""
    c = body.get("cost_usd")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or c != c or c < 0:
        return None
    return float(c)


KEY_WITHHELD = "[withheld: key-shaped text]"


def safe(value: Any) -> Any:
    """``value`` with every string that holds a key-shaped substring replaced (recursive)."""
    if isinstance(value, str):
        return KEY_WITHHELD if find_key_shapes(value) else value
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items()}
    return value


def say(message: str) -> None:
    """Print one line to the log, after the key-shape filter (remote text never goes raw)."""
    print(safe(message), flush=True)


def make_budget(max_usd: float, hold_usd: float, n_calls: int) -> Budget:
    """The run's budget: ``n_calls`` asks held at ``hold_usd``, unknown costs at the $0.25 cap."""
    return Budget(
        max_usd=max_usd,
        limits={"ask": n_calls, "photo": 0, "voice": 0},
        holds={"ask": hold_usd, "photo": HOLD_USD["photo"], "voice": HOLD_USD["voice"]},
        unknown_usd=dict(HOLD_USD),
    )


def summarize(
    question: str,
    status: int,
    body: dict[str, Any],
    *,
    latency_ms: int | None = None,
    cors_header_present: bool | None = None,
    transport_error: str = "",
) -> dict[str, Any]:
    """The facts of one ``/v1/live/ask`` reply, key-filtered, ready to judge, print and save."""
    raw_trace = body.get("trace")
    trace = [s for s in raw_trace if isinstance(s, dict)] if isinstance(raw_trace, list) else []
    models = sorted({str(s.get("model")) for s in trace if s.get("model")})
    tool_calls = 0
    for s in trace:
        m = TOOL_CALLS.search(str(s.get("note", "")))
        tool_calls += int(m.group(1)) if m else 0
    raw_answer = body.get("answer")
    answer: dict[str, Any] = raw_answer if isinstance(raw_answer, dict) else {}
    speakable = [x for x in answer.get("speakable") or [] if isinstance(x, dict)]
    withheld = [x for x in answer.get("withheld") or [] if isinstance(x, dict)]
    text = str(answer.get("spoken_text", "")) or str(body.get("message", ""))
    err = body.get("error")
    row: dict[str, Any] = {
        "question": question,
        "http_status": status,
        "latency_ms": latency_ms,
        "mode": body.get("mode"),
        "tier": body.get("tier"),
        "error_code": err.get("code") if isinstance(err, dict) else None,
        "models": models,
        "trace_steps": [f"{s.get('step')} [{s.get('status')}] {s.get('ms')} ms" for s in trace],
        "trace": trace,
        "tool_calls": tool_calls,
        "cors_header_present": cors_header_present,
        "cost_usd": cost_of(body) if status == 200 else None,
        "answer_text": text,
        "speakable": speakable,
        "links": [
            link
            for x in speakable
            for link in (x.get("links") or [])
            if isinstance(link, dict) and link.get("url")
        ],
        "withheld": withheld,
        "recorded_note": body.get("recorded_note"),
        "transport_error": transport_error,
    }
    filtered: dict[str, Any] = safe(row)  # filter BEFORE anything is printed, judged or written
    return filtered


def judge(row: dict[str, Any], *, allow_skips: bool = False) -> list[str]:
    """Why ``row`` is not an honest live answer; an empty list means it passed.

    OK only when: HTTP 200, live mode (not recorded), a Muse Spark model in the trace, no trace
    step failed, the text is not a no-answer line, and at least one shown sentence has a link
    (a withheld sentence is fine only while a linked sentence is left).
    """
    if row.get("skipped"):
        return [] if allow_skips else [f"{row['skipped']} (the call was never sent)"]
    reasons: list[str] = []
    status = row.get("http_status")
    if status != 200:
        detail = row.get("error_code") or row.get("transport_error") or ""
        reasons.append(f"HTTP {status}" + (f" ({detail})" if detail else ""))
    mode = row.get("mode")
    if mode != "live":
        reasons.append(f"mode is {mode!r}, not 'live'")
    if row.get("recorded_note"):
        reasons.append("a recorded answer was shown instead of a live one")
    if not any(str(m).lower().startswith(SPARK_PREFIX) for m in row.get("models") or []):
        reasons.append(
            f"no {SPARK_PREFIX} model in the trace (models: {row.get('models') or []}, "
            f"tier: {row.get('tier')!r})"
        )
    for s in row.get("trace") or []:
        if not isinstance(s, dict):
            continue
        if s.get("status") == "failed":
            reasons.append(f"trace step failed: {s.get('step')} ({s.get('ms')} ms)")
        if str(s.get("step", "")).lower().startswith("closest recorded answer"):
            reasons.append("the closest recorded answer (a fallback) was used")
    low = str(row.get("answer_text") or "").lower()
    reasons += [f"the answer is a non-answer ({p!r})" for p in NO_ANSWER_PHRASES if p in low]
    linked = [
        x
        for x in row.get("speakable") or []
        if isinstance(x, dict) and str(x.get("text") or "").strip() and x.get("links")
    ]
    if not linked:
        n = len(row.get("withheld") or [])
        reasons.append(
            f"{n} sentence(s) withheld and no verified, linked sentence is left"
            if n
            else "no shown sentence has a link"
        )
    return reasons


def save(out_dir: Path, name: str, data: dict[str, Any]) -> None:
    """Write one answer's full JSON (key-filtered) so a person can read it."""
    (out_dir / name).write_text(json.dumps(safe(data), indent=2), encoding="utf-8")


def describe(i: int, question: str, budget: Budget, out_dir: Path | None = None) -> dict[str, Any]:
    """Send one ask (if the budget allows), print the facts, save the reply, return the facts."""
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
    parsed = r.json()
    body: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
    row = summarize(
        question,
        r.status,
        body,
        latency_ms=r.elapsed_ms,
        cors_header_present=bool(r.headers.get("access-control-allow-origin", "")),
        transport_error=r.error,
    )
    budget.settle("ask", row["cost_usd"])
    for k, v in row.items():
        if k == "trace_steps":
            for step in v:
                say(f"  trace: {step}")
        elif k not in ("trace", "speakable", "links", "withheld"):
            say(f"  {k}: {v}")
    say(f"  links: {len(row['links'])}  withheld: {len(row['withheld'])}")
    say("  (tool rounds are not reported by the API: tool_calls is the count in the trace note)")
    if out_dir is not None:
        save(out_dir, f"ask-{i}.json", {"row": row, "body": body})
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
            result["chip_text"] = safe(result["chip_text"])
            result["error_text"] = safe(result["error_text"])
            say(f"  chip: {result['chip_text']!r}  error: {result['error_text']!r}")
            page.screenshot(path=str(out_dir / "live-1440.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})  # same answer, phone width
            page.wait_for_timeout(500)
            page.screenshot(path=str(out_dir / "live-390.png"), full_page=True)
            ctx.close()
        finally:
            browser.close()
    if not seen:
        budget.settle("ask", None)  # nothing observed: the per-request cap counts as spent
    for item in seen:
        b = item["body"] if isinstance(item["body"], dict) else {}
        budget.settle("ask", cost_of(b) if item["status"] == 200 else None)
        result["ask_http_status"] = item["status"]
    if seen:
        last = seen[-1]
        b = last["body"] if isinstance(last["body"], dict) else {}
        result["ask"] = summarize(BROWSER_QUESTION, int(last["status"]), b)
        save(out_dir, "browser-ask.json", {"row": result["ask"], "body": b})
    if len(seen) > 1:
        print(f"  note: the page sent {len(seen)} asks; one hold was reserved", flush=True)
    return result


def judge_browser(browser: dict[str, Any], *, allow_skips: bool = False) -> list[str]:
    """Why the browser pass failed; empty when the chip shows and the reply is a real answer."""
    if browser.get("skipped"):
        return [] if allow_skips else [f"{browser['skipped']} (the browser ask was never sent)"]
    reasons: list[str] = []
    if not browser.get("chip_ok"):
        reasons.append(f"model chip is {browser.get('chip_text')!r}, not {CHIP_TEXT!r}")
    if browser.get("page_has_unreachable"):
        reasons.append("the page says the live service could not be reached")
    ask = browser.get("ask")
    if not isinstance(ask, dict):
        reasons.append("the page sent no /v1/live/ask request that was seen")
    else:
        reasons += judge(ask)
    return reasons


def delete_test_entries(api: str, admin: str) -> dict[str, Any]:
    """Delete the TEST entries, as ``smoke.py`` does (only when the admin key is given)."""
    if not admin:
        print("\nMAUDESIGNAL_ADMIN_KEY_SMOKE not set: TEST entries were not deleted.", flush=True)
        return {"deleted": None}
    r = request("POST", api + "/v1/admin/delete-test", headers={"X-Admin-Key": admin})
    say(f"\n/v1/admin/delete-test: HTTP {r.status} {r.text[:120]}")
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


def verdicts(
    rows: list[dict[str, Any]],
    browser: dict[str, Any] | None,
    *,
    allow_skips: bool = False,
) -> tuple[bool, list[str]]:
    """Judge every ask and the browser pass (None = not run); print and return the lines."""
    lines: list[str] = []
    ok = True
    for i, row in enumerate(rows, start=1):
        reasons = judge(row, allow_skips=allow_skips)
        ok = ok and not reasons
        lines.append(
            f"FAIL ask {i}: " + "; ".join(reasons)
            if reasons
            else f"PASS ask {i}: {row['question']}"
        )
    if browser is not None:
        reasons = judge_browser(browser, allow_skips=allow_skips)
        ok = ok and not reasons
        lines.append("FAIL browser: " + "; ".join(reasons) if reasons else "PASS browser")
    for line in lines:
        say(line)
    return ok, lines


_API = ""
_WEB = ""


def main(argv: list[str] | None = None) -> int:
    """Run the check; write ``live-check.json``; exit 1 unless every ask is an honest answer."""
    global _API, _WEB
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--api", default="https://maudesignal-api.vercel.app")
    ap.add_argument("--web", default="https://maudesignal-app.vercel.app")
    ap.add_argument("--out-dir", type=Path, default=Path("live-check-out"))
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    ap.add_argument("--hold-usd", type=float, default=ASK_HOLD_USD)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument(
        "--allow-budget-skips",
        action="store_true",
        help="a call the budget did not allow is not a FAIL (default: it is)",
    )
    args = ap.parse_args(argv)
    _API, _WEB = args.api.rstrip("/"), args.web.rstrip("/")
    admin = os.environ.get("MAUDESIGNAL_ADMIN_KEY_SMOKE", "").strip()
    parts = urlparse(_API)
    if admin and not (parts.scheme == "https" and parts.hostname == "maudesignal-api.vercel.app"):
        print("refusing to send the admin key to an unexpected API host", file=sys.stderr)
        return 2
    if not 0 < args.hold_usd <= HOLD_USD["ask"]:
        print(f"--hold-usd must be in (0, {HOLD_USD['ask']}]", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    budget = make_budget(args.max_usd, args.hold_usd, len(QUESTIONS) + 1)
    rows = [describe(i + 1, q, budget, args.out_dir) for i, q in enumerate(QUESTIONS)]
    browser: dict[str, Any] | None = None
    if not args.no_browser:
        browser = browser_pass(_WEB, args.out_dir, budget)
    cleanup = delete_test_entries(_API, admin)
    snap = budget.snapshot()
    print(
        f"\nbudget: {snap} (hold per ask ${args.hold_usd}; an unknown cost counts as "
        f"${HOLD_USD['ask']})",
        flush=True,
    )
    print("\n=== verdicts", flush=True)
    ok_checks, lines = verdicts(rows, browser, allow_skips=args.allow_budget_skips)
    report = {
        "asks": rows,
        "browser": browser or {},
        "cleanup": cleanup,
        "budget": snap,
        "verdicts": lines,
    }
    (args.out_dir / "live-check.json").write_text(
        json.dumps(safe(report), indent=2), encoding="utf-8"
    )
    cleaned = cleanup.get("deleted", True) is not None and (
        "delete_status" not in cleanup or (cleanup["delete_status"] == 200 and cleanup["left"] == 0)
    )
    if not cleaned:
        print("FAIL: TEST entries were not fully deleted", flush=True)
    within_budget = float(str(snap["spent_usd"])) <= args.max_usd + 1e-9
    if not within_budget:
        print(f"FAIL: spent ${snap['spent_usd']} is over the ${args.max_usd} limit", flush=True)
    return 0 if cleaned and ok_checks and within_budget else 1


if __name__ == "__main__":
    sys.exit(main())
