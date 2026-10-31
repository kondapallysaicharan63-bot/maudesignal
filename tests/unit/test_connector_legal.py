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
        "No names",
        "IP addresses are never stored",
        "2026-11-30",
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


def test_two_keys_over_http(tmp_path: Path) -> None:
    c = _client(tmp_path, f"{K1}, {K2}")
    for key, code in ((K1, 200), (K2, 200), ("z" * 40, 401)):
        assert c.get("/v1/audit/recent", headers={"X-API-Key": key}).status_code == code
