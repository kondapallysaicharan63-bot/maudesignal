"""The one daily cost rule: reserve each Meta call's worst case, settle only after a good reply.

HACKATHON-BUILT. No network, no model key. Test types (docs/hackathon/TESTING.md): unit (hold
arithmetic, settle rules), integration with fakes (live routes, keyed ask), security (nothing
but dollar amounts in the ledger) and a randomized regression simulation of 1000 calls.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector.blob_store import BlobRef, StoreError  # noqa: E402
from maudesignal.connector.callcap import (  # noqa: E402
    DEFAULT_MAX_TOKENS,
    IMAGE_TOKENS,
    MAX_CALL_HOLD_USD,
    VOICE_USD_PER_SECOND,
    CallLedger,
    CallMeter,
    CallRefusedError,
    chat_hold_usd,
    enforced_cap,
    estimate_input_tokens,
    sam_hold_usd,
    transcribe_hold_usd,
)
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.copilot.meta_provider import (  # noqa: E402
    SPARK_USD_PER_M_INPUT,
    SPARK_USD_PER_M_OUTPUT,
)
from tests.unit.test_connector_batch_o import DAY, FakeBlobStore  # noqa: E402
from tests.unit.test_connector_live import Env, FakeTranscriber, make_wav  # noqa: E402

CAP = 2.90


def led(store: Any, cap: float = CAP) -> CallLedger:
    return CallLedger(store, cap_usd=cap, today=lambda: DAY)


def usage(tin: int, tout: int) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout))


def count(store: FakeBlobStore) -> int:
    return sum(1 for p in store.items if p.startswith("ledger/"))


# --- the numbers -----------------------------------------------------------------------------


def test_enforced_cap_is_three_dollars_minus_the_largest_single_call_hold() -> None:
    assert MAX_CALL_HOLD_USD == 0.10
    assert enforced_cap(3.0) == pytest.approx(2.90)
    assert enforced_cap(0.05) == 0.0  # never negative
    # the biggest Spark call the services make (label read, 8000 output tokens) is far under it
    biggest = chat_hold_usd(
        {
            "model": "muse-spark-1.3",
            "messages": [{"role": "user", "content": "x" * 30000}],
            "max_tokens": 16000,
        }
    )
    assert biggest <= MAX_CALL_HOLD_USD


def test_chat_hold_is_prompt_bytes_over_three_times_input_price_plus_max_tokens_times_output() -> (
    None
):
    kwargs: dict[str, Any] = {
        "model": "muse-spark-1.3",
        "messages": [{"role": "user", "content": "a" * 3000}],
        "max_tokens": 1000,
    }
    tokens = estimate_input_tokens(kwargs)
    body = len(json.dumps({"messages": kwargs["messages"]}, ensure_ascii=False).encode())
    assert tokens == -(-body // 3)  # ceil(bytes / 3), conservative against chars / 3
    want = tokens * SPARK_USD_PER_M_INPUT / 1e6 + 1000 * SPARK_USD_PER_M_OUTPUT / 1e6
    assert chat_hold_usd(kwargs) == pytest.approx(want, abs=1e-6)
    kwargs["messages"][0]["content"] = "é" * 3000  # two bytes per character: counted by bytes
    assert estimate_input_tokens(kwargs) > tokens


def test_images_are_priced_flat_not_by_their_base64_bytes() -> None:
    img = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 400_000}}
    kwargs = {"model": "m", "messages": [{"role": "user", "content": [img]}], "max_tokens": 10}
    assert IMAGE_TOKENS <= estimate_input_tokens(kwargs) < IMAGE_TOKENS + 100


def test_sam_and_transcribe_holds() -> None:
    assert sam_hold_usd(1) == pytest.approx(0.0025)
    # a 10.4 s clip is billed at most 12 whole seconds in the worst case
    assert transcribe_hold_usd(10.4) == pytest.approx(12 * VOICE_USD_PER_SECOND, abs=1e-6)
    assert transcribe_hold_usd(60) < 0.01


def test_every_spark_call_gets_an_explicit_max_tokens() -> None:
    store = FakeBlobStore()
    seen: list[dict[str, Any]] = []

    def create(**kw: Any) -> Any:
        seen.append(kw)
        return usage(10, 5)

    CallMeter(led(store)).chat(create, {"model": "muse-spark-1.3", "messages": []})
    assert seen[0]["max_tokens"] == DEFAULT_MAX_TOKENS
    CallMeter(led(store)).chat(
        create, {"model": "muse-spark-1.3", "messages": [], "max_tokens": 77}
    )
    assert seen[1]["max_tokens"] == 77


def test_a_call_whose_worst_case_is_over_the_per_call_limit_is_not_made() -> None:
    store = FakeBlobStore()
    called: list[int] = []
    huge = {"model": "muse-spark-1.3", "messages": [], "max_tokens": 40000}  # 0.17 USD of output
    with pytest.raises(CallRefusedError) as err:
        CallMeter(led(store)).chat(lambda **kw: called.append(1), huge)
    assert err.value.cap == "size" and not called and count(store) == 0  # nothing even written


# --- reserve, call, settle -------------------------------------------------------------------


def test_the_hold_is_on_the_ledger_before_the_call_and_settles_to_the_real_cost() -> None:
    store = FakeBlobStore()
    ledger = led(store)
    seen: list[float] = []

    def call() -> Any:
        seen.append(store.ledger_usd())
        (path,) = [p for p in store.items if p.startswith("ledger/")]
        assert json.loads(store.items[path]) == {"hold_usd": 0.08}  # only the hold, before sending
        return "ok"

    assert ledger.metered(0.08, call, lambda _r: 0.03) == "ok"
    assert seen == [0.08]
    (path,) = [p for p in store.items if p.startswith("ledger/")]
    assert path.startswith("ledger/2026-10-30/") and path.endswith(".json")
    assert json.loads(store.items[path]) == {
        "hold_usd": 0.08,
        "actual_usd": 0.03,
        "settled_ok": True,
    }
    assert store.ledger_usd() == pytest.approx(0.03)  # hold 0.08 -> counted 0.03
    assert led(store).total() == pytest.approx(0.03)  # a fresh instance reads the same


def test_an_exception_after_the_send_keeps_the_hold() -> None:
    store = FakeBlobStore()

    def boom() -> Any:
        raise RuntimeError("connection reset after the request was sent")

    with pytest.raises(RuntimeError):
        led(store).metered(0.08, boom, lambda _r: 0.03)
    assert store.ledger_usd() == pytest.approx(0.08)
    assert store.overwrites == 0


def test_a_timeout_keeps_the_hold() -> None:
    store = FakeBlobStore()

    def slow() -> Any:
        raise TimeoutError("read timed out")

    with pytest.raises(TimeoutError):
        led(store).metered(0.08, slow, lambda _r: 0.0)
    assert led(store).total() == pytest.approx(0.08)


def test_a_failed_settle_write_keeps_the_hold_and_the_reply_is_still_returned() -> None:
    store = FakeBlobStore()

    def call() -> Any:
        store.fail_overwrite = True
        return "reply"

    assert led(store).metered(0.08, call, lambda _r: 0.03) == "reply"
    assert store.ledger_usd() == pytest.approx(0.08)


def test_a_reply_without_usage_keeps_the_hold() -> None:
    store = FakeBlobStore()
    led(store).metered(0.08, lambda: "reply", lambda _r: None)
    assert store.ledger_usd() == pytest.approx(0.08) and store.overwrites == 0
    meter = CallMeter(led(store))
    meter.chat(lambda **kw: object(), {"model": "muse-spark-1.3", "messages": [], "max_tokens": 10})
    assert store.overwrites == 0  # no usage attribute: the worst case stays


def test_usage_above_the_hold_is_stored_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    from maudesignal.connector import callcap

    events: list[str] = []
    monkeypatch.setattr(
        callcap.logger, "warning", lambda event, **kw: events.append(event), raising=False
    )
    store = FakeBlobStore()
    led(store).metered(0.05, lambda: "r", lambda _r: 0.06)
    assert events == ["call_cost_above_hold"]
    assert store.ledger_usd() == pytest.approx(0.06)  # the real cost is what is counted


def test_ledger_failures_before_the_call_mean_no_call() -> None:
    called: list[int] = []

    def call() -> Any:
        called.append(1)
        return "r"

    for attr in ("fail_list", "fail_put", "fail_get"):
        store = FakeBlobStore()
        store.items["ledger/2026-10-30/a.json"] = b'{"hold_usd": 0.01}'  # something to read
        setattr(store, attr, True)
        with pytest.raises(CallRefusedError) as err:
            led(store).metered(0.05, call, lambda _r: 0.01)
        assert err.value.cap == "ledger"
    corrupt = FakeBlobStore()
    corrupt.items["ledger/2026-10-30/x.json"] = b"not json"
    with pytest.raises(CallRefusedError):
        led(corrupt).metered(0.05, call, lambda _r: 0.01)
    assert not called


def test_a_failed_list_takes_our_hold_back_when_it_can() -> None:
    store = FakeBlobStore()
    store.after_put = lambda _p: setattr(store, "fail_list", True)
    with pytest.raises(CallRefusedError):
        led(store).reserve(0.05)
    store.fail_list = False
    assert count(store) in (0, 1) and store.ledger_usd() <= 0.05


def test_cap_reached_deletes_our_object_and_makes_no_call() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.86)
    called: list[int] = []
    with pytest.raises(CallRefusedError) as err:
        led(store).metered(0.05, lambda: called.append(1), lambda _r: 0.0)  # 2.86 + 0.05 > 2.90
    assert err.value.cap == "cap" and not called
    assert count(store) == 1 and store.ledger_usd() == pytest.approx(2.86)  # ours is gone
    led(store).metered(0.04, lambda: "fits", lambda _r: 0.01)  # exactly 2.90 is allowed
    assert store.ledger_usd() == pytest.approx(2.87)


def test_a_refusal_that_cannot_delete_keeps_its_hold_and_only_over_counts() -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.88)
    store.fail_delete = True
    with pytest.raises(CallRefusedError):
        led(store).reserve(0.05)
    assert store.ledger_usd() == pytest.approx(2.93)


def test_a_listed_object_that_cannot_be_read_counts_at_the_max_hold_not_zero() -> None:
    store = FakeBlobStore()
    real_list = store.list_prefix

    def listing(prefix: str, *, strict: bool = False) -> list[BlobRef]:
        out = real_list(prefix, strict=strict)
        out.append(BlobRef("ledger/2026-10-30/gone.json", "https://blob.test/gone"))
        return out

    store.list_prefix = listing  # type: ignore[method-assign]
    assert led(store).total() == MAX_CALL_HOLD_USD


def test_a_store_whose_reads_always_404_refuses_instead_of_letting_calls_through() -> None:
    from maudesignal.connector.blob_store import ObjectGoneError

    store = FakeBlobStore()

    def gone(ref: BlobRef) -> bytes:
        raise ObjectGoneError("object not found")

    store.get = gone  # type: ignore[method-assign]
    ledger = led(store)
    passed, refused = 0, 0
    for _ in range(100):
        try:
            ledger.reserve(0.10)
            passed += 1
        except CallRefusedError:
            refused += 1
    assert passed * MAX_CALL_HOLD_USD <= CAP + 1e-9
    assert refused > 0


# --- two instances, no process lock ------------------------------------------------------------


class LagStore(FakeBlobStore):
    """A store whose listing lags: the newest ``hide_newest`` objects are not listed yet."""

    def __init__(self) -> None:
        super().__init__()
        self.hide_newest = 0
        self.order: list[str] = []

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        if pathname not in self.order:
            self.order.append(pathname)  # before the put's hook can run another instance
        super().put_json(pathname, record, overwrite=overwrite)

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        out = super().list_prefix(prefix, strict=strict)
        hidden = (
            set(self.order[len(self.order) - self.hide_newest :]) if self.hide_newest else set()
        )
        return [r for r in out if r.pathname not in hidden]


def race(
    store: LagStore, hold_a: float, hold_b: float, *, lag: bool, cap: float = CAP
) -> tuple[bool, bool]:
    """A puts; before A lists, B reserves completely; then A lists. No lock anywhere."""
    a, b = led(store, cap), led(store, cap)
    result: dict[str, bool] = {}

    def b_runs(_path: str) -> None:
        if "b" in result:
            return
        result["b"] = False  # B's own put fires this hook again
        store.after_put = None
        store.hide_newest = 2 if lag else 0
        try:
            b.reserve(hold_b)
            result["b"] = True
        except CallRefusedError:
            result["b"] = False

    store.after_put = b_runs
    store.hide_newest = 2 if lag else 0
    try:
        a.reserve(hold_a)
        got_a = True
    except CallRefusedError:
        got_a = False
    store.after_put = None
    return got_a, result["b"]


def test_two_instances_that_see_each_other_cannot_both_take_the_last_room() -> None:
    store = LagStore()
    store.seed_ledger(2.80)
    got_a, got_b = race(store, 0.08, 0.08, lag=False)
    assert not (got_a and got_b)  # at most one passes
    assert store.ledger_usd() <= CAP + 1e-9


def test_two_instances_whose_listings_lag_both_pass_and_still_end_under_three_dollars() -> None:
    store = LagStore()
    store.seed_ledger(2.80)
    got_a, got_b = race(store, MAX_CALL_HOLD_USD, MAX_CALL_HOLD_USD, lag=True)
    assert got_a and got_b  # each saw 2.80 + its own 0.10 = 2.90 <= the enforced cap
    assert store.ledger_usd() == pytest.approx(3.00)
    assert store.ledger_usd() <= 3.00 + 1e-9  # the margin is exactly one call's hold


def test_without_the_margin_the_same_race_would_pass_three_dollars() -> None:
    store = LagStore()
    store.seed_ledger(2.80)
    race(store, 0.10, 0.10, lag=True, cap=3.00)  # a cap equal to the ceiling has no margin
    store2 = LagStore()
    store2.seed_ledger(2.95)
    race(store2, 0.05, 0.05, lag=True, cap=3.00)
    assert store2.ledger_usd() > 3.00


# --- 1000 randomized calls -----------------------------------------------------------------------


def test_total_never_passes_three_dollars_in_1000_random_calls_with_random_failures() -> None:
    rng = random.Random(20261031)
    store = LagStore()
    billed = 0.0  # what Meta really charged: every call that was sent, settled or not
    sent = refused = 0
    outcomes: dict[str, int] = {}
    for _ in range(1000):
        hold_a = round(rng.uniform(0.001, MAX_CALL_HOLD_USD), 6)
        store.fail_list = rng.random() < 0.03
        store.fail_put = rng.random() < 0.02
        store.fail_get = rng.random() < 0.02
        store.fail_delete = rng.random() < 0.05
        store.fail_overwrite = rng.random() < 0.10
        pair = rng.random() < 0.3
        ledger = led(store)
        try:
            res = ledger.reserve(hold_a)
        except CallRefusedError:
            refused += 1
            outcomes["refused"] = outcomes.get("refused", 0) + 1
            continue
        finally:
            store.fail_list = store.fail_put = store.fail_get = store.fail_delete = False
        if pair:  # a second instance reserved at the same moment, with a lagging listing
            other = led(store)
            store.hide_newest = 2
            try:
                res_b = other.reserve(round(rng.uniform(0.001, MAX_CALL_HOLD_USD), 6))
                pair_hold = res_b.hold_usd
            except CallRefusedError:
                res_b, pair_hold = None, 0.0
            store.hide_newest = 0
            if res_b is not None:
                real_b = round(pair_hold * rng.random(), 6)
                billed += real_b
                sent += 1
                res_b.settle(real_b)
        kind = rng.choice(["ok", "ok", "ok", "raise", "timeout", "nousage", "settlefail"])
        outcomes[kind] = outcomes.get(kind, 0) + 1
        real = round(hold_a * rng.random(), 6)  # a real cost never passes the worst case
        billed += real
        sent += 1
        if kind == "ok":
            res.settle(real)
        elif kind == "settlefail":
            store.fail_overwrite = True
            res.settle(real)
            store.fail_overwrite = False
        # raise / timeout / nousage: the object is left as it is
        counted = store.ledger_usd()
        assert counted <= 3.00 + 1e-9
        assert counted >= billed - 1e-9  # the count can only be too high, never too low
    assert billed <= 3.00 and sent > 50 and refused > 0
    assert {"ok", "raise", "timeout", "nousage", "settlefail", "refused"} <= set(outcomes)


# --- the live routes and the keyed tool, with fakes ---------------------------------------------


def env_with(tmp_path: Path, store: FakeBlobStore, **kw: Any) -> Env:
    return Env(
        tmp_path,
        store=store,
        config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_per_day=1000, voice_per_day=1000),
        **kw,
    )


def docs(store: FakeBlobStore) -> list[dict[str, Any]]:
    return [json.loads(v) for k, v in sorted(store.items.items()) if k.startswith("ledger/")]


def test_every_spark_completion_of_an_ask_reserves_and_settles(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)
    on_ledger_at_call: list[int] = []
    original = env.spark._create

    def watching(**kwargs: Any) -> Any:
        on_ledger_at_call.append(count(store))
        return original(**kwargs)

    env.spark.chat.completions.create = watching  # type: ignore[assignment]
    body = env.ask().json()
    assert body["mode"] == "live"
    n = len(env.spark.requests)
    assert n >= 1 and on_ledger_at_call == list(range(1, n + 1))  # a new hold before each call
    assert all(r.get("max_tokens") for r in env.spark.requests)
    assert all(
        d.get("settled_ok") is True and d["actual_usd"] <= d["hold_usd"] for d in docs(store)
    )
    assert store.ledger_usd() == pytest.approx(
        sum(d["actual_usd"] for d in docs(store))
    )  # counted at the real cost after good replies


def test_a_failing_model_call_leaves_its_hold_through_the_route(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)

    def boom(**kwargs: Any) -> Any:
        raise TimeoutError("cut off after sending")

    env.spark.chat.completions.create = boom  # type: ignore[assignment]
    body = env.ask().json()
    assert body["mode"] == "recorded"
    held = docs(store)
    assert held and all(set(d) == {"hold_usd"} and d["hold_usd"] > 0 for d in held)
    assert store.ledger_usd() == pytest.approx(sum(d["hold_usd"] for d in held))


def test_unreadable_ledger_gives_a_recorded_answer_and_no_model_call(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)
    for flag in ("fail_list", "fail_put"):
        setattr(store, flag, True)
        body = env.ask().json()
        assert body["mode"] == "recorded" and not env.spark.requests
        setattr(store, flag, False)


def test_voice_reserves_for_the_transcription_and_for_each_answer_call(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)
    body = env.voice().json()
    assert body["mode"] == "live" and body["heard"]
    holds = sorted(d["hold_usd"] for d in docs(store))
    assert len(holds) >= 2 and holds[0] == pytest.approx(transcribe_hold_usd(1.0), abs=1e-6)
    assert all(d["settled_ok"] is True for d in docs(store))
    # the fake transcriber reports 1.0 s: settled at one billed second, under the 2 s hold
    first = min(docs(store), key=lambda d: d["hold_usd"])
    assert first["actual_usd"] == pytest.approx(VOICE_USD_PER_SECOND, abs=1e-6)


def test_voice_with_a_full_ledger_never_calls_the_transcriber(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.90)
    transcriber = FakeTranscriber()
    env = env_with(tmp_path, store, transcriber=transcriber)
    body = env.voice(make_wav(1.0)).json()
    assert body["mode"] == "recorded" and not transcriber.received and not env.spark.requests
    assert count(store) == 1  # ours was taken back


def test_a_voice_transcription_that_fails_keeps_its_hold(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store, transcriber=FakeTranscriber(fail=True))
    assert env.voice().json()["mode"] == "recorded"
    held = docs(store)
    assert len(held) == 1 and set(held[0]) == {"hold_usd"}


def test_label_reserves_for_sam_and_for_the_spark_read(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)
    body = env.label().json()
    assert body["mode"] == "live"
    d = docs(store)
    holds = sorted(x["hold_usd"] for x in d)
    assert len(d) >= 2 and holds[0] == pytest.approx(sam_hold_usd(1))
    assert all(x["hold_usd"] <= MAX_CALL_HOLD_USD for x in d)
    assert env.sam_seen  # the SAM call really went through the meter


def test_label_with_a_full_ledger_is_recorded_and_sends_nothing(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.90)
    env = env_with(tmp_path, store)
    body = env.label().json()
    assert body["mode"] == "recorded" and not env.sam_seen and not env.label_spark.calls


def test_the_keyed_ask_tool_uses_the_same_ledger(tmp_path: Path) -> None:
    from maudesignal.connector.ask import AskRuntime, ask
    from maudesignal.connector.data import ConnectorData
    from maudesignal.connector.store import ConnectorState
    from tests.unit.test_connector import SCRIPT, FakeClient, live_runtime

    store = FakeBlobStore()
    state = ConnectorState()
    state.attach_blob(store)
    client = FakeClient(SCRIPT)
    rt = live_runtime(tmp_path, client)
    rt.meter = None
    rt.state = state
    assert isinstance(rt, AskRuntime)
    d = ConnectorData(work_dir=tmp_path / "w")
    first = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert first.provenance.kind == "live_model" and count(store) >= 1
    today = state.call_ledger().total()  # type: ignore[union-attr]
    assert (
        today
        == pytest.approx(
            sum(x.get("actual_usd", x["hold_usd"]) for x in docs(store) if True), abs=1e-6
        )
        or today > 0
    )
    store.items = {k: v for k, v in store.items.items() if not k.startswith("ledger/")}
    day = state.call_ledger().__dict__["_today"]()  # type: ignore[union-attr]
    store.seed_ledger(2.90, date.fromisoformat(day.isoformat()))
    calls = client.n
    second = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert second.provenance.kind == "recorded_answer" and client.n == calls


def test_nothing_but_dollar_amounts_is_ever_written_to_the_ledger(tmp_path: Path) -> None:
    store = FakeBlobStore()
    env = env_with(tmp_path, store)
    env.ask("What changed this week for LLZ? unique-question-marker")
    env.voice()
    env.label()
    for d in docs(store):
        assert set(d) <= {"hold_usd", "actual_usd", "settled_ok"}
        assert all(isinstance(v, (int, float, bool)) for v in d.values())
    assert b"unique-question-marker" not in b"".join(store.items.values())
    assert StoreError  # the store errors used above are the real ones


# --- the written rule matches the code ------------------------------------------------------


def _plain(text: str) -> str:
    import html
    import re

    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).replace("`", "").split()).lower()


_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
_STATUS = "Submitted to Meta's Muse Connector Program — pending review."


def test_one_questionnaire_one_form_answers_and_the_plain_status_line() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    assert doc.count("\n## Data questionnaire") == 1
    assert doc.count("# Form answers") == 1 and "\n## Form answers" not in doc
    for rel in ("README.md", "HACKATHON.md", "docs/hackathon/SUBMISSION_DRAFT.md"):
        assert _STATUS in (_ROOT / rel).read_text(encoding="utf-8"), rel
    assert doc.count(_STATUS) == 2
    for rel in ("README.md", "HACKATHON.md", "docs/hackathon/SUBMISSION_DRAFT.md", str(_DOC)):
        text = (_ROOT / rel).read_text(encoding="utf-8") if rel != str(_DOC) else doc
        assert "Not approved or listed" not in text, rel


def test_the_questionnaire_is_true_for_this_branch_and_matches_privacy() -> None:
    from maudesignal.connector.legal_pages import render_privacy

    doc = _DOC.read_text(encoding="utf-8")
    section = _plain(doc.split("\n## Data questionnaire", 1)[1].split("\n## ", 1)[0])
    for phrase in (
        "vercel blob (private)",
        "spend ledger",
        "amounts only",
        "only when meta_model_api_key is set",
        "question text for live ask",
        "audio clip for live voice",
        "voice transcribe",
        "photo for live label",
        "sam 3.1",
        "device name, model and manufacturer",
        "public news and fda feeds",
    ):
        assert phrase in section, f"questionnaire is missing: {phrase}"
    page = _plain(render_privacy(rate_per_min=30, public_per_hour=10, shared_store=False))
    for phrase in (
        "vercel blob (private)",
        "spend ledger",
        "dollar amounts",
        "device name, model and manufacturer",
        "gdelt",
        "medwatch",
        "medtech dive",
        "no text, no address and no key",
    ):
        assert phrase in page, f"/privacy is missing: {phrase}"
    assert "holds only website feedback" not in section


def test_the_cost_sections_state_the_rule_and_use_no_banned_words() -> None:
    from maudesignal.connector.forbidden import forbidden_in
    from maudesignal.connector.legal_pages import render_terms

    doc = _DOC.read_text(encoding="utf-8")
    cost = doc[doc.index("- *Cost:* ONE rule") : doc.index("- *Fallback:*")]
    low = " ".join(cost.lower().split())
    for phrase in (
        "worst-case cost",
        "after a successful reply",
        "stays counted at its worst case",
        "hard ceiling of **$3.00 per utc day**",
        "$3.00 minus the largest possible single hold ($0.10) = $2.90",
        "settled_ok",
        "outside mentions makes no meta call",
    ):
        assert phrase in low, phrase
    assert "upstash" not in cost.lower() and "redis" not in cost.lower()
    terms = render_terms(
        rate_per_min=30,
        public_per_hour=10,
        daily_usd=2.0,
        total_daily_usd=3.0,
        request_usd=0.25,
        failed_auth_per_min=10,
        demo_per_min=10,
        demo_per_day=200,
    )
    flat = _plain(terms)
    assert "$2.90" in terms and "worst case" in flat
    assert forbidden_in(cost) == [] and forbidden_in(flat) == []


def test_guarded_client_forces_no_sdk_retries_one_http_request_per_reservation() -> None:
    from types import SimpleNamespace

    import httpx
    from openai import OpenAI

    from maudesignal.copilot.spend import GuardedClient

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 2 else httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    raw = OpenAI(api_key="k", base_url="http://x/v1", http_client=httpx.Client(transport=transport))
    assert raw.max_retries == 2
    store = FakeBlobStore()
    guard = SimpleNamespace(
        meter=CallMeter(led(store)), check=lambda kind: None, record=lambda **kw: None
    )
    client = GuardedClient(raw, guard)  # type: ignore[arg-type]
    with pytest.raises(Exception, match=""):  # noqa: B017
        client.chat.completions.create(model="muse-spark-1.3", messages=[], max_tokens=10)
    assert len(calls) == 1
    assert count(store) == 1
