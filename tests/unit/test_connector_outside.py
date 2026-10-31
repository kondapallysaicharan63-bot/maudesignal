"""The ``outside_mentions`` connector tool (HACKATHON-BUILT). Offline: run_research is faked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
jsonschema = pytest.importorskip("jsonschema")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector import outside, research  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.manifest import build_manifest  # noqa: E402
from maudesignal.connector.models import WEB_RESEARCH_LABEL  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_research import FakeTransport  # noqa: E402

DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"
ADMIN = "admin-key-NOT-REAL-0123456789"
EXACT_LABEL = "Web research — not FDA records, not verified by the gate"
WEB_TITLE = "WEBTEXT-ONLY-TITLE about LLZ"
WEB_URL = "https://news.example.com/webtext-only"
WEB_SUMMARY = "WEBTEXT-ONLY-SUMMARY a web page says something"
TOPIC = "software update"
PATH = "/v1/tools/outside_mentions"
SKILL = Path(__file__).resolve().parents[2] / "skills" / "web-research" / "SKILL.md"


class FakeRunner:
    """Stands in for research.run_research and keeps what it was asked."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, question: str, product_code: str | None, **kw: Any) -> dict[str, Any]:
        self.calls.append({"question": question, "product_code": product_code, **kw})
        item = {"title": WEB_TITLE, "url": WEB_URL, "date": None, "source": "news.example.com"}
        return research.block("ok", [item], WEB_SUMMARY, 0.0123, None)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("outside"))


def make(
    data: ConnectorData,
    monkeypatch: pytest.MonkeyPatch,
    *,
    on: bool = True,
    runner: Any = None,
    per_day: int | None = None,
    code_exists: Any = lambda _c: True,
    **extra: Any,
) -> tuple[TestClient, FakeRunner, KeyStore, ConnectorState]:
    if on:
        monkeypatch.setenv("MAUDESIGNAL_RESEARCH", "1")
    else:
        monkeypatch.delenv("MAUDESIGNAL_RESEARCH", raising=False)
    if per_day is None:
        monkeypatch.delenv("MAUDESIGNAL_RESEARCH_PER_KEY_DAY", raising=False)
    else:
        monkeypatch.setenv("MAUDESIGNAL_RESEARCH_PER_KEY_DAY", str(per_day))
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY", ADMIN)
    ks = KeyStore.from_env(
        {
            "MAUDESIGNAL_API_KEYS": f"reviewer-1={KEY}",
            "MAUDESIGNAL_DEMO_KEYS": DEMO,
            "MAUDESIGNAL_KEY_PEPPER": "pepper-NOT-REAL",
        }
    )
    fake = runner if runner is not None else FakeRunner()
    state = extra.pop("state", None) or ConnectorState()
    settings = Settings(
        keys=ks,
        limiter=RateLimiter(100),
        demo_limiter=RateLimiter(100),
        data=data,
        live_checker=fake_check,
        code_exists=code_exists,
        feedback_store=MemoryStore(),
        state=state,
        chat_tiers=False,
        research_runner=fake,
        research_fetcher=None,
        **extra,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), fake, ks, state


def rpc(c: TestClient, key: str, method: str, params: dict[str, Any] | None = None) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return c.post("/mcp", json=body, headers={"X-API-Key": key}).json()


def listed(c: TestClient, key: str = KEY) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in rpc(c, key, "tools/list")["result"]["tools"]}


H = {"X-API-Key": KEY}


# --- flag off: production behaviour unchanged -------------------------------------------------


