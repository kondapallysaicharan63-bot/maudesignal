"""Live check on openFDA counts gives the same answer as the stored-records detector."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.monitor.deterioration import (
    EventFact,
    build_window,
    detect_deterioration,
)
from maudesignal.monitor.live_check import (
    LiveCheckError,
    WindowCounts,
    check_product_code,
    classify_counts,
    normalize_code,
)

TYPES = ("Malfunction", "Injury", "Death", "Other", "")


def _facts(rng: random.Random, as_of: date) -> list[EventFact]:
    n_old = rng.choice([0, 0, 3, 40])
    n_base = rng.choice([0, 2, 8, 30])
    n_cur = rng.choice([0, 1, 3, 9, 25])
    weights = [rng.random() for _ in TYPES]
    facts: list[EventFact] = []
    w = build_window(as_of)

    def add(n: int, first: date, last: date, prefix: str, types: tuple[str, ...]) -> None:
        span = (last - first).days
        for i in range(n):
            t = rng.choices(types, weights=weights[: len(types)])[0]
            facts.append(
                EventFact(
                    report_id=f"{prefix}{i}",
                    product_code="ABC",
                    date_received=first + timedelta(days=rng.randint(0, span)),
                    event_type=t.lower() or "unknown",
                )
            )

    add(
        n_old,
        w.baseline_start - timedelta(days=400),
        w.baseline_start - timedelta(days=1),
        "o",
        TYPES[:3],
    )
    add(n_base, w.baseline_start, w.baseline_end, "b", TYPES)
    add(n_cur, w.current_start, w.current_end, "c", TYPES)
    return facts


def _counts(facts: list[EventFact], as_of: date) -> WindowCounts:
    w = build_window(as_of)

    def types(sel: list[EventFact]) -> tuple[tuple[str, int], ...]:
        out: dict[str, int] = {}
        for f in sel:
            out[f.event_type] = out.get(f.event_type, 0) + 1
        return tuple(sorted(out.items()))

    cur = [f for f in facts if w.current_start <= f.date_received <= w.current_end]
    base = [f for f in facts if w.baseline_start <= f.date_received <= w.baseline_end]
    prior = [f for f in facts if f.date_received < w.current_start]
    return WindowCounts(len(cur), len(base), len(prior), types(cur), types(base), types(prior))


@pytest.mark.parametrize("seed", range(300))
def test_counts_and_records_agree(seed: int) -> None:
    rng = random.Random(seed)
    as_of = date(2026, 8, 31)
    facts = _facts(rng, as_of)
    if not facts:
        return
    stored = detect_deterioration(facts, as_of).signals[0]
    live = classify_counts("ABC", _counts(facts, as_of), build_window(as_of))
    assert live.classification == stored.classification
    assert live.triggers == stored.triggers
    assert live.current_count == stored.current_count
    assert live.baseline_weekly_mean == stored.baseline_weekly_mean
    assert live.current_severe_share == stored.current_severe_share
    assert live.severe_share_delta_pp == stored.severe_share_delta_pp
    assert live.spike_ratio == stored.spike_ratio
    assert live.new_event_types == stored.new_event_types
    assert live.prior_report_count == stored.prior_report_count


def test_codes_are_three_letters() -> None:
    assert normalize_code(" llz ") == "LLZ"
    for bad in ("", "LL", "LLZZ", "L1Z", "LLZ;"):
        with pytest.raises(LiveCheckError):
            normalize_code(bad)


def _fake_openfda(day_counts: dict[str, int], types: dict[str, dict[str, int]]) -> httpx.Client:
    """Answers count=date_received, count=event_type.exact and limit=1 totals from tables."""

    def in_range(day: str, search: str) -> bool:
        if "date_received:[" not in search:
            return True
        lo, hi = search.split("date_received:[")[1].rstrip("]").split(" TO ")
        return lo <= day <= hi

    def handler(request: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(request.url)).query)
        search = q["search"][0]
        assert "device.device_report_product_code:LLZ" in search
        days = {d: n for d, n in day_counts.items() if in_range(d, search)}
        if q.get("count") == ["date_received"]:
            rows = [{"time": d, "count": n} for d, n in sorted(days.items())]
            return httpx.Response(200, json={"results": rows}) if rows else httpx.Response(404)
        if q.get("count") == ["event_type.exact"]:
            tally: dict[str, int] = {}
            for d in days:
                for t, n in types.get(d, {}).items():
                    tally[t] = tally.get(t, 0) + n
            rows = [{"term": t, "count": n} for t, n in tally.items()]
            return httpx.Response(200, json={"results": rows}) if rows else httpx.Response(404)
        total = sum(days.values())
        if not total:
            return httpx.Response(404)
        return httpx.Response(200, json={"meta": {"results": {"total": total}}, "results": [{}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_product_code_end_to_end_with_recorded_shape() -> None:
    # Baseline: 2 reports a week for 4 weeks; this week: 9 (a spike), one an injury.
    days: dict[str, int] = {}
    types: dict[str, dict[str, int]] = {}
    for k in range(4):
        d = (date(2026, 8, 1) + timedelta(days=7 * k)).strftime("%Y%m%d")
        days[d] = 2
        types[d] = {"Malfunction": 2}
    days["20260830"] = 9
    types["20260830"] = {"Malfunction": 8, "Injury": 1}
    days["20250105"] = 1
    types["20250105"] = {"Injury": 1}
    client = OpenFDAClient()
    client._client = _fake_openfda(days, types)
    r = check_product_code(client, "llz", today=date(2026, 10, 29))
    assert r.as_of == date(2026, 8, 30)
    assert r.classification == "spike" and r.change == "reports suddenly increased"
    assert r.current_count == 9 and r.baseline_count == 8 and r.baseline_weekly_mean == 2.0
    assert r.current_severe_count == 1
    assert r.all_dates_total == 18
    assert len(r.queries) == 5 and all(u.startswith("https://api.fda.gov/") for _, u in r.queries)
    assert "api_key" not in json.dumps(r.to_dict())


def test_code_with_no_recent_reports_is_reported_plainly() -> None:
    client = OpenFDAClient()
    client._client = _fake_openfda({"20200101": 3}, {"20200101": {"Malfunction": 3}})
    r = check_product_code(client, "LLZ", today=date(2026, 10, 29))
    assert r.as_of is None and r.classification == "stable" and r.prior_report_count == 3


def test_a_sweep_date_compares_every_code_on_the_same_week() -> None:
    days = {"20260810": 4, "20260830": 3}
    types = {d: {"Malfunction": n} for d, n in days.items()}
    client = OpenFDAClient()
    client._client = _fake_openfda(days, types)
    r = check_product_code(client, "LLZ", today=date(2026, 10, 29), as_of=date(2026, 8, 20))
    assert r.as_of == date(2026, 8, 20)
    assert r.current_count == 0 and r.baseline_count == 4 and r.classification == "stable"
    assert r.all_dates_total == 4  # the report after the sweep date is not counted
