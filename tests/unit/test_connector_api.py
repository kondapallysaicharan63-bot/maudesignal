"""REST API tests for the Muse connector (HACKATHON-BUILT). No network, no model key."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData  # noqa: E402
from maudesignal.connector.models import ADVISORY  # noqa: E402
from maudesignal.connector.openapi import build_spec, render  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from tests.unit.test_connector import KEY, fake_check, offline  # noqa: E402

H = {"X-API-Key": KEY}
TOOL_CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "what_changed_this_week", {"product_code": "LLZ"}),
    ("GET", "check_device_type", {"product_code": "QAS"}),
    ("POST", "ask", {"json": {"question": "What changed this week for LLZ?"}}),
    ("GET", "get_report", {"report_id": "50426770"}),
    ("GET", "recalls", {"product_code": "LLZ"}),
]


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("api"))


def make_client(
    data: ConnectorData, tmp_path: Path, *, limit: int = 100, keys: str = KEY
) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": keys}),
        limiter=RateLimiter(limit),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=fake_check,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def call(c: TestClient, method: str, tool: str, spec: dict[str, Any], **kw: Any) -> Any:
    url = f"/v1/tools/{tool}"
    if method == "POST":
        return c.post(url, json=spec["json"], **kw)
    return c.get(url, params=spec, **kw)


def test_health_needs_no_key(data: ConnectorData, tmp_path: Path) -> None:
    r = make_client(data, tmp_path).get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["read_only"] is True
    assert body["tools"] == [t for _, t, _ in TOOL_CALLS]


@pytest.mark.parametrize(("method", "tool", "spec"), TOOL_CALLS)
def test_contract_per_tool(
    data: ConnectorData, tmp_path: Path, method: str, tool: str, spec: dict[str, Any]
) -> None:
    r = call(make_client(data, tmp_path), method, tool, spec, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"tool", "speakable", "facts", "advisory", "provenance", "withheld"}
    assert body["tool"] == tool
    assert body["advisory"] == ADVISORY
    assert body["speakable"] and isinstance(body["facts"], list)
    for fact in body["facts"]:
        assert set(fact) == {"text", "link", "link_label"} and fact["link"].startswith("https://")
    prov = body["provenance"]
    assert prov["kind"] in {"stored_demo_snapshot", "live_openfda", "recorded_answer", "live_model"}
    if prov["kind"] == "live_openfda":
        assert prov["queried_at_utc"]
    elif prov["kind"] == "stored_demo_snapshot":
        assert "snapshot fetched" in (prov["data_dates"] or "")
    assert r.headers["x-ratelimit-limit"] == "100"


def test_auth_missing_wrong_and_right_key(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    url = "/v1/tools/recalls?product_code=LLZ"
    missing = c.get(url)
    wrong = c.get(url, headers={"X-API-Key": "wrong-key-value"})
    right = c.get(url, headers=H)
    assert missing.status_code == 401 and wrong.status_code == 401 and right.status_code == 200
    assert missing.json() == wrong.json()  # same body: no hint which part failed
    assert missing.json()["error"]["code"] == "unauthorized"
    assert "wrong-key-value" not in wrong.text


def test_unauthenticated_request_with_bad_input_still_401(
    data: ConnectorData, tmp_path: Path
) -> None:
    assert make_client(data, tmp_path).get("/v1/tools/recalls?product_code=1").status_code == 401


def test_no_keys_configured_fails_closed(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, keys="")
    assert c.get("/v1/tools/recalls?product_code=LLZ", headers=H).status_code == 503


def test_rate_limit_returns_429_after_limit(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, limit=3)
    codes = [c.get("/v1/tools/recalls?product_code=LLZ", headers=H).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = c.get("/v1/tools/recalls?product_code=LLZ", headers=H)
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert KEY not in r.text and KEY not in json.dumps(dict(r.headers))
    assert c.get("/v1/health").status_code == 200  # health is not limited


def test_cost_cap_falls_back_to_recorded_answer_over_http(
    data: ConnectorData, tmp_path: Path
) -> None:
    def boom(*_: Any) -> Any:
        raise AssertionError("no live call after the cap")

    rt = AskRuntime(agent_factory=boom, live_enabled=lambda: True, ledger_dir=tmp_path / "led")
    key_id = KeyStoreId.of(KEY)
    rt.ledger_for(key_id).add(rt.caps.daily_usd + 1, 1)
    c = TestClient(
        create_app(
            Settings(
                keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
                limiter=RateLimiter(10),
                data=data,
                ask_runtime=rt,
                live_checker=fake_check,
            )
        )
    )
    r = c.post("/v1/tools/ask", json={"question": "What changed this week?"}, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["provenance"]["kind"] == "recorded_answer"
    assert "budget is used up" in body["speakable"]


class KeyStoreId:
    @staticmethod
    def of(key: str) -> str:
        return KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}).key_id(key)


def test_ask_over_http_never_speaks_withheld(data: ConnectorData, tmp_path: Path) -> None:
    trap = next(t for t in data.transcripts() if t.get("label") == "06-trap")
    r = make_client(data, tmp_path).post(
        "/v1/tools/ask", json={"question": trap["question"]}, headers=H
    )
    body = r.json()
    assert body["withheld"], "the gate-withheld sentence must be listed"
    for w in body["withheld"]:
        assert w["status"] == "withheld" and w["reason"]
        assert w["text"] not in body["speakable"]
        assert all(w["text"] != f["text"] for f in body["facts"])


def test_error_statuses(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    assert c.get("/v1/tools/get_report?report_id=00000000", headers=H).status_code == 404
    assert c.get("/v1/tools/get_report?report_id=a/b", headers=H).status_code == 422
    assert c.get("/v1/tools/check_device_type?product_code=ab", headers=H).status_code == 422
    assert c.get("/v1/tools/check_device_type", headers=H).status_code == 422
    assert c.post("/v1/tools/ask", json={"question": ""}, headers=H).status_code == 422
    assert (
        c.post("/v1/tools/ask", json={"question": "hi there", "x": 1}, headers=H).status_code == 422
    )
    offline_client = TestClient(
        create_app(
            Settings(
                keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
                limiter=RateLimiter(10),
                data=data,
                ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "l"),
                live_checker=offline,
            )
        ),
        raise_server_exceptions=False,
    )
    r = offline_client.get("/v1/tools/check_device_type?product_code=QAS", headers=H)
    assert r.status_code == 502 and r.json()["error"]["code"] == "source_unavailable"


def test_unexpected_error_is_generic(data: ConnectorData, tmp_path: Path) -> None:
    def explode(_: str) -> Any:
        raise RuntimeError(f"secret detail {KEY}")

    c = TestClient(
        create_app(
            Settings(
                keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
                limiter=RateLimiter(10),
                data=data,
                ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "l"),
                live_checker=explode,
            )
        ),
        raise_server_exceptions=False,
    )
    r = c.get("/v1/tools/check_device_type?product_code=QAS", headers=H)
    assert r.status_code == 500 and KEY not in r.text and "secret detail" not in r.text


class RecordingLogger:
    """Stands in for the structlog logger (other tests reconfigure structlog globally)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def _log(self, event: str, **kw: Any) -> None:
        self.lines.append(f"{event} {kw}")

    info = warning = error = debug = _log


