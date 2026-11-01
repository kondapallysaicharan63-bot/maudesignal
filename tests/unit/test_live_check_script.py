"""live_check.py must never print a key-shaped string from a response (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RELEASE = Path(__file__).resolve().parents[2] / "scripts" / "release"
sys.path.insert(0, str(RELEASE))

import live_check  # noqa: E402
from budget import Budget  # noqa: E402
from netutil import Response  # noqa: E402

LEAK = "MAUDESIGNAL_API_KEYS=abcdefgh12345678"


def test_a_key_shaped_answer_never_reaches_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        b'{"mode":"live","tier":"live","cost_usd":0.01,"trace":[{"step":"s","model":"m","ms":1,'
        b'"status":"ok","note":"1 tool call(s): x"}],'
        b'"answer":{"spoken_text":"here is ' + LEAK.encode() + b'"}}'
    )
    monkeypatch.setattr(live_check, "request", lambda *a, **k: Response(200, {}, body, 5))
    row = live_check.describe(1, "q?", Budget(max_usd=0.4))
    out = capsys.readouterr().out
    assert "abcdefgh12345678" not in out and "abcdefgh12345678" not in str(row)
    assert live_check.KEY_WITHHELD in out
    assert "tool_calls: 1" in out


def test_safe_filters_nested_values() -> None:
    assert live_check.safe({"a": [LEAK, "fine"]}) == {"a": [live_check.KEY_WITHHELD, "fine"]}


def test_admin_key_goes_only_to_the_exact_api_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY_SMOKE", "adminadminadmin")
    for api in (
        "https://maudesignal-api.evil.example",
        "https://maudesignal-api.vercel.app.evil.io",
    ):
        assert live_check.main(["--api", api, "--out-dir", str(tmp_path), "--no-browser"]) == 2
