"""Tests for the O-api batch (HACKATHON-BUILT). No network, no model key.

Covers: the durable global cost ledger in the private Blob store (reserve before the call,
settle after, fail closed, cold start, concurrency), the keyed ask counted against it, name
redaction, the outside-mentions endpoint and its quote gate, the demo key and labelled keys,
/v1/connect, the /privacy and /terms pages, and malformed input.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector import mentions as mn  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.blob_store import BlobRef, MemoryStore, StoreError  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.globalcap import LEDGER_ID, blob_enforced_cap  # noqa: E402
from maudesignal.connector.legal_pages import (  # noqa: E402
    contact_line,
    render_privacy,
    render_terms,
)
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter, sha256_hex  # noqa: E402
from maudesignal.connector.store import BlobLedger, BlobLedgerError, ConnectorState  # noqa: E402
from maudesignal.copilot.spend import SpendCaps  # noqa: E402
from tests.unit.test_connector import (
    KEY,
    SCRIPT,
    FakeClient,
    fake_check,
    live_runtime,
)  # noqa: E402
from tests.unit.test_connector_live import (  # noqa: E402
    ORIGIN,
    QUESTION,
    Env,
    RecordingSpark,
)

DAY = date(2026, 10, 30)
ADMIN = "admin-key-NOT-REAL-0123456789"
ORIGINS = frozenset({ORIGIN})

# Words the task forbids on any page or doc, as whole words (a superset of forbidden.py).
DROP_WORDS = (
    "FDA-approved",
    "Part 11 compliant",
    "validated",
    "overnight",
    "worsening signals",
    "citation-checked",
    "complaint data",
    "safe",
    "unsafe",
    "compliant",
    "approved",
)


def has_drop_word(text: str) -> list[str]:
    import re

    return [
        w for w in DROP_WORDS if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", text, re.I)
    ]


class FakeBlobStore:
    """A private-Blob-like store: overwrite flag honoured, failures and races injectable."""

    backend = "blob_private"

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.fail_list = self.fail_put = self.fail_get = False
        self.after_put: Any = None
        self.puts = 0

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        if self.fail_put:
            raise StoreError("blob store unreachable")
        with self.lock:
            if pathname in self.items and not overwrite:
                raise StoreError("exists")
            self.items[pathname] = json.dumps(record, sort_keys=True).encode()
            self.puts += 1
        if self.after_put:
            self.after_put(pathname)

    def list_prefix(self, prefix: str) -> list[BlobRef]:
        if self.fail_list:
            raise StoreError("blob store unreachable")
        with self.lock:
            return [
                BlobRef(p, "https://blob.test/" + p)
                for p in sorted(self.items)
                if p.startswith(prefix)
            ]

    def get(self, ref: BlobRef) -> bytes:
        if self.fail_get:
            raise StoreError("blob store unreachable")
        with self.lock:
            try:
                return self.items[ref.pathname]
            except KeyError:
                raise StoreError("not found") from None

    def delete(self, ref: BlobRef) -> None:
        with self.lock:
            self.items.pop(ref.pathname, None)

    def seed_ledger(self, usd: float, day: date = DAY, name: str = LEDGER_ID) -> None:
        """Replace the day's ledger entries with one real-cost entry of ``usd``."""
        prefix = f"ledger/{name}/{day.isoformat()}/"
        for p in [p for p in self.items if p.startswith(prefix)]:
            del self.items[p]
        micros = int(round(usd * 1_000_000))
        self.items[f"{prefix}a-{micros}-1-{'0' * 32}.json"] = b"{}"

    def ledger_usd(self, day: date = DAY, name: str = LEDGER_ID) -> float:
        prefix = f"ledger/{name}/{day.isoformat()}/"
        total = 0
        for p in self.items:
            if p.startswith(prefix):
                kind, micros = p[len(prefix) :].split("-")[:2]
                total += -int(micros) if kind == "r" else int(micros)
        return total / 1_000_000


def ledger(store: FakeBlobStore, **kw: Any) -> BlobLedger:
    return BlobLedger(store, LEDGER_ID, today=lambda: DAY, **kw)


# --- 1. durable global ledger ----------------------------------------------------------------


def test_blob_ledger_reserves_then_settles_with_the_real_cost() -> None:
    store = FakeBlobStore()
    led = ledger(store)
    assert led.spent_today() == 0.0  # no objects is a new day
    assert led.reserve(0.25, 2.7) is True
    assert store.ledger_usd() == 0.25
    led.add(0.04, 1)  # the real cost
    led.release(0.25)  # the hold goes back
    assert store.ledger_usd() == pytest.approx(0.04)
    assert led.spent_today() == pytest.approx(0.04)
    # one object per event, none overwritten
    assert len(store.items) == 3
    assert all(p.startswith("ledger/live-global/2026-10-30/") for p in store.items)


def test_blob_ledger_refuses_a_hold_over_the_cap_and_holds_nothing() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.6)
    led = ledger(store)
    assert led.reserve(0.25, 2.7) is False
    assert store.ledger_usd() == 2.6 and len(store.items) == 1  # not even written


def test_a_hold_that_loses_the_race_is_taken_back() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.5)
    fired: list[int] = []

    def other_writes(path: str) -> None:
        if "/h-250000-" in path and not fired:  # another instance's hold lands after ours
            fired.append(1)
            store.items[f"ledger/{LEDGER_ID}/2026-10-30/h-250000-0-{'b' * 32}.json"] = b"{}"

    store.after_put = other_writes
    assert ledger(store).reserve(0.25, 2.8) is False  # 2.5 + 0.25 + 0.25 > 2.8
    assert store.ledger_usd() == pytest.approx(2.75)  # only the other hold is left; ours is gone


def test_cold_start_keeps_the_total() -> None:
    store = FakeBlobStore()
    assert ledger(store).reserve(1.0, 2.7)
    fresh = ledger(store)  # a new object, as after a cold start: only the store remembers
    assert fresh.spent_today() == 1.0
    assert fresh.reserve(1.0, 2.7) and not fresh.reserve(1.0, 2.7)