def test_key_never_appears_in_any_response_or_log(
    data: ConnectorData,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr("maudesignal.connector.app.logger", rec)
    monkeypatch.setattr("maudesignal.connector.ask.logger", rec)
    caplog.set_level(logging.DEBUG)
    c = make_client(data, tmp_path, limit=4)
    seen: list[str] = []
    for method, tool, spec in TOOL_CALLS:
        r = call(c, method, tool, spec, headers=H)
        seen += [r.text, json.dumps(dict(r.headers))]
    for _ in range(3):  # reaches 429
        r = c.get("/v1/tools/recalls?product_code=LLZ", headers=H)
        seen += [r.text, json.dumps(dict(r.headers))]
    r = c.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY + "x"})
    seen += [r.text, json.dumps(dict(r.headers))]
    out = capsys.readouterr()
    seen += [out.out, out.err, caplog.text, *rec.lines]
    assert sum("connector_request" in line for line in rec.lines) == 9, "every request is logged"
    for blob in seen:
        assert KEY not in blob and KEY[:8] not in blob and (KEY + "x") not in blob


def test_openapi_committed_and_in_sync() -> None:
    committed = (PROJECT_ROOT / "api" / "openapi.json").read_text(encoding="utf-8")
    assert committed == render(
        build_spec()
    ), "api/openapi.json is out of date: run `python3.12 -m maudesignal.connector.openapi`"
    spec = json.loads(committed)
    assert spec["openapi"].startswith("3.")
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    tool_ops = {
        op["operationId"]: op
        for path, item in spec["paths"].items()
        if path.startswith("/v1/tools/")
        for op in item.values()
    }
    assert set(tool_ops) == {t for _, t, _ in TOOL_CALLS}
    for op in tool_ops.values():
        assert op["x-maudesignal-read-only"] is True and op["security"]
        assert {"401", "429"} <= set(op["responses"])
    assert "security" not in spec["paths"]["/v1/health"]["get"]