def test_flag_off_tool_is_absent_everywhere(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, fake, _ks, _st = make(data, monkeypatch, on=False)
    assert "outside_mentions" not in listed(c)
    err = rpc(c, KEY, "tools/call", {"name": "outside_mentions", "arguments": {}})
    assert err["error"]["message"] == "Unknown tool."
    assert c.post(PATH, json={"product_code": "LLZ"}, headers=H).status_code == 404
    assert c.post(PATH, json={"bad": 1}).status_code == 404  # 404 before key or body checks
    assert PATH not in c.get("/openapi.json").json()["paths"]
    assert "outside_mentions" not in [t["name"] for t in build_manifest()["tools"]]
    assert "Web research is off here" in c.get("/privacy").text
    assert fake.calls == []


# --- flag on ------------------------------------------------------------------------------------


def test_flag_on_listed_with_hints_and_description(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _fake, _ks, _st = make(data, monkeypatch)
    tool = listed(c)["outside_mentions"]
    assert tool["annotations"] == {
        "title": tool["title"],
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    desc = tool["description"]
    assert "not FDA records" in desc and "not verified" in desc and EXACT_LABEL in desc
    assert tool["inputSchema"]["required"] == ["product_code"]
    assert tool["inputSchema"]["properties"]["topic"]["maxLength"] == 120
    op = c.get("/openapi.json").json()["paths"][PATH]["post"]
    assert op["description"] == desc
    assert "Web research is ON here" in " ".join(c.get("/privacy").text.split())


def test_label_is_exact_over_rest_and_mcp(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert research.LABEL == WEB_RESEARCH_LABEL == EXACT_LABEL
    c, fake, _ks, _st = make(data, monkeypatch)
    r = c.post(PATH, json={"product_code": "llz", "topic": TOPIC}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == EXACT_LABEL
    assert set(body) == {"status", "label", "items", "summary_text", "cost_usd", "note"}
    res = rpc(
        c, KEY, "tools/call", {"name": "outside_mentions", "arguments": {"product_code": "LLZ"}}
    )
    res = res["result"]
    assert res["isError"] is False and res["structuredContent"]["label"] == EXACT_LABEL
    assert res["content"][0]["text"].startswith(EXACT_LABEL)
    assert [x["product_code"] for x in fake.calls] == ["LLZ", "LLZ"]


def test_schema_contract_mcp_and_rest(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _fake, _ks, _st = make(data, monkeypatch)
    tool = listed(c)["outside_mentions"]
    res = rpc(
        c, KEY, "tools/call", {"name": "outside_mentions", "arguments": {"product_code": "QIH"}}
    )
    jsonschema.validate(res["result"]["structuredContent"], tool["outputSchema"])
    skill_schema = json.loads(
        (SKILL.parent / "schemas" / "output.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(res["result"]["structuredContent"], skill_schema)
    spec = c.get("/openapi.json").json()
    schema = spec["paths"][PATH]["post"]["responses"]["200"]["content"]["application/json"]
    r = c.post(PATH, json={"product_code": "QIH"}, headers=H)
    jsonschema.validate(r.json(), {**schema["schema"], "components": spec["components"]})
    assert build_manifest()["tools"][-1]["outputSchema"] == tool["outputSchema"]


def test_question_comes_from_the_skill_file(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, fake, _ks, _st = make(data, monkeypatch)
    c.post(PATH, json={"product_code": "LLZ"}, headers=H)
    c.post(PATH, json={"product_code": "LLZ", "topic": "  software   update "}, headers=H)
    plain, with_topic = outside.load_templates()
    skill = SKILL.read_text(encoding="utf-8")
    assert plain in skill and with_topic in skill and "{topic}" in with_topic
    assert fake.calls[0]["question"] == plain
    assert fake.calls[1]["question"] == with_topic.replace("{topic}", TOPIC)


def test_demo_key_is_refused(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake, _ks, _st = make(data, monkeypatch)
    r = c.post(PATH, json={"product_code": "LLZ"}, headers={"X-API-Key": DEMO})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_key"
    assert "not available with the demo key" in r.json()["error"]["message"]
    res = rpc(
        c, DEMO, "tools/call", {"name": "outside_mentions", "arguments": {"product_code": "LLZ"}}
    )["result"]
    assert res["isError"] is True and "not available with the demo key" in res["content"][0]["text"]
    assert fake.calls == []


def test_per_key_daily_limit(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fake, _ks, _st = make(data, monkeypatch, per_day=2)
    bodies = [c.post(PATH, json={"product_code": "LLZ"}, headers=H).json() for _ in range(3)]
    assert len(fake.calls) == 2
    last = bodies[-1]
    assert last["status"] == "unavailable" and last["items"] == [] and last["cost_usd"] == 0
    assert last["label"] == EXACT_LABEL and "Daily limit of 2" in last["note"]
    assert outside.per_key_day({}) == 10
    assert outside.per_key_day({"MAUDESIGNAL_RESEARCH_PER_KEY_DAY": "x"}) == 10


def test_bad_inputs_never_reach_the_paid_search(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, fake, _ks, _st = make(data, monkeypatch, code_exists=lambda _c: False)
    r = c.post(PATH, json={"product_code": "QIJ"}, headers=H)  # typo of QIH
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_product_code"
    assert "QIH" in r.json()["error"].get("suggestions", [])
    assert c.post(PATH, json={"product_code": "LL"}, headers=H).status_code == 422
    assert (
        c.post(PATH, json={"product_code": "LLZ", "topic": "x" * 121}, headers=H).status_code == 422
    )
    phi = c.post(PATH, json={"product_code": "LLZ", "topic": "MRN 1234567"}, headers=H)
    assert phi.status_code == 422 and "patient details" in phi.json()["error"]["message"]
    res = rpc(
        c,
        KEY,
        "tools/call",
        {"name": "outside_mentions", "arguments": {"product_code": "LLZ", "extra": "x"}},
    )["result"]
    assert res["isError"] is True
    assert fake.calls == []


def test_no_web_text_enters_any_gated_answer_audit_or_cache(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _fake, ks, state = make(data, monkeypatch)
    c.post(PATH, json={"product_code": "LLZ", "topic": TOPIC}, headers=H)
    rpc(c, KEY, "tools/call", {"name": "outside_mentions", "arguments": {"product_code": "LLZ"}})
    gated = [
        c.post("/v1/tools/ask", json={"question": "What changed this week for LLZ?"}, headers=H),
        c.get("/v1/tools/what_changed_this_week", params={"product_code": "LLZ"}, headers=H),
        c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H),
    ]
    audit = c.get("/v1/audit/recent", params={"limit": 50}, headers=H)
    for text in [g.text for g in gated] + [audit.text, json.dumps(state._cache)]:
        for web in (WEB_TITLE, WEB_URL, WEB_SUMMARY, "WEBTEXT", TOPIC, EXACT_LABEL):
            assert web not in text
    rows = [e for e in audit.json()["entries"] if e["action"] == "tool:outside_mentions"]
    first = json.loads(rows[0]["payload_json"])
    assert len(rows) == 2 and "topic_sha256" in first["inputs"]
    assert first["research"]["items"] == 1
    clients = c.get("/v1/admin/clients", headers={"X-Admin-Key": ADMIN}).json()
    [row] = [x for x in clients["clients"] if x["client_id"] == str(ks.verify(KEY))[:8]]
    assert row["calls_today"] == 5 and row["kind"] == "REST, MCP"


def test_spend_goes_through_the_call_ledger(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real run_research with a fake transport: the request is reserved in the call ledger."""
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    transport = FakeTransport()
    state = ConnectorState()
    c, _fake, _ks, _st = make(
        data,
        monkeypatch,
        runner=research.run_research,
        state=state,
        research_transport=lambda: transport,
    )
    r = c.post(PATH, json={"product_code": "LLZ"}, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["cost_usd"] > 0
    assert len(transport.sent) == 1 and "LLZ" in transport.sent[0]["input"]
    ledger = state.call_ledger(allow_memory=True)
    assert ledger is not None and ledger.total() == pytest.approx(body["cost_usd"])
