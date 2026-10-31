"""Tests for /privacy, /terms, the icon files and the two-key setup (HACKATHON-BUILT).

Covers unit, API, security (escaping, no stored address), interface (links, rewrites),
compatibility (viewport, light and dark CSS) and exploratory cases. No network.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData  # noqa: E402
from maudesignal.connector.legal_pages import CONTACT_ENV, ISSUES_URL  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402
from tests.unit.test_connector import NOW  # noqa: E402

FORBIDDEN = re.compile(
    r"(?<![A-Za-z])(?:FDA-approved|approved|official\w*|part[\s-]*11|validated|overnight"
    r"|worsening|citation[\s-]*checked|complaint[\s-]+data|safe|unsafe|compliant)(?![A-Za-z])",
    re.IGNORECASE,
)
K1 = "k1-" + "a" * 40
K2 = "k2-" + "b" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        CONTACT_ENV,
        "META_MODEL_API_KEY",
        "MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP",
        "UPSTASH_REDIS_REST_URL",
        "UPSTASH_REDIS_REST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def _client(tmp_path: Path, keys: str = K1) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": keys}),
        limiter=RateLimiter(30),
        failed_auth=RateLimiter(10),
        public_limiter=RateLimiter(10, window_seconds=3600),
        data=ConnectorData(work_dir=tmp_path / "d"),
        now=lambda: NOW,
        state=ConnectorState(),
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path)


@pytest.mark.parametrize("path", ["/privacy", "/terms"])
def test_pages_are_public_html_without_forbidden_words(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    text = re.sub(r"<[^>]+>", " ", r.text)
    assert FORBIDDEN.findall(text) == []
    assert "width=device-width" in r.text  # phone width
    assert "prefers-color-scheme:dark" in r.text  # light and dark
    assert not re.search(r"<(?:script|link|img)\b", r.text)  # no external assets


def test_privacy_has_the_questionnaire_answers(client: TestClient) -> None:
    page = " ".join(client.get("/privacy").text.split())
    for needle in (
        "openFDA",
        "MHRA (UK)",
        "iad1",
        "Washington DC",
        "Vercel Blob (private)",
        "Vercel Inc.",
        "Meta Platforms",
        "GOV.UK search API",
        "api.fda.gov",
        "peppered one-way hash",
        "<strong>not</strong> logged",
        "no names and no email addresses",
        "Feedback sent before 31 October 2026 could include a name the",
        "IP addresses are never stored",
        "2026-12-31",
        "No sale of data, no advertising and no tracking cookies",
        "not medical advice",
        "nothing is filed with FDA",
        "not an FDA-cleared device",
        "Saicharan Kondapally",
        "2026-10-31",
    ):
        assert needle in page, needle


def test_terms_have_the_real_numbers(client: TestClient) -> None:
    page = " ".join(client.get("/terms").text.split())
    for needle in (
        "without warranty",
        "research and demonstration",
        "not medical advice",
        "30 requests per key per minute",
        "10 wrong or missing keys per address per minute",
        "10 keyless device-type checks per address per hour",
        "3 to 500 characters",
        "$0.25 per call",
        "$2.00 per key per UTC day",
        "revoked at any time",
        "Do not try to bypass",
        "2026-10-31",
    ):
        assert needle in page, needle


@pytest.mark.parametrize("path", ["/privacy", "/terms"])
def test_contact_fallback_and_env_escaped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    assert ISSUES_URL in client.get(path).text
    assert "Email " not in client.get(path).text
    monkeypatch.setenv(CONTACT_ENV, '<script>alert(1)</script>"x@example.org')
    page = client.get(path).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&quot;x@example.org" in page
    monkeypatch.setenv(CONTACT_ENV, "person@example.org")
    assert "Email person@example.org" in client.get(path).text


def test_live_ask_line_follows_the_environment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "Live ask is OFF" in client.get("/privacy").text
    monkeypatch.setenv("META_MODEL_API_KEY", "secret-model-key")  # key alone: recorded answers
    assert "Live ask is OFF" in client.get("/privacy").text
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    page = client.get("/privacy").text
    assert "Live ask is ON" in page and "Live ask is OFF" not in page
    assert "secret-model-key" not in page


def test_exploratory_wrong_methods_and_paths(client: TestClient) -> None:
    assert client.post("/privacy").status_code == 405
    assert client.get("/terms/").status_code in (200, 307, 404)
    assert client.get("/privacy?x=" + "a" * 5000).status_code == 200
    assert client.get("/terms", headers={"X-API-Key": "bad"}).status_code == 200


def test_links_rewrites_and_openapi(client: TestClient) -> None:
    for path in ("/", "/docs-page"):
        page = client.get(path).text
        assert 'href="/privacy"' in page or "href='/privacy'" in page
        assert 'href="/terms"' in page or "href='/terms'" in page
    vercel = json.loads((PROJECT_ROOT / "vercel.json").read_text())
    assert {"/privacy", "/terms"} <= {r["source"] for r in vercel["rewrites"]}
    assert vercel["regions"] == ["iad1"]
    spec = json.loads((PROJECT_ROOT / "api" / "openapi.json").read_text())
    assert spec["info"]["termsOfService"] == "https://maudesignal-api.vercel.app/terms"
    assert spec["info"]["contact"]["url"].endswith("/issues")
    assert "/privacy" not in spec["paths"] and "/terms" not in spec["paths"]


def test_no_email_address_in_the_page_source() -> None:
    pages = (PROJECT_ROOT / "src/maudesignal/connector/legal_pages.py").read_text()
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[a-z]{2,}", pages)
    out = subprocess.run(
        ["git", "grep", "-nIE", r"[A-Za-z0-9._%+-]+@sjsu\.edu", "--", "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout == ""


def test_icon_files() -> None:
    d = PROJECT_ROOT / "docs" / "hackathon"
    svg = (d / "maudesignal-icon.svg").read_text()
    assert 'width="512"' in svg and 'height="512"' in svg and 'viewBox="0 0 512 512"' in svg
    assert "<script" not in svg and "href=" not in svg
    png = (d / "maudesignal-icon.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (512, 512)


# --- two keys in MAUDESIGNAL_API_KEYS ---------------------------------------------------------


def test_two_keys_both_work_and_whitespace_is_tolerated() -> None:
    ks = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"  {K1}  ,\t{K2} \n"})
    a, b = ks.verify(K1), ks.verify(K2)
    assert a and b and a != b
    assert ks.verify("k3-" + "c" * 40) is None


def test_removing_one_key_revokes_only_that_key() -> None:
    both = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{K1},{K2}"})
    only_first = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": K1})
    assert both.verify(K2) and only_first.verify(K2) is None
    assert only_first.verify(K1)
    assert KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{K1},,"}).verify(K1)


def test_with_a_pepper_the_remaining_key_keeps_its_id() -> None:
    pepper = {"MAUDESIGNAL_KEY_PEPPER": "p" * 32}
    both = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{K1},{K2}"} | pepper)
    only_first = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": K1} | pepper)
    assert both.verify(K1) == only_first.verify(K1) is not None
    # without a pepper the ids come from all digests: removing a key changes the other's id
    bare_both = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": f"{K1},{K2}"})
    bare_first = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": K1})
    assert bare_both.verify(K1) != bare_first.verify(K1)


def test_two_keys_over_http(tmp_path: Path) -> None:
    c = _client(tmp_path, f"{K1}, {K2}")
    for key, code in ((K1, 200), (K2, 200), ("z" * 40, 401)):
        assert c.get("/v1/audit/recent", headers={"X-API-Key": key}).status_code == code


# --- no raw address anywhere, and one cap over all keys -----------------------------------------


def test_no_raw_address_reaches_any_limiter_or_redis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_connector import fake_check
    from tests.unit.test_connector_store import FakeRedis, make_state

    ip = "203.0.113.7"
    monkeypatch.setenv("MAUDESIGNAL_TRUST_FORWARDED", "1")
    fake = FakeRedis()
    state = make_state(fake)
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": K1}),
        data=ConnectorData(work_dir=tmp_path / "d"),
        now=lambda: NOW,
        state=state,
        live_checker=fake_check,
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    h = {"X-Forwarded-For": ip}
    assert c.get("/v1/audit/recent", headers=h | {"X-API-Key": "z" * 40}).status_code == 401
    assert c.get("/v1/public/check_device_type?product_code=LLZ", headers=h).status_code == 200
    seen = [str(cmd) for cmd in fake.calls] + list(fake.kv) + list(fake.lists)
    assert any("failed-auth" in x for x in seen) and any("public-check" in x for x in seen)
    assert not any(ip in x for x in seen)


def test_total_cap_over_all_keys_falls_back_to_recorded(tmp_path: Path) -> None:
    from maudesignal.connector.ask import AskRuntime, ask
    from maudesignal.copilot.spend import SpendCaps

    def boom(*_: object) -> object:
        raise AssertionError("no live call once the total cap is reached")

    rt = AskRuntime(
        agent_factory=boom,  # type: ignore[arg-type]
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=0.25, session_calls=20, daily_usd=2.0),
        total_daily_usd=3.0,
        ledger_dir=tmp_path / "led",
    )
    rt.ledger_for("key-a").add(1.9, 1)  # each key is under its own $2.00 cap ...
    rt.ledger_for("key-b").add(1.2, 1)  # ... but together they are over $3.00
    assert rt.ledger_for("key-a").key.spent_today() < 2.0
    assert rt.ledger_for("key-b").key.spent_today() < 2.0
    d = ConnectorData(work_dir=tmp_path / "w")
    a = ask(d, "What changed this week for LLZ?", key_id="key-b", runtime=rt, now=lambda: NOW)
    assert a.provenance.kind == "recorded_answer"
    # a third key starts at zero of its own, but the total still blocks it
    b = ask(d, "What changed this week for LLZ?", key_id="key-c", runtime=rt, now=lambda: NOW)
    assert b.provenance.kind == "recorded_answer"


def test_total_cap_holds_in_the_shared_store(tmp_path: Path) -> None:
    from maudesignal.connector.ask import AskRuntime
    from maudesignal.copilot.spend import SpendCaps
    from tests.unit.test_connector_store import FakeRedis, make_state

    fake = FakeRedis()
    rt = AskRuntime(
        caps=SpendCaps(session_usd=0.25, session_calls=20, daily_usd=2.0),
        total_daily_usd=0.40,
        state=make_state(fake),
        ledger_dir=tmp_path / "led",
    )
    first = rt.ledger_for("key-a")
    assert first.shared and first.reserve(0.25)
    other = rt.ledger_for("key-b")
    assert other.reserve(0.25) is False  # the $0.40 total would be passed; nothing stays held
    first.release(0.25)
    assert other.reserve(0.25) is True
    assert any(":spend:ALL:" in k for k in fake.kv)


def test_terms_show_the_total_cap(tmp_path: Path) -> None:
    text = _client(tmp_path).get("/terms").text
    assert "$3.00 over all keys together" in text and "$2.00 per key" in text


def test_privacy_statements_match_the_code(tmp_path: Path) -> None:
    text = " ".join(_client(tmp_path).get("/privacy").text.split())
    assert "does not call GOV.UK when you use it" in text
    assert "queried live with a product code only" in text
    assert "Spend on <code>ask</code> is kept as a daily total per key id" in text
    assert "replaced by its SHA-256" in text
    assert "salted one-way hash" in text
