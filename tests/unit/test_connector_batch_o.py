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

from maudesignal.connector import mentions as mn  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.blob_store import (  # noqa: E402
    BlobRef,
    MemoryStore,
    ObjectGoneError,
    StoreError,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.globalcap import LEDGER_ID, blob_enforced_cap  # noqa: E402
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.connector.store import (  # noqa: E402
    BlobLedger,
    BlobLedgerError,
    ConnectorState,
    _Reservation,
)
from maudesignal.copilot.spend import DailyLedger, SpendCaps  # noqa: E402
from tests.unit.test_connector import (
    KEY,
    SCRIPT,
    FakeClient,
    live_runtime,
)  # noqa: E402
from tests.unit.test_connector_live import (  # noqa: E402
    ORIGIN,
    Env,
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
    """A private-Blob-like store: overwrite honoured, failures and races injectable."""

    backend = "blob_private"

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.fail_list = self.fail_put = self.fail_get = self.fail_overwrite = False
        self.fail_delete = False
        self.after_put: Any = None
        self.after_list: Any = None
        self.puts = 0
        self.overwrites = 0

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

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        if self.fail_overwrite:
            raise StoreError("blob store unreachable")
        with self.lock:
            self.items[pathname] = json.dumps(record, sort_keys=True).encode()
            self.overwrites += 1

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        if self.fail_list:
            raise StoreError("blob store unreachable")
        with self.lock:
            out = [
                BlobRef(p, "https://blob.test/" + p)
                for p in sorted(self.items)
                if p.startswith(prefix)
            ]
        if self.after_list:
            self.after_list(prefix)
        return out

    def get(self, ref: BlobRef) -> bytes:
        if self.fail_get:
            raise StoreError("blob store unreachable")
        with self.lock:
            try:
                return self.items[ref.pathname]
            except KeyError:
                raise ObjectGoneError("not found") from None

    def delete(self, ref: BlobRef) -> None:
        if self.fail_delete:
            raise StoreError("blob store unreachable")
        with self.lock:
            self.items.pop(ref.pathname, None)

    def seed_ledger(self, usd: float, day: date = DAY, name: str = LEDGER_ID) -> None:
        """Replace the day's ledger entries with one settled request that cost ``usd``."""
        prefix = f"ledger/{day.isoformat()}/"
        for p in [p for p in self.items if p.startswith(prefix)]:
            del self.items[p]
        self.items[f"{prefix}{'0' * 32}.json"] = json.dumps(
            {"hold_usd": usd, "actual_usd": usd, "settled": True}
        ).encode()

    def ledger_usd(self, day: date = DAY, name: str = LEDGER_ID) -> float:
        """What the ledger counts for the day: actual if settled, else at least the hold."""
        prefix = f"ledger/{day.isoformat()}/"
        total = 0.0
        for p, raw in self.items.items():
            if p.startswith(prefix):
                rec = json.loads(raw)
                hold, actual = rec.get("hold_usd", 0.0), rec.get("actual_usd", 0.0)
                total += actual if rec.get("settled") else max(hold, actual)
        return total


def ledger(store: FakeBlobStore, **kw: Any) -> BlobLedger:
    return BlobLedger(store, LEDGER_ID, today=lambda: DAY, **kw)


# --- 1. durable global ledger (append-only: one object per request) ---------------------------


def test_blob_ledger_reserves_then_settles_with_the_real_cost() -> None:
    store = FakeBlobStore()
    led = ledger(store)
    assert led.spent_today() == 0.0  # no objects is a new day
    assert led.reserve(0.25, 2.7) is True
    (path,) = store.items
    assert path.startswith("ledger/2026-10-30/") and path.endswith(".json")
    assert json.loads(store.items[path]) == {"hold_usd": 0.25}  # written before the call
    assert store.ledger_usd() == 0.25
    led.add(0.04, 1)  # the real cost
    assert json.loads(store.items[path]) == {"hold_usd": 0.25}  # nothing written per call
    led.release(0.25)  # settle: only our own object is overwritten
    assert list(store.items) == [path]
    assert json.loads(store.items[path]) == {"hold_usd": 0.25, "actual_usd": 0.04, "settled": True}
    assert store.overwrites == 1 and store.puts == 1
    assert led.spent_today() == pytest.approx(0.04)


def test_blob_ledger_refuses_a_hold_over_the_cap_and_removes_its_own_object() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.6)
    led = ledger(store)
    assert led.reserve(0.25, 2.7) is False
    assert store.ledger_usd() == 2.6 and len(store.items) == 1  # our object is gone again
    assert led.release(0.25) is None  # nothing is held: a no-op


def test_a_refused_hold_that_cannot_be_deleted_is_zeroed_or_kept() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.6)
    store.fail_delete = True
    assert ledger(store).reserve(0.25, 2.7) is False
    assert store.ledger_usd() == 2.6  # zeroed in place: a refusal started no model call
    store2 = FakeBlobStore()
    store2.seed_ledger(2.6)
    store2.fail_delete = store2.fail_overwrite = True
    assert ledger(store2).reserve(0.25, 2.7) is False
    assert store2.ledger_usd() == pytest.approx(2.85)  # kept: it can only over-count