def test_concurrent_reservations_never_pass_the_cap() -> None:
    store = FakeBlobStore()
    results: list[bool] = []
    guard = threading.Lock()

    def worker() -> None:
        ok = ledger(store).reserve(0.25, 2.7)  # separate objects, as separate requests
        with guard:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # no process lock exists: overlapping holds may refuse each other (fail closed), never pass
    assert sum(results) <= 10
    assert store.ledger_usd() == pytest.approx(0.25 * sum(results))
    assert store.ledger_usd() <= 2.7


def test_two_instances_interleaved_lose_nothing() -> None:
    """Instance A and B reserve the same amount; nothing is read-modify-written."""
    store = FakeBlobStore()
    a, b = ledger(store), ledger(store)
    assert a.reserve(0.25, 2.7) and b.reserve(0.25, 2.7)
    assert store.ledger_usd() == pytest.approx(0.50)
    a.add(0.04, 1)
    b.add(0.05, 1)
    a.release(0.25)
    b.release(0.25)
    assert store.ledger_usd() == pytest.approx(0.09)  # equals the real spend
    assert a.spent_today() == pytest.approx(0.09)
    assert b.spent_today() == pytest.approx(0.09) and b.spent_today() <= 3.0


def test_same_total_writes_from_two_instances_both_count() -> None:
    store = FakeBlobStore()
    a, b = ledger(store), ledger(store)
    a.add(0.25, 1)
    b.add(0.25, 1)  # same amount, same moment: two objects, total 0.50
    assert a.spent_today() == pytest.approx(0.5)


def test_unreadable_unwritable_or_corrupt_ledger_fails_closed() -> None:
    store = FakeBlobStore()
    store.fail_list = True
    with pytest.raises(BlobLedgerError):
        ledger(store).reserve(0.25, 2.7)
    with pytest.raises(BlobLedgerError):
        ledger(store).spent_today()
    store.fail_list = False
    store.fail_put = True
    with pytest.raises(BlobLedgerError):
        ledger(store).reserve(0.25, 2.7)
    store.fail_put = False
    store.items[f"ledger/{LEDGER_ID}/2026-10-30/garbage.json"] = b"not json"
    with pytest.raises(BlobLedgerError):
        ledger(store).reserve(0.25, 2.7)  # an unparseable entry is an error, never zero
    with pytest.raises(BlobLedgerError):
        ledger(store).spent_today()


def test_enforced_cap_is_the_daily_total_minus_the_largest_request() -> None:
    assert blob_enforced_cap({}) == pytest.approx(3.0 - 0.30)
    env = {"MAUDESIGNAL_LIVE_DAILY_USD": "3", "MAUDESIGNAL_API_REQUEST_USD": "0.5"}
    assert blob_enforced_cap(env) == pytest.approx(2.5)
    cfg = LiveConfig(daily_usd=3.0, ask_usd=0.25, voice_usd=0.3, label_usd=0.3)
    assert cfg.effective_daily_usd(shared=True, race_margin=cfg.largest_request_usd({})) == 2.7


def test_state_picks_blob_only_for_a_private_blob_store() -> None:
    state = ConnectorState()
    assert state.global_mode == "none" and state.global_ledger("x") is None
    state.attach_blob(MemoryStore())
    assert state.global_mode == "none"
    state.attach_blob(FakeBlobStore())
    assert state.global_mode == "blob" and isinstance(state.global_ledger("x"), BlobLedger)


def blob_env(tmp_path: Path, store: FakeBlobStore, **kw: Any) -> Env:
    return Env(
        tmp_path,
        store=store,
        config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_per_day=1000),
        **kw,
    )


def test_live_ask_reserves_before_the_call_and_settles_on_the_shared_ledger(tmp_path: Path) -> None:
    store = FakeBlobStore()
    seen_during_call: list[float] = []
    env = blob_env(tmp_path, store)
    original = env.spark._create

    def watching(**kwargs: Any) -> Any:
        seen_during_call.append(store.ledger_usd())  # the hold is already on the ledger
        return original(**kwargs)

    env.spark.chat.completions.create = watching  # type: ignore[assignment]
    body = env.ask().json()
    assert body["mode"] == "live"
    assert seen_during_call and seen_during_call[0] >= 0.25
    after = store.ledger_usd()
    assert 0 < after < 0.25  # the hold was returned; the real (small) cost stays
    assert body["cost_usd"] == pytest.approx(after, abs=1e-5)


def test_cold_start_keeps_the_cap_through_the_route(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.6)  # yesterday's instance left this behind; the enforced cap is 2.70
    env = blob_env(tmp_path, store)  # a brand new app, as after a cold start
    body = env.ask().json()
    assert body["mode"] == "recorded" and not env.spark.requests
    assert store.ledger_usd() == 2.6  # nothing was held or added


