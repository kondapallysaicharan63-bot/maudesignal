"""The $3.00/day cap holds: real spend never exceeds a request's hold (unit + integration).

Covers the fix round: the spend guard refuses a call unless its worst case still fits, so
``actual <= hold``; a failed settle with ``actual > hold`` writes the excess; a voice request
that reserves twice on one ledger settles both; settled objects are read once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector.globalcap import blob_enforced_cap  # noqa: E402
from maudesignal.connector.store import BlobLedger, BlobLedgerError  # noqa: E402
from maudesignal.copilot.spend import (  # noqa: E402
    DailyLedger,
    SpendCaps,
    SpendGuard,
    SpendLimitError,
    worst_case_call_usd,
)
from tests.unit.test_connector_batch_o import DAY, FakeBlobStore, blob_env  # noqa: E402

HOLD = 0.25
DAILY = 3.00


def _ledger(store: FakeBlobStore) -> BlobLedger:
    return BlobLedger(store, "x", today=lambda: DAY)


def _run_request(led: BlobLedger, call_usd: float, reserve: float) -> float:
    """One request: hold, then model calls through a guard until it refuses; settle."""
    assert led.reserve(HOLD, blob_enforced_cap({}))
    guard = SpendGuard(
        session_id="t",
        caps=SpendCaps(
            session_usd=HOLD, session_calls=20, daily_usd=DAILY, call_reserve_usd=reserve
        ),
        ledger=led,
    )
    spent = 0.0
    while True:
        try:
            guard.check("test")
        except SpendLimitError:
            break
        guard.record(kind="chat", model="muse-spark", cost_usd=call_usd)  # the call returned
        spent += call_usd
    led.release(HOLD)
    return spent


def test_worst_case_call_is_a_few_cents() -> None:
    assert 0.03 < worst_case_call_usd() < 0.15  # 8000 output + 40000 input tokens, Spark rates


def test_without_the_call_reserve_a_request_can_pass_its_hold() -> None:
    """Shows what the old guard allowed: 0.24 spent, then one more 0.08 call."""
    store = FakeBlobStore()
    assert _run_request(_ledger(store), 0.08, reserve=0.0) > HOLD


def test_ten_requests_each_spend_up_to_the_cap_and_the_day_stays_under_three_dollars() -> None:
    """Ten requests admitted together, each making calls until its guard stops it."""
    store = FakeBlobStore()
    ledgers = [_ledger(store) for _ in range(10)]  # ten instances / requests
    worst = worst_case_call_usd()
    holds_placed = [led.reserve(HOLD, blob_enforced_cap({})) for led in ledgers]
    assert all(holds_placed)  # 10 x 0.25 = 2.50 <= 2.70: all admitted together
    for led, call_usd in zip(ledgers, [0.08, worst] * 5, strict=True):
        guard = SpendGuard(
            session_id="t",
            caps=SpendCaps(HOLD, 20, DAILY, call_reserve_usd=worst),
            ledger=led,
        )
        spent = 0.0
        while True:
            try:
                guard.check("test")
            except SpendLimitError:
                break
            guard.record(kind="chat", model="muse-spark", cost_usd=call_usd)
            spent += call_usd
        assert spent <= HOLD + 1e-9
        led.release(HOLD)
    assert store.ledger_usd() <= DAILY
    for raw in store.items.values():
        rec = json.loads(raw)
        assert rec["settled"] is True and rec["actual_usd"] <= rec["hold_usd"] + 1e-9


def test_requests_run_through_the_guard_never_pass_their_hold() -> None:
    store = FakeBlobStore()
    for call_usd in (0.01, 0.05, 0.08, worst_case_call_usd()):
        spent = _run_request(_ledger(store), call_usd, reserve=worst_case_call_usd())
        assert 0 < spent <= HOLD + 1e-9


def test_settle_failure_with_actual_over_hold_records_the_excess() -> None:
    store = FakeBlobStore()
    led = _ledger(store)
    assert led.reserve(0.25, 2.7)
    led.add(0.33, 1)
    store.fail_overwrite = True
    led.release(0.25)
    store.fail_overwrite = False
    assert store.ledger_usd() == pytest.approx(0.33)  # hold 0.25 + excess object 0.08
    assert led.spent_today() == pytest.approx(0.33)


def test_settle_failure_with_actual_under_hold_counts_the_hold() -> None:
    store = FakeBlobStore()
    led = _ledger(store)
    assert led.reserve(0.25, 2.7)
    led.add(0.10, 1)
    store.fail_overwrite = True
    led.release(0.25)
    assert store.ledger_usd() == pytest.approx(0.25)  # never lower than the real cost


def test_unrecordable_excess_makes_the_ledger_refuse_all_later_holds() -> None:
    store = FakeBlobStore()
    led = _ledger(store)
    assert led.reserve(0.25, 2.7)
    led.add(0.33, 1)
    store.fail_overwrite = store.fail_put = True
    led.release(0.25)  # neither write works
    store.fail_overwrite = store.fail_put = False
    with pytest.raises(BlobLedgerError):
        led.reserve(0.10, 2.7)  # fails closed from now on


def test_nested_reservations_on_one_ledger_both_settle() -> None:
    """The voice route: an outer hold (transcribe) and the ask's own hold on the same ledger."""
    store = FakeBlobStore()
    led = _ledger(store)
    assert led.reserve(0.30, 2.7)  # outer
    led.add(0.01, 1)  # transcribe cost goes to the outer hold
    assert led.reserve(0.29, 2.7)  # inner (the ask)
    led.add(0.05, 1)  # ask cost goes to the inner hold
    led.release(0.29)  # inner settles first
    led.release(0.30)  # then the outer
    recs = sorted(json.loads(v)["actual_usd"] for v in store.items.values())
    assert recs == [0.01, 0.05]
    assert store.ledger_usd() == pytest.approx(0.59)  # max(hold, actual) per request: 0.30 + 0.29
    assert all(json.loads(v)["settled"] is True for v in store.items.values())


