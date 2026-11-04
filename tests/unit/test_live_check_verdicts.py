"""live_check.py passes only on an honest live answer; budget fits the plan (canned, no network)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

RELEASE = Path(__file__).resolve().parents[2] / "scripts" / "release"
sys.path.insert(0, str(RELEASE))

import live_check  # noqa: E402
from budget import HOLD_USD, Budget  # noqa: E402
from netutil import Response  # noqa: E402

LINK = {"label": "openFDA query", "url": "https://api.fda.gov/device/event.json?search=x"}
SENTENCE = "MYN has 12 stored reports, 3 of them injuries."


def _live_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mode": "live",
        "tier": "live",
        "cost_usd": 0.031,
        "trace": [
            {
                "step": "Muse Spark answers from stored records",
                "model": "muse-spark-1.3",
                "ms": 9000,
                "status": "ok",
            },
            {
                "step": "Read-only tools and claim gate",
                "model": None,
                "ms": 40,
                "status": "ok",
                "note": "2 tool call(s): count_reports, top_problems",
            },
        ],
        "answer": {
            "speakable": [{"text": SENTENCE, "links": [LINK]}],
            "withheld": [],
            "spoken_text": SENTENCE,
        },
    }
    body.update(over)
    return body


def _row(body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    return live_check.summarize("q?", status, body)


# The Nov 3 reply that the old check passed.
NOV3: dict[str, Any] = {
    "mode": "recorded",
    "tier": "live",
    "cost_usd": None,
    "trace": [
        {
            "step": "Muse Spark answers from stored records",
            "model": "muse-spark-1.3",
            "ms": 32147,
            "status": "failed",
            "note": "The model call failed.",
        },
        {
            "step": "Closest recorded answer",
            "model": None,
            "ms": 3,
            "status": "failed",
            "note": "no recorded answer matches",
        },
    ],
    "answer": {
        "speakable": [
            {
                "text": "I have no verified answer to that question right now. Try the what "
                "changed, device check, report or recalls tools instead.",
                "links": [],
            }
        ],
        "withheld": [],
        "spoken_text": "I have no verified answer to that question right now.",
    },
    "recorded_note": "The model call failed. No recorded answer matches this question.",
}


def test_a_linked_live_muse_spark_answer_passes() -> None:
    row = _row(_live_body())
    assert live_check.judge(row) == []
    assert row["links"] == [LINK] and row["models"] == ["muse-spark-1.3"]
    assert row["tool_calls"] == 2 and row["cost_usd"] == 0.031


def test_the_nov_3_non_answer_fails_with_every_reason() -> None:
    reasons = " | ".join(live_check.judge(_row(NOV3)))
    assert "mode is 'recorded'" in reasons
    assert "recorded answer was shown" in reasons
    assert "trace step failed: Muse Spark answers from stored records (32147 ms)" in reasons
    assert "closest recorded answer" in reasons
    assert "non-answer ('no verified answer')" in reasons
    assert "no shown sentence has a link" in reasons


def test_could_not_verify_with_everything_withheld_fails() -> None:
    line = "I could not verify an answer to that, so I am not stating one."
    body = _live_body(
        answer={
            "speakable": [{"text": line, "links": []}],
            "withheld": [{"reason": "count not found in a tool result"}],
            "spoken_text": line,
        }
    )
    reasons = live_check.judge(_row(body))
    assert any("could not verify an answer" in r for r in reasons)
    assert any("1 sentence(s) withheld and no verified, linked sentence" in r for r in reasons)


def test_a_withheld_sentence_is_fine_while_a_linked_one_is_left() -> None:
    body = _live_body(
        answer={
            "speakable": [{"text": SENTENCE, "links": [LINK]}],
            "withheld": [{"reason": "not tied to a source"}],
            "spoken_text": SENTENCE
            + " One sentence was left out because it could not be verified.",
        }
    )
    assert live_check.judge(_row(body)) == []


@pytest.mark.parametrize(
    ("over", "expect"),
    [
        ({"mode": "direct", "tier": "direct", "trace": []}, "mode is 'direct'"),
        ({"mode": "canned", "tier": "canned"}, "mode is 'canned'"),
        (
            {
                "tier": "cache",
                "trace": [{"step": "Answer reused", "model": None, "ms": 2, "status": "ok"}],
            },
            "no muse-spark model in the trace",
        ),
        (
            {
                "trace": [
                    {"step": "Muse Spark", "model": "muse-spark-1.3", "ms": 5, "status": "ok"},
                    {"step": "Claim gate", "model": None, "ms": 5, "status": "failed"},
                ]
            },
            "trace step failed: Claim gate",
        ),
    ],
)
def test_other_non_live_replies_fail(over: dict[str, Any], expect: str) -> None:
    reasons = live_check.judge(_row(_live_body(**over)))
    assert any(expect in r for r in reasons), reasons


def test_a_non_200_fails_with_its_code() -> None:
    body = {"error": {"code": "live_timeout", "message": "The live answer took too long."}}
    reasons = live_check.judge(_row(body, status=504))
    assert reasons[0] == "HTTP 504 (live_timeout)"


def test_a_budget_skip_fails_unless_allowed() -> None:
    row = {"question": "q?", "skipped": "skipped: budget"}
    assert live_check.judge(row) == ["skipped: budget (the call was never sent)"]
    assert live_check.judge(row, allow_skips=True) == []
    skipped_browser = {"url": "u", "skipped": "skipped: budget"}
    assert live_check.judge_browser(skipped_browser) != []
    assert live_check.judge_browser(skipped_browser, allow_skips=True) == []


def test_browser_needs_the_chip_and_a_real_answer() -> None:
    good = {"chip_ok": True, "page_has_unreachable": False, "ask": _row(_live_body())}
    assert live_check.judge_browser(good) == []
    assert live_check.judge_browser({**good, "ask": _row(NOV3)}) != []
    assert live_check.judge_browser({**good, "chip_ok": False, "chip_text": "Recorded"}) != []
    assert live_check.judge_browser({**good, "page_has_unreachable": True}) != []
    no_ask = {k: v for k, v in good.items() if k != "ask"}
    assert any("no /v1/live/ask" in r for r in live_check.judge_browser(no_ask))


def test_the_browser_question_is_not_also_an_api_question() -> None:
    # the same question twice would come back from the API's same-day cache, with no model call
    assert live_check.BROWSER_QUESTION not in live_check.QUESTIONS
    assert "What share of all stored MYN reports are injuries?" in live_check.QUESTIONS
    assert any("50 injury reports" in q and "820.100" in q for q in live_check.QUESTIONS)


def test_the_default_plan_fits_and_the_worst_case_stays_under_a_dollar() -> None:
    n = len(live_check.QUESTIONS) + 1  # every ask plus the browser ask
    b = live_check.make_budget(live_check.DEFAULT_MAX_USD, live_check.ASK_HOLD_USD, n)
    assert all(b.reserve("ask") for _ in range(n))  # all fit at their holds, none settled yet
    # worst case: every call reports no cost and counts at the $0.25 per-request cap
    w = live_check.make_budget(live_check.DEFAULT_MAX_USD, live_check.ASK_HOLD_USD, n)
    while w.reserve("ask"):
        w.settle("ask", None)
    worst = float(str(w.snapshot()["spent_usd"]))
    bound = live_check.DEFAULT_MAX_USD - live_check.ASK_HOLD_USD + HOLD_USD["ask"]
    assert worst <= bound + 1e-9 <= 1.00 + 1e-9
    # observed costs (~$0.03 each): every planned call runs
    o = live_check.make_budget(live_check.DEFAULT_MAX_USD, live_check.ASK_HOLD_USD, n)
    for _ in range(n):
        assert o.reserve("ask")
        o.settle("ask", 0.03)
    assert o.snapshot()["refused"] == []


def test_the_workflow_passes_the_same_limits() -> None:
    wf = (RELEASE.parents[1] / ".github" / "workflows" / "live-check.yml").read_text()
    assert f"--max-usd {live_check.DEFAULT_MAX_USD}" in wf
    assert f"--hold-usd {live_check.ASK_HOLD_USD:.2f}" in wf
    assert "--allow-budget-skips" not in wf


def test_budget_defaults_are_unchanged_for_smoke() -> None:
    b = Budget(max_usd=0.4)
    assert b.holds == HOLD_USD and b.unknown_usd == HOLD_USD
    assert b.reserve("ask") and not b.reserve("ask")  # 0.25 + 0.25 > 0.40
    b.settle("ask", None)
    assert b.snapshot()["spent_usd"] == 0.25


def _fake_request(ask_body: dict[str, Any]) -> tuple[Callable[..., Response], list[str]]:
    sent: list[str] = []

    def fake(method: str, url: str, **kw: Any) -> Response:
        sent.append(url)
        if url.endswith("/v1/live/ask"):
            headers = {"access-control-allow-origin": "x"}
            return Response(200, headers, json.dumps(ask_body).encode(), 7)
        if url.endswith("/v1/admin/delete-test"):
            return Response(200, {}, b'{"deleted": 4}', 3)
        return Response(200, {}, b'{"codes": []}', 3)

    return fake, sent


def test_main_passes_on_real_answers_and_saves_each_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY_SMOKE", "adminadminadmin")
    fake, sent = _fake_request(_live_body())
    monkeypatch.setattr(live_check, "request", fake)
    assert live_check.main(["--out-dir", str(tmp_path), "--no-browser"]) == 0
    asks = [u for u in sent if u.endswith("/v1/live/ask")]
    assert len(asks) == len(live_check.QUESTIONS)  # every planned ask ran
    for i in range(1, len(live_check.QUESTIONS) + 1):
        saved = json.loads((tmp_path / f"ask-{i}.json").read_text())
        assert saved["row"]["answer_text"] == SENTENCE and saved["row"]["links"] == [LINK]
        assert saved["row"]["mode"] == "live" and saved["row"]["models"] == ["muse-spark-1.3"]
        assert saved["row"]["trace"] and saved["row"]["cost_usd"] == 0.031
        assert saved["body"]["answer"]["speakable"]
    report = json.loads((tmp_path / "live-check.json").read_text())
    assert len(report["verdicts"]) == len(live_check.QUESTIONS)
    out = capsys.readouterr().out
    assert out.count("PASS ask") == len(live_check.QUESTIONS) and "FAIL" not in out


def test_main_fails_on_the_nov_3_reply_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY_SMOKE", "adminadminadmin")
    fake, _ = _fake_request(NOV3)
    monkeypatch.setattr(live_check, "request", fake)
    assert live_check.main(["--out-dir", str(tmp_path), "--no-browser"]) == 1
    out = capsys.readouterr().out
    assert "FAIL ask 1: " in out and "non-answer" in out and "trace step failed" in out


def test_main_fails_when_the_budget_skips_an_ask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY_SMOKE", "adminadminadmin")
    fake, _ = _fake_request(_live_body())
    monkeypatch.setattr(live_check, "request", fake)
    argv = ["--out-dir", str(tmp_path), "--no-browser", "--max-usd", "0.15"]
    assert live_check.main(argv) == 1
    assert "skipped: budget (the call was never sent)" in capsys.readouterr().out
    assert live_check.main([*argv, "--allow-budget-skips"]) == 0