def test_unreadable_ledger_gives_a_recorded_answer_and_no_model_call(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = blob_env(tmp_path, store)
    store.fail_list = True
    body = env.ask().json()
    assert body["mode"] == "recorded" and not env.spark.requests
    store.fail_list = False
    store.fail_put = True
    assert env.ask().json()["mode"] == "recorded" and not env.spark.requests


def test_total_never_exceeds_the_daily_cap_over_many_asks(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.40)
    env = blob_env(tmp_path, store)
    modes = []
    for _ in range(30):
        modes.append(env.ask().json()["mode"])
        assert store.ledger_usd() <= 3.0
    assert "live" in modes  # room for one more hold below the enforced cap of 2.70
    store.seed_ledger(2.69)  # the hold no longer fits: stored answers from here on
    calls = len(env.spark.requests)
    assert [env.ask().json()["mode"] for _ in range(5)] == ["recorded"] * 5
    assert len(env.spark.requests) == calls and store.ledger_usd() == 2.69


def test_keyed_ask_counts_against_the_same_global_ledger(tmp_path: Path) -> None:
    store = FakeBlobStore()
    state = ConnectorState()
    state.attach_blob(store)
    today = datetime.now(UTC).date()
    d = ConnectorData(work_dir=tmp_path / "w")
    client = FakeClient(SCRIPT)
    rt = live_runtime(tmp_path, client)
    rt.state = state
    from maudesignal.connector.ask import ask

    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert a.provenance.kind == "live_model"
    spent = store.ledger_usd(today)
    assert spent > 0 and spent == pytest.approx(rt.ledger_for("abc").spent_today())
    # the global cap is shared with the live routes: at the cap the keyed tool answers recorded
    store.seed_ledger(2.69, today)
    calls = client.n
    b = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert b.provenance.kind == "recorded_answer" and client.n == calls
    store.fail_list = True
    from maudesignal.connector import ask as ask_mod

    reasons: list[str] = []
    real = ask_mod._outcome_recorded

    def spy(best: Any, reason: str, *a: Any, **kw: Any) -> Any:
        reasons.append(reason)
        return real(best, reason, *a, **kw)

    ask_mod._outcome_recorded = spy  # type: ignore[assignment]
    try:
        c = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    finally:
        ask_mod._outcome_recorded = real  # type: ignore[assignment]
    assert c.provenance.kind == "recorded_answer" and client.n == calls  # fail closed
    assert reasons == ["cap"]  # not "model_error": the ledger, not the model, was unavailable


# --- 2. redact old names -------------------------------------------------------------------


def feedback_record(rid: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": rid,
        "rating": 4,
        "comment": "ok",
        "blocker": "none",
        "one_thing": "x",
        "consent": "no_quote",
        "ref": "r1",
        "page": "/",
        **kw,
    }


def admin_app(store: Any, tmp_path: Path) -> TestClient:
    import os

    os.environ["MAUDESIGNAL_ADMIN_KEY"] = ADMIN
    try:
        app = create_app(
            Settings(
                keys=KeyStore([]),
                limiter=RateLimiter(100),
                data=ConnectorData(work_dir=tmp_path / "w"),
                feedback_store=store,
                web_origins=tuple(ORIGINS),
            )
        )
    finally:
        os.environ.pop("MAUDESIGNAL_ADMIN_KEY", None)
    return TestClient(app, raise_server_exceptions=False)


def seed_feedback(store: Any) -> None:
    store.put_json("feedback/2026-10-30/a.json", feedback_record("a", name="Jane Doe", role="QA"))
    store.put_json(
        "feedback/2026-10-30/b.json",
        feedback_record("b", name="Sam Roe", consent="quote_name_role", role="RA"),
    )
    store.put_json("feedback/2026-10-30/c.json", feedback_record("c", name="  "))
    store.put_json("feedback/2026-10-30/d.json", feedback_record("d"))
    store.put_json("visits/2026-10-30/v.json", {"id": "v", "ref": "r1", "page": "/", "name": "Vis"})


def stored(store: Any, path: str) -> dict[str, Any]:
    return json.loads(store.get(BlobRef(path, path)))  # type: ignore[no-any-return]


@pytest.mark.parametrize("store_cls", [MemoryStore, FakeBlobStore])
def test_redact_names_dry_run_then_real(tmp_path: Path, store_cls: Any) -> None:
    store = store_cls()
    seed_feedback(store)
    c = admin_app(store, tmp_path)
    h = {"X-Admin-Key": ADMIN}
    dry = c.post("/v1/admin/redact-names", json={"dry_run": True}, headers=h)
    assert dry.status_code == 200
    assert dry.json() == {
        "checked": 4,
        "names_removed": 1,
        "names_kept_for_quote_by_name": 1,
        "dry_run": True,
        "failed": 0,
    }
    assert stored(store, "feedback/2026-10-30/a.json")["name"] == "Jane Doe"  # untouched
    real = c.post("/v1/admin/redact-names", json={"dry_run": False}, headers=h).json()
    assert (real["names_removed"], real["names_kept_for_quote_by_name"]) == (1, 1)
    a = stored(store, "feedback/2026-10-30/a.json")
    assert "name" not in a and a["role"] == "QA" and a["comment"] == "ok"  # only the name went
    assert stored(store, "feedback/2026-10-30/b.json")["name"] == "Sam Roe"  # quote by name: kept
    assert stored(store, "feedback/2026-10-30/c.json")["name"] == "  "  # empty: not touched
    assert stored(store, "visits/2026-10-30/v.json")["name"] == "Vis"  # visits: never touched
    again = c.post("/v1/admin/redact-names", json={"dry_run": False}, headers=h).json()
    assert again["names_removed"] == 0 and again["names_kept_for_quote_by_name"] == 1


def test_redact_names_needs_the_admin_key_and_valid_body(tmp_path: Path) -> None:
    store = MemoryStore()
    seed_feedback(store)
    c = admin_app(store, tmp_path)
    assert c.post("/v1/admin/redact-names", json={"dry_run": False}).status_code == 401
    bad = {"X-Admin-Key": "wrong-key"}
    assert c.post("/v1/admin/redact-names", json={"dry_run": False}, headers=bad).status_code == 401
    assert stored(store, "feedback/2026-10-30/a.json")["name"] == "Jane Doe"
    h = {"X-Admin-Key": ADMIN}
    for body in (
        '{"dry_run": "yes"}',
        '{"dry_run": 1}',
        "[1]",
        '{"dry_run": true, "x": 1}',
        "nope",
    ):
        r = c.post(
            "/v1/admin/redact-names", content=body, headers=h | {"content-type": "application/json"}
        )
        assert r.status_code == 422, body
    assert stored(store, "feedback/2026-10-30/a.json")["name"] == "Jane Doe"


def test_redact_names_store_down_and_write_failure(tmp_path: Path) -> None:
    store = FakeBlobStore()
    seed_feedback(store)
    c = admin_app(store, tmp_path)
    h = {"X-Admin-Key": ADMIN}
    store.fail_put = True
    r = c.post("/v1/admin/redact-names", json={"dry_run": False}, headers=h).json()
    assert r["names_removed"] == 0 and r["failed"] == 1  # not counted as removed
    store.fail_put = False
    store.fail_list = True
    assert c.post("/v1/admin/redact-names", json={"dry_run": True}, headers=h).status_code == 503


def test_admin_page_has_the_remove_names_button_with_confirm(tmp_path: Path) -> None:
    c = admin_app(MemoryStore(), tmp_path)
    page = c.get("/admin").text
    assert "Remove names (keep only 'quote me by name')" in page
    assert "confirm(" in page and "dry_run:dry" in page


# --- 3. outside mentions -------------------------------------------------------------------

RECALL_SENTENCE = "The firm recalled the LLZ imaging system after a software fault was found."
GOOD_SENTENCE = "The agency said the LLZ image processing software had a labeling problem in 2026."
GDELT = {
    "articles": [
        {
            "url": "https://news.example.com/a",
            "title": GOOD_SENTENCE,
            "seendate": "20261030T120000Z",
        },
        {
            "url": "https://news.example.com/b",
            "title": "LLZ software update draws a long and detailed review.",
            "seendate": "20261029T010000Z",
        },
        {
            "url": "https://news.example.com/c",
            "title": "Patient John Smith reported that the LLZ device failed him.",
            "seendate": "20261028T000000Z",
        },
        {
            "url": "https://news.example.com/d",
            "title": "A story about something else entirely, long enough to count.",
            "seendate": "20261027T000000Z",
        },
    ]
}


def rss(items: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
        "<pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item>"
        for t, u, d in items
    )
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>"


class FakeHttp:
    """Maps a URL prefix to ``(status, body)``; anything else is a network error."""

    def __init__(self, routes: dict[str, tuple[int, str]]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        self.requested.append(url)
        best = max((p for p in self.routes if url.startswith(p)), key=len, default=None)
        if best is None:
            raise ConnectionError("no route")
        return self.routes[best]


def page(sentence: str) -> str:
    return (
        "<html><head><title>x</title><script>var a='LLZ';</script></head>"
        f"<body><p>{sentence}</p></body></html>"
    )


def standard_http() -> FakeHttp:
    return FakeHttp(
        {
            "https://api.gdeltproject.org/": (200, json.dumps(GDELT)),
            "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/": (
                200,
                rss(
                    [
                        (
                            "Recall of LLZ system",
                            "https://www.fda.gov/safety/recalls/1",
                            RECALL_SENTENCE,
                        )
                    ]
                ),
            ),
            "https://www.fda.gov/": (500, ""),
            "https://www.medtechdive.com/": (200, "<rss><channel></channel></rss>"),
            "https://www.massdevice.com/": (200, "not xml"),
            "https://news.example.com/a": (200, page(GOOD_SENTENCE)),
            # b: the headline offered by the source is NOT on the fetched page
            "https://news.example.com/b": (
                200,
                page("Something unrelated, but LLZ is named here in a long enough line."),
            ),
            "https://news.example.com/c": (
                200,
                page("Patient John Smith reported that the LLZ device failed him."),
            ),
            "https://news.example.com/d": (
                200,
                page("Nothing about the product code at all in this long sentence."),
            ),
            "https://www.fda.gov/safety/recalls/1": (
                200,
                page("The firm recalled the LLZ imaging system after a software fault was found."),
            ),
        }
    )


def run_search(http: FakeHttp) -> mn.SearchResult:
    return mn.search_mentions(
        "llz", ["image processing"], http, now=lambda: datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
    )


def test_quote_not_on_the_page_personal_details_and_off_topic_are_dropped() -> None:
    r = run_search(standard_http())
    quotes = {m["quote"] for m in r.mentions}
    assert GOOD_SENTENCE in quotes
    assert not any("John Smith" in q for q in quotes)  # personal details
    assert not any("long and detailed review" in q for q in quotes)  # not on the fetched page
    assert r.dropped == {"quote_not_found": 1, "personal_details": 1, "off_topic": 1}
    for m in r.mentions:
        assert m["badge"] == mn.BADGE and m["why_matched"].startswith(
            "The quoted sentence contains"
        )
        assert m["quote"] in mn.page_text(standard_http().routes[m["url"]][1])
        assert set(m) == {
            "source_name",
            "source_kind",
            "date",
            "url",
            "quote",
            "why_matched",
            "badge",
        }


def test_fda_host_is_official_and_news_is_news() -> None:
    r = run_search(standard_http())
    kinds = {m["url"]: m["source_kind"] for m in r.mentions}
    assert kinds["https://www.fda.gov/safety/recalls/1"] == "official"
    assert kinds["https://news.example.com/a"] == "news"
    assert r.mentions and r.network_ok


def test_sources_tried_report_each_status_and_search_terms_are_not_echoed() -> None:
    r = run_search(standard_http())
    status = {s["name"]: s["status"] for s in r.sources_tried}
    assert status["GDELT DOC 2.0 (news index)"] == "ok"
    assert status["FDA press releases (RSS)"].startswith("failed")
    assert status["MassDevice (RSS)"].startswith("failed")
    assert all("?" not in s["url"] and "LLZ" not in s["url"] for s in r.sources_tried)
    assert all(set(s) == {"name", "url", "status", "n"} for s in r.sources_tried)
    assert all({"step", "ms", "status"} <= set(t) for t in r.trace)


def test_everything_unreachable_is_not_a_live_result() -> None:
    r = run_search(FakeHttp({}))
    assert not r.network_ok and r.mentions == []


def test_at_most_ten_mentions_and_forbidden_words_are_dropped() -> None:
    items = [
        (
            f"LLZ report number {i} is described here in some detail",
            f"https://news.example.com/n{i}",
            f"LLZ report number {i} is described here in some detail.",
        )
        for i in range(12)
    ]
    routes = {"https://api.gdeltproject.org/": (200, json.dumps({"articles": []}))}
    routes["https://www.medtechdive.com/"] = (200, rss(items))
    for i in range(12):
        routes[f"https://news.example.com/n{i}"] = (
            200,
            page(f"LLZ report number {i} is described here in some detail."),
        )
    r = mn.search_mentions(
        "LLZ", [], FakeHttp(routes), sources=tuple(s for s in mn.SOURCES if "MedTech" in s.name)
    )
    assert len(r.mentions) <= 8  # per-source candidate cap; never more than 10 in any case
    banned = mn.search_mentions(
        "LLZ",
        [],
        FakeHttp(
            {
                "https://www.medtechdive.com/": (
                    200,
                    rss(
                        [
                            (
                                "LLZ",
                                "https://news.example.com/x",
                                "The LLZ device was approved by the agency last week as stated.",
                            )
                        ]
                    ),
                ),
                "https://news.example.com/x": (
                    200,
                    page("The LLZ device was approved by the agency last week as stated."),
                ),
            }
        ),
        sources=tuple(s for s in mn.SOURCES if "MedTech" in s.name),
    )
    assert banned.mentions == [] and banned.dropped["off_topic"] == 1


@pytest.mark.parametrize(
    "sentence",
    [
        "Mrs. Jones said the LLZ system stopped during her scan last week at the clinic.",
        "A 67-year-old man was scanned with the LLZ system when the fault happened to it.",
        "Contact jane@example.com about the LLZ system fault that was found last week.",
        "Call 555-123-4567 about the LLZ system fault that was found last week in the field.",
        "The LLZ system fault was reported for patient Brown during a routine check last week.",
    ],
)
def test_personal_detail_patterns(sentence: str) -> None:
    assert mn.has_personal_details(sentence)


def test_plain_sentences_are_not_personal_details() -> None:
    assert not mn.has_personal_details(GOOD_SENTENCE)
    assert not mn.has_personal_details(
        "The U.S. Food and Drug Administration posted a recall for LLZ devices."
    )


def make_recorded(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "LLZ.json").write_text(
        json.dumps(
            {
                "product_code": "LLZ",
                "searched_utc": "2026-10-29T10:00:00Z",
                "sources_tried": [],
                "mentions": [
                    {
                        "source_name": "x",
                        "source_kind": "news",
                        "date": "2026-10-28",
                        "url": "https://n.example/1",
                        "quote": "A stored sentence about LLZ devices.",
                        "why_matched": "w",
                        "badge": "old",
                    }
                ],
                "dropped": {"quote_not_found": 0, "personal_details": 0, "off_topic": 0},
                "trace": [],
                "mode": "recorded",
            }
        )
    )


def test_route_live_shape_and_label(tmp_path: Path) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    r = env.client.post(
        "/v1/live/mentions", json={"product_code": "llz", "device_terms": ["image processing"]}
    )
    assert r.status_code == 200
    b = r.json()
    assert (
        b["mode"] == "live" and b["label"] == "news and public web" and b["product_code"] == "LLZ"
    )
    assert {"searched_utc", "sources_tried", "mentions", "dropped", "trace", "limits"} <= set(b)
    assert "recorded_note" not in b and len(b["mentions"]) <= 10
    assert b["limits"]["remaining_today"] == 9
    assert all(m["badge"] == mn.BADGE for m in b["mentions"])
    # source_kind is a fixed machine value ("official" | "news" | "web") the contract requires;
    # every free-text field is screened
    shown = {
        **b,
        "mentions": [{k: v for k, v in m.items() if k != "source_kind"} for m in b["mentions"]],
    }
    assert not forbidden_in(json.dumps(shown))
    assert {m["source_kind"] for m in b["mentions"]} <= {"official", "news", "web"}


def test_route_falls_back_to_the_stored_file_when_nothing_is_reachable(tmp_path: Path) -> None:
    make_recorded(tmp_path / "stored")
    env = Env(tmp_path, fetcher=FakeHttp({}), mentions_dir=tmp_path / "stored")
    b = env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()
    assert b["mode"] == "recorded" and "2026-10-29" in b["recorded_note"]
    assert b["mentions"][0]["badge"] == mn.BADGE  # the badge is always the current one
    none = env.client.post("/v1/live/mentions", json={"product_code": "QIH"}).json()
    assert (
        none["mode"] == "recorded"
        and none["mentions"] == []
        and "No stored mentions" in none["recorded_note"]
    )


def test_mentions_are_inside_the_global_cost_cap_even_without_a_model(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.70)  # the enforced cap is 2.70
    make_recorded(tmp_path / "stored")
    http = standard_http()
    env = blob_env(tmp_path, store, fetcher=http, mentions_dir=tmp_path / "stored")
    b = env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()
    assert b["mode"] == "recorded" and "budget is used up" in b["recorded_note"]
    assert http.requested == [], "no fetch starts once the cap is reached"
    assert store.ledger_usd() == 2.70
    store.fail_list = True  # unreadable ledger: fail closed
    assert (
        env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()["mode"]
        == "recorded"
    )
    store.fail_list = False
    store.seed_ledger(1.0)
    ok = env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()
    assert ok["mode"] == "live" and store.ledger_usd() == 1.0
    assert len(store.items) == 1  # a free route writes nothing to the ledger


def test_mentions_per_ip_limit_is_ten_per_day(tmp_path: Path) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    codes = [
        env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"product_code": "LL"},
        {"product_code": "LLZ1"},
        {"product_code": 123},
        {"product_code": "LLZ", "device_terms": "x"},
        {"product_code": "LLZ", "device_terms": ["a", "b", "c", "d", "e", "f"]},
        {"product_code": "LLZ", "device_terms": [""]},
        {"product_code": "LLZ", "device_terms": ["x" * 61]},
        {"product_code": "LLZ", "device_terms": [5]},
        {"product_code": "LLZ", "extra": 1},
        [],
        "text",
        None,
    ],
)
def test_mentions_rejects_malformed_bodies(tmp_path: Path, body: Any) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    r = env.client.post("/v1/live/mentions", json=body)
    assert r.status_code == 422
    assert (
        env.client.post(
            "/v1/live/mentions", content=b"{bad", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )


def test_mentions_refuses_patient_details_in_terms_and_big_bodies(tmp_path: Path) -> None:
    http = standard_http()
    env = Env(tmp_path, fetcher=http)
    r = env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ", "device_terms": ["Mrs. Jones"]}
    )
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert http.requested == []
    big = env.client.post("/v1/live/mentions", content=b"x" * 70_000)
    assert big.status_code == 413


