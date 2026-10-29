"""Tool-layer tests for the Muse connector (HACKATHON-BUILT). No network, no model key.

Stored-data tests read the committed demo snapshot; live openFDA and the Muse Spark
model are replaced by fakes.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.common.exceptions import OpenFDAAPIError
from maudesignal.connector import tools
from maudesignal.connector.ask import AskRuntime, ask
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from maudesignal.connector.forbidden import forbidden_in
from maudesignal.connector.models import ADVISORY, ToolAnswer
from maudesignal.connector.security import KeyStore, RateLimiter, sha256_hex
from maudesignal.connector.speech import plain, speak_date
from maudesignal.copilot.agent import CopilotAgent
from maudesignal.copilot.spend import SpendCaps, SpendGuard
from maudesignal.monitor.deterioration import build_window
from maudesignal.monitor.live_check import LiveCheck, WindowCounts, classify_counts, verify_url

NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
KEY = "test-key-NOT-A-REAL-SECRET-0123456789"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("connector"))


def fake_check(code: str) -> LiveCheck:
    """Live result for the week ending 2026-09-07: 5 reports vs 4 in the 4 weeks before."""
    counts = WindowCounts(
        current_total=5,
        baseline_total=4,
        prior_total=100,
        current_types=(("injury", 1), ("malfunction", 4)),
        baseline_types=(("malfunction", 4),),
        prior_types=(("injury", 3), ("malfunction", 97)),
    )
    w = build_window(date(2026, 9, 7))
    result = classify_counts(code, counts, w)
    from dataclasses import replace

    return replace(
        result,
        queries=(
            (
                "Reports per day (latest date, both windows)",
                verify_url(code, "20240101", "20261029", "date_received"),
            ),
            (
                "This week, by event type",
                verify_url(code, "20260901", "20260907", "event_type.exact"),
            ),
            (
                "4 weeks before, by event type",
                verify_url(code, "20260804", "20260831", "event_type.exact"),
            ),
            ("Everything before this week", verify_url(code, "19900101", "20260831")),
            (
                "Everything before this week, by event type",
                verify_url(code, "19900101", "20260831", "event_type.exact"),
            ),
        ),
    )


def offline(_: str) -> LiveCheck:
    raise OpenFDAAPIError("no network in tests")


def no_model_runtime(tmp_path: Path) -> AskRuntime:
    def boom(*_: Any) -> CopilotAgent:
        raise AssertionError("the live model must not be called")

    return AskRuntime(agent_factory=boom, live_enabled=lambda: False, ledger_dir=tmp_path / "led")


def check_shape(a: ToolAnswer, tool: str) -> None:
    """The contract every answer shares."""
    assert a.tool == tool
    assert a.advisory == ADVISORY
    assert a.speakable.strip() and not re.search(r"[*_`#>|\[\]]", a.speakable)
    assert "http" not in a.speakable
    assert 1 <= len(SENTENCE_END.split(a.speakable.strip())) <= 3
    assert a.facts or tool == "ask"
    for f in a.facts:
        assert f.link.startswith("https://") and f.text.strip()
    assert a.provenance.kind and a.provenance.source
    assert forbidden_in(json.dumps(a.model_dump())) == []


# --- what_changed_this_week -------------------------------------------------------------


def test_what_changed_stored_uses_snapshot_numbers_and_dates(data: ConnectorData) -> None:
    a = tools.what_changed_this_week(data, live_checker=offline, now=lambda: NOW)
    check_shape(a, "what_changed_this_week")
    assert a.provenance.kind == "stored_demo_snapshot"
    assert "August 25, 2026 to August 31, 2026" in a.speakable
    assert "LLZ" in a.speakable and "33 reports" in a.speakable and "8.75" in a.speakable
    assert "demo snapshot" in a.speakable
    assert "2026" in (a.provenance.data_dates or "") and "fetched 2026-10-27" in (
        a.provenance.data_dates or ""
    )
    llz = next(f for f in a.facts if f.text.startswith("LLZ"))
    assert "device/event.json" in llz.link and "LLZ" in llz.link and "20260825" in llz.link
    assert len(a.facts) == 4  # LLZ flagged, MYN/POK/QIH stable


def test_what_changed_stored_code_filter(data: ConnectorData) -> None:
    a = tools.what_changed_this_week(data, "llz", live_checker=offline, now=lambda: NOW)
    check_shape(a, "what_changed_this_week")
    assert len(a.facts) == 1 and a.provenance.kind == "stored_demo_snapshot"
    qih = tools.what_changed_this_week(data, "QIH", live_checker=offline, now=lambda: NOW)
    assert "no change" in qih.speakable


def test_what_changed_unstored_code_is_live(data: ConnectorData) -> None:
    a = tools.what_changed_this_week(data, "QAS", live_checker=fake_check, now=lambda: NOW)
    check_shape(a, "what_changed_this_week")
    assert a.provenance.kind == "live_openfda"
    assert a.provenance.queried_at_utc == "2026-10-29T12:00:00Z"
    assert "5 reports" in a.speakable and "September 7, 2026" in a.speakable


def test_what_changed_rejects_bad_code(data: ConnectorData) -> None:
    with pytest.raises(InvalidInputError):
        tools.what_changed_this_week(data, "LL1", live_checker=fake_check)


# --- check_device_type ------------------------------------------------------------------


def test_check_device_type_live_counts_match_detector_rules(data: ConnectorData) -> None:
    a = tools.check_device_type(data, "qas", live_checker=fake_check, now=lambda: NOW)
    check_shape(a, "check_device_type")
    assert a.provenance.kind == "live_openfda"
    texts = " ".join(f.text for f in a.facts)
    assert "5 reports received" in texts and "4 reports received" in texts
    assert "100 reports received before" in texts
    # 5 reports >= 3 and 5 >= 2 x (4 / 4): spike; 1 of 5 severe vs 0 of 4: escalation.
    assert "more serious than usual and reports suddenly increased" in a.speakable


def test_check_device_type_falls_back_to_stored_when_offline(data: ConnectorData) -> None:
    a = tools.check_device_type(data, "LLZ", live_checker=offline, now=lambda: NOW)
    check_shape(a, "check_device_type")
    assert a.provenance.kind == "stored_demo_snapshot"
    assert "could not be reached" in (a.provenance.note or "")


def test_check_device_type_unstored_and_offline_is_unavailable(data: ConnectorData) -> None:
    with pytest.raises(SourceUnavailableError):
        tools.check_device_type(data, "QAS", live_checker=offline)


def test_check_device_type_no_reports(data: ConnectorData) -> None:
    def none(code: str) -> LiveCheck:
        c = fake_check(code)
        from dataclasses import replace

        return replace(c, as_of=None, window=None, current_count=0, prior_report_count=7)

    a = tools.check_device_type(data, "ZZZ", live_checker=none, now=lambda: NOW)
    check_shape(a, "check_device_type")
    assert "no reports on openFDA in the last two years" in a.speakable


# --- get_report -------------------------------------------------------------------------


def test_get_report_stored(data: ConnectorData) -> None:
    a = tools.get_report(data, "50426770")
    check_shape(a, "get_report")
    assert a.provenance.kind == "stored_demo_snapshot"
    assert "5 0 4 2 6 7 7 0" in a.speakable  # digit by digit for a voice
    assert all("mdr_report_key" in f.link and "50426770" in f.link for f in a.facts)
    assert any("Philips received a complaint" in f.text for f in a.facts)


def test_get_report_missing_and_invalid(data: ConnectorData) -> None:
    with pytest.raises(NotFoundError):
        tools.get_report(data, "00000000")
    with pytest.raises(InvalidInputError):
        tools.get_report(data, "../etc/passwd")


# --- recalls ----------------------------------------------------------------------------


def test_recalls_stored(data: ConnectorData) -> None:
    a = tools.recalls(data, "llz")
    check_shape(a, "recalls")
    # 561 openFDA recall product records belong to 433 distinct recall events
    assert "561 recall product records (433 recall events)" in a.speakable
    assert "561 FDA recalls" not in a.speakable
    assert any("561 recall product records (433 recall events)" in f.text for f in a.facts)
    assert a.provenance.kind == "stored_demo_snapshot"
    assert "fetched 2026-10-27" in (a.provenance.data_dates or "")
    assert 1 < len(a.facts) <= 6
    assert all("recall.json" in f.link for f in a.facts)


def test_recalls_none_stored(data: ConnectorData) -> None:
    a = tools.recalls(data, "ZZZ")
    check_shape(a, "recalls")
    assert "holds no recalls" in a.speakable and "does not mean none exist" in a.speakable


# --- ask: recorded path -----------------------------------------------------------------


def test_ask_without_model_key_returns_labelled_recording(
    data: ConnectorData, tmp_path: Path
) -> None:
    a = ask(
        data, "What changed this week for LLZ?", key_id="k1", runtime=no_model_runtime(tmp_path)
    )
    check_shape(a, "ask")
    assert a.provenance.kind == "recorded_answer"
    assert "recorded answer to a different, similar question" in a.speakable
    assert "What changed this week" in a.speakable  # the recorded question is spoken
    assert "stored reports through August 31, 2026" in a.speakable
    assert a.facts and all("api.fda.gov" in f.link for f in a.facts)


def test_ask_never_speaks_a_withheld_sentence(data: ConnectorData, tmp_path: Path) -> None:
    trap = next(t for t in data.transcripts() if t.get("label") == "06-trap")
    bad = [s for s in trap["final"]["sentences"] if s["status"] == "block"]
    assert bad, "fixture transcript must contain a withheld sentence"
    a = ask(data, trap["question"], key_id="k1", runtime=no_model_runtime(tmp_path))
    check_shape(a, "ask")
    withheld_texts = [w.text for w in a.withheld]
    assert [t for t in withheld_texts if t in [s["text"] for s in bad]] == [s["text"] for s in bad]
    assert all(w.status == "withheld" and w.reason for w in a.withheld)
    for s in bad:
        assert plain(s["text"]) not in a.speakable and s["text"] not in a.speakable
        assert all(s["text"] != f.text for f in a.facts)
    assert "left out" in a.speakable


def test_ask_unrelated_question_gets_no_invented_answer(
    data: ConnectorData, tmp_path: Path
) -> None:
    a = ask(data, "Recommend a pasta recipe", key_id="k1", runtime=no_model_runtime(tmp_path))
    check_shape(a, "ask")
    assert a.facts == [] and "no verified answer" in a.speakable


@pytest.mark.parametrize("q", ["", "  ", "x" * 501])
def test_ask_rejects_bad_questions(data: ConnectorData, tmp_path: Path, q: str) -> None:
    with pytest.raises(InvalidInputError):
        ask(data, q, key_id="k1", runtime=no_model_runtime(tmp_path))


# --- ask: live path with a scripted model and the real gate -----------------------------


def _msg(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeClient:
    def __init__(self, content: str) -> None:
        self.n = 0
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_: Any) -> Any:
        self.n += 1
        return _msg(self.content)


GOOD = {
    "kind": "count",
    "product_code": "LLZ",
    "value": 33,
    "date_from": "20260825",
    "date_to": "20260831",
}
BAD = {**GOOD, "value": 99}
SCRIPT = json.dumps(
    {
        "sentences": [
            {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [GOOD]},
            {"text": "LLZ had 99 reports from August 25 to August 31, 2026.", "claims": [BAD]},
        ]
    }
)


def live_runtime(tmp_path: Path, client: FakeClient, daily_usd: float = 5.0) -> AskRuntime:
    def factory(d: ConnectorData, guard: SpendGuard) -> CopilotAgent:
        return CopilotAgent(guard.wrap(client), d.tool_context())

    return AskRuntime(
        agent_factory=factory,
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=1.0, session_calls=20, daily_usd=daily_usd),
        ledger_dir=tmp_path / "led",
    )


def test_live_ask_gate_blocks_wrong_number_and_it_is_not_speakable(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_runtime(tmp_path, FakeClient(SCRIPT))
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt, now=lambda: NOW)
    check_shape(a, "ask")
    assert (
        a.provenance.kind == "live_model" and a.provenance.queried_at_utc == "2026-10-29T12:00:00Z"
    )
    assert "33 reports" in a.speakable and "99" not in a.speakable
    assert len(a.withheld) == 1 and "99" not in a.withheld[0].text  # text never returned live
    assert a.withheld[0].claim_kinds == ["count"]
    assert a.facts and "device/event.json" in a.facts[0].link
    # the spend was recorded against this key's ledger
    assert rt.ledger_for("abc").spent_today() > 0
    assert rt.ledger_for("other").spent_today() == 0


def test_live_ask_daily_cost_cap_falls_back_to_recorded(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = FakeClient(SCRIPT)
    rt = live_runtime(tmp_path, client, daily_usd=1.0)
    rt.ledger_for("abc").add(1.5, 3)  # today's budget is already used up
    a = ask(d, "What changed this week for LLZ?", key_id="abc", runtime=rt)
    assert client.n == 0, "no model call may start once the cap is reached"
    assert a.provenance.kind == "recorded_answer"
    assert "budget is used up" in a.speakable and "daily cost cap" in (a.provenance.note or "")


def test_live_ask_model_failure_falls_back_without_leaking_error(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")

    def factory(_: ConnectorData, __: SpendGuard) -> CopilotAgent:
        raise RuntimeError(f"upstream said bad key {KEY}")

    rt = AskRuntime(agent_factory=factory, live_enabled=lambda: True, ledger_dir=tmp_path / "led")
    a = ask(d, "What changed this week for LLZ?", key_id="abc", runtime=rt)
    assert a.provenance.kind == "recorded_answer"
    assert KEY not in json.dumps(a.model_dump())


# --- security building blocks ------------------------------------------------------------


def test_keystore_plain_and_hashed_entries() -> None:
    other = "another-key-value-0123456789-abcdefgh"
    env = {"MAUDESIGNAL_API_KEYS": f" {KEY} , sha256:{sha256_hex(other)} ,,"}
    ks = KeyStore.from_env(env)
    assert ks.configured
    assert ks.verify(KEY) == ks.key_id(KEY)
    assert ks.verify(other) == ks.key_id(other)
    assert ks.verify("nope") is None and ks.verify("") is None and ks.verify(None) is None
    assert ks.verify("x" * 1000) is None
    assert not KeyStore.from_env({}).configured


def test_rate_limiter_window() -> None:
    t = [0.0]
    rl = RateLimiter(3, clock=lambda: t[0])
    assert [rl.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, remaining, retry = rl.check("a")
    assert (allowed, remaining) == (False, 0) and 1 <= retry <= 60
    assert rl.check("b")[0] is True  # another key has its own budget
    t[0] = 61.0
    assert rl.check("a")[0] is True


def test_rate_limit_env() -> None:
    assert RateLimiter.from_env({"MAUDESIGNAL_RATE_LIMIT_PER_MIN": "7"}).limit == 7
    assert RateLimiter.from_env({"MAUDESIGNAL_RATE_LIMIT_PER_MIN": "abc"}).limit == 30
    assert RateLimiter.from_env({}).limit == 30


def test_speech_helpers() -> None:
    assert speak_date("20260831") == "August 31, 2026"
    assert (
        plain("**3.77x** is up 15% at [link](http://x.y)") == "3.77 times is up 15 percent at link"
    )
    assert plain("report 50426770") == "report 5 0 4 2 6 7 7 0"
    assert plain("33 reports, 8.75 average") == "33 reports, 8.75 average"


def test_key_id_is_peppered_and_short_keys_are_refused(caplog: pytest.LogCaptureFixture) -> None:
    plain_prefix = sha256_hex(KEY)[:12]
    a = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY, "MAUDESIGNAL_KEY_PEPPER": "pepper-one"})
    b = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY, "MAUDESIGNAL_KEY_PEPPER": "pepper-two"})
    assert a.verify(KEY) != plain_prefix, "id must not be a plain SHA-256 prefix"
    assert a.verify(KEY) != b.verify(KEY), "id depends on the server-side pepper"
    assert a.verify(KEY) == a.key_id(KEY) and len(a.key_id(KEY)) == 12
    short = "short-key-123"
    ks = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{short},{KEY}"})
    assert ks.verify(short) is None and ks.verify(KEY) is not None
    assert not KeyStore.from_env({"MAUDESIGNAL_API_KEYS": short}).configured
    assert short not in caplog.text


# --- live mode needs more than the model key -------------------------------------------


def test_model_key_alone_returns_recorded_answer(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("META_MODEL_API_KEY", "set-but-not-a-real-key")
    monkeypatch.delenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", raising=False)

    def boom(*_: object) -> object:
        raise AssertionError("no live call without the explicit per-instance override")

    rt = AskRuntime(agent_factory=boom, ledger_dir=tmp_path / "led")  # type: ignore[arg-type]
    assert rt.live_enabled() is False
    a = ask(data, "What changed this week for LLZ?", key_id="k1", runtime=rt)
    assert a.provenance.kind == "recorded_answer"
    assert "no_model" not in a.speakable  # the reason code is not spoken
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    assert rt.live_enabled() is True
    monkeypatch.delenv("META_MODEL_API_KEY")
    assert rt.live_enabled() is False, "the override alone does not enable live mode"


# --- stored text is screened on every tool ---------------------------------------------


def test_screen_replaces_forbidden_terms_but_keeps_links() -> None:
    from maudesignal.connector.models import Fact, Provenance
    from maudesignal.connector.tools import OMITTED_SPEAKABLE, OMITTED_TEXT, screen

    ans = ToolAnswer(
        tool="recalls",
        speakable="The device was validated by the firm.",
        facts=[
            Fact(text="Reason: approved by the board.", link="https://api.fda.gov/x"),
            Fact(text="Reason: plain wording.", link="https://api.fda.gov/y"),
        ],
        provenance=Provenance(kind="stored_demo_snapshot", source="test"),
    )
    out = screen(ans)
    assert out.speakable == OMITTED_SPEAKABLE
    assert out.facts[0].text == OMITTED_TEXT and out.facts[0].link == "https://api.fda.gov/x"
    assert out.facts[1].text == "Reason: plain wording."


def test_every_stored_report_and_recall_output_is_clean(data: ConnectorData) -> None:
    ids = sorted({r.report_id for r in data.store.records})
    assert len(ids) > 100
    for rid in ids:
        a = tools.get_report(data, rid)
        assert forbidden_in(a.speakable) == [], rid
        assert all(forbidden_in(f.text) == [] and f.link.startswith("https://") for f in a.facts)
    codes = sorted({r.product_code for r in data.store.recalls})
    assert codes
    for code in codes:
        a = tools.recalls(data, code)
        assert forbidden_in(a.speakable) == [], code
        assert all(forbidden_in(f.text) == [] and f.link.startswith("https://") for f in a.facts)


def test_check_device_type_fallback_says_live_failed(data: ConnectorData) -> None:
    from maudesignal.common.exceptions import OpenFDAAPIError

    def down(_: str) -> LiveCheck:
        raise OpenFDAAPIError("unreachable")

    a = tools.check_device_type(data, "LLZ", live_checker=down)
    assert a.speakable.startswith("Live openFDA could not be reached, so this is the stored demo")
    assert a.provenance.kind == "stored_demo_snapshot"
    assert len(re.split(r"(?<=[.!?])\s+", a.speakable)) <= 3
