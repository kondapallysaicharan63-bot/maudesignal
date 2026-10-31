"""Self-hosted company audit mode (``MAUDESIGNAL_AUDIT_FULL_TEXT``). Offline; no model key."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import (  # noqa: E402
    AUDIT_ASK_COMPANY,
    AUDIT_ASK_PUBLIC,
    Settings,
    create_app,
)
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.audit_mode import (  # noqa: E402
    AUDIT_FULL_TEXT_ENV,
    DEMO_KEYS_ENV,
    PUBLIC_DEMO_ENV,
    SELF_HOSTED_ENV,
    VERCEL_ENV,
    WEB_ORIGINS_ENV,
    WITHHELD_PHI,
    full_text_requested,
    refusal_reasons,
    resolve_full_text,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.legal_pages import render_privacy  # noqa: E402
from maudesignal.connector.openapi import OPENAPI_PATH, build_spec, render  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState, verify_chain  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_lookup import ROW_802, FakeSearcher  # noqa: E402

DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"
H = {"X-API-Key": KEY}
QUESTION = "What changed this week for LLZ?"
PHI_QUESTION = "Patient DOB 03/04/1950, MRN 1234567: what changed this week for LLZ?"
ALL_ENVS = (
    AUDIT_FULL_TEXT_ENV,
    SELF_HOSTED_ENV,
    DEMO_KEYS_ENV,
    PUBLIC_DEMO_ENV,
    VERCEL_ENV,
    WEB_ORIGINS_ENV,
)
COMPANY_ON = {AUDIT_FULL_TEXT_ENV: "1", SELF_HOSTED_ENV: "1"}
#: Each refusal condition: (env to add on top of a fully-on company env, reason it names).
REFUSALS: list[tuple[dict[str, str], str]] = [
    ({SELF_HOSTED_ENV: "0"}, f"{SELF_HOSTED_ENV} is not on"),
    ({DEMO_KEYS_ENV: DEMO}, f"{DEMO_KEYS_ENV} is set"),
    ({PUBLIC_DEMO_ENV: "true"}, f"{PUBLIC_DEMO_ENV} is on"),
    ({VERCEL_ENV: "production"}, f"{VERCEL_ENV} is production"),
    ({WEB_ORIGINS_ENV: "https://app.example.com"}, f"{WEB_ORIGINS_ENV} is set"),
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL_ENVS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("audit-mode"))


def set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def make_client(
    data: ConnectorData,
    tmp_path: Path,
    *,
    full_text: bool | None = None,
    demo: bool = False,
) -> tuple[TestClient, ConnectorState]:
    env = {"MAUDESIGNAL_API_KEYS": KEY, "MAUDESIGNAL_KEY_PEPPER": "p"}
    if demo:
        env[DEMO_KEYS_ENV] = DEMO
    state = ConnectorState(None)
    settings = Settings(
        keys=KeyStore.from_env(env),
        limiter=RateLimiter(100),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=fake_check,
        lookup_searcher=FakeSearcher(k510=[ROW_802]),
        state=state,
        audit_full_text=full_text,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), state


def ask_entries(state: ConnectorState) -> list[dict[str, Any]]:
    rows = state.audit_recent(200)
    ok, bad = verify_chain(rows)
    assert ok and bad is None
    return [json.loads(r["payload_json"]) for r in rows if r["action"] == "tool:ask"]


def ask(c: TestClient, question: str, key: str = KEY) -> Any:
    r = c.post("/v1/tools/ask", json={"question": question}, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    return r.json()


def mcp_ask(c: TestClient, question: str) -> Any:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ask", "arguments": {"question": question}},
    }
    r = c.post("/mcp", json=body, headers=H)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    return result["structuredContent"]


def logged(capsys: pytest.CaptureFixture[str]) -> str:
    seen = capsys.readouterr()
    return seen.out + seen.err


# --- env semantics ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_flag_on_values(value: str) -> None:
    assert full_text_requested({AUDIT_FULL_TEXT_ENV: value}) is True


@pytest.mark.parametrize("value", [None, "", "0", "false", "False", "no", "off", "2"])
def test_flag_off_values(value: str | None) -> None:
    env = {} if value is None else {AUDIT_FULL_TEXT_ENV: value}
    assert full_text_requested(env) is False


def test_fully_on_needs_both_flags_and_no_public_signal() -> None:
    assert refusal_reasons(COMPANY_ON) == []
    assert resolve_full_text(True, COMPANY_ON) is True
    assert resolve_full_text(False, COMPANY_ON) is False
    assert refusal_reasons({SELF_HOSTED_ENV: "yes", VERCEL_ENV: "preview"}) == []
    assert refusal_reasons(COMPANY_ON, demo_keys=True) == ["a public demo key is configured"]
    assert refusal_reasons(COMPANY_ON, web_origins=True) == [f"{WEB_ORIGINS_ENV} is set"]


@pytest.mark.parametrize(("extra", "reason"), REFUSALS)
def test_each_refusal_condition_is_named_without_values(
    capsys: pytest.CaptureFixture[str], extra: dict[str, str], reason: str
) -> None:
    env = COMPANY_ON | extra
    assert refusal_reasons(env) == [reason]
    assert resolve_full_text(True, env) is False
    out = logged(capsys)
    assert "audit_full_text_refused" in out and reason in out
    assert DEMO not in out and "app.example.com" not in out  # values are never logged


def test_not_requested_logs_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert resolve_full_text(False, {DEMO_KEYS_ENV: DEMO}) is False
    assert "audit_full_text_refused" not in logged(capsys)


# --- app behaviour ------------------------------------------------------------------------


def test_default_off_stores_hash_only(data: ConnectorData, tmp_path: Path) -> None:
    c, state = make_client(data, tmp_path)
    answer = ask(c, QUESTION)
    (payload,) = ask_entries(state)
    raw = json.dumps(payload)
    assert set(payload) == {"tool", "inputs", "error", "answer_sha256", "gate", "provenance"}
    assert set(payload["inputs"]) == {"question_sha256", "question_length"}
    normalised = " ".join(QUESTION.split()).lower()
    assert payload["inputs"]["question_sha256"] == hashlib.sha256(normalised.encode()).hexdigest()
    assert QUESTION not in raw and "this week for" not in raw
    assert answer["speakable"] not in raw


def test_audit_flag_alone_is_not_enough(
    data: ConnectorData,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(AUDIT_FULL_TEXT_ENV, "1")  # no MAUDESIGNAL_SELF_HOSTED
    c, state = make_client(data, tmp_path)
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload and "full_text" not in payload
    assert f"{SELF_HOSTED_ENV} is not on" in logged(capsys)


def test_env_on_stores_text_and_chain_verifies(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, COMPANY_ON)
    c, state = make_client(data, tmp_path)
    answer = ask(c, "  What changed   this week for LLZ? ")
    ask(c, QUESTION)
    entries = ask_entries(state)  # verifies the chain with the text inside the hashed record
    assert len(entries) == 2
    for payload in entries:
        assert payload["full_text"] == "stored"
        assert payload["question_text"] == QUESTION
        assert set(payload["inputs"]) == {"question_sha256", "question_length"}
    assert entries[0]["answer_text"] == answer["speakable"]
    # The text is part of the hashed record: changing it breaks the chain.
    rows = state.audit_recent(200)
    tampered = dict(rows[0])
    tampered["payload_json"] = tampered["payload_json"].replace("LLZ", "LLX")
    assert verify_chain([tampered, *rows[1:]])[0] is False


@pytest.mark.parametrize("on", [False, True])
def test_mcp_ask_stores_text_only_when_on(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on: bool
) -> None:
    if on:
        set_env(monkeypatch, COMPANY_ON)
    c, state = make_client(data, tmp_path)
    answer = mcp_ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert set(payload["inputs"]) == {"question_sha256", "question_length"}
    if on:
        assert payload["question_text"] == QUESTION
        assert payload["answer_text"] == answer["speakable"]
    else:
        raw = json.dumps(payload)
        assert "question_text" not in payload and QUESTION not in raw
        assert answer["speakable"] not in raw


def test_audit_list_shows_text_only_when_stored(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c_off, _ = make_client(data, tmp_path / "off")
    ask(c_off, QUESTION)
    body = c_off.get("/v1/audit/recent", headers=H).json()
    assert body["chain"]["verified"] is True
    assert all(QUESTION not in e["payload_json"] for e in body["entries"])

    set_env(monkeypatch, {SELF_HOSTED_ENV: "1"})
    c_on, _ = make_client(data, tmp_path / "on", full_text=True)
    ask(c_on, QUESTION)
    body = c_on.get("/v1/audit/recent", headers=H).json()
    assert body["chain"]["verified"] is True
    assert any(QUESTION in e["payload_json"] for e in body["entries"])


@pytest.mark.parametrize(("extra", "reason"), REFUSALS)
def test_app_stays_off_for_each_refusal_condition(
    data: ConnectorData,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: dict[str, str],
    reason: str,
) -> None:
    set_env(monkeypatch, COMPANY_ON | extra)
    c, state = make_client(data, tmp_path)
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload and "full_text" not in payload
    assert QUESTION not in json.dumps(payload)
    assert reason in logged(capsys)


def test_explicit_setting_cannot_bypass_public_guard(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, {SELF_HOSTED_ENV: "1", PUBLIC_DEMO_ENV: "yes"})
    c, state = make_client(data, tmp_path, full_text=True)
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload


def test_demo_key_in_store_refuses(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, COMPANY_ON)  # MAUDESIGNAL_DEMO_KEYS unset: the key store has one
    c, state = make_client(data, tmp_path, demo=True)
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload


def test_phi_rejected_text_never_stored(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, COMPANY_ON)
    c, state = make_client(data, tmp_path)
    answer = ask(c, PHI_QUESTION)
    (payload,) = ask_entries(state)
    raw = json.dumps(payload)
    assert payload["full_text"] == WITHHELD_PHI
    assert "question_text" not in payload and "answer_text" not in payload
    assert "1234567" not in raw and "1950" not in raw
    assert answer["speakable"] not in raw
    assert set(payload["inputs"]) == {"question_sha256", "question_length"}


def test_demo_key_path_unchanged(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c_ref, state_ref = make_client(data, tmp_path / "ref", demo=True)
    ref = ask(c_ref, QUESTION, key=DEMO)
    set_env(monkeypatch, COMPANY_ON)
    c, state = make_client(data, tmp_path / "flag", demo=True)
    got = ask(c, QUESTION, key=DEMO)
    assert got == ref
    (p_ref,) = ask_entries(state_ref)
    (p_got,) = ask_entries(state)
    assert p_got == p_ref
    assert "question_text" not in p_got
    assert c.get("/v1/audit/recent", headers={"X-API-Key": DEMO}).status_code == 403


# --- served text stays true ---------------------------------------------------------------


def _audit_description(c: TestClient) -> str:
    spec = c.get("/openapi.json").json()
    return str(spec["paths"]["/v1/audit/recent"]["get"]["description"])


def test_served_text_follows_the_resolved_flag(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c_off, _ = make_client(data, tmp_path / "off")
    assert AUDIT_ASK_PUBLIC in _audit_description(c_off)
    page_off = c_off.get("/privacy").text
    assert "The text of a question is <strong>not</strong> logged" in page_off
    assert "company audit mode" not in page_off

    set_env(monkeypatch, COMPANY_ON)
    c_on, _ = make_client(data, tmp_path / "on")
    desc = _audit_description(c_on)
    assert AUDIT_ASK_COMPANY in desc and AUDIT_ASK_PUBLIC not in desc
    page_on = c_on.get("/privacy").text
    assert "Self-hosted company audit mode is <strong>on</strong>" in page_on
    assert "The text of a question is <strong>not</strong> logged" not in page_on
    assert "does not cover these routes" in page_on


def test_privacy_off_is_the_public_page_and_openapi_snapshot_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kw: dict[str, Any] = {"rate_per_min": 30, "public_per_hour": 10, "shared_store": False}
    for live_on in (True, False):
        public = render_privacy(**kw, live_on=live_on)
        assert render_privacy(**kw, live_on=live_on, audit_full_text=False) == public
        assert render_privacy(**kw, live_on=live_on, audit_full_text=True) != public
    set_env(monkeypatch, COMPANY_ON)  # the committed spec never depends on the environment
    assert render(build_spec()) == OPENAPI_PATH.read_text(encoding="utf-8")


# --- the website's live routes never store text --------------------------------------------


def test_live_ask_with_company_mode_on_stores_no_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_connector_live import Env

    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    set_env(monkeypatch, COMPANY_ON)
    env = Env(tmp_path, origins=())  # no web origin, so company mode is fully on
    assert "Self-hosted company audit mode is <strong>on</strong>" in (
        env.client.get("/privacy").text
    )
    question = "What changed this week for LLZ? unique-marker-7731"
    r = env.ask(question)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "live"
    spoken = r.json()["answer"]["spoken_text"]
    # The connector audit chain: no entry for the live route, no text in any entry.
    rows = env.state.audit_recent(200)
    assert verify_chain(rows)[0] is True
    everything = json.dumps(rows)
    assert "unique-marker-7731" not in everything and spoken not in everything
    # No record store object, and the copilot's working database keeps only a hash.
    assert env.store.list_prefix("") == []
    db_text = "".join(p.read_bytes().decode("latin-1") for p in (tmp_path / "work").glob("*.db"))
    assert "unique-marker-7731" not in db_text