def test_mentions_cors_allows_only_listed_origins(tmp_path: Path) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    ok = env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ"}, headers={"Origin": ORIGIN}
    )
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    bad = env.client.post(
        "/v1/live/mentions",
        json={"product_code": "LLZ"},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers
    assert "/v1/live/mentions" not in env.client.get("/openapi.json").json()["paths"]


def test_http_fetcher_refuses_private_and_non_http_urls() -> None:
    f = mn.HttpFetcher()
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest",
    ):
        with pytest.raises(ValueError):
            f.get(url, 1.0)


def test_record_script_parses_requests_and_the_request_file_is_off() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "record_mentions", root / "scripts" / "record_mentions.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.parse_request("0\n")) == {"LLZ"}
    got = mod.parse_request("1 qih\njak=heart monitor;ecg  # note\n# only a comment\n")
    assert set(got) == {"LLZ", "QIH", "JAK"} and got["JAK"] == ["heart monitor", "ecg"]
    assert (root / "demo" / "mentions" / "REQUEST").read_text().strip() == "0"
    wf = (root / ".github" / "workflows" / "mentions-record.yml").read_text()
    assert "branches: [track-c-live]" in wf and 'paths: ["demo/mentions/REQUEST"]' in wf
    assert "secrets." not in wf and "META_MODEL_API_KEY" not in wf


