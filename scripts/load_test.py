"""Load / stress test of the keyless demo app with concurrent browser sessions.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Each simulated user opens the app in its own headless-Chromium context, waits
for the What changed page to render, then opens the Copilot page (recorded runs,
no Meta call — the demo holds no key). Levels rise until a level has failures
or its slowest user exceeds ``--limit-s``: that level is the breaking point.
Never point this at an app that holds a Meta key.

    python scripts/load_test.py --url http://localhost:8501 --levels 1 5 10 20 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

READY = "MAUDE records on file"


async def one_user(browser: Any, url: str, timeout_ms: int) -> float:
    """Seconds for one user to load What changed and switch to Copilot."""
    ctx = await browser.new_context()
    page = await ctx.new_page()
    t = time.perf_counter()
    try:
        await page.goto(url, timeout=timeout_ms)
        await page.wait_for_selector(f"text={READY}", timeout=timeout_ms)
        await page.wait_for_selector("text=Why it is ranked first", timeout=timeout_ms)
        await page.locator(".st-key-ms_topbar").get_by_role("radio", name="Copilot").click()
        await page.wait_for_selector("text=Recorded Muse Spark runs", timeout=timeout_ms)
        return time.perf_counter() - t
    finally:
        await ctx.close()


async def level(url: str, users: int, timeout_ms: int) -> dict[str, Any]:
    """Run ``users`` sessions at once."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        t = time.perf_counter()
        results = await asyncio.gather(
            *(one_user(browser, url, timeout_ms) for _ in range(users)), return_exceptions=True
        )
        wall = time.perf_counter() - t
        await browser.close()
    ok = [r for r in results if isinstance(r, float)]
    fails = [r for r in results if not isinstance(r, float)]
    return {
        "users": users,
        "ok": len(ok),
        "failed": len(fails),
        "median_s": round(statistics.median(ok), 2) if ok else None,
        "max_s": round(max(ok), 2) if ok else None,
        "wall_s": round(wall, 2),
        "first_error": (type(fails[0]).__name__ + ": " + str(fails[0])[:120]) if fails else None,
    }


def main() -> int:
    """Raise the load level by level; print JSON lines and a Markdown table."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 5, 10, 20])
    ap.add_argument("--limit-s", type=float, default=30.0)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    rows = []
    for n in args.levels:
        r = asyncio.run(level(args.url, n, int(args.limit_s * 2000)))
        rows.append(r)
        print(json.dumps(r), flush=True)
        if r["failed"] or (r["max_s"] or 0) > args.limit_s:
            break
    print("\n| users | ok | failed | median s | slowest s | wall s |\n|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['users']} | {r['ok']} | {r['failed']} | {r['median_s']} | {r['max_s']} | "
            f"{r['wall_s']} |"
        )
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
