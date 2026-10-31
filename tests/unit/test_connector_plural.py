"""Singular/plural wording in speakable answers, /v1/connect base URL and key-label spacing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maudesignal.connector import tools
from maudesignal.connector.security import split_label
from maudesignal.connector.speech import plural, were
from maudesignal.monitor.live_check import LiveCheck
from tests.unit.test_connector import NOW, fake_check


@pytest.mark.parametrize(
    ("n", "text"), [(0, "0 reports"), (1, "1 report"), (2, "2 reports"), (561, "561 reports")]
)
def test_plural_reports(n: int, text: str) -> None:
    assert plural(n, "report") == text


def test_plural_irregular_and_phrases() -> None:
    assert plural(1, "recall product record") == "1 recall product record"
    assert plural(2, "recall event") == "2 recall events"
    assert plural(1, "sentence") == "1 sentence"
    assert plural(0, "code", "codes") == "0 codes"
    assert plural(1, "answer") == "1 answer"
    assert (were(0), were(1), were(2)) == ("were", "was", "were")


def _live(current: int, baseline: int, prior: int) -> tools.ToolAnswer:
    check: LiveCheck = replace(
        fake_check("LLZ"),
        current_count=current,
        baseline_count=baseline,
        prior_report_count=prior,
        current_severe_count=0,
    )
    return tools._live_answer("what_changed", check, NOW)


@pytest.mark.parametrize(
    ("n", "spoken", "fact"),
    [
        (0, "There were 0 reports in the 7 days", "0 reports received"),
        (1, "There was 1 report in the 7 days", "1 report received"),
        (2, "There were 2 reports in the 7 days", "2 reports received"),
    ],
)
def test_live_week_count_wording(n: int, spoken: str, fact: str) -> None:
    a = _live(n, n, n)
    assert spoken in a.speakable
    texts = [f.text for f in a.facts]
    assert any(t.startswith(fact) for t in texts)
    assert any(t.startswith(f"{plural(n, 'report')} received") and "before" in t for t in texts)
    assert "1 reports" not in a.speakable and not any("1 reports" in t for t in texts)


def test_live_severe_fact_agrees_with_count() -> None:
    check = replace(fake_check("LLZ"), current_count=1, current_severe_count=1)
    a = tools._live_answer("what_changed", check, NOW)
    assert any("1 of this week's 1 report was injury or death." in f.text for f in a.facts)
    check = replace(fake_check("LLZ"), current_count=2, current_severe_count=1)
    a = tools._live_answer("what_changed", check, NOW)
    assert any("1 of this week's 2 reports was injury or death." in f.text for f in a.facts)


@pytest.mark.parametrize(
    ("total", "severe", "said"),
    [
        (5, 1, "1 of this week's 5 reports was injury or death."),
        (5, 0, "0 of this week's 5 reports were injury or death."),
        (5, 2, "2 of this week's 5 reports were injury or death."),
        (2, 2, "2 of this week's 2 reports were injury or death."),
        (1, 0, "0 of this week's 1 report were injury or death."),
    ],
)
def test_severe_verb_follows_the_severe_count(total: int, severe: int, said: str) -> None:
    check = replace(fake_check("LLZ"), current_count=total, current_severe_count=severe)
    a = tools._live_answer("what_changed", check, NOW)
    assert any(said in f.text for f in a.facts)


@pytest.mark.parametrize(
    ("total", "said"),
    [(0, "openFDA returned no reports"), (1, "1 report in total"), (2, "2 reports in total")],
)
def test_no_window_totals(total: int, said: str) -> None:
    check = replace(fake_check("LLZ"), window=None, as_of=None, prior_report_count=total)
    a = tools._live_answer("what_changed", check, datetime.now(UTC))
    assert said in a.speakable
    if total:
        assert any(f.text.startswith(f"{plural(total, 'report')} on openFDA") for f in a.facts)


@pytest.mark.parametrize("raw", ["lab = " + "k" * 40, "lab =" + "k" * 40, "lab= " + "k" * 40])
def test_label_with_spaces_around_equals(raw: str) -> None:
    label, key = split_label(raw)
    assert label == "lab"
    assert key == "k" * 40


def test_connect_uses_constant_base_for_other_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maudesignal.connector.app import API_BASE_URL
    from maudesignal.connector.data import ConnectorData
    from tests.unit.test_connector_keys_demo import DEMO, K1, client, store

    monkeypatch.delenv("MAUDESIGNAL_PUBLIC_URL", raising=False)
    c = client(ConnectorData(work_dir=tmp_path), tmp_path, store(K1, f"pub={DEMO}"))
    r = c.get("/v1/connect", headers={"host": "evil.example.net"})
    assert r.status_code == 200
    b = r.json()
    assert API_BASE_URL == "https://maudesignal-api.vercel.app"
    for k in ("mcp_url", "openapi_url", "docs_url", "privacy_url", "terms_url"):
        assert b[k].startswith(API_BASE_URL + "/") and "evil" not in b[k]
