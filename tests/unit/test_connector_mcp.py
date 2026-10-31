"""MCP transport tests for the Muse connector (HACKATHON-BUILT). No network, no model key.

JSON-RPC is posted over the ASGI test client; REST and MCP answers must be identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.manifest import MANIFEST_PATH, build_manifest, render  # noqa: E402
from maudesignal.connector.mcp_server import PROTOCOL_VERSION  # noqa: E402
from maudesignal.connector.models import ADVISORY  # noqa: E402
from maudesignal.connector.registry import TOOL_SPECS  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_api import TOOL_CALLS, call  # noqa: E402
from tests.unit.test_connector_lookup import ROW_802, FakeSearcher  # noqa: E402
from tests.unit.test_connector_safety import (  # noqa: E402
    BLOCKED,
    BLOCKED_SCRIPT,
    OneAnswerClient,
    _assert_no_sentence_text,
    live_rt,
)

H = {"X-API-Key": KEY}
BEARER = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("mcp"))


def make_client(
    data: ConnectorData, tmp_path: Path, *, limit: int = 100, runtime: AskRuntime | None = None
) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(limit),
        data=data,
        ask_runtime=runtime or AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=fake_check,
        lookup_searcher=FakeSearcher(k510=[ROW_802]),
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def rpc(
    c: TestClient, method: str, params: dict[str, Any] | None = None, *, rid: int = 1, **kw: Any
) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    kw.setdefault("headers", H)
    return c.post("/mcp", json=body, **kw)


def test_initialize_and_notification(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = rpc(c, "initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert res["capabilities"] == {"tools": {"listChanged": False}}
    assert "Mcp-Session-Id" not in r.headers and "mcp-session-id" not in r.headers
    note = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=H)
    assert note.status_code == 202 and note.content == b""
    assert rpc(c, "ping").json()["result"] == {}


def test_tools_list_has_six_read_only_tools(data: ConnectorData, tmp_path: Path) -> None:
    tools = rpc(make_client(data, tmp_path), "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == [t for _, t, _ in TOOL_CALLS]
    assert len(tools) == 6
    for t in tools:
        a = t["annotations"]
        assert a["readOnlyHint"] is True and a["destructiveHint"] is False
        assert t["inputSchema"]["type"] == "object" and t["description"]
    open_world = {t["name"]: t["annotations"]["openWorldHint"] for t in tools}
    assert open_world == {
        "what_changed_this_week": True,
        "check_device_type": True,
        "ask": True,
        "get_report": False,
        "recalls": False,
        "lookup_device": True,
    }


@pytest.mark.parametrize(("method", "tool", "spec"), TOOL_CALLS)
def test_tools_call_equals_rest(
    data: ConnectorData, tmp_path: Path, method: str, tool: str, spec: dict[str, Any]
) -> None:
    c = make_client(data, tmp_path)
    rest = call(c, method, tool, spec, headers=H).json()
    args = spec["json"] if method == "POST" else spec
    res = rpc(c, "tools/call", {"name": tool, "arguments": args}).json()["result"]
    assert res["isError"] is False
    assert res["structuredContent"] == rest
    assert res["content"] == [{"type": "text", "text": rest["speakable"]}]
    assert res["structuredContent"]["advisory"] == ADVISORY


def test_tool_errors_are_tool_results_and_rpc_errors(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    missing = rpc(c, "tools/call", {"name": "get_report", "arguments": {"report_id": "0000001"}})
    assert missing.json()["result"]["isError"] is True
    bad = rpc(c, "tools/call", {"name": "recalls", "arguments": {"product_code": "LLZZ"}})
    assert bad.json()["result"]["isError"] is True
    extra = rpc(
        c, "tools/call", {"name": "recalls", "arguments": {"product_code": "LLZ", "x": "1"}}
    )
    assert extra.json()["result"]["isError"] is True
    unknown = rpc(c, "tools/call", {"name": "draft_capa", "arguments": {}}).json()
    assert unknown["error"]["code"] == -32602
    assert rpc(c, "nope").json()["error"]["code"] == -32601
    garbled = c.post("/mcp", content=b"{not json", headers=H)
    assert garbled.status_code == 400 and garbled.json()["error"]["code"] == -32700
    batch = c.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=H)
    assert batch.status_code == 400
    assert c.get("/mcp", headers=H).status_code == 405
    assert KEY not in json.dumps(unknown) and KEY not in missing.text and KEY not in bad.text


# --- auth, rate limit, transport guards ------------------------------------------------------


def test_auth_is_enforced_on_mcp(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert c.post("/mcp", json=msg).status_code == 401
    wrong = c.post("/mcp", json=msg, headers={"X-API-Key": "not-the-key-" * 4})
    assert wrong.status_code == 401
    bearer_wrong = c.post("/mcp", json=msg, headers={"Authorization": "Bearer " + "x" * 40})
    assert bearer_wrong.status_code == 401
    assert c.post("/mcp", json=msg, headers=BEARER).status_code == 200
    assert c.post("/mcp", json=msg, headers=H).status_code == 200
    for r in (c.post("/mcp", json=msg), wrong, bearer_wrong):
        assert KEY not in r.text
    assert c.post(f"/mcp?api_key={KEY}", json=msg, headers=H).status_code == 400


def test_bearer_also_works_on_rest(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=BEARER)
    assert r.status_code == 200


def test_rate_limit_is_shared_between_rest_and_mcp(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, limit=3)
    assert rpc(c, "ping").status_code == 200
    assert c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H).status_code == 200
    assert rpc(c, "tools/list").status_code == 200
    limited = rpc(c, "ping")
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert KEY not in limited.text


def test_origin_and_protocol_version_guards(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = rpc(c, "ping", headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = rpc(c, "ping", headers={**H, "MCP-Protocol-Version": "1999-01-01"})
    assert r.status_code == 400
    r = rpc(c, "ping", headers={**H, "MCP-Protocol-Version": PROTOCOL_VERSION})
    assert r.status_code == 200


def test_mcp_calls_are_audited(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    rpc(c, "tools/call", {"name": "recalls", "arguments": {"product_code": "LLZ"}})
    rpc(c, "tools/call", {"name": "ask", "arguments": {"question": "secret question text here"}})
    body = c.get("/v1/audit/recent", params={"limit": 5}, headers=H).json()
    assert body["chain"]["verified"] is True
    actions = [e["action"] for e in body["entries"]]
    assert "tool:recalls" in actions and "tool:ask" in actions
    assert "secret question text" not in json.dumps(body) and KEY not in json.dumps(body)


# --- manifest ----------------------------------------------------------------------------------


def test_manifest_matches_registry_and_tools_list(data: ConnectorData, tmp_path: Path) -> None:
    assert MANIFEST_PATH.read_text(encoding="utf-8") == render(
        build_manifest()
    ), "api/mcp-manifest.json is stale: run python3.12 -m maudesignal.connector.manifest"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert [t["name"] for t in manifest["tools"]] == [s.name for s in TOOL_SPECS]
    c = make_client(data, tmp_path)
    assert manifest["tools"] == rpc(c, "tools/list").json()["result"]["tools"]
    assert c.get("/mcp-manifest.json").json() == manifest  # public, no key
    assert manifest["protocolVersion"] == PROTOCOL_VERSION and manifest["readOnly"] is True
    for word in ("approved", "official", "endorsed"):
        assert word not in json.dumps(manifest).lower()


def test_rest_descriptions_and_names_come_from_the_registry(
    data: ConnectorData, tmp_path: Path
) -> None:
    spec = make_client(data, tmp_path).get("/openapi.json").json()
    for s in TOOL_SPECS:
        ops = [
            op
            for path in spec["paths"].values()
            for op in path.values()
            if op.get("operationId") == s.name
        ]
        assert len(ops) == 1 and ops[0]["description"] == s.description


# --- withheld sentences in live mode ------------------------------------------------------------


def test_mcp_live_body_never_holds_a_withheld_sentence(data: ConnectorData, tmp_path: Path) -> None:
    """Text and structuredContent of a live ask: no withheld sentence, whole raw body scanned."""
    runtime = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    c = make_client(data, tmp_path, runtime=runtime)
    r = rpc(
        c,
        "tools/call",
        {"name": "ask", "arguments": {"question": "How many LLZ reports this week?"}},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    answer = result["structuredContent"]
    assert answer["provenance"]["kind"] == "live_model"
    assert len(answer["withheld"]) == 4
    _assert_no_sentence_text(r.text)  # the raw response body, every field
    _assert_no_sentence_text(r.content.decode("utf-8"))
    _assert_no_sentence_text(result["content"][0]["text"])  # what a voice reads
    _assert_no_sentence_text(json.dumps(answer))
    for sentence in BLOCKED:  # also the JSON-escaped form of the raw body
        assert json.dumps(sentence)[1:-1] not in r.text
    assert forbidden_in(r.text) == []
    assert "left out" in result["content"][0]["text"]  # the speakable says some were left out


def test_client_disconnect_while_reading_the_body_is_a_quiet_400(
    data: ConnectorData, tmp_path: Path
) -> None:
    import asyncio

    from starlette.requests import ClientDisconnect

    app = create_app(
        Settings(
            keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
            limiter=RateLimiter(100),
            data=data,
            ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
            live_checker=fake_check,
        )
    )
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 1),
        "headers": [(b"x-api-key", KEY.encode()), (b"content-type", b"application/json")],
    }
    asyncio.run(app(scope, receive, send))  # must not raise ClientDisconnect
    assert ClientDisconnect  # imported to show the exact exception this guards
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 400


def test_oversized_declared_length_is_rejected_before_reading(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make_client(data, tmp_path)
    r = c.post(
        "/mcp", content=b"x" * (64 * 1024 + 1), headers={**H, "content-type": "application/json"}
    )
    assert r.status_code == 413


def test_part_two_of_the_doc_has_no_forbidden_words() -> None:
    doc = Path(__file__).resolve().parents[2] / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
    text = doc.read_text(encoding="utf-8")
    part_two = text[text.index("# Part 2.") :]
    assert forbidden_in(part_two) == []
