"""Offline tests for scripts/research_probe.py (recorded fake payloads, no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "research_probe", ROOT / "scripts" / "research_probe.py"
)
assert _spec and _spec.loader
probe = importlib.util.module_from_spec(_spec)
sys.modules["research_probe"] = probe  # dataclasses look the module up
_spec.loader.exec_module(probe)

KEY = "sk-test-not-a-real-key-123"

#: Shape of an OpenAI-style Responses reply with web search calls and url citations.
FAKE_OK: dict[str, Any] = {
    "id": "resp_1",
    "status": "completed",
    "model": "muse-spark-1.3",
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "FDA safety communication CT scanner",
                "sources": [
                    {"type": "url", "url": "https://www.fda.gov/a", "title": "A"},
                    {"type": "url", "url": "https://www.fda.gov/b", "published_date": "2026-05-01"},
                ],
            },
        },
        {
            "type": "web_search_call",
            "id": "ws_2",
            "status": "completed",
            "action": {"type": "search", "queries": ["CT recall 2026"], "sources": []},
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "FDA posted X on 2026-05-01 [1].",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://www.fda.gov/b",
                            "title": "CT scanner communication",
                            "start_index": 0,
                            "end_index": 10,
                        },
                        {"type": "file_citation", "file_id": "f1"},
                    ],
                }
            ],
        },
    ],
    "usage": {
        "input_tokens": 12000,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 600,
        "output_tokens_details": {"reasoning_tokens": 150},
        "total_tokens": 12600,
    },
}

#: Probe 1's real outcome shape: searches made, output cap hit, no message.
FAKE_INCOMPLETE: dict[str, Any] = {
    "status": "incomplete",
    "incomplete_details": {"reason": "max_output_tokens"},
    "output": [
        {"type": "web_search_call", "status": "completed", "action": {"query": "q"}},
        {"type": "reasoning"},
    ],
    "usage": {"input_tokens": 24256, "output_tokens": 800},
}


def _err(param: str, message: str) -> dict[str, Any]:
    return {"error": {"type": "invalid_request_error", "param": param, "message": message}}


def test_build_request_shape() -> None:
    body = probe.build_request("muse-spark-1.3")
    assert body["tools"] == [{"type": "web_search"}]
    assert body["max_output_tokens"] == 3000
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_tool_calls"] == 2
    assert body["include"] == ["web_search_call.action.sources"]
    dropped = probe.build_request("muse-spark-1.3", frozenset({"include"}))
    assert "include" not in dropped and dropped["max_tool_calls"] == 2


def test_parse_ok_payload() -> None:
    res = probe.parse_response(FAKE_OK)
    assert res.status == "completed"
    assert res.web_search_calls == 2
    assert res.search_queries == ["FDA safety communication CT scanner", "CT recall 2026"]
    assert [s.sources for s in res.searches] == [2, 0]
    assert [c.url for c in res.citations] == ["https://www.fda.gov/b"]
    cite = res.citations[0]
    assert cite.kind == "url_citation" and (cite.start, cite.end) == (0, 10)
    assert [s.url for s in res.sources] == ["https://www.fda.gov/a", "https://www.fda.gov/b"]
    assert res.sources[1].date == "2026-05-01"
    assert res.input_tokens == 12000 and res.output_tokens == 600
    assert res.reasoning_tokens == 150
    assert "2026-05-01" in res.text


def test_parse_incomplete_payload() -> None:
    res = probe.parse_response(FAKE_INCOMPLETE)
    assert res.incomplete_reason == "max_output_tokens"
    assert res.web_search_calls == 1 and res.citations == [] and res.text == ""
    lines = "\n".join(probe.report("muse-spark-1.3", 200, res, probe.build_request("m")))
    assert "incomplete: max_output_tokens" in lines and "search 1:" in lines


def test_parse_odd_payloads() -> None:
    res = probe.parse_response({"output": [None, "x", {"type": "message", "content": [1]}]})
    assert res.web_search_calls == 0 and res.citations == [] and res.text == ""
    assert probe.parse_response({"output_text": "hi"}).text == "hi"


def test_cost_line() -> None:
    res = probe.parse_response(FAKE_OK)
    line = probe.cost_line("muse-spark-1.3", res)
    # 12000 * 1.25/M + 600 * 4.25/M = 0.015 + 0.00255
    assert "$0.017550" in line and "web_search tool fee: price unknown" in line
    assert "price unknown for other-model" in probe.cost_line("other-model", res)


def test_expected_max_cost_at_most_ten_cents() -> None:
    # 1 billed call x (40,000 x $1.25/M + 3,000 x $4.25/M) = $0.05 + $0.01275
    assert probe.expected_max_cost_usd() == pytest.approx(0.06275)
    assert probe.expected_max_cost_usd() <= 0.10


def test_rejected_params() -> None:
    msg = probe.error_message(_err("max_tool_calls", "Unknown parameter: max_tool_calls"))
    assert probe.rejected_params(400, msg) == {"max_tool_calls"}
    msg = probe.error_message(_err("include", "include value not supported"))
    assert probe.rejected_params(400, msg) == {"include"}
    assert probe.rejected_params(400, "bad request") == {"max_tool_calls", "include"}
    assert probe.rejected_params(401, "max_tool_calls") == frozenset()
    assert probe.rejected_params(429, "rate limited") == frozenset()
    assert probe.error_message("plain text") == "plain text"


def test_redact() -> None:
    assert KEY not in probe.redact(f"bad key {KEY}", KEY)
    assert probe.redact("x", "") == "x"


def _run(
    monkeypatch: pytest.MonkeyPatch, handler: Any, capsys: Any
) -> tuple[int, str, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.meta.ai/v1/responses"
        sent.append(json.loads(request.read()))
        return handler(sent[-1])  # type: ignore[no-any-return]

    transport = httpx.MockTransport(wrapped)
    real = httpx.Client
    monkeypatch.setattr(probe.httpx, "Client", lambda *a, **k: real(transport=transport))
    monkeypatch.setenv("META_MODEL_API_KEY", KEY)
    monkeypatch.delenv("META_MODEL_API_BASE_URL", raising=False)
    code = probe.main()
    out = capsys.readouterr().out
    assert KEY not in out and "Bearer" not in out and "Authorization" not in out
    return code, out, sent


def test_main_success_one_call(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    code, out, sent = _run(monkeypatch, lambda b: httpx.Response(200, json=FAKE_OK), capsys)
    assert code == 0 and len(sent) == 1
    assert "web_search accepted: yes" in out and "https://www.fda.gov/b" in out
    assert "web_search_call items: 2" in out and "span 0-10" in out
    assert "expected max token cost: $0.0628" in out


def test_main_retries_once_without_rejected_param(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def handler(body: dict[str, Any]) -> httpx.Response:
        if "max_tool_calls" in body:
            return httpx.Response(400, json=_err("max_tool_calls", "unknown parameter"))
        return httpx.Response(200, json=FAKE_OK)

    code, out, sent = _run(monkeypatch, handler, capsys)
    assert code == 0 and len(sent) == 2
    assert "include" in sent[1] and "max_tool_calls" not in sent[1]
    assert "retrying once without: max_tool_calls" in out


def test_main_never_more_than_two_calls(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    code, out, sent = _run(
        monkeypatch, lambda b: httpx.Response(400, json=_err("include", "bad include")), capsys
    )
    assert code == 1 and len(sent) == 2 and "requests made: 2" in out


def test_main_no_retry_on_other_error(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    body = {"error": {"message": f"invalid api key {KEY}"}}
    code, out, sent = _run(monkeypatch, lambda b: httpx.Response(401, json=body), capsys)
    assert len(sent) == 1 and code == 1 and "[REDACTED]" in out


def test_main_without_key(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    assert probe.main() == 2
    assert "no request made" in capsys.readouterr().out