def test_vercel_entry_point_exports_app() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("api_index", PROJECT_ROOT / "api" / "index.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert any(getattr(r, "path", "") == "/v1/health" for r in mod.app.routes)


# --- a key in the URL ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["api_key", "key", "token", "x-api-key", "API_KEY", "access_token"]
)
def test_key_in_query_string_is_rejected_with_400(
    data: ConnectorData, tmp_path: Path, name: str
) -> None:
    c = make_client(data, tmp_path)
    for url in (f"/v1/tools/recalls?product_code=LLZ&{name}={KEY}", f"/v1/health?{name}={KEY}"):
        r = c.get(url, headers=H)
        assert r.status_code == 400 and r.json()["error"]["code"] == "key_in_url"
        assert KEY not in r.text and KEY not in json.dumps(dict(r.headers))


def test_key_in_query_is_blanked_before_any_access_log_can_read_it() -> None:
    import asyncio

    from maudesignal.connector.asgi import RejectKeyInQuery, has_key_param

    async def never(*_: Any) -> None:
        raise AssertionError("the app must not run")

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    scope: dict[str, Any] = {
        "type": "http",
        "path": "/v1/tools/recalls",
        "query_string": f"product_code=LLZ&api_key={KEY}".encode(),
    }
    asyncio.run(RejectKeyInQuery(never)(scope, receive, send))
    assert scope["query_string"] == b"" and KEY not in repr(scope)
    assert sent[0]["status"] == 400 and KEY.encode() not in sent[1]["body"]
    assert not has_key_param(b"product_code=LLZ&report_id=1")


def test_health_states_that_limits_are_per_instance(data: ConnectorData, tmp_path: Path) -> None:
    assert make_client(data, tmp_path).get("/v1/health").json()["limits_scope"] == "per_instance"


def test_repeated_wrong_keys_get_429_before_key_check(data: ConnectorData, tmp_path: Path) -> None:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(100),
        failed_auth=RateLimiter(3),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=fake_check,
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    url = "/v1/tools/recalls?product_code=LLZ"
    guess = {"X-API-Key": "wrong-" + "0" * 40}
    codes = [c.get(url, headers=guess).status_code for _ in range(3)]
    assert codes == [401, 401, 401]
    r = c.get(url, headers=guess)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert "guess" not in r.text and KEY not in r.text
    # a different client address is not affected
    other = c.get(url, headers={**H, "X-Forwarded-For": "203.0.113.9"})
    assert other.status_code == 200
    assert c.get(url).status_code == 429  # missing key counts from the blocked address too