# --- 4/5. demo key, labels, two keys, /v1/connect ---------------------------------------------

KEY_A = "key-a-NOT-A-REAL-SECRET-0123456789ab"
KEY_B = "key-b-NOT-A-REAL-SECRET-0123456789cd"
DEMO = "demo-key-PUBLIC-ON-PURPOSE-0123456789"


def keyed_client(
    tmp_path: Path, env: dict[str, str], **kw: Any
) -> tuple[TestClient, RecordingSpark, Any]:
    spark = RecordingSpark()

    def factory(d: ConnectorData, guard: Any) -> Any:
        from maudesignal.copilot.agent import CopilotAgent

        return CopilotAgent(guard.wrap(spark), d.tool_context())

    runtime = AskRuntime(
        agent_factory=factory,
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=1.0, session_calls=20, daily_usd=5.0),
        ledger_dir=tmp_path / "led",
    )
    settings = Settings(
        keys=KeyStore.from_env(env),
        data=ConnectorData(work_dir=tmp_path / "w"),
        live_checker=fake_check,
        ask_runtime=runtime,
        web_origins=tuple(ORIGINS),
        feedback_store=MemoryStore(),
        **kw,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), spark, settings


def test_several_keys_each_revocable_and_plain_and_hashed_entries_work(tmp_path: Path) -> None:
    both = {"MAUDESIGNAL_API_KEYS": f"{KEY_A},sha256:{sha256_hex(KEY_B)}"}
    c, _, _ = keyed_client(tmp_path, both)
    assert (
        c.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_A}).status_code == 200
    )
    assert (
        c.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_B}).status_code == 200
    )
    only_b = {"MAUDESIGNAL_API_KEYS": f"sha256:{sha256_hex(KEY_B)}"}  # key A revoked by deleting it
    c2, _, _ = keyed_client(tmp_path, only_b)
    assert (
        c2.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_A}).status_code
        == 401
    )
    assert (
        c2.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_B}).status_code
        == 200
    )


