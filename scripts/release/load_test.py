"""A light load test of the deployed API: virtual users, a time limit, a hard limit on live asks.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Each virtual user loops until the time is up, with a pause between calls, and mixes:

* ``GET /v1/public/check_device_type`` (no key; the server limits it per address, so many
  answers are 429, counted as "limited" and not as errors),
* ``GET /v1/health`` (a cheap baseline),
* ``POST /v1/live/ask`` (a real question; at most ``--max-live-asks`` (default 0) in the whole run, so the
  daily cap is not burned; each answer's ``cost_usd`` is added up).

Reported: calls, p50 / p95 / max latency in ms per kind, error rate (no answer or HTTP 5xx), the
share of 429 answers, live asks made, their total cost and the last ``remaining_today`` the API
gave. Fails when the error rate is over ``--max-error-rate`` or the live cost is over
``--max-cost``.

    python3 scripts/release/load_test.py --base https://maudesignal-api.vercel.app \
        --vus 20 --seconds 120 --max-live-asks 0 --out-dir release-out
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import itertools
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from budget import MAX_USD, Budget  # noqa: E402
from netutil import Response, percentile, request  # noqa: E402
from report import FAIL, PASS, Report  # noqa: E402

CODES = ("LLZ", "QIH", "MYN", "POK", "JAK", "FLL")
QUESTION = "What changed this week for LLZ?"
Sample = tuple[str, int, int, float, int | None]  # kind, status, ms, cost_usd, remaining_today


def summarize(samples: list[Sample]) -> dict[str, Any]:
    """Aggregate ``samples`` (kind, status, elapsed ms, cost, remaining_today) into numbers."""
    out: dict[str, Any] = {"calls": len(samples), "kinds": {}}
    by_kind: dict[str, list[Sample]] = {}
    for s in samples:
        by_kind.setdefault(s[0], []).append(s)
    total_errors = total_limited = 0
    for kind, rows in sorted(by_kind.items()):
        ms = [float(r[2]) for r in rows if r[1] != 0]
        errors = sum(1 for r in rows if r[1] == 0 or r[1] >= 500)
        limited = sum(1 for r in rows if r[1] == 429)
        total_errors += errors
        total_limited += limited
        out["kinds"][kind] = {
            "calls": len(rows),
            "p50_ms": round(percentile(ms, 50)),
            "p95_ms": round(percentile(ms, 95)),
            "max_ms": round(max(ms)) if ms else 0,
            "errors": errors,
            "limited_429": limited,
            "ok_2xx": sum(1 for r in rows if 200 <= r[1] < 300),
        }
    all_ms = [float(s[2]) for s in samples if s[1] != 0]
    out.update(
        p50_ms=round(percentile(all_ms, 50)),
        p95_ms=round(percentile(all_ms, 95)),
        errors=total_errors,
        error_rate=round(total_errors / len(samples), 4) if samples else 1.0,
        limited_429=total_limited,
        limited_share=round(total_limited / len(samples), 4) if samples else 0.0,
        live_asks=len(by_kind.get("live_ask", [])),
        live_cost_usd=round(sum(s[3] for s in samples), 6),
    )
    remaining = [s[4] for s in samples if s[4] is not None]
    out["last_remaining_today"] = remaining[-1] if remaining else None
    return out


def run_load(
    base: str,
    *,
    vus: int,
    seconds: float,
    max_live_asks: int,
    think_s: float = 1.0,
    send: Callable[..., Response] = request,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    budget: Budget | None = None,
) -> list[Sample]:
    """Run the virtual users and return every call as a sample.

    With a ``budget`` every live ask is reserved first (dollar hold and count); a refused ask
    becomes a public ``check_device_type`` call instead, so spending never passes the budget.
    """
    samples: list[Sample] = []
    lock = threading.Lock()
    live_left = [max_live_asks]
    deadline = clock() + seconds
    codes = itertools.cycle(CODES)

    def take_live_slot() -> bool:
        with lock:
            if live_left[0] <= 0:
                return False
            if budget is not None and not budget.reserve("ask"):
                live_left[0] = 0  # the budget is short: no more live asks in this run
                return False
            live_left[0] -= 1
            return True

    def one(kind: str, call: Callable[[], Response]) -> None:
        r = call()
        cost, remaining = 0.0, None
        known: float | None = None  # None: no cost came back, so the hold stays as spent
        if kind == "live_ask" and r.status == 200:
            body = r.json()
            if isinstance(body, dict):
                if body.get("cost_usd") is not None:
                    known = cost = float(body["cost_usd"])
                remaining = (body.get("limits") or {}).get("remaining_today")
        if kind == "live_ask" and budget is not None:
            budget.settle("ask", known)
        with lock:
            samples.append((kind, r.status, r.elapsed_ms, cost, remaining))

    def user(n: int) -> None:
        i = n
        while clock() < deadline:
            i += 1
            if i % 7 == 0 and take_live_slot():
                one(
                    "live_ask",
                    lambda: send(
                        "POST", base + "/v1/live/ask", json_body={"question": QUESTION}, timeout=90
                    ),
                )
            elif i % 2 == 0 or i % 7 == 0:  # a refused live slot becomes a public check
                code = next(codes)
                one(
                    "public_check",
                    lambda c=code: send(
                        "GET", f"{base}/v1/public/check_device_type?product_code={c}"
                    ),
                )
            else:
                one("health", lambda: send("GET", base + "/v1/health"))
            sleep(think_s)

    threads = [threading.Thread(target=user, args=(n,), daemon=True) for n in range(vus)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=seconds + 120)
    return samples


def evaluate(
    rep: Report, stats: dict[str, Any], max_error_rate: float, max_cost: float, max_live: int
) -> None:
    """Turn the numbers into checks (the numbers themselves go into the report metrics)."""
    rep.metrics["load"] = stats
    rep.add(
        "calls were made",
        PASS if stats["calls"] > 0 else FAIL,
        f"{stats['calls']} calls",
        group="load",
    )
    rep.add(
        "error rate (no answer or HTTP 5xx) is within the limit",
        PASS if stats["error_rate"] <= max_error_rate else FAIL,
        f"{stats['errors']} of {stats['calls']} = {stats['error_rate']:.2%} (limit {max_error_rate:.0%})",
        group="load",
        error_rate=stats["error_rate"],
    )
    rep.add(
        "live asks stayed within the limit",
        PASS if stats["live_asks"] <= max_live else FAIL,
        f"{stats['live_asks']} live asks (limit {max_live})",
        group="load",
    )
    rep.add(
        "live cost stayed within the limit",
        PASS if stats["live_cost_usd"] <= max_cost + 1e-9 else FAIL,
        f"${stats['live_cost_usd']:.4f} (limit ${max_cost:.2f})",
        group="load",
        live_cost_usd=stats["live_cost_usd"],
    )
    for kind, k in stats["kinds"].items():
        rep.add(
            f"latency {kind}",
            PASS,
            f"p50 {k['p50_ms']} ms, p95 {k['p95_ms']} ms, max {k['max_ms']} ms over {k['calls']} calls "
            f"({k['ok_2xx']} ok, {k['limited_429']} limited, {k['errors']} errors)",
            group="load",
            required=False,
        )


def main(argv: list[str] | None = None) -> int:
    """Run the load test and write ``load-test.json`` and ``.md``."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--base", required=True)
    ap.add_argument("--vus", type=int, default=20)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--max-live-asks", type=int, default=0)
    ap.add_argument("--max-error-rate", type=float, default=0.02)
    ap.add_argument("--max-cost", type=float, default=0.60)
    ap.add_argument("--think", type=float, default=1.0)
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    args = ap.parse_args(argv)
    rep = Report("load test")
    budget = Budget(max_usd=MAX_USD)  # standalone runs obey the same $0.60 ledger
    allowed = min(args.max_live_asks, budget.max_asks_by_dollars())
    samples = run_load(
        args.base.rstrip("/"),
        vus=args.vus,
        seconds=args.seconds,
        max_live_asks=allowed,
        think_s=args.think,
        budget=budget,
    )
    stats = summarize(samples)
    stats.update(vus=args.vus, seconds=args.seconds)
    evaluate(rep, stats, args.max_error_rate, min(args.max_cost, MAX_USD), allowed)
    rep.write(args.out_dir, "load-test")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