def test_a_hold_that_loses_the_race_is_taken_back() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.5)
    fired: list[int] = []

    def other_writes(path: str) -> None:
        if (
            "ledger/2026-10-30/" in path
            and not fired
            and path != f"ledger/2026-10-30/{'0' * 32}.json"
        ):
            fired.append(1)  # another instance's hold lands right after ours
            store.items[f"ledger/2026-10-30/{'b' * 32}.json"] = b'{"hold_usd": 0.25}'

    store.after_put = other_writes
    assert ledger(store).reserve(0.25, 2.8) is False  # 2.5 + 0.25 + 0.25 > 2.8
    assert store.ledger_usd() == pytest.approx(2.75)  # only the other hold is left; ours is gone


def test_cold_start_keeps_the_total() -> None:
    store = FakeBlobStore()
    assert ledger(store).reserve(1.0, 2.7)
    fresh = ledger(store)  # a new object, as after a cold start: only the store remembers
    assert fresh.spent_today() == 1.0  # an unsettled hold still counts
    assert fresh.reserve(1.0, 2.7) and not fresh.reserve(1.0, 2.7)


def _interleaved(
    store: FakeBlobStore, cap: float, hold: float
) -> tuple[bool, bool, BlobLedger, BlobLedger]:
    """The worst-case order: A puts, B puts, A lists, B lists, then each decides.

    ``a.reserve`` runs for real; B's steps are driven from hooks on A's put and A's listing,
    using the same helpers ``reserve`` uses, so both listings happen before either hold is
    taken back.
    """
    a, b = ledger(store), ledger(store)
    day = DAY.isoformat()
    state: dict[str, Any] = {}

    def after_a_put(_path: str) -> None:
        if "b_path" not in state:
            state["b_path"] = ""  # set first: B's own put fires this hook again
            state["b_path"] = b._write_new(day, {"hold_usd": hold})  # B puts

    def after_a_list(_prefix: str) -> None:
        if "b_ok" not in state:  # B lists (A has already listed), before A decides
            store.after_list = None
            total, _refs = b._sum(day)
            state["b_ok"] = total <= cap + 1e-9
            if state["b_ok"]:
                b._set_mine(_Reservation(day, state["b_path"], hold))
            else:
                b._drop(day, state["b_path"])

    store.after_put, store.after_list = after_a_put, after_a_list
    got_a = a.reserve(hold, cap)
    store.after_put = store.after_list = None
    return got_a, bool(state["b_ok"]), a, b


