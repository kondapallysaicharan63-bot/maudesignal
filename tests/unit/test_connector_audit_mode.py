"""Self-hosted company audit mode (``MAUDESIGNAL_AUDIT_FULL_TEXT``). Offline; no model key."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.audit_mode import (  # noqa: E402
    AUDIT_FULL_TEXT_ENV,
    DEMO_KEYS_ENV,
    PUBLIC_DEMO_ENV,
    WITHHELD_PHI,
    deployment_looks_public,
    full_text_requested,
    resolve_full_text,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState, verify_chain  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_lookup import ROW_802, FakeSearcher  # noqa: E402

DEMO = "demo-key-PUBLIC-BY-DESIGN-0123456789abc"
H = {"X-API-Key": KEY}
QUESTION = "What changed this week for LLZ?"
PHI_QUESTION = "Patient DOB 03/04/1950, MRN 1234567: what changed this week for LLZ?"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (AUDIT_FULL_TEXT_ENV, DEMO_KEYS_ENV, PUBLIC_DEMO_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("audit-mode"))


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


# --- env semantics ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_flag_on_values(value: str) -> None:
    assert full_text_requested({AUDIT_FULL_TEXT_ENV: value}) is True


@pytest.mark.parametrize("value", [None, "", "0", "false", "False", "no", "off", "2"])
def test_flag_off_values(value: str | None) -> None:
    env = {} if value is None else {AUDIT_FULL_TEXT_ENV: value}
    assert full_text_requested(env) is False


def test_public_detection() -> None:
    assert deployment_looks_public({}) is False
    assert deployment_looks_public({DEMO_KEYS_ENV: "  "}) is False
    assert deployment_looks_public({DEMO_KEYS_ENV: DEMO}) is True
    assert deployment_looks_public({PUBLIC_DEMO_ENV: "1"}) is True
    assert deployment_looks_public({PUBLIC_DEMO_ENV: "0"}) is False
    assert deployment_looks_public({}, demo_keys=True) is True


def test_resolve_refuses_public_with_warning(capsys: pytest.CaptureFixture[str]) -> None:
    assert resolve_full_text(True, {}) is True
    assert resolve_full_text(False, {}) is False
    assert resolve_full_text(True, {PUBLIC_DEMO_ENV: "1"}) is False
    assert resolve_full_text(True, {DEMO_KEYS_ENV: DEMO}) is False
    seen = capsys.readouterr()
    assert (seen.out + seen.err).count("audit_full_text_refused_public_demo") == 2


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


def test_env_on_stores_text_and_chain_verifies(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUDIT_FULL_TEXT_ENV, "1")
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


def test_audit_list_shows_text_only_when_stored(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c_off, _ = make_client(data, tmp_path / "off")
    ask(c_off, QUESTION)
    body = c_off.get("/v1/audit/recent", headers=H).json()
    assert body["chain"]["verified"] is True
    assert all(QUESTION not in e["payload_json"] for e in body["entries"])

    c_on, _ = make_client(data, tmp_path / "on", full_text=True)
    ask(c_on, QUESTION)
    body = c_on.get("/v1/audit/recent", headers=H).json()
    assert body["chain"]["verified"] is True
    assert any(QUESTION in e["payload_json"] for e in body["entries"])


@pytest.mark.parametrize("how", ["demo_keys", "public_env"])
def test_public_demo_stays_off_with_warning(
    data: ConnectorData,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    how: str,
) -> None:
    monkeypatch.setenv(AUDIT_FULL_TEXT_ENV, "true")
    if how == "public_env":
        monkeypatch.setenv(PUBLIC_DEMO_ENV, "1")
    c, state = make_client(data, tmp_path, demo=how == "demo_keys")
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload and "full_text" not in payload
    assert QUESTION not in json.dumps(payload)
    seen = capsys.readouterr()
    assert "audit_full_text_refused_public_demo" in seen.out + seen.err


def test_explicit_setting_cannot_bypass_public_guard(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PUBLIC_DEMO_ENV, "yes")
    c, state = make_client(data, tmp_path, full_text=True)
    ask(c, QUESTION)
    (payload,) = ask_entries(state)
    assert "question_text" not in payload


def test_phi_rejected_text_never_stored(data: ConnectorData, tmp_path: Path) -> None:
    c, state = make_client(data, tmp_path, full_text=True)
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
    monkeypatch.setenv(AUDIT_FULL_TEXT_ENV, "1")
    c, state = make_client(data, tmp_path / "flag", demo=True)
    got = ask(c, QUESTION, key=DEMO)
    assert got == ref
    (p_ref,) = ask_entries(state_ref)
    (p_got,) = ask_entries(state)
    assert p_got == p_ref
    assert "question_text" not in p_got
    assert c.get("/v1/audit/recent", headers={"X-API-Key": DEMO}).status_code == 403
