"""Connected-clients counters and the /admin panel (HACKATHON-BUILT). No network."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore, StoreError  # noqa: E402
from maudesignal.connector.clients import (  # noqa: E402
    ClientCounter,
    panel_enabled,
    short_client_id,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.feedback import ADMIN_PAGE  # noqa: E402
from maudesignal.connector.legal_pages import render_privacy  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState, UpstashClient  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_store import TOKEN, URL, FakeRedis  # noqa: E402

DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"
ADMIN = "admin-key-NOT-REAL-0123456789"
QUESTION = "Which recalls are on file for QIH SECRET-QUESTION-TEXT?"
A = {"X-Admin-Key": ADMIN}
FIXED = datetime(2026, 10, 31, 15, 4, 5, tzinfo=UTC)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("clients"))


def keys() -> KeyStore:
    return KeyStore.from_env(
        {
            "MAUDESIGNAL_API_KEYS": f"reviewer-1={KEY}",
            "MAUDESIGNAL_DEMO_KEYS": DEMO,
            "MAUDESIGNAL_KEY_PEPPER": "pepper-NOT-REAL",
        }
    )


def make(
    data: ConnectorData,
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: Any = None,
    panel: bool = True,
    now: Any = lambda: FIXED,
    state: ConnectorState | None = None,
) -> tuple[TestClient, Any, KeyStore]:
    monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY", ADMIN)
    ks = keys()
    st = store if store is not None else MemoryStore()
    settings = Settings(
        keys=ks,
        limiter=RateLimiter(100),
        demo_limiter=RateLimiter(100),
        data=data,
        live_checker=fake_check,
        now=now,
        feedback_store=st,
        clients_panel=panel,
        chat_tiers=False,
        state=state or ConnectorState(),
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), st, ks


def mcp_call(c: TestClient, key: str, name: str, arguments: dict[str, Any]) -> Any:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    return c.post("/mcp", json=body, headers={"X-API-Key": key})


def stored_text(store: MemoryStore) -> str:
    refs = store.list_prefix("clients/")
    return "\n".join(r.pathname + " " + store.get(r).decode("utf-8") for r in refs)


def by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["client_id"]: c for c in payload["clients"]}


def test_rest_and_mcp_calls_are_counted_per_key(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, ks = make(data, monkeypatch)
    h = {"X-API-Key": KEY}
    assert c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h).status_code == 200
    assert c.post("/v1/tools/ask", json={"question": QUESTION}, headers=h).status_code == 200
    assert mcp_call(c, KEY, "recalls", {"product_code": "QIH"}).status_code == 200
    # MCP housekeeping (initialize, tools/list) is not a tool call.
    c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h)

    r = c.get("/v1/admin/clients", headers=A)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["enabled"] is True and body["today_utc"] == "2026-10-31"
    cid = str(ks.verify(KEY))[:8]
    row = by_id(body)[cid]
    assert row == {
        "client_id": cid,
        "label": "reviewer-1",
        "kind": "REST, MCP",
        "calls_today": 3,
        "calls_window": 3,
        "last_seen_utc": "2026-10-31T15:04:05+00:00",
    }


def test_demo_key_is_counted_as_demo(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _store, ks = make(data, monkeypatch)
    hd = {"X-API-Key": DEMO}
    assert c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=hd).status_code == 200
    assert mcp_call(c, DEMO, "recalls", {"product_code": "QIH"}).status_code == 200
    row = by_id(c.get("/v1/admin/clients", headers=A).json())[str(ks.verify(DEMO))[:8]]
    assert row["kind"] == "demo" and row["label"] == "demo" and row["calls_window"] == 2


def test_today_and_total_split_by_utc_day(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": datetime(2026, 10, 30, 23, 59, 0, tzinfo=UTC)}
    c, _store, ks = make(data, monkeypatch, now=lambda: clock["t"])
    h = {"X-API-Key": KEY}
    c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h)
    c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h)
    clock["t"] = datetime(2026, 10, 31, 0, 1, 0, tzinfo=UTC)
    c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h)
    row = by_id(c.get("/v1/admin/clients", headers=A).json())[str(ks.verify(KEY))[:8]]
    assert (row["calls_today"], row["calls_window"]) == (1, 3)
    assert row["last_seen_utc"] == "2026-10-31T00:01:00+00:00"


def test_nothing_sensitive_is_stored_or_returned(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, ks = make(data, monkeypatch)
    h = {"X-API-Key": KEY, "User-Agent": "UA-SECRET-STRING", "X-Forwarded-For": "203.0.113.9"}
    c.post("/v1/tools/ask", json={"question": QUESTION}, headers=h)
    mcp_call(c, DEMO, "ask", {"question": QUESTION})
    returned_first = c.get("/v1/admin/clients", headers=A).text  # also waits for the writes
    stored = stored_text(store)
    returned = returned_first
    full_id = str(ks.verify(KEY))
    for text in (stored, returned):
        assert text  # something was counted
        for secret in (
            KEY,
            DEMO,
            KEY[:8],
            DEMO[:8],
            "SECRET-QUESTION-TEXT",
            "UA-SECRET-STRING",
            "testclient",
            "203.0.113.9",
            "127.0.0.1",
            full_id,  # only 8 of the 12 id characters are kept
        ):
            assert secret not in text, secret
    rec = json.loads(store.get(store.list_prefix("clients/")[0]))
    assert set(rec) == {"client_id", "kind", "label", "at_utc"}


def test_store_failure_never_breaks_the_call(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down(MemoryStore):
        def put_json(self, pathname: str, record: dict[str, Any], **_: Any) -> None:
            if pathname.startswith("clients/"):
                raise StoreError("down")
            super().put_json(pathname, record)

        def list_prefix(self, prefix: str, *, strict: bool = False) -> list[Any]:
            if prefix.startswith("clients/"):
                raise StoreError("down")
            return super().list_prefix(prefix, strict=strict)

    c, _store, _ks = make(data, monkeypatch, store=Down())
    h = {"X-API-Key": KEY}
    assert c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h).status_code == 200
    reply = mcp_call(c, KEY, "recalls", {"product_code": "QIH"})
    assert reply.status_code == 200 and reply.json()["result"]["isError"] is False
    r = c.get("/v1/admin/clients", headers=A)
    assert r.status_code == 503 and r.json()["error"]["code"] == "store_unavailable"


def test_slow_store_never_slows_the_tool_call(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Slow(MemoryStore):
        def put_json(self, pathname: str, record: dict[str, Any], **_: Any) -> None:
            if pathname.startswith("clients/"):
                time.sleep(2.0)
            super().put_json(pathname, record)

    c, _store, _ks = make(data, monkeypatch, store=Slow())
    h = {"X-API-Key": KEY}
    c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h)  # warm up the app
    for call in (
        lambda: c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h),
        lambda: mcp_call(c, KEY, "recalls", {"product_code": "QIH"}),
    ):
        start = time.monotonic()
        assert call().status_code == 200
        assert time.monotonic() - start < 0.3


def test_full_queue_drops_instead_of_waiting() -> None:
    class Stuck(MemoryStore):
        def put_json(self, pathname: str, record: dict[str, Any], **_: Any) -> None:
            time.sleep(1.0)

    counter = ClientCounter(Stuck(), enabled=True, now=lambda: FIXED, max_pending=2)
    start = time.monotonic()
    results = [counter.record("0123456789ab", "REST") for _ in range(10)]
    assert time.monotonic() - start < 0.2
    assert results.count(False) >= 7 and counter.dropped == results.count(False)


def test_bad_inputs_are_not_counted() -> None:
    store = MemoryStore()
    counter = ClientCounter(store, enabled=True, now=lambda: FIXED)
    assert counter.record("not-hex-id", "REST") is False
    assert counter.record("0123456789ab", "SOAP") is False
    assert counter.record("0123456789ab", "MCP", "bad label/../x") is True
    assert counter.flush()
    [ref] = store.list_prefix("clients/")
    assert ref.pathname.startswith("clients/2026-10-31/01234567/MCP/-/150405-")
    assert short_client_id("0123456789AB") == "01234567"


def test_only_the_last_30_days_are_listed_and_a_bad_day_marks_incomplete() -> None:
    listed: list[str] = []

    class Spy(MemoryStore):
        def list_prefix(self, prefix: str, *, strict: bool = False) -> list[Any]:
            listed.append(prefix)
            assert strict
            if prefix == "clients/2026-10-20/":
                raise StoreError("longer than the page limit")
            return super().list_prefix(prefix, strict=strict)

    store = Spy()
    for when in (FIXED, datetime(2026, 9, 1, tzinfo=UTC)):  # the second is outside 30 days
        writer = ClientCounter(store, enabled=True, now=lambda w=when: w)
        assert writer.record("0123456789ab", "REST") and writer.flush()
    out = ClientCounter(store, enabled=True, now=lambda: FIXED).summary()
    assert len(listed) == 30 and "clients/2026-10-31/" in listed and "clients/2026-10-02/" in listed
    assert out["complete"] is False and out["window_days"] == 30
    [row] = out["clients"]
    assert (row["calls_today"], row["calls_window"]) == (1, 1)


def test_upstash_counts_are_atomic_hashes_and_hold_nothing_sensitive(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HashRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.hashes: dict[str, dict[str, str]] = {}
            self.sets: dict[str, set[str]] = {}

        def run(self, cmd: list[str]) -> Any:
            op, args = cmd[0].upper(), cmd[1:]
            if op == "SADD":
                self.sets.setdefault(args[0], set()).update(args[1:])
                return 1
            if op == "SMEMBERS":
                return sorted(self.sets.get(args[0], set()))
            if op == "HINCRBY":
                h = self.hashes.setdefault(args[0], {})
                h[args[1]] = str(int(h.get(args[1], "0")) + int(args[2]))
                return int(h[args[1]])
            if op == "HSET":
                h = self.hashes.setdefault(args[0], {})
                h.update(dict(zip(args[1::2], args[2::2], strict=True)))
                return 1
            if op == "HGETALL":
                return [x for kv in self.hashes.get(args[0], {}).items() for x in kv]
            if op == "EXPIREAT":
                return 1
            return super().run(cmd)

    fake = HashRedis()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    state = ConnectorState(UpstashClient(URL, TOKEN, http=http))
    store = MemoryStore()
    c, _store, ks = make(data, monkeypatch, store=store, state=state)
    h = {"X-API-Key": KEY}
    c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h)
    c.post("/v1/tools/ask", json={"question": QUESTION}, headers=h)
    mcp_call(c, DEMO, "recalls", {"product_code": "QIH"})
    body = c.get("/v1/admin/clients", headers=A).json()
    assert body["store"] == "upstash_redis" and body["complete"] is True
    rows = by_id(body)
    full = rows[str(ks.verify(KEY))[:8]]
    assert (full["calls_today"], full["calls_window"], full["kind"]) == (2, 2, "REST")
    assert full["label"] == "reviewer-1" and full["last_seen_utc"] == "2026-10-31T15:04:05+00:00"
    assert rows[str(ks.verify(DEMO))[:8]]["kind"] == "demo"
    assert store.list_prefix("clients/") == []  # Redis, not Blob
    counted = json.dumps(
        [fake.hashes, sorted(fake.sets.get("maudesignal:connector:clients:index", set()))]
    )
    for secret in (KEY, DEMO, "SECRET-QUESTION-TEXT", "127.0.0.1", str(ks.verify(KEY))):
        assert secret not in counted
    assert any(cmd[0] == "HINCRBY" for cmd in fake.calls)


def test_admin_key_is_required(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _store, _ks = make(data, monkeypatch)
    assert c.get("/v1/admin/clients").status_code == 401
    assert c.get("/v1/admin/clients", headers={"X-Admin-Key": "wrong"}).status_code == 401
    # an API key is not an admin key
    assert c.get("/v1/admin/clients", headers={"X-API-Key": KEY}).status_code == 401
    monkeypatch.delenv("MAUDESIGNAL_ADMIN_KEY")
    c2 = TestClient(
        create_app(
            Settings(
                keys=keys(),
                limiter=RateLimiter(100),
                data=data,
                live_checker=fake_check,
                feedback_store=MemoryStore(),
            )
        )
    )
    assert c2.get("/v1/admin/clients", headers=A).status_code == 503


def test_flag_off_counts_nothing_and_panel_says_off(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ks = make(data, monkeypatch, panel=False)
    h = {"X-API-Key": KEY}
    assert c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=h).status_code == 200
    time.sleep(0.05)
    assert store.list_prefix("clients/") == []
    body = c.get("/v1/admin/clients", headers=A).json()
    assert body["enabled"] is False and body["status"] == "Off" and body["clients"] == []
    assert "Client tracking is off: set MAUDESIGNAL_CLIENTS_PANEL=1" in ADMIN_PAGE
    assert "No client has called a tool yet." in ADMIN_PAGE
    page = c.get("/privacy").text
    assert "Per-client call counts are switched off here" in page


def test_flag_env_values() -> None:
    assert panel_enabled({}) is True
    assert panel_enabled({"MAUDESIGNAL_CLIENTS_PANEL": "1"}) is True
    for off in ("0", "off", "OFF", "false", "no", " 0 "):
        assert panel_enabled({"MAUDESIGNAL_CLIENTS_PANEL": off}) is False


def test_admin_page_has_panel_and_privacy_names_counts(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _store, _ks = make(data, monkeypatch)
    page = c.get("/admin").text
    assert "Connected clients" in page and "/v1/admin/clients" in page
    privacy = render_privacy(rate_per_min=30, public_per_hour=10, shared_store=False)
    assert "Per-client call counts" in privacy
    assert "per-client call counts are kept until 2026-12-31" in " ".join(privacy.split())
