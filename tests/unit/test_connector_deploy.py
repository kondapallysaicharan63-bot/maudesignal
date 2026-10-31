"""Deploy-pack tests for the Muse connector (HACKATHON-BUILT): docs page, OpenAPI route,
Vercel config, audit log, shared state, the keyless web route. No network, no model key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.common.exceptions import OpenFDAAPIError  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime, live_mode_allowed  # noqa: E402
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.models import ADVISORY  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from maudesignal.monitor.live_check import LiveCheck  # noqa: E402
from tests.unit.test_connector import KEY, NOW, fake_check  # noqa: E402
from tests.unit.test_connector_safety import (  # noqa: E402
    BLOCKED,
    BLOCKED_SCRIPT,
    OneAnswerClient,
    _assert_no_sentence_text,
    live_rt,
)
from tests.unit.test_connector_store import TOKEN, URL, FakeRedis, make_state  # noqa: E402

H = {"X-API-Key": KEY}
ORIGIN = "https://app.example.com"
SUPPORT = "https://github.com/kondapallysaicharan63-bot/maudesignal/issues"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("deploy"))


def offline_runtime(tmp_path: Path) -> AskRuntime:
    return AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led")


def make(
    data: ConnectorData,
    tmp_path: Path,
    *,
    state: ConnectorState | None = None,
    checker: Callable[[str], LiveCheck] = fake_check,
    public_limit: int = 100,
    limit: int = 100,
    keys: str = KEY,
    runtime: AskRuntime | None = None,
    origins: tuple[str, ...] = (ORIGIN,),
) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": keys}),
        limiter=RateLimiter(limit),
        failed_auth=RateLimiter(100),
        public_limiter=RateLimiter(public_limit, window_seconds=3600),
        data=data,
        ask_runtime=runtime or offline_runtime(tmp_path),
        live_checker=checker,
        now=lambda: NOW,
        state=state or ConnectorState(),
        web_origins=origins,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


# --- docs page and OpenAPI route ------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/docs-page"])
def test_docs_page_renders_without_a_key(data: ConnectorData, tmp_path: Path, path: str) -> None:
    r = make(data, tmp_path).get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    for needle in (
        "X-API-Key",
        ADVISORY,
        SUPPORT,
        "/openapi.json",
        "what_changed_this_week",
        "check_device_type",
        "get_report",
        "recalls",
        "/v1/tools/ask",
        "/v1/public/check_device_type",
        "/v1/audit/recent",
        "requests per minute",
        "cost",
        "provenance",
        "--paper",  # the design-system tokens are inlined
    ):
        assert needle in page, needle
    assert "{{" not in page and "}}" not in page.replace("}}</", "")
    assert forbidden_in(re.sub(r"<style.*?</style>", "", page, flags=re.S)) == []
    assert "<script" not in page.lower() and "http-equiv" not in page.lower()
    assert "background-image" not in page and "gradient" not in re.sub(
        r"<style>\n.*?</style>", "", page, count=1, flags=re.S
    )
    assert KEY not in page
    auth = re.search(r'<h2 id="auth">.*?</section>|<h2 id="auth">.*?<h2', page, flags=re.S)
    assert auth and "HMAC" in auth.group(0) and "12 hex" in auth.group(0)
    assert "SHA-256" not in auth.group(0) and "8 hex" not in auth.group(0)


def test_docs_page_shows_real_captured_examples() -> None:
    examples = json.loads((PROJECT_ROOT / "api" / "examples.json").read_text(encoding="utf-8"))
    titles = " ".join(e["title"] for e in examples)
    for tool in ("health", "what_changed_this_week", "check_device_type", "ask", "get_report"):
        assert tool in titles, tool
    assert "recalls" in titles and "401" in titles and "429" in titles and "audit" in titles
    for e in examples:
        assert set(e) == {"title", "request", "status", "body"}
        keyless = "/v1/health" in e["request"] or "/v1/public/" in e["request"]
        assert keyless or "X-API-Key: $MAUDESIGNAL_KEY" in e["request"] or "401" in e["title"]
        assert KEY not in json.dumps(e)


def test_docs_page_states_per_instance_or_shared(data: ConnectorData, tmp_path: Path) -> None:
    assert "per instance" in make(data, tmp_path).get("/").text
    shared = make(data, tmp_path, state=make_state(FakeRedis())).get("/").text
    assert "shared by every server instance" in shared and "per instance, reset" not in shared


def test_openapi_route_serves_the_committed_spec(data: ConnectorData, tmp_path: Path) -> None:
    c = make(data, tmp_path)
    r = c.get("/openapi.json")
    assert r.status_code == 200
    committed = json.loads((PROJECT_ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert r.json() == committed
    paths = set(committed["paths"])
    assert paths == {
        "/v1/health",
        "/v1/connect",
        "/v1/tools/what_changed_this_week",
        "/v1/tools/check_device_type",
        "/v1/tools/ask",
        "/v1/tools/get_report",
        "/v1/tools/recalls",
        "/v1/public/check_device_type",
        "/v1/audit/recent",
    }
    assert "/" not in paths and "/docs-page" not in paths  # the page is not part of the API
    for path, item in committed["paths"].items():
        for method, op in item.items():
            assert method in {"get", "post"}
            if path in {"/v1/health", "/v1/connect", "/v1/public/check_device_type"}:
                assert "security" not in op  # no key needed
            else:
                assert op["security"] == [{"APIKeyHeader": []}]
    schema = committed["components"]["schemas"]["PublicCheckAnswer"]
    assert "check" in schema["properties"] and "withheld" in schema["properties"]
    live = committed["components"]["schemas"]["LiveCheckData"]["properties"]
    assert {"classification", "change", "queries", "window", "current_count"} <= set(live)


# --- Vercel configuration -----------------------------------------------------------------


def test_vercel_json_parses_and_its_paths_exist() -> None:
    cfg = json.loads((PROJECT_ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert list(cfg["functions"]) == ["api/index.py"]
    assert (PROJECT_ROOT / "api" / "index.py").is_file()
    include = cfg["functions"]["api/index.py"]["includeFiles"]
    patterns = [include] if isinstance(include, str) else list(include)
    expanded: list[str] = []
    for pat in patterns:
        m = re.fullmatch(r"\{([^}]*)\}(/.*)", pat)
        expanded += [d + m.group(2) for d in m.group(1).split(",")] if m else [pat]
    for pat in expanded:
        assert list(PROJECT_ROOT.glob(pat)), f"includeFiles matches nothing: {pat}"
    needed = [
        "src/maudesignal/connector/app.py",
        "data/demo/maudesignal_demo.db",
        "data/demo/SEED_MANIFEST.json",
        "demo/transcripts",
        "digests",
        "skills/safety-copilot/SKILL.md",
        "api/docs.html",
        "api/examples.json",
        "design-system/tokens.css",
        "design-system/maudesignal.css",
    ]
    prefixes = [e[: -len("**")] for e in expanded]  # "src/**" -> "src/"
    for rel in needed:
        assert (PROJECT_ROOT / rel).exists(), rel
        assert any((rel + "/").startswith(pre) for pre in prefixes), f"not bundled: {rel}"
    excluded = cfg["functions"]["api/index.py"]["excludeFiles"]
    for rel in needed:
        assert not re.match(r"^(web|docs|tests|screenshots)/", rel), rel
    assert "web" in excluded and "tests" in excluded
    sources = {r["source"] for r in cfg["rewrites"]}
    assert {"/", "/docs-page", "/openapi.json", "/v1/(.*)"} <= sources
    assert all(r["destination"] == "/api/index" for r in cfg["rewrites"])
    assert "builds" not in cfg  # the web workspace is its own project; nothing here builds it


def test_api_requirements_are_small() -> None:
    reqs = (PROJECT_ROOT / "api" / "requirements.txt").read_text(encoding="utf-8").lower()
    for heavy in ("streamlit", "weasyprint", "playwright", "pandas", "scipy", "evidently"):
        assert not re.search(rf"^{heavy}\b", reqs, flags=re.M), heavy
    assert "fastapi" in reqs and "httpx" in reqs


# --- audit log --------------------------------------------------------------------------------


def test_every_tool_call_is_audited_and_the_chain_verifies(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make(data, tmp_path)
    c.get("/v1/tools/what_changed_this_week", params={"product_code": "LLZ"}, headers=H)
    c.get("/v1/tools/check_device_type", params={"product_code": "QAS"}, headers=H)
    c.post("/v1/tools/ask", json={"question": "What changed this week for LLZ?"}, headers=H)
    c.get("/v1/tools/get_report", params={"report_id": "50426770"}, headers=H)
    c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H)
    c.get("/v1/tools/get_report", params={"report_id": "000"}, headers=H)  # 404 is audited too
    r = c.get("/v1/audit/recent", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["store"] == "in_memory_per_instance"
    assert body["chain"] == {"verified": True, "first_bad_seq": None, "entries_checked": 6}
    entries = body["entries"]
    assert [e["entity_id"] for e in entries] == [
        "what_changed_this_week",
        "check_device_type",
        "ask",
        "get_report",
        "recalls",
        "get_report",
    ]
    peppered = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}).key_id(KEY)
    assert {e["actor"] for e in entries} == {f"connector:key:{peppered}"}
    import hashlib as _h

    assert _h.sha256(KEY.encode()).hexdigest()[:8] not in r.text  # no plain-SHA-256 prefix
    assert entries[0]["prev_hash"] == "GENESIS"
    first = json.loads(entries[0]["payload_json"])
    assert set(first) == {"tool", "inputs", "error", "answer_sha256", "gate", "provenance"}
    assert first["inputs"] == {"product_code": "LLZ"} and len(first["answer_sha256"]) == 64
    assert set(first["gate"]) == {"facts_with_links", "withheld"}
    assert first["provenance"]["kind"] == "stored_demo_snapshot"
    live = json.loads(entries[1]["payload_json"])
    assert live["provenance"]["kind"] == "live_openfda" and live["provenance"]["queried_at_utc"]
    assert json.loads(entries[5]["payload_json"])["error"] == "not_found"
    # the audited answer hash is the hash of the answer the caller got
    again = c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H).json()
    import hashlib

    digest = hashlib.sha256(json.dumps(again, sort_keys=True).encode()).hexdigest()
    last = c.get("/v1/audit/recent?limit=1", headers=H).json()["entries"][0]
    assert json.loads(last["payload_json"])["answer_sha256"] == digest
    assert KEY not in r.text and KEY[:8] not in r.text


def test_audit_recent_needs_a_key_and_counts_against_the_limit(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make(data, tmp_path, limit=2)
    assert c.get("/v1/audit/recent").status_code == 401
    assert c.get("/v1/audit/recent", headers=H).status_code == 200
    assert c.get("/v1/audit/recent", headers=H).status_code == 200
    assert c.get("/v1/audit/recent", headers=H).status_code == 429
    assert c.get("/v1/audit/recent?limit=0", headers=H).status_code in (422, 429)
    assert c.post("/v1/audit/recent", headers=H).status_code == 405  # read-only


def test_audit_stores_the_question_and_hash_but_never_withheld_text(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    c = make(d, tmp_path, runtime=rt)
    r = c.post("/v1/tools/ask", json={"question": "How many LLZ reports this week?"}, headers=H)
    assert r.status_code == 200
    log = c.get("/v1/audit/recent", headers=H)
    _assert_no_sentence_text(log.text)
    payload = json.loads(log.json()["entries"][0]["payload_json"])
    assert payload["gate"]["withheld"] == 4 and payload["provenance"]["kind"] == "live_model"


def test_audit_failure_never_fails_the_request(data: ConnectorData, tmp_path: Path) -> None:
    fake = FakeRedis()
    state = make_state(fake)
    c = make(data, tmp_path, state=state)
    fake.fail = True
    r = c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H)
    assert r.status_code == 200
    assert c.get("/v1/audit/recent", headers=H).status_code == 503
    assert TOKEN not in c.get("/v1/audit/recent", headers=H).text


# --- shared state through the app ------------------------------------------------------------


def test_shared_state_is_used_for_limits_audit_and_health(
    data: ConnectorData, tmp_path: Path
) -> None:
    fake = FakeRedis()
    state = make_state(fake)

    def app_on(shared: ConnectorState) -> TestClient:
        settings = Settings(
            keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
            data=data,
            ask_runtime=offline_runtime(tmp_path),
            live_checker=fake_check,
            now=lambda: NOW,
            state=shared,
            web_origins=(),
        )
        return TestClient(create_app(settings), raise_server_exceptions=False)

    a, b = app_on(state), app_on(make_state(fake))  # two "instances", one Redis
    health = a.get("/v1/health").json()
    assert health["state_store"] == "upstash_redis" and health["limits_scope"] == "shared"
    a.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers=H)
    b.get("/v1/tools/recalls", params={"product_code": "QAS"}, headers=H)
    for client in (a, b):  # either instance reads the same chained log
        rows = client.get("/v1/audit/recent", headers=H).json()
        assert rows["store"] == "upstash_redis"
        assert rows["chain"]["verified"] is True and rows["chain"]["entries_checked"] == 2
    assert any(c[0] == "INCR" and ":rl:tools:" in c[1] for c in fake.calls)
    assert all(TOKEN not in json.dumps(c) for c in fake.calls)
    assert KEY not in json.dumps(fake.calls) and KEY not in json.dumps(fake.lists)
    assert KEY not in json.dumps(fake.kv)


def test_in_memory_health_says_per_instance(data: ConnectorData, tmp_path: Path) -> None:
    h = make(data, tmp_path).get("/v1/health").json()
    assert h["state_store"] == "in_memory_per_instance" and h["limits_scope"] == "per_instance"


def test_live_ask_needs_the_override_unless_a_shared_store_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.setenv("META_MODEL_API_KEY", "x" * 12)
    assert live_mode_allowed() is False
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", URL)
    assert live_mode_allowed() is False  # URL without token is not a store
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", TOKEN)
    assert live_mode_allowed() is True
    monkeypatch.delenv("META_MODEL_API_KEY")
    assert live_mode_allowed() is False  # a store alone never switches the model on


def test_shared_ledger_is_used_by_ask_and_a_redis_outage_falls_back_to_recorded(
    tmp_path: Path,
) -> None:
    fake = FakeRedis()
    state = make_state(fake)
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    rt.state = state
    c = make(d, tmp_path, runtime=rt, state=state)
    ok = c.post("/v1/tools/ask", json={"question": "How many LLZ reports this week?"}, headers=H)
    assert ok.json()["provenance"]["kind"] == "live_model"
    assert any(k.startswith("maudesignal:connector:spend:") for k in fake.kv)
    per_key = [
        float(v)
        for k, v in fake.kv.items()
        if k.endswith(":usd") and ":spend:" in k and ":live-global:" not in k
    ]
    glob = [float(v) for k, v in fake.kv.items() if k.endswith(":usd") and ":live-global:" in k]
    assert per_key and all(u < rt.caps.session_usd for u in per_key)  # the key's hold was released
    assert glob and all(u >= rt.caps.session_usd - 1e-9 for u in glob)  # the global hold stays
    fake.fail = True  # cap cannot be read: no live spend, the recorded answer is returned
    down = c.post("/v1/tools/ask", json={"question": "What changed this week for LLZ?"}, headers=H)
    assert down.status_code == 200 and down.json()["provenance"]["kind"] == "recorded_answer"


# --- the keyless route for the web workspace --------------------------------------------------


def public(c: TestClient, code: str = "QAS", **kw: Any) -> Any:
    return c.get("/v1/public/check_device_type", params={"product_code": code}, **kw)


def test_public_route_needs_no_key_even_when_none_are_configured(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make(data, tmp_path, keys="")
    assert c.get("/v1/tools/recalls?product_code=LLZ").status_code == 503
    r = public(c)
    assert r.status_code == 200, r.text
    assert r.headers["x-ratelimit-limit"] == "100"


def test_public_answer_equals_the_keyed_answer_plus_check(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make(data, tmp_path)
    keyed = c.get("/v1/tools/check_device_type", params={"product_code": "QAS"}, headers=H).json()
    open_ = public(c).json()
    check = open_.pop("check")
    assert open_ == keyed
    expected = json.loads(json.dumps(fake_check("QAS").to_dict()))
    assert check == expected  # LiveCheck.to_dict(), field for field
    assert set(check) >= {
        "classification",
        "change",
        "current_count",
        "current_severe_share",
        "window",
        "queries",
    }
    assert check["queries"] and all(
        len(q) == 2 and q[1].startswith("https://api.fda.gov/") for q in check["queries"]
    )
    assert keyed["facts"] and all(
        f["link"].startswith("https://api.fda.gov/") for f in open_["facts"]
    )


def test_public_route_uses_server_side_openfda_key_and_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import maudesignal.connector.app as app_mod

    seen: dict[str, Any] = {}

    class Spy:
        def __init__(self, api_key: str | None = None, **_: Any) -> None:
            seen["api_key"] = api_key

        def __enter__(self) -> Spy:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    monkeypatch.setenv("OPENFDA_API_KEY", "server-side-openfda-key-NOT-REAL")
    monkeypatch.setattr(app_mod, "OpenFDAClient", Spy)
    monkeypatch.setattr(app_mod, "check_product_code", lambda client, code, today: fake_check(code))
    result = app_mod._default_live_checker("QAS")
    assert result.product_code == "QAS" and seen["api_key"] == "server-side-openfda-key-NOT-REAL"
    from maudesignal.ingestion.openfda_client import USER_AGENT

    assert "MaudeSignal" in USER_AGENT


def test_public_route_never_sends_the_openfda_key_to_the_caller(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENFDA_API_KEY", "server-side-openfda-key-NOT-REAL")
    r = public(make(data, tmp_path))
    assert "server-side-openfda-key-NOT-REAL" not in r.text + str(r.headers)


def test_public_route_per_address_limit_gives_429_and_other_addresses_are_unaffected(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_TRUST_FORWARDED", "1")
    c = make(data, tmp_path, public_limit=3)
    ip_a, ip_b = {"X-Forwarded-For": "203.0.113.5"}, {"X-Forwarded-For": "203.0.113.6"}
    assert [public(c, headers=ip_a).status_code for _ in range(3)] == [200, 200, 200]
    over = public(c, headers={**ip_a, "Origin": ORIGIN})
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "rate_limited"
    assert int(over.headers["retry-after"]) >= 1
    assert over.headers["access-control-allow-origin"] == ORIGIN  # the browser can read the 429
    assert public(c, headers=ip_b).status_code == 200
    assert "retry in" in over.json()["error"]["message"].lower()


def test_public_default_limit_is_ten_per_hour_and_env_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR", raising=False)
    assert (
        RateLimiter.from_env(
            name="MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR", default=10, window_seconds=3600
        ).limit
        == 10
    )
    monkeypatch.setenv("MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR", "4")
    lim = RateLimiter.from_env(
        name="MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR", default=10, window_seconds=3600
    )
    assert lim.limit == 4 and lim.window == 3600
    # the app reads the same variable when the settings do not pass a limiter
    app = create_app(Settings(keys=KeyStore([]), state=ConnectorState(), web_origins=()))
    page = TestClient(app).get("/").text
    assert "4 per hour" in page


def test_public_route_caches_a_code_for_six_hours(data: ConnectorData, tmp_path: Path) -> None:
    calls: list[str] = []

    def counting(code: str) -> LiveCheck:
        calls.append(code)
        return fake_check(code)

    c = make(data, tmp_path, checker=counting)
    first, second = public(c).json(), public(c).json()
    assert first == second and calls == ["QAS"]
    public(c, "ZZZ")
    assert calls == ["QAS", "ZZZ"]
    assert public(c).json()["provenance"]["queried_at_utc"] == first["provenance"]["queried_at_utc"]


def test_cache_ttl_is_six_hours_in_the_shared_store(data: ConnectorData, tmp_path: Path) -> None:
    fake = FakeRedis()
    c = make(data, tmp_path, state=make_state(fake))
    public(c)
    sets = [x for x in fake.calls if x[0] == "SET" and ":cache:" in x[1]]
    assert sets and sets[0][-2:] == ["EX", str(6 * 3600)]


def test_stored_fallback_is_not_cached_and_has_no_check(
    data: ConnectorData, tmp_path: Path
) -> None:
    calls: list[str] = []

    def down(code: str) -> LiveCheck:
        calls.append(code)
        raise OpenFDAAPIError("no network in tests")

    c = make(data, tmp_path, checker=down)
    r = public(c, "LLZ")  # LLZ is in the stored set, so the snapshot answers
    assert r.status_code == 200 and r.json()["check"] is None
    assert r.json()["provenance"]["kind"] == "stored_demo_snapshot"
    public(c, "LLZ")
    assert calls == ["LLZ", "LLZ"]  # tried openFDA again, nothing stale was cached
    assert public(c, "ZZZ").status_code == 502  # unstored code and no openFDA: an honest error


def test_public_route_validates_the_code(data: ConnectorData, tmp_path: Path) -> None:
    c = make(data, tmp_path)
    assert public(c, "12").status_code == 422
    assert public(c, "LLZZ").status_code == 422
    assert c.get("/v1/public/check_device_type").status_code == 422


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (ORIGIN, True),
        (ORIGIN + "/", True),
        ("https://evil.example.com", False),
        ("http://app.example.com", False),
        ("https://app.example.com.evil.example", False),
        ("null", False),
        ("*", False),
    ],
)
def test_cors_header_only_for_listed_origins(
    data: ConnectorData, tmp_path: Path, origin: str, allowed: bool
) -> None:
    c = make(data, tmp_path)
    r = public(c, headers={"Origin": origin})
    assert r.status_code == 200
    got = r.headers.get("access-control-allow-origin")
    assert (got == origin.rstrip("/")) if allowed else (got is None)
    assert r.headers["vary"] == "Origin"
    pre = c.options(
        "/v1/public/check_device_type",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert pre.status_code == 204
    assert ("access-control-allow-methods" in pre.headers) is allowed
    assert (pre.headers.get("access-control-allow-origin") == origin.rstrip("/")) is allowed


def test_no_cors_without_origin_and_never_a_wildcard(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = make(data, tmp_path)
    assert "access-control-allow-origin" not in public(c).headers
    assert not any(v == "*" for v in public(c, headers={"Origin": ORIGIN}).headers.values())
    monkeypatch.setenv(
        "MAUDESIGNAL_WEB_ORIGINS", "*, https://*.example.com, https://ok.example.com/"
    )
    from maudesignal.connector.app import _origins_from_env

    assert _origins_from_env() == ("https://ok.example.com",)
    monkeypatch.delenv("MAUDESIGNAL_WEB_ORIGINS")
    assert _origins_from_env() == ()


def test_no_cors_on_the_keyed_routes(data: ConnectorData, tmp_path: Path) -> None:
    c = make(data, tmp_path)
    r = c.get("/v1/tools/recalls", params={"product_code": "LLZ"}, headers={**H, "Origin": ORIGIN})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_public_route_never_spends_model_credit_and_exposes_no_ask(tmp_path: Path) -> None:
    def boom(*_: Any) -> Any:
        raise AssertionError("the model must not be called from the public route")

    d = ConnectorData(work_dir=tmp_path / "w")
    rt = AskRuntime(agent_factory=boom, live_enabled=lambda: True, ledger_dir=tmp_path / "led")
    c = make(d, tmp_path, runtime=rt)
    assert public(c).status_code == 200
    assert c.post("/v1/public/ask", json={"question": "hello there"}).status_code in (404, 405)
    assert c.get("/v1/public/ask").status_code == 404
    assert not any(
        p.startswith("/v1/public/") and "ask" in p for p in c.get("/openapi.json").json()["paths"]
    )
    assert list((tmp_path / "led").glob("*")) == []  # no ledger entry: nothing was spent


def test_public_calls_are_audited_without_a_key_id(data: ConnectorData, tmp_path: Path) -> None:
    c = make(data, tmp_path)
    public(c)
    rows = c.get("/v1/audit/recent", headers=H).json()
    assert rows["entries"][0]["actor"] == "public"
    assert rows["entries"][0]["action"] == "tool:public_check_device_type"


# --- a withheld sentence never reaches a live-mode response ------------------------------------


def test_withheld_sentence_text_never_appears_anywhere_in_the_live_mode_response(
    tmp_path: Path,
) -> None:
    """Live mode, REST, four sentences the gate or the screen holds back.

    The whole exchange is scanned: raw body bytes, every header, and the places the same call
    leaves traces (the audit log, the spec, the docs page). Neither a full sentence nor any
    20-character run of one may be there; the `withheld` list holds only neutral placeholders.
    """
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    c = make(d, tmp_path, runtime=rt, state=make_state(FakeRedis()))
    r = c.post("/v1/tools/ask", json={"question": "How many LLZ reports this week?"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["provenance"]["kind"] == "live_model"
    assert "33 reports" in body["speakable"]  # the verified sentence is spoken
    assert len(body["withheld"]) == 4
    for w in body["withheld"]:
        assert w["status"] == "withheld"
        assert w["text"] in (
            "Sentence left out by the claim gate.",
            "Sentence left out: it contains a term this service does not use.",
        )
    raw = r.content.decode("utf-8")
    assert raw == r.text
    surfaces = {
        "raw body": raw,
        "headers": "\n".join(f"{k}: {v}" for k, v in r.headers.items()),
        "audit log": c.get("/v1/audit/recent", headers=H).text,
        "openapi": c.get("/openapi.json").text,
        "docs page": c.get("/").text,
    }
    for where, text in surfaces.items():
        _assert_no_sentence_text(text)
        for sentence in BLOCKED:
            assert sentence not in text, where
            assert json.dumps(sentence)[1:-1] not in text, where  # JSON-escaped form too
    for sentence in BLOCKED:  # and not in any single field of the parsed answer
        for field in (body["speakable"], body["advisory"], json.dumps(body["facts"])):
            assert sentence not in field


# --- review fixes: question privacy, bad cache entry --------------------------------------------


def test_audit_log_never_holds_the_question_text(data: ConnectorData, tmp_path: Path) -> None:
    import hashlib as _h

    c = make(data, tmp_path, runtime=offline_runtime(tmp_path))
    secret_question = "What about patient Jane Roe, born 1950-01-02, in LLZ reports?"
    r = c.post("/v1/tools/ask", json={"question": secret_question}, headers=H)
    assert r.status_code == 200
    log = c.get("/v1/audit/recent", headers=H)
    for fragment in ("Jane", "Roe", "1950", secret_question, secret_question.lower()):
        assert fragment not in log.text
    payload = json.loads(log.json()["entries"][0]["payload_json"])
    norm = " ".join(secret_question.split()).lower()
    assert payload["inputs"] == {
        "question_sha256": _h.sha256(norm.encode()).hexdigest(),
        "question_length": str(len(norm)),
    }


def test_audit_question_hash_ignores_case_and_spacing(data: ConnectorData, tmp_path: Path) -> None:
    c = make(data, tmp_path, runtime=offline_runtime(tmp_path))
    for q in ("What changed for LLZ?", "  what   CHANGED for llz? "):
        assert c.post("/v1/tools/ask", json={"question": q}, headers=H).status_code == 200
    entries = c.get("/v1/audit/recent", headers=H).json()["entries"]
    inputs = [json.loads(e["payload_json"])["inputs"] for e in entries[:2]]
    assert inputs[0] == inputs[1]


def test_corrupt_cached_public_answer_is_a_cache_miss(data: ConnectorData, tmp_path: Path) -> None:
    fake = FakeRedis()
    state = make_state(fake)
    calls: list[str] = []

    def counting(code: str) -> LiveCheck:
        calls.append(code)
        return fake_check(code)

    c = make(data, tmp_path, state=state, checker=counting)
    assert public(c).status_code == 200 and calls == ["QAS"]
    cache_keys = [k for k in fake.kv if ":cache:public-check:v1:QAS" in k]
    assert len(cache_keys) == 1, "the cache key carries a schema version"
    fake.kv[cache_keys[0]] = '{"tool": "check_device_type", "unexpected": true}'
    r = public(c)
    assert r.status_code == 200 and calls == ["QAS", "QAS"]  # refetched, no 500
    fake.kv[cache_keys[0]] = "not json at all"
    assert public(c).status_code == 200
