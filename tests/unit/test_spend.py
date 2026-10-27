"""Per-session and daily spend caps for live Meta calls (no network)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.copilot.spend import (
    DailyLedger,
    SpendCaps,
    SpendGuard,
    SpendLimitError,
    chat_cost_usd,
    closest_recorded,
)
from maudesignal.storage.database import Database


class FakeCompletions:
    def __init__(self, prompt: int = 1000, completion: int = 500) -> None:
        self.calls = 0
        self.usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(usage=self.usage, choices=[])


def _client(fc: FakeCompletions) -> Any:
    return SimpleNamespace(chat=SimpleNamespace(completions=fc))


def _guard(
    tmp_path: Path, caps: SpendCaps, db: Database | None = None, sid: str = "a" * 32
) -> SpendGuard:
    ledger = DailyLedger(tmp_path / "ledger.json", today=lambda: date(2026, 10, 27))
    return SpendGuard(session_id=sid, caps=caps, ledger=ledger, db=db)


def test_caps_from_env_defaults_and_overrides() -> None:
    assert SpendCaps.from_env({}) == SpendCaps(1.0, 20, 10.0)
    caps = SpendCaps.from_env(
        {
            "MAUDESIGNAL_CAP_SESSION_USD": "0.25",
            "MAUDESIGNAL_CAP_SESSION_CALLS": "5",
            "MAUDESIGNAL_CAP_DAILY_USD": "3",
        }
    )
    assert caps == SpendCaps(0.25, 5, 3.0)
    # Invalid or negative values keep the defaults.
    assert SpendCaps.from_env({"MAUDESIGNAL_CAP_SESSION_USD": "x"}).session_usd == 1.0
    assert SpendCaps.from_env({"MAUDESIGNAL_CAP_DAILY_USD": "-1"}).daily_usd == 10.0


def test_call_cap_stops_the_next_call_before_it_is_made(tmp_path: Path) -> None:
    fc = FakeCompletions(prompt=10, completion=10)
    g = _guard(tmp_path, SpendCaps(session_usd=1.0, session_calls=3, daily_usd=10.0))
    client = g.wrap(_client(fc))
    for _ in range(3):
        client.chat.completions.create(model="muse-spark-1.3", messages=[])
    with pytest.raises(SpendLimitError) as info:
        client.chat.completions.create(model="muse-spark-1.3", messages=[])
    assert info.value.cap == "session_calls"
    assert fc.calls == 3  # the 4th call never reached the API
    assert g.remaining().session_calls == 0 and g.remaining().exhausted


def test_dollar_cap_whichever_comes_first(tmp_path: Path) -> None:
    # 1M input + 1M output tokens per call = 1.25 + 4.25 = $5.50 per Spark call.
    fc = FakeCompletions(prompt=1_000_000, completion=1_000_000)
    g = _guard(tmp_path, SpendCaps(session_usd=1.0, session_calls=20, daily_usd=10.0))
    client = g.wrap(_client(fc))
    client.chat.completions.create(model="muse-spark-1.3", messages=[])
    assert g.session_usd == 5.5 and g.session_calls == 1
    with pytest.raises(SpendLimitError) as info:
        client.chat.completions.create(model="muse-spark-1.3", messages=[])
    assert info.value.cap == "session_usd" and fc.calls == 1


def test_daily_cap_is_shared_across_sessions(tmp_path: Path) -> None:
    fc = FakeCompletions(prompt=1_000_000, completion=0)  # $1.25 per call
    caps = SpendCaps(session_usd=5.0, session_calls=20, daily_usd=2.0)
    a = _guard(tmp_path, caps, sid="a" * 32)
    b = _guard(tmp_path, caps, sid="b" * 32)
    a.wrap(_client(fc)).chat.completions.create(model="muse-spark-1.3", messages=[])
    b.wrap(_client(fc)).chat.completions.create(model="muse-spark-1.3", messages=[])
    assert a.ledger.spent_today() == 2.5
    with pytest.raises(SpendLimitError) as info:
        a.check("chat")
    assert info.value.cap == "daily_usd"
    data = json.loads((tmp_path / "ledger.json").read_text())
    assert data == {"2026-10-27": {"calls": 2, "usd": 2.5}}
    # A new day starts from zero.
    tomorrow = DailyLedger(tmp_path / "ledger.json", today=lambda: date(2026, 10, 28))
    assert tomorrow.spent_today() == 0.0


def test_usage_and_cap_hit_are_audited_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    fc = FakeCompletions(prompt=100, completion=100)
    g = _guard(tmp_path, SpendCaps(1.0, 1, 10.0), db=db)
    g.wrap(_client(fc)).chat.completions.create(model="muse-wonder-1.0", messages=[])
    for _ in range(2):
        with pytest.raises(SpendLimitError):
            g.check("voice")
    trail = db.list_audit()
    assert [a.action for a in trail] == ["meta.usage", "meta.cap_hit"]
    usage = json.loads(trail[0].payload_json)
    assert usage["model"] == "muse-wonder-1.0"
    assert usage["estimated_cost_usd"] == chat_cost_usd("muse-wonder-1.0", 100, 100) == 0.0024
    assert json.loads(trail[1].payload_json)["cap"] == "session_calls"
    assert trail[0].entity_id == "S-" + "a" * 12
    assert db.verify_audit_chain() == (True, None)


def test_external_calls_counted_with_record(tmp_path: Path) -> None:
    g = _guard(tmp_path, SpendCaps(1.0, 2, 10.0))
    g.check("voice")
    g.record(kind="voice", model="muse-voice-transcribe-1.0", cost_usd=0.0002)
    g.record(kind="sam", model="sam-3.1", cost_usd=0.0025)
    assert g.remaining().session_calls == 0
    with pytest.raises(SpendLimitError):
        g.check("chat")


def test_closest_recorded_answer() -> None:
    ts = [
        {"label": "01", "question": "What came in overnight? Is anything worsening?"},
        {"label": "07", "question": "How many QIH reports are on file?"},
    ]
    assert closest_recorded("how many QIH reports do we have", ts)["label"] == "07"
    assert closest_recorded("anything worsening overnight", ts)["label"] == "01"
    assert closest_recorded("anything", []) is None