def test_voice_route_ledger_total_is_transcribe_plus_ask(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = blob_env(tmp_path, store)
    body: dict[str, Any] = env.voice().json()
    assert body["mode"] == "live"
    objs = [json.loads(v) for v in store.items.values()]
    assert all(o.get("settled") is True for o in objs)  # nothing left counting its hold
    assert body["cost_usd"] > 0
    assert store.ledger_usd() >= body["cost_usd"]  # holds stay: only ever too high


def test_settled_objects_are_read_once_and_a_day_of_objects_is_fast() -> None:
    store = FakeBlobStore()
    for i in range(40):
        store.items[f"ledger/{DAY.isoformat()}/{i:032x}.json"] = json.dumps(
            {"hold_usd": 0.1, "actual_usd": 0.05, "settled": True}
        ).encode()
    reads: list[str] = []
    real_get = store.get

    def counting_get(ref: Any) -> bytes:
        reads.append(ref.pathname)
        return real_get(ref)

    store.get = counting_get  # type: ignore[method-assign]
    led = _ledger(store)
    assert led.spent_today() == pytest.approx(4.0)  # max(hold, actual) per object
    assert led.spent_today() == pytest.approx(4.0)  # max(hold, actual) per object
    assert len(reads) == 40  # the second sum came from the cache of settled objects
    assert isinstance(led, DailyLedger)


# --- the connector document agrees with /privacy ------------------------------------------

_DOC = Path(__file__).resolve().parents[2] / "docs" / "hackathon" / "MUSE_CONNECTOR.md"


def _plain(text: str) -> str:
    import html
    import re

    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).replace("`", "").split()).lower()


def test_questionnaire_matches_the_privacy_page_on_the_live_routes() -> None:
    from maudesignal.connector.legal_pages import render_privacy

    doc = _DOC.read_text(encoding="utf-8")
    assert doc.count("\n## Data questionnaire") == 1  # no stale second copy
    assert doc.count("Form answers") >= 1 and "\n## Form answers" not in doc
    assert "Not submitted" not in doc and "pending review (submitted Oct 30)" in doc
    assert "2026-12-31" in doc and "30 November 2026" not in doc
    section = _plain(doc.split("\n## Data questionnaire", 1)[1].split("\n## ", 1)[0])
    page = _plain(render_privacy(rate_per_min=30, public_per_hour=10, shared_store=False))
    for phrase in (
        "vercel blob (private)",
        "spend ledger",
        "one small object per paid live request",
        "live ask, voice and label routes",
        "gdelt",
        "medwatch",
        "medtech dive",
        "text fields read from the label",
        "no text, no address and no key",
    ):
        assert phrase in section, f"questionnaire is missing: {phrase}"
        assert phrase in page, f"/privacy is missing: {phrase}"
    assert "holds only website feedback" not in section


# --- fix round: a call that is sent but never recorded still keeps its hold ---------------


class _RaisingCompletions:
    """A model client whose call is billed upstream but raises here (timeout, 5xx, reset)."""

    def __init__(self) -> None:
        self.sent = 0

    def create(self, **kwargs: Any) -> Any:
        self.sent += 1
        raise TimeoutError("cut off after the request was sent")


def _raising_client() -> Any:
    completions = _RaisingCompletions()
    client = type("C", (), {})()
    client.chat = type("Chat", (), {"completions": completions})()
    client.completions = completions
    return client


def _failed_request(led: BlobLedger) -> bool:
    """One request whose model call is sent and then raises; the `finally` still settles."""
    if not led.reserve(HOLD, blob_enforced_cap({})):
        return False
    guard = SpendGuard(
        session_id="t",
        caps=SpendCaps(
            session_usd=HOLD,
            session_calls=20,
            daily_usd=DAILY,
            call_reserve_usd=worst_case_call_usd(),
        ),
        ledger=led,
    )
    client = _raising_client()
    try:
        guard.wrap(client).chat.completions.create(model="muse-spark", messages=[])
    except TimeoutError:
        pass
    finally:
        led.release(HOLD)
    assert client.completions.sent == 1
    return True