def test_labels_are_parsed_and_shown_in_the_audit_actor(tmp_path: Path) -> None:
    env = {"MAUDESIGNAL_API_KEYS": f"charan={KEY_A},meta-review=sha256:{sha256_hex(KEY_B)}"}
    ks = KeyStore.from_env(env)
    ma, mb = ks.match(KEY_A), ks.match(KEY_B)
    assert ma and ma.label == "charan" and not ma.demo
    assert mb and mb.label == "meta-review" and mb.key_id != ma.key_id
    assert ks.verify(KEY_A) == ma.key_id and ks.match("nope") is None
    c, _, settings = keyed_client(tmp_path, env)
    assert (
        c.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_B}).status_code == 200
    )
    rows = settings.state.audit_recent(5)
    assert (
        rows
        and rows[-1]["actor"] == f"connector:key:meta-review:{mb.key_id}"
        or rows[0]["actor"] == f"connector:key:meta-review:{mb.key_id}"
    )
    assert KEY_B not in json.dumps(rows)
    # a plain key without a label still audits as before
    c3, _, s3 = keyed_client(tmp_path, {"MAUDESIGNAL_API_KEYS": KEY_A})
    c3.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_A})
    assert all(":" not in r["actor"].split("connector:key:")[-1] for r in s3.state.audit_recent(5))


def test_label_syntax_edge_cases() -> None:
    ks = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"bad label={KEY_A}, x={'y' * 10}, {KEY_B}"})
    assert ks.match(KEY_B) is not None and ks.match(KEY_B).label is None  # type: ignore[union-attr]
    assert ks.match("y" * 10) is None  # a short key behind a label is still refused
    padded = "z" * 40 + "="
    assert KeyStore.from_env({"MAUDESIGNAL_API_KEYS": padded}).match(padded) is not None


def demo_env() -> dict[str, str]:
    return {
        "MAUDESIGNAL_API_KEYS": KEY_A,
        "MAUDESIGNAL_DEMO_KEYS": f"{DEMO},demo-two-PUBLIC-0123456789abcdefgh",
    }


def test_demo_key_reads_but_never_starts_a_live_call(tmp_path: Path) -> None:
    c, spark, _ = keyed_client(tmp_path, demo_env())
    h = {"X-API-Key": DEMO}
    assert c.get("/v1/tools/recalls?product_code=LLZ", headers=h).status_code == 200
    assert c.get("/v1/tools/what_changed_this_week?product_code=LLZ", headers=h).status_code == 200
    r = c.post("/v1/tools/ask", json={"question": QUESTION}, headers=h)
    assert r.status_code == 200 and r.json()["provenance"]["kind"] == "recorded_answer"
    assert "demo key" in r.json()["provenance"]["note"] and not spark.requests
    # a full key on the same server does start a live call
    full = c.post("/v1/tools/ask", json={"question": QUESTION}, headers={"X-API-Key": KEY_A})
    assert full.json()["provenance"]["kind"] == "live_model" and spark.requests


def test_demo_key_has_its_own_lower_per_minute_limit(tmp_path: Path) -> None:
    c, _, _ = keyed_client(tmp_path, demo_env(), demo_limiter=RateLimiter(3))
    h = {"X-API-Key": DEMO}
    codes = [c.get("/v1/tools/recalls?product_code=LLZ", headers=h).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert (
        c.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY_A}).status_code == 200
    )


