"""Labelled keys, the public demo key and ``GET /v1/connect`` (HACKATHON-BUILT). No network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.security import (  # noqa: E402
    DEFAULT_DEMO_RATE_PER_MIN,
    DEMO_PER_DAY,
    KeyConfigError,
    KeyStore,
    RateLimiter,
    sha256_hex,
)
from tests.unit.test_connector import fake_check, fake_meter  # noqa: E402

K1 = "charan-key-NOT-A-REAL-SECRET-0123456789"
K2 = "review-key-NOT-A-REAL-SECRET-0123456789"
DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("keysdemo"))


def store(keys: str = "", demo: str = "") -> KeyStore:
    return KeyStore.from_env(
        {"MAUDESIGNAL_API_KEYS": keys, "MAUDESIGNAL_DEMO_KEYS": demo, "MAUDESIGNAL_KEY_PEPPER": "p"}
    )


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


def client(
    data: ConnectorData,
    tmp_path: Path,
    keys: KeyStore,
    *,
    live: Any = None,
    demo_limit: int = 10,
    clock: Clock | None = None,
) -> TestClient:
    runtime = AskRuntime(
        live_enabled=lambda: live is not None, ledger_dir=tmp_path / "led", meter=fake_meter()
    )
    if live is not None:
        runtime.agent_factory = live
    settings = Settings(
        keys=keys,
        limiter=RateLimiter(100),
        demo_limiter=RateLimiter(demo_limit),
        data=data,
        ask_runtime=runtime,
        chat_tiers=False,  # pins the Muse Spark path (tier 4)
        live_checker=fake_check,
        now=clock or Clock(),
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def get(c: TestClient, key: str | None, path: str = "/v1/tools/recalls?product_code=LLZ") -> Any:
    return c.get(path, headers={"X-API-Key": key} if key else {})


# --- labelled keys ------------------------------------------------------------------------


def test_both_labelled_keys_authenticate_and_label_is_not_a_key(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = client(data, tmp_path, store(f"charan={K1}, meta-review={K2}"))
    assert get(c, K1).status_code == 200
    assert get(c, K2).status_code == 200
    for wrong in (f"charan={K1}", f"meta-review={K2}", "charan", "meta-review", "charan="):
        assert get(c, wrong).status_code == 401


def test_label_is_never_part_of_the_key() -> None:
    ks = store(f"charan={K1},meta-review={K2}")
    m1, m2 = ks.match(K1), ks.match(K2)
    assert m1 is not None and m1.label == "charan"
    assert m2 is not None and m2.label == "meta-review"
    assert ks.match(f"charan={K1}") is None


def test_removing_one_entry_revokes_only_that_key(data: ConnectorData, tmp_path: Path) -> None:
    both = store(f"charan={K1},meta-review={K2}")
    only_charan = store(f"charan={K1}")
    assert only_charan.verify(K2) is None and only_charan.verify(K1) is not None
    assert only_charan.verify(K1) == both.verify(K1)  # with a pepper the id is unchanged
    c = client(data, tmp_path, only_charan)
    assert get(c, K1).status_code == 200 and get(c, K2).status_code == 401


def test_mixed_formats_and_whitespace() -> None:
    other = "x" * 40
    raw = (
        f"  charan={K1} ,\n {K2} , rev=sha256:{sha256_hex(DEMO).upper()}, ,"
        f"sha256:{sha256_hex(other)}"
    )
    ks = store(raw)
    m1, m2, m3 = ks.match(K1), ks.match(K2), ks.match(DEMO)
    assert m1 is not None and m1.label == "charan"
    assert m2 is not None and m2.label is None
    assert m3 is not None and m3.label == "rev"
    assert ks.match(other) is not None
    assert ks.match("y" * 40) is None


def test_plain_key_with_base64_padding_stays_whole() -> None:
    padded = "a" * 42 + "="
    assert store(padded).match(padded) is not None
    m = store(f"lab={padded}").match(padded)
    assert m is not None and m.label == "lab"


@pytest.mark.parametrize(
    "bad",
    [
        f"bad label={K1}",
        f"{'x' * 33}={K1}",
        f"=={K1}",
        f"=thing{K1}",
        f"na!me={K1}",
        f"ok={K1},bad.label={K2}",
    ],
)
def test_bad_label_is_rejected_at_startup_with_a_clear_error(bad: str) -> None:
    with pytest.raises(KeyConfigError) as exc:
        store(bad)
    msg = str(exc.value)
    assert "label" in msg and "1 to 32" in msg
    assert K1 not in msg and K2 not in msg  # the message never holds a key


def test_bad_demo_label_is_rejected_too() -> None:
    with pytest.raises(KeyConfigError):
        store("", f"bad label={DEMO}")


def test_bad_label_stops_app_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_API_KEYS", f"bad label={K1}")
    with pytest.raises(KeyConfigError):
        Settings()


def test_short_labelled_key_is_refused_not_accepted_with_its_label() -> None:
    ks = store("charan=shortkey, meta-review=" + "k" * 25)
    assert not ks.configured


def test_audit_shows_label_then_key_id(data: ConnectorData, tmp_path: Path) -> None:
    ks = store(f"charan={K1},{K2}")
    c = client(data, tmp_path, ks)
    get(c, K1)
    get(c, K2)
    rows = get(c, K1, "/v1/audit/recent?limit=10").json()["entries"]
    actors = [r["actor"] for r in rows]
    assert f"connector:key:charan:{ks.verify(K1)}" in actors
    assert f"connector:key:{ks.verify(K2)}" in actors  # no label: key id only
    assert K1 not in json.dumps(rows) and K2 not in json.dumps(rows)


# --- demo key -----------------------------------------------------------------------------


def test_demo_key_reads_but_not_audit(data: ConnectorData, tmp_path: Path) -> None:
    c = client(data, tmp_path, store(f"charan={K1}", f"pub={DEMO}"))
    for path in (
        "/v1/tools/recalls?product_code=LLZ",
        "/v1/tools/what_changed_this_week?product_code=LLZ",
        "/v1/tools/check_device_type?product_code=QAS",
        "/v1/tools/get_report?report_id=50426770",
    ):
        assert get(c, DEMO, path).status_code == 200, path
    r = get(c, DEMO, "/v1/audit/recent")
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_key"
    assert get(c, K1, "/v1/audit/recent").status_code == 200


def test_demo_key_alone_is_enough_to_configure() -> None:
    ks = store("", DEMO)
    assert ks.configured and ks.demo_configured
    m = ks.match(DEMO)
    assert m is not None and m.demo


def test_demo_key_audit_label_is_demo(data: ConnectorData, tmp_path: Path) -> None:
    ks = store(K1, f"pub={DEMO}")
    c = client(data, tmp_path, ks)
    get(c, DEMO)
    rows = get(c, K1, "/v1/audit/recent?limit=5").json()["entries"]
    assert any(r["actor"] == f"connector:key:demo:{ks.verify(DEMO)}" for r in rows)


def _no_live(calls: list[int]) -> Any:
    def factory(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("the live model must not be called")

    return factory


def test_demo_key_never_calls_the_live_model_and_ask_says_recorded(
    data: ConnectorData, tmp_path: Path
) -> None:
    calls: list[int] = []
    c = client(data, tmp_path, store(K1, DEMO), live=_no_live(calls))
    r = c.post(
        "/v1/tools/ask",
        json={"question": "What changed this week for LLZ?"},
        headers={"X-API-Key": DEMO},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert calls == []
    assert body["provenance"]["kind"] == "recorded_answer"
    assert "demo key" in body["provenance"]["note"]


def test_demo_key_ask_over_mcp_is_recorded_too(data: ConnectorData, tmp_path: Path) -> None:
    calls: list[int] = []
    c = client(data, tmp_path, store(K1, DEMO), live=_no_live(calls))
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ask", "arguments": {"question": "What changed this week for LLZ?"}},
    }
    r = c.post("/mcp", json=rpc, headers={"X-API-Key": DEMO})
    assert r.status_code == 200 and calls == []


def test_full_key_still_reaches_the_live_path(data: ConnectorData, tmp_path: Path) -> None:
    calls: list[int] = []
    c = client(data, tmp_path, store(K1, DEMO), live=_no_live(calls))
    c.post(
        "/v1/tools/ask",
        json={"question": "What changed this week for LLZ?"},
        headers={"X-API-Key": K1},
    )
    assert calls == [1]  # it tried; the failing fake falls back to a recording


def test_demo_minute_limit_is_its_own(data: ConnectorData, tmp_path: Path) -> None:
    c = client(data, tmp_path, store(K1, DEMO), demo_limit=2)
    assert [get(c, DEMO).status_code for _ in range(3)] == [200, 200, 429]
    assert get(c, K1).status_code == 200  # the full key is not affected


def test_demo_daily_limit_and_reset(data: ConnectorData, tmp_path: Path) -> None:
    clock = Clock()
    c = client(data, tmp_path, store(K1, DEMO), demo_limit=10_000, clock=clock)
    codes = [get(c, DEMO).status_code for _ in range(DEMO_PER_DAY + 1)]
    assert codes[:DEMO_PER_DAY] == [200] * DEMO_PER_DAY and codes[-1] == 429
    r = get(c, DEMO)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert get(c, K1).status_code == 200
    clock.t += timedelta(days=1)
    assert get(c, DEMO).status_code == 200


def test_demo_limit_defaults() -> None:
    assert DEFAULT_DEMO_RATE_PER_MIN == 10 and DEMO_PER_DAY == 200


# --- /v1/connect --------------------------------------------------------------------------


def test_connect_needs_no_key_and_lists_the_urls(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_PUBLIC_URL", "https://api.example.org/")
    c = client(data, tmp_path, store(K1, f"pub={DEMO}"))
    r = c.get("/v1/connect")
    assert r.status_code == 200
    b = r.json()
    assert b["mcp_url"] == "https://api.example.org/mcp"
    assert b["openapi_url"] == "https://api.example.org/openapi.json"
    assert b["docs_url"] == "https://api.example.org/docs-page"
    assert b["privacy_url"] == "https://api.example.org/privacy"
    assert b["terms_url"] == "https://api.example.org/terms"
    assert b["auth_header"] == "X-API-Key"
    assert b["demo_key"] == DEMO  # public by design; the label is not part of it
    assert b["demo_limits"]["per_minute"] == 10 and b["demo_limits"]["per_day"] == 200
    assert b["demo_limits"]["live_model"] is False
    assert len(b["steps"]) == 3 and all(len(s) < 120 for s in b["steps"])
    assert K1 not in r.text


def test_connect_without_demo_key_is_null(data: ConnectorData, tmp_path: Path) -> None:
    c = client(data, tmp_path, store(f"charan={K1}"))
    b = c.get("/v1/connect").json()
    assert b["demo_key"] is None and K1 not in json.dumps(b)


def test_connect_digest_demo_key_is_not_revealed(data: ConnectorData, tmp_path: Path) -> None:
    c = client(data, tmp_path, store(K1, f"sha256:{sha256_hex(DEMO)}"))
    assert c.get("/v1/connect").json()["demo_key"] is None


def test_connect_cors_only_for_listed_origins(data: ConnectorData, tmp_path: Path) -> None:
    settings = Settings(
        keys=store(K1, DEMO),
        limiter=RateLimiter(100),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        chat_tiers=False,  # pins the Muse Spark path (tier 4)
        live_checker=fake_check,
        web_origins=("https://web.example.org",),
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    ok = c.get("/v1/connect", headers={"Origin": "https://web.example.org"})
    assert ok.headers.get("access-control-allow-origin") == "https://web.example.org"
    no = c.get("/v1/connect", headers={"Origin": "https://evil.example.org"})
    assert "access-control-allow-origin" not in no.headers


def test_privacy_and_terms_mention_the_demo_key(data: ConnectorData, tmp_path: Path) -> None:
    c = client(data, tmp_path, store(K1, DEMO))
    privacy = " ".join(c.get("/privacy").text.split())
    assert "Calls made with the public demo key are logged the same way" in privacy
    assert "2026-12-31" in privacy and "2026-11-30" not in privacy
    terms = " ".join(c.get("/terms").text.split())
    assert "never starts a live model call" in terms
    assert "10 requests per minute and 200 per UTC day" in terms