def test_a_call_that_raises_after_it_was_sent_keeps_its_hold_in_the_day_total() -> None:
    store = FakeBlobStore()
    led = _ledger(store)
    assert _failed_request(led)
    assert store.ledger_usd() == pytest.approx(HOLD)  # recorded cost 0, but the hold stays
    assert _ledger(store).spent_today() == pytest.approx(HOLD)  # a fresh instance sees it too


def test_unrecorded_billed_calls_cannot_pass_the_daily_cap() -> None:
    """200 requests that each bill $0.10 with nothing recorded: the total stays under $3."""
    store = FakeBlobStore()
    admitted = sum(_failed_request(_ledger(store)) for _ in range(200))
    billed = admitted * 0.10
    assert 0 < admitted < 200
    assert billed <= DAILY
    assert store.ledger_usd() <= DAILY and store.ledger_usd() >= billed


def test_a_hold_is_never_lowered_by_settling_with_a_smaller_cost() -> None:
    store = FakeBlobStore()
    led = _ledger(store)
    assert led.reserve(HOLD, 2.7)
    led.add(0.01, 1)
    led.release(HOLD)
    assert store.ledger_usd() == pytest.approx(HOLD)
    assert led.spent_today() == pytest.approx(HOLD)


# --- keyed ask: the global ledger gets the cost even if the per-key write fails ------------


def test_tee_ledger_adds_to_the_global_ledger_even_when_the_key_ledger_raises() -> None:
    from maudesignal.connector.ask import _TeeLedger
    from maudesignal.connector.store import UpstashError

    class Boom(DailyLedger):
        def __init__(self) -> None:
            super().__init__(Path("/dev/null"))

        def add(self, usd: float, calls: int) -> float:
            raise UpstashError("per-key store down")

    store = FakeBlobStore()
    glob = _ledger(store)
    assert glob.reserve(HOLD, 2.7)
    tee = _TeeLedger(Boom(), glob)
    with pytest.raises(UpstashError):
        tee.add(0.2, 1)
    glob.release(HOLD)
    assert store.ledger_usd() >= 0.2  # the paid call is in the global total


# --- Redis as the global ledger: a failed write cannot lower the day's total ---------------


def _redis_global(fake: Any) -> Any:
    from tests.unit.test_connector_store import make_state

    return make_state(fake).global_ledger("live-global", today=lambda: DAY)


def _global_usd(fake: Any) -> float:
    return sum(float(v) for k, v in fake.kv.items() if k.endswith(":usd") and ":live-global:" in k)


def test_redis_global_ledger_keeps_the_hold_when_redis_fails_after_the_paid_call() -> None:
    from tests.unit.test_connector_store import FakeRedis

    fake = FakeRedis()
    led = _redis_global(fake)
    assert led.reserve(HOLD, 2.7)
    fake.fail = True  # Redis goes down after the paid call
    led.add(0.2, 1)  # inside the hold: kept in memory, no network
    led.release(HOLD)  # nothing is given back
    fake.fail = False
    assert _global_usd(fake) >= HOLD - 1e-9


def test_redis_global_ledger_never_gives_a_hold_back_and_adds_only_the_excess() -> None:
    from tests.unit.test_connector_store import FakeRedis

    fake = FakeRedis()
    led = _redis_global(fake)
    assert led.reserve(HOLD, 2.7)
    led.add(0.10, 1)
    led.release(HOLD)
    assert _global_usd(fake) == pytest.approx(HOLD)
    assert led.reserve(HOLD, 2.7)
    led.add(0.33, 1)  # over its hold
    led.release(HOLD)
    assert _global_usd(fake) == pytest.approx(2 * HOLD + 0.08)


def test_redis_global_ledger_refuses_after_an_unrecordable_excess() -> None:
    from tests.unit.test_connector_store import FakeRedis, UpstashError

    fake = FakeRedis()
    led = _redis_global(fake)
    assert led.reserve(HOLD, 2.7)
    led.add(0.33, 1)
    fake.fail = True
    led.release(HOLD)
    fake.fail = False
    with pytest.raises(UpstashError):
        led.reserve(0.01, 2.7)


# --- one global ledger per state: the "broken" flag outlives a request ---------------------


def test_the_global_ledger_is_one_object_per_state_so_a_broken_flag_is_seen_by_every_ask() -> None:
    from maudesignal.connector.store import ConnectorState

    store = FakeBlobStore()
    state = ConnectorState()
    state.attach_blob(store)
    first = state.global_ledger("live-global")
    assert first is state.global_ledger("live-global")  # what each keyed ask now receives
    assert isinstance(first, BlobLedger)
    assert first.reserve(0.25, 2.7)
    first.add(0.33, 1)
    store.fail_overwrite = store.fail_put = True
    first.release(0.25)  # an excess that cannot be recorded
    store.fail_overwrite = store.fail_put = False
    again = state.global_ledger("live-global")
    assert isinstance(again, BlobLedger)
    with pytest.raises(BlobLedgerError):
        again.reserve(0.10, 2.7)