def test_demo_key_daily_limit_is_200(tmp_path: Path) -> None:
    c, _, _ = keyed_client(tmp_path, demo_env(), demo_limiter=RateLimiter(10_000))
    h = {"X-API-Key": DEMO}
    codes = [c.get("/v1/tools/recalls?product_code=LLZ", headers=h).status_code for _ in range(201)]
    assert codes.count(200) == 200 and codes[-1] == 429


def test_demo_default_rate_is_ten_and_env_configurable() -> None:
    assert RateLimiter.from_env({}, name="MAUDESIGNAL_DEMO_RATE_PER_MIN", default=10).limit == 10
    env = {"MAUDESIGNAL_DEMO_RATE_PER_MIN": "4"}
    assert RateLimiter.from_env(env, name="MAUDESIGNAL_DEMO_RATE_PER_MIN", default=10).limit == 4


def test_connect_without_a_key_has_the_documented_shape(tmp_path: Path) -> None:
    c, _, _ = keyed_client(tmp_path, demo_env())
    r = c.get("/v1/connect", headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGIN
    b = r.json()
    assert b["auth_header"] == "X-API-Key" and b["demo_key"] == DEMO
    assert b["mcp_url"].endswith("/mcp") and b["openapi_url"].endswith("/openapi.json")
    assert b["docs_url"].endswith("/docs-page")
    assert b["demo_limits"] == {
        "per_minute": 10,
        "per_day": 200,
        "live_model": False,
        "note": "Read tools only. ask returns a recorded answer, labelled recorded.",
    }
    assert len(b["steps"]) == 3
    assert KEY_A not in r.text  # the demo key is public by design; a full key never is
    other = c.get("/v1/connect", headers={"Origin": "https://evil.example"})
    assert other.status_code == 200 and "access-control-allow-origin" not in other.headers


def test_connect_demo_key_is_null_when_unset_or_only_a_digest(tmp_path: Path) -> None:
    c, _, _ = keyed_client(tmp_path, {"MAUDESIGNAL_API_KEYS": KEY_A})
    assert c.get("/v1/connect").json()["demo_key"] is None
    c2, _, _ = keyed_client(
        tmp_path,
        {"MAUDESIGNAL_API_KEYS": KEY_A, "MAUDESIGNAL_DEMO_KEYS": f"sha256:{sha256_hex(DEMO)}"},
    )
    assert c2.get("/v1/connect").json()["demo_key"] is None
    c3, _, _ = keyed_client(
        tmp_path, {"MAUDESIGNAL_API_KEYS": KEY_A, "MAUDESIGNAL_DEMO_KEYS": f"public={DEMO}"}
    )
    assert c3.get("/v1/connect").json()["demo_key"] == DEMO


def test_connect_uses_the_public_url_env_and_does_not_echo_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_PUBLIC_URL", "https://api.example.org/")
    c, _, _ = keyed_client(tmp_path, demo_env())
    b = c.get(
        "/v1/connect", headers={"X-API-Key": KEY_A, "Authorization": "Bearer secret-token-xyz"}
    ).json()
    assert b["mcp_url"] == "https://api.example.org/mcp"
    assert KEY_A not in json.dumps(b) and "secret-token-xyz" not in json.dumps(b)


def test_the_demo_key_is_not_committed() -> None:
    root = Path(__file__).resolve().parents[2]
    for f in ("vercel.json", "api/openapi.json", "docs/hackathon/MUSE_CONNECTOR.md"):
        assert DEMO not in (root / f).read_text(encoding="utf-8")


# --- 6. privacy and terms --------------------------------------------------------------------


def test_pages_render_with_contact_from_env_and_fallback(tmp_path: Path) -> None:
    c, _, _ = keyed_client(tmp_path, {"MAUDESIGNAL_API_KEYS": KEY_A})
    for path in ("/privacy", "/terms"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert (
            "<h1>" in r.text
            and "https://github.com/kondapallysaicharan63-bot/maudesignal/issues" in r.text
        )
        assert "http://" not in r.text.replace("http://www.w3.org", "") and "<link" not in r.text
        assert "src=" not in r.text  # no external assets
    assert contact_line({"MAUDESIGNAL_CONTACT_EMAIL": "help@example.org"}) == (
        "help@example.org",
        "mailto:help@example.org",
    )
    assert "help@example.org" in render_privacy({"MAUDESIGNAL_CONTACT_EMAIL": "help@example.org"})
    assert "help@example.org" in render_terms({"MAUDESIGNAL_CONTACT_EMAIL": "help@example.org"})
    evil = '"><script>alert(1)</script>@x.org'
    assert "<script" not in render_privacy(
        {"MAUDESIGNAL_CONTACT_EMAIL": evil}
    )  # not an address: fallback
    assert contact_line({"MAUDESIGNAL_CONTACT_EMAIL": evil})[0].startswith("https://github.com/")


def test_privacy_answers_the_data_questionnaire() -> None:
    import html as _html

    text = _html.unescape(render_privacy({}))
    for needle in (
        "iad1",
        "Vercel",
        "Blob",
        "Meta Model API",
        "openFDA",
        "GOV.UK",
        "GDELT",
        "Vercel's runtime-log retention for this plan",
        "30 November 2026",
        "No sale of data",
        "No tracking cookies",
        "never stores an IP address",
        "region of that store is chosen when the store is created",
        "in their own locations",
        "not medical advice",
        "Saicharan Kondapally",
        "How do I ask for deletion?",
    ):
        assert needle.lower() in text.lower(), needle
    assert "@" not in text.replace("@media", "")  # no personal email in git or in the default page
    assert "any other country" not in text  # a claim nothing in the code can support
    from maudesignal.connector.legal_pages import STATIC_ANSWERS

    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
    ).read_text(encoding="utf-8")
    for question, answer in STATIC_ANSWERS:  # one text, two places
        assert answer in doc, question


def test_pages_contain_no_forbidden_words() -> None:
    for text in (render_privacy({}), render_terms({})):
        assert not forbidden_in(text) and not has_drop_word(text)
    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
    ).read_text(encoding="utf-8")
    top = doc.split("# Part 2.")[0] if "# Part 2." in doc else doc
    assert top  # the form-answer section is checked in test_connector_doc_is_the_single_source