def test_two_instances_interleaved_with_room_for_only_one_both_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic two-instance interleave; the process lock is patched to a no-op.

    Both write their hold before either lists, so each listing sees both holds. With room for
    one only (cap 0.30, holds 0.25) they cannot both pass, and what stays is within the cap.
    """
    monkeypatch.setattr(DailyLedger, "_lock", _NoLock())  # the ledger must not rely on a lock
    store = FakeBlobStore()
    got_a, got_b, _, _ = _interleaved(store, cap=0.30, hold=0.25)
    assert not (got_a and got_b)
    assert store.ledger_usd() <= 0.30 + 1e-9
    assert store.ledger_usd() == pytest.approx(0.25 * (got_a + got_b))


def test_two_instances_interleaved_that_both_pass_end_under_the_daily_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DailyLedger, "_lock", _NoLock())
    store = FakeBlobStore()
    store.seed_ledger(2.0)
    cap = blob_enforced_cap({})  # 3.00 minus the largest single-request cap = 2.70
    got_a, got_b, a, b = _interleaved(store, cap=cap, hold=0.30)
    assert got_a is True and got_b is True  # 2.00 + 0.30 + 0.30 = 2.60 <= 2.70
    a.add(0.30, 1)
    b.add(0.30, 1)  # each pays its full hold
    a.release(0.30)
    b.release(0.30)
    assert store.ledger_usd() == pytest.approx(2.60)
    assert store.ledger_usd() <= 3.0
    # one more small request fits under the enforced cap, the next large one does not
    assert ledger(store).reserve(0.10, cap) is True
    assert ledger(store).reserve(0.30, cap) is False


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
    assert store.ledger_usd() <= 2.7
    assert store.ledger_usd() == pytest.approx(0.25 * sum(results))


def test_settle_failure_keeps_the_hold_and_can_only_over_count() -> None:
    store = FakeBlobStore()
    led = ledger(store)
    assert led.reserve(0.25, 2.7)
    led.add(0.04, 1)
    store.fail_overwrite = True  # the write after the paid call fails
    led.release(0.25)
    (path,) = store.items
    assert json.loads(store.items[path]) == {"hold_usd": 0.25}  # the hold is still in place
    assert store.ledger_usd() == 0.25  # counted at the hold, never lower
    assert ledger(store).spent_today() == 0.25
    assert led.release(0.25) is None  # a second settle has nothing to do


def test_add_without_a_reservation_writes_its_own_object() -> None:
    store = FakeBlobStore()
    led = ledger(store)
    assert led.add(0.05, 1) == pytest.approx(0.05)
    (rec,) = (json.loads(v) for v in store.items.values())
    assert rec["hold_usd"] == 0.0 and rec["actual_usd"] == 0.05
    store.fail_put = True
    with pytest.raises(BlobLedgerError):
        led.add(0.05, 1)


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
    store.items["ledger/2026-10-30/garbage.json"] = b"not json"
    with pytest.raises(BlobLedgerError):
        ledger(store).reserve(0.25, 2.7)  # an unparseable entry is an error, never zero
    with pytest.raises(BlobLedgerError):
        ledger(store).spent_today()
    assert "ledger/2026-10-30/garbage.json" in store.items
    # our own holds are not left counting after the failed sums: deleted, or zeroed in place
    others = [json.loads(v) for k, v in store.items.items() if not k.endswith("garbage.json")]
    assert all(o == {"hold_usd": 0.0, "actual_usd": 0.0} for o in others)


def test_a_failed_read_after_our_write_takes_the_hold_back() -> None:
    store = FakeBlobStore()
    store.after_put = lambda _p: setattr(store, "fail_list", True)
    with pytest.raises(BlobLedgerError):
        ledger(store).reserve(0.25, 2.7)
    store.fail_list = False
    store.after_put = None
    assert len(store.items) in (0, 1)  # deleted, or zeroed/kept if deleting failed
    assert store.ledger_usd() <= 0.25


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


def test_without_blob_or_upstash_live_calls_stay_off(tmp_path: Path) -> None:
    env = Env(tmp_path, config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_per_day=1000))
    body = env.ask().json()
    assert body["mode"] == "recorded" and not env.spark.requests


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
    assert 0 < after < 0.25  # settled: the real (small) cost, not the hold, now counts
    assert body["cost_usd"] == pytest.approx(after, abs=1e-5)
    assert len(store.items) == 1  # one object for the one request


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


def test_settle_failure_through_the_route_leaves_the_hold(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = blob_env(tmp_path, store)
    store.fail_overwrite = True
    body = env.ask().json()
    assert body["mode"] == "live"  # the answer was already paid for and is shown
    assert store.ledger_usd() >= 0.25  # but the day's count kept the hold, never less
    store.fail_overwrite = False


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


class _NoLock:
    """A process lock that does nothing (proves the ledger does not rely on one)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None


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


def test_route_live_shape_and_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
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
    first = (root / "demo" / "mentions" / "REQUEST").read_text().split()[:1]
    assert first in (["0"], ["1"])  # off, or on for one free recording run
    wf = (root / ".github" / "workflows" / "mentions-record.yml").read_text()
    assert "branches: [track-c-live]" in wf and 'paths: ["demo/mentions/REQUEST"]' in wf
    assert "secrets." not in wf and "META_MODEL_API_KEY" not in wf


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
    assert ledger_docs and all(set(d) == {"hold_usd", "actual_usd", "settled"} for d in ledger_docs)


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


# --- fix round: demo key and the audit list, blob listing, running total, Upstash margin -------


def test_blob_listing_longer_than_the_page_limit_fails_closed() -> None:
    import httpx

    from maudesignal.connector import blob_store as bs

    page = {"blobs": [{"pathname": "ledger/x/1.json", "url": "u"}], "hasMore": True, "cursor": "c"}
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json=page))
    store = bs.VercelBlobStore("tok", client=httpx.Client(transport=transport))
    assert len(store.list_prefix("ledger/")) == bs.MAX_LIST_PAGES  # exports keep the old cut-off
    with pytest.raises(bs.StoreError):
        store.list_prefix("ledger/", strict=True)


def test_blob_ledger_add_writes_once_and_does_not_list_again() -> None:
    store = FakeBlobStore()
    led = ledger(store)
    assert led.reserve(0.25, 3.0)
    lists = 0
    orig = store.list_prefix

    def counting(prefix: str, *, strict: bool = False) -> list[BlobRef]:
        nonlocal lists
        lists += 1
        return orig(prefix, strict=strict)

    store.list_prefix = counting  # type: ignore[method-assign]
    total = led.add(0.1, 1)  # no I/O at all: the cost is kept for the settle
    assert lists == 0 and store.puts == 1 and total == pytest.approx(0.1)
    assert store.ledger_usd() == pytest.approx(0.25)  # in flight: still counted at the hold
    led.release(0.25)
    assert store.ledger_usd() == pytest.approx(0.1)


def test_upstash_mode_also_keeps_the_margin_for_the_keyed_ask() -> None:
    from types import SimpleNamespace

    rt = AskRuntime(
        agent_factory=lambda d, g: None,  # type: ignore[arg-type, return-value]
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=0.25, session_calls=20, daily_usd=3.0),
        state=SimpleNamespace(global_mode="upstash"),  # type: ignore[arg-type]
    )
    assert rt.global_cap() == pytest.approx(2.7)  # 3.00 minus the largest request cap (0.30)