def test_openapi_info_links_the_terms_and_docs_page_links_both() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = json.loads((root / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["termsOfService"].endswith("/terms")
    assert (
        '"/privacy"' in (root / "vercel.json").read_text()
        or "/privacy" in (root / "vercel.json").read_text()
    )
    html = (root / "api" / "docs.html").read_text(encoding="utf-8")
    assert 'href="/privacy"' in html and 'href="/terms"' in html


# --- 7/8. the single source doc and the icon ---------------------------------------------------


def test_connector_doc_is_the_single_source() -> None:
    root = Path(__file__).resolve().parents[2]
    doc = (root / "docs" / "hackathon" / "MUSE_CONNECTOR.md").read_text(encoding="utf-8")
    assert "## Form answers" in doc and "## Data questionnaire" in doc
    form = doc.split("## Form answers", 1)[1].split("\n## ", 2)
    section = "## Form answers" + "".join(form[:1])
    for needle in (
        "Not submitted",
        "X-API-Key",
        "maudesignal-icon.svg",
        "/privacy",
        "/terms",
        "MAUDESIGNAL_CONTACT_EMAIL",
        "$3.00",
        "demo key",
        "meta-review",
    ):
        assert needle in doc, needle
    quest = doc.split("## Data questionnaire", 1)[1].split("\n## ", 1)[0]
    assert not forbidden_in(section + quest) and not has_drop_word(section + quest)
    for q, a in __import__("maudesignal.connector.legal_pages", fromlist=["x"]).STATIC_ANSWERS:
        assert a in quest, q  # the same answers as the page


def test_icon_files_exist_and_are_512_square_without_logos() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "hackathon"
    svg = (root / "maudesignal-icon.svg").read_text(encoding="utf-8")
    assert 'width="512"' in svg and 'height="512"' in svg and 'viewBox="0 0 512 512"' in svg
    assert "<image" not in svg and "http" not in svg.replace("http://www.w3.org/2000/svg", "")
    from PIL import Image

    with Image.open(root / "maudesignal-icon.png") as im:
        assert im.size == (512, 512)


# --- security: nothing personal or secret in logs, ledgers or records -------------------------


def test_no_address_key_or_query_text_in_logs_or_the_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FakeBlobStore()
    env = blob_env(tmp_path, store, fetcher=standard_http())
    env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ", "device_terms": ["secret device phrase"]}
    )
    env.ask("What changed this week for LLZ? unique-question-marker")
    env.client.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY})
    seen = capsys.readouterr()
    logged = seen.out + seen.err
    for needle in (
        "testclient",
        "127.0.0.1",
        KEY,
        "secret device phrase",
        "unique-question-marker",
    ):
        assert needle not in logged, needle
    stored_text = b"".join(store.items.values()).decode()
    for needle in ("testclient", KEY, "secret device phrase", "unique-question-marker"):
        assert needle not in stored_text
    ledger_docs = [json.loads(v) for k, v in store.items.items() if k.startswith("ledger/")]
    assert ledger_docs and all(set(d) == {"day", "kind", "usd", "calls"} for d in ledger_docs)


def test_no_redis_key_or_limiter_key_contains_the_raw_address(tmp_path: Path) -> None:
    """Failed-key counters and the public-check limiter see only a peppered hash."""
    import httpx

    from maudesignal.connector.store import UpstashClient
    from tests.unit.test_connector_store import TOKEN, URL, FakeRedis

    fake = FakeRedis()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    env = Env(tmp_path, state=ConnectorState(UpstashClient(URL, TOKEN, http=http)))
    # a wrong key (failed-auth counter) and a public check (public limiter), from a known address
    env.client.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": "wrong-" + "x" * 40})
    env.client.get("/v1/public/check_device_type?product_code=LLZ")
    keys = [c[1] for c in fake.calls if len(c) > 1]
    assert any(":rl:failed-auth:" in k for k in keys)
    assert any(":rl:public-check:" in k for k in keys)
    for k in keys:
        assert "testclient" not in k and "127.0.0.1" not in k, k


def test_key_containing_equals_is_not_mistaken_for_a_label() -> None:
    padded = "A" * 32 + "=="  # base64-style padding: a plain key, not label "AAAA..."
    ks = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{padded},charan={KEY_A}"})
    assert ks.match(padded) is not None and ks.match(padded).label is None  # type: ignore[union-attr]
    m = ks.match(KEY_A)
    assert m is not None and m.label == "charan"
    # a short remainder is not a label either: the whole entry is judged as a plain key
    short = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": "name=tooshort"})
    assert short.match("tooshort") is None and short.match("name=tooshort") is None


def test_http_fetcher_connects_to_the_address_it_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: list[httpx.Request] = []
    lookups: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "93.184.216.34" and request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://other.example/b"})
        return httpx.Response(200, text="<p>ok</p>")

    def resolve(host: str, timeout_s: float) -> str | None:
        lookups.append(host)
        return {"news.example": "93.184.216.34", "other.example": "93.184.216.35"}.get(host)

    monkeypatch.setattr(mn, "_resolve_public", resolve)
    f = mn.HttpFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    status, text = f.get("https://news.example/a", 5.0)
    assert status == 200 and "ok" in text
    # each hop resolved once, then connected by address with the name kept for Host and TLS
    assert lookups == ["news.example", "other.example"]
    assert [r.url.host for r in seen] == ["93.184.216.34", "93.184.216.35"]
    assert [r.headers["host"] for r in seen] == ["news.example", "other.example"]
    assert all(r.extensions.get("sni_hostname") for r in seen)
    # a redirect to a name that resolves to a private address is refused
    monkeypatch.setattr(
        mn, "_resolve_public", lambda h, t: None if h == "other.example" else "93.184.216.34"
    )
    with pytest.raises(ValueError):
        f.get("https://news.example/a", 5.0)


def test_http_fetcher_has_a_wall_clock_deadline_for_slow_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    import httpx

    class Drip(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            for _ in range(100):
                time.sleep(0.02)
                yield b"x" * 10

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Drip())

    monkeypatch.setattr(mn, "_resolve_public", lambda h, t: "93.184.216.34")
    f = mn.HttpFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        f.get("https://slow.example/", 0.15)
    assert time.monotonic() - started < 1.0
