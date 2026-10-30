"""Feedback, visit and admin-export tests (no network: fake store, fake notifier, mock HTTP)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.common.exceptions import OpenFDAAPIError, OpenFDAUnavailableError  # noqa: E402
from maudesignal.connector import app as app_module  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.blob_store import (  # noqa: E402
    BlobRef,
    MemoryStore,
    StoreError,
    VercelBlobStore,
    store_from_env,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.feedback import (  # noqa: E402
    FEEDBACK_COLUMNS,
    REF_PATTERN,
    VISIT_COLUMNS,
)
from maudesignal.connector.notify import (
    NoopNotifier,
    ResendNotifier,
    notifier_from_env,
)  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402

ORIGIN = "https://app.example.com"
ADMIN = "admin-key-NOT-REAL-0123456789"
GOOD: dict[str, Any] = {
    "rating": 4,
    "comment": "Useful for trend review.",
    "blocker": "Needs our complaint system export.",
    "one_thing": "Saved views per product code.",
    "name": "A. Tester",
    "role": "RA lead",
    "consent": "quote_anonymous",
    "ref": "dr-smith_1",
    "page": "signals",
    "client_ts": "2026-10-30T10:00:00Z",
}


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def feedback(self, record: dict[str, Any]) -> None:
        self.sent.append(record)


class RecordingLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _log(self, event: str, **kw: Any) -> None:
        self.lines.append(f"{event} {kw}")

    info = warning = error = debug = _log


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("fb"))


def make(
    data: ConnectorData,
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: Any = None,
    notifier: Any = None,
    admin: str | None = ADMIN,
    per_hour: int | None = None,
    live: Any = fake_check,
) -> tuple[TestClient, Any, FakeNotifier]:
    if admin is None:
        monkeypatch.delenv("MAUDESIGNAL_ADMIN_KEY", raising=False)
    else:
        monkeypatch.setenv("MAUDESIGNAL_ADMIN_KEY", admin)
    if per_hour is not None:
        monkeypatch.setenv("MAUDESIGNAL_FEEDBACK_PER_HOUR", str(per_hour))
    else:
        monkeypatch.delenv("MAUDESIGNAL_FEEDBACK_PER_HOUR", raising=False)
    st = store or MemoryStore()
    nt = notifier or FakeNotifier()
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(100),
        data=data,
        live_checker=live,
        web_origins=(ORIGIN,),
        feedback_store=st,
        notifier=nt,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), st, nt


def all_stored(store: MemoryStore, kind: str) -> list[dict[str, Any]]:
    return [json.loads(store.get(r)) for r in store.list_prefix(f"{kind}/")]


H = {"Origin": ORIGIN}
A = {"X-Admin-Key": ADMIN}


def test_feedback_stored_with_id_and_time_and_no_network_identity(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ = make(data, monkeypatch)
    r = c.post("/v1/feedback", json=GOOD, headers=H | {"User-Agent": "UA-SECRET-STRING"})
    assert r.status_code == 201
    [rec] = all_stored(store, "feedback")
    assert rec["id"] == r.json()["id"] and rec["received_utc"].endswith("+00:00")
    assert rec["rating"] == 4 and rec["consent"] == "quote_anonymous" and rec["ref"] == "dr-smith_1"
    blob = json.dumps(rec)
    assert "UA-SECRET-STRING" not in blob and "testclient" not in blob and "127.0.0.1" not in blob
    assert not {"ip", "user_agent", "ua", "address"} & set(rec)
    [ref] = store.list_prefix("feedback/")
    assert ref.pathname == f"feedback/{rec['received_utc'][:10]}/{rec['id']}.json"


@pytest.mark.parametrize(
    "patch",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": "4"},
        {"rating": True},
        {"consent": "public"},
        {"consent": None},
        {"comment": "x" * 2001},
        {"name": "n" * 101},
        {"page": "p" * 65},
        {"extra_field": 1},
    ],
)
def test_validation_rejects(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, patch: dict[str, Any]
) -> None:
    c, store, _ = make(data, monkeypatch)
    r = c.post("/v1/feedback", json=GOOD | patch, headers=H)
    assert r.status_code == 422
    assert all_stored(store, "feedback") == []


@pytest.mark.parametrize("consent", ["quote_name_role", "quote_anonymous", "no_quote"])
def test_consent_values_accepted(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, consent: str
) -> None:
    c, _, _ = make(data, monkeypatch)
    assert c.post("/v1/feedback", json=GOOD | {"consent": consent}, headers=H).status_code == 201


def test_optional_fields_and_non_json(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = make(data, monkeypatch)
    minimal = {"rating": 3, "consent": "no_quote"}
    assert c.post("/v1/feedback", json=minimal, headers=H).status_code == 201
    r = c.post("/v1/feedback", content=b"not json", headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


def test_body_over_16kb_is_413(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store, _ = make(data, monkeypatch)
    big = json.dumps(GOOD | {"comment": "x" * 20000})
    r = c.post("/v1/feedback", content=big, headers=H | {"Content-Type": "application/json"})
    assert r.status_code == 413
    assert all_stored(store, "feedback") == []


@pytest.mark.parametrize(
    "text",
    [
        "mail me at jane.doe@example.com",
        "call 415-555-0134 please",
        "(415) 555 0134",
        "patient SSN 123-45-6789",
        "MRN 00123456 had a fall",
        "MRN: 99887766",
        "DOB 04/12/1961",
        "date of birth: 1961",
    ],
)
def test_phi_guard_returns_422_and_stores_nothing(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    c, store, nt = make(data, monkeypatch)
    for field in ("comment", "blocker", "one_thing", "name", "role"):
        r = c.post("/v1/feedback", json=GOOD | {field: text}, headers=H)
        assert r.status_code == 422, field
        assert "remove patient details" in r.json()["error"]["message"]
    assert all_stored(store, "feedback") == [] and nt.sent == []


def test_phi_guard_lets_ordinary_text_through(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    text = (
        "We review 510(k) K231234 and 3 product codes in 2026; FDA MDR 30-day clock; "
        "report received 10/12/2025."
    )
    assert c.post("/v1/feedback", json=GOOD | {"comment": text}, headers=H).status_code == 201


def test_feedback_rate_limit_5_per_hour_then_429(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    for _ in range(5):
        assert c.post("/v1/feedback", json=GOOD, headers=H).status_code == 201
    r = c.post("/v1/feedback", json=GOOD, headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_feedback_limit_env_override(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = make(data, monkeypatch, per_hour=1)
    assert c.post("/v1/feedback", json=GOOD, headers=H).status_code == 201
    assert c.post("/v1/feedback", json=GOOD, headers=H).status_code == 429


def test_cors_only_for_listed_origins(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store, _ = make(data, monkeypatch)
    pre = c.options(
        "/v1/feedback",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 204
    assert pre.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in pre.headers["access-control-allow-methods"]
    bad = c.options("/v1/feedback", headers={"Origin": "https://evil.example"})
    assert bad.status_code == 204 and "access-control-allow-origin" not in bad.headers
    blocked = c.post("/v1/feedback", json=GOOD, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403 and "access-control-allow-origin" not in blocked.headers
    assert all_stored(store, "feedback") == []
    ok = c.post("/v1/feedback", json=GOOD, headers=H)
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    visit_bad = c.post("/v1/visit", json={"page": "x"}, headers={"Origin": "https://evil.example"})
    assert visit_bad.status_code == 403


def test_visit_204_stores_no_identity_and_validates(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ = make(data, monkeypatch)
    r = c.post(
        "/v1/visit",
        json={"ref": "abc", "page": "signals", "client_ts": "2026-10-30T01:00:00.000Z"},
        headers=H | {"User-Agent": "UA-SECRET-STRING"},
    )
    assert r.status_code == 204 and r.content == b""
    [rec] = all_stored(store, "visits")
    assert set(rec) == {"id", "received_utc", "ref", "page", "client_ts"}
    assert "UA-SECRET-STRING" not in json.dumps(rec)
    assert c.post("/v1/visit", json={"ref": "ok"}, headers=H).status_code == 422
    assert c.post("/v1/visit", json={"page": "p" * 65}, headers=H).status_code == 422
    [ref] = store.list_prefix("visits/")
    assert ref.pathname.startswith("visits/") and ref.pathname.endswith(".json")


def test_visit_limit_60_per_hour(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = make(data, monkeypatch)
    codes = [c.post("/v1/visit", json={"page": "p"}, headers=H).status_code for _ in range(61)]
    assert codes[:60] == [204] * 60 and codes[60] == 429


def test_health_says_which_store(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = make(data, monkeypatch)
    assert c.get("/v1/health").json()["feedback_store"] == "memory"
    blob = VercelBlobStore("tok", client=httpx.Client(transport=httpx.MockTransport(lambda r: r)))
    c2, _, _ = make(data, monkeypatch, store=blob)
    assert c2.get("/v1/health").json()["feedback_store"] == "blob_private"


def test_store_failure_is_503_not_silent(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down(MemoryStore):
        def put_json(self, pathname: str, record: dict[str, Any]) -> None:
            raise StoreError("down")

    c, _, nt = make(data, monkeypatch, store=Down())
    assert c.post("/v1/feedback", json=GOOD, headers=H).status_code == 503
    assert nt.sent == []


def test_routes_hidden_from_public_openapi(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    paths = c.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "feedback" in p or "visit" in p or "admin" in p]


# --- admin -------------------------------------------------------------------------------


def seed(c: TestClient) -> None:
    c.post("/v1/feedback", json=GOOD, headers=H)
    c.post("/v1/feedback", json=GOOD | {"rating": 2, "comment": "=HYPERLINK(1)"}, headers=H)
    c.post("/v1/feedback", json=GOOD | {"ref": None, "rating": 5}, headers=H)
    c.post("/v1/visit", json={"ref": "dr-smith_1", "page": "signals"}, headers=H)
    c.post("/v1/visit", json={"ref": "dr-smith_1", "page": "trends"}, headers=H)
    c.post("/v1/visit", json={"page": "signals"}, headers=H)


def test_admin_503_when_unconfigured_never_open(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch, admin=None)
    for url in ("/v1/admin/summary", "/v1/admin/export?kind=feedback"):
        r = c.get(url, headers=A)
        assert r.status_code == 503 and "admin export not configured" in r.text
        assert c.get(url).status_code == 503
    assert c.get("/v1/admin/export?kind=feedback", headers={"X-Admin-Key": ""}).status_code == 503


def test_admin_401_and_failed_auth_limiter(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    assert c.get("/v1/admin/summary").status_code == 401
    assert c.get("/v1/admin/summary", headers={"X-Admin-Key": "wrong"}).status_code == 401
    codes = [
        c.get("/v1/admin/summary", headers={"X-Admin-Key": "wrong"}).status_code for _ in range(12)
    ]
    assert 429 in codes
    assert c.get("/v1/admin/summary", headers=A).status_code == 429  # blocked even when right


def test_admin_summary_counts_and_average(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    seed(c)
    r = c.get("/v1/admin/summary", headers=A)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["totals"] == {"visits": 3, "feedback": 3}
    refs = {x["ref"]: x for x in body["by_ref"]}
    assert refs["dr-smith_1"] == {
        "ref": "dr-smith_1",
        "visits": 2,
        "feedback": 2,
        "avg_rating": 3.0,
    }
    assert refs["email-batch-1"]["avg_rating"] == 5.0
    pages = {x["page"]: x for x in body["by_page"]}
    assert pages["signals"]["visits"] == 2 and pages["signals"]["feedback"] == 3


def test_admin_export_csv_columns_and_json(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    seed(c)
    r = c.get("/v1/admin/export?kind=feedback&format=csv", headers=A)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == FEEDBACK_COLUMNS and len(rows) == 4
    assert "'=HYPERLINK(1)" in [cell for row in rows for cell in row]  # formula neutralised
    v = list(csv.reader(io.StringIO(c.get("/v1/admin/export?kind=visits", headers=A).text)))
    assert v[0] == VISIT_COLUMNS and len(v) == 4
    j = c.get("/v1/admin/export?kind=visits&format=json", headers=A)
    assert j.status_code == 200 and len(j.json()) == 3
    assert c.get("/v1/admin/export?kind=other", headers=A).status_code == 422


def test_admin_page_has_no_data_and_is_private(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    seed(c)
    r = c.get("/admin")
    assert r.status_code == 200 and "password" in r.text and "sessionStorage" in r.text
    assert "dr-smith_1" not in r.text and "Useful for trend review" not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert ADMIN not in r.text


# --- email -------------------------------------------------------------------------------


def test_email_sent_with_fake_client_only_when_configured() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "x"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    env = {"RESEND_API_KEY": "re_fake_key", "FEEDBACK_NOTIFY_TO": "me@example.com"}
    n = notifier_from_env(env)
    assert isinstance(n, ResendNotifier)
    assert isinstance(notifier_from_env({}), NoopNotifier)
    assert isinstance(notifier_from_env({"RESEND_API_KEY": "k"}), NoopNotifier)
    n2 = ResendNotifier("re_fake_key", ["me@example.com"], client=client)
    rec = GOOD | {"id": "i1", "received_utc": "2026-10-30T00:00:00+00:00"}
    n2.feedback(rec)
    n2.feedback(rec | {"ref": None})
    assert str(seen[0].url) == "https://api.resend.com/emails"
    assert seen[0].headers["authorization"] == "Bearer re_fake_key"
    body = json.loads(seen[0].content)
    assert body["subject"] == "MaudeSignal feedback: 4/5 (dr-smith_1)"
    assert body["from"] == "MaudeSignal <onboarding@resend.dev>"
    assert body["to"] == ["me@example.com"] and "Useful for trend review." in body["text"]
    assert json.loads(seen[1].content)["subject"].endswith("(no code)")


def test_email_failure_never_fails_request_or_logs_key(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr("maudesignal.connector.notify.logger", rec)

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route re_fake_key")

    n = ResendNotifier(
        "re_fake_key", ["me@example.com"], client=httpx.Client(transport=httpx.MockTransport(boom))
    )
    c, _, _ = make(data, monkeypatch, notifier=n)
    assert c.post("/v1/feedback", json=GOOD, headers=H).status_code == 201
    n_500 = ResendNotifier(
        "re_fake_key",
        ["me@example.com"],
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    c2, _, _ = make(data, monkeypatch, notifier=n_500)
    assert c2.post("/v1/feedback", json=GOOD, headers=H).status_code == 201
    text = " ".join(rec.lines)
    assert "ConnectError" in text and "status" in text and "re_fake_key" not in text


def test_notify_skipped_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr("maudesignal.connector.notify.logger", rec)
    NoopNotifier().feedback({})
    assert rec.lines == ["notify_skipped {}"]


# --- blob client -------------------------------------------------------------------------


def test_blob_client_request_shapes() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "PUT":
            return httpx.Response(200, json={"pathname": "x"})
        if req.url.path == "/":
            cursor = req.url.params.get("cursor")
            if not cursor:
                return httpx.Response(
                    200,
                    json={
                        "blobs": [{"pathname": "feedback/d/a.json", "url": "https://s/a"}],
                        "cursor": "c2",
                        "hasMore": True,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "blobs": [
                        {
                            "pathname": "feedback/d/b.json",
                            "url": "https://s/b",
                            "downloadUrl": "https://s/b?d=1",
                        }
                    ],
                    "hasMore": False,
                },
            )
        return httpx.Response(200, content=b'{"ok": 1}')

    store = VercelBlobStore("tok_fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    store.put_json("feedback/2026-10-30/id1.json", {"a": 1})
    put = seen[0]
    assert put.method == "PUT" and put.url.path == "/feedback/2026-10-30/id1.json"
    assert put.headers["authorization"] == "Bearer tok_fake"
    assert put.headers["x-vercel-blob-access"] == "private"
    assert put.headers["x-add-random-suffix"] == "0"
    assert json.loads(put.content) == {"a": 1}
    refs = store.list_prefix("feedback/")
    assert [r.pathname for r in refs] == ["feedback/d/a.json", "feedback/d/b.json"]
    assert seen[1].url.params["prefix"] == "feedback/" and seen[2].url.params["cursor"] == "c2"
    assert store.get(refs[0]) == b'{"ok": 1}'
    assert seen[-1].headers["authorization"] == "Bearer tok_fake"


def test_blob_client_errors_hide_token(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr("maudesignal.connector.blob_store.logger", rec)
    store = VercelBlobStore(
        "tok_fake",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
    )
    with pytest.raises(StoreError) as err:
        store.put_json("feedback/d/i.json", {})
    with pytest.raises(StoreError):
        store.list_prefix("feedback/")
    with pytest.raises(StoreError):
        store.get(BlobRef("p", "https://s/p"))
    assert "tok_fake" not in str(err.value) and "tok_fake" not in " ".join(rec.lines)


def test_store_from_env_picks_backend() -> None:
    assert store_from_env({}).backend == "memory"
    assert store_from_env({"BLOB_READ_WRITE_TOKEN": "t"}).backend == "blob_private"


# --- openFDA failure logging ---------------------------------------------------------------


def test_openfda_failure_logs_class_and_status_only(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(app_module, "logger", rec)

    class Boom:
        def __init__(self, api_key: str | None = None) -> None:
            pass

        def __enter__(self) -> Boom:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fail(*_: Any) -> None:
        raise OpenFDAUnavailableError("openFDA server error 503 api_key=SECRETKEY")

    monkeypatch.setattr(app_module, "OpenFDAClient", Boom)
    monkeypatch.setattr(app_module, "check_product_code", fail)
    monkeypatch.setenv("OPENFDA_API_KEY", "SECRETKEY")
    with pytest.raises(OpenFDAAPIError):
        app_module._default_live_checker("LLZ")
    [line] = rec.lines
    assert "connector_openfda_failed" in line
    assert "OpenFDAUnavailableError" in line and "'status': 503" in line
    assert "SECRETKEY" not in line and "api_key" not in line


def test_openfda_transport_error_logs_no_status_or_text(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(app_module, "logger", rec)

    class Boom:
        def __init__(self, api_key: str | None = None) -> None:
            pass

        def __enter__(self) -> Boom:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fail(*_: Any) -> None:
        raise OpenFDAAPIError("HTTP error contacting openFDA: https://x/?api_key=SECRETKEY 500")

    monkeypatch.setattr(app_module, "OpenFDAClient", Boom)
    monkeypatch.setattr(app_module, "check_product_code", fail)
    with pytest.raises(OpenFDAAPIError):
        app_module._default_live_checker("LLZ")
    [line] = rec.lines
    assert "'status': None" in line and "SECRETKEY" not in line


def test_no_ip_in_limiter_ids_or_logs(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr("maudesignal.connector.feedback.logger", rec)
    c, _, _ = make(data, monkeypatch)
    c.post("/v1/feedback", json=GOOD, headers=H | {"X-Forwarded-For": "203.0.113.9"})
    assert "203.0.113.9" not in " ".join(rec.lines) and "testclient" not in " ".join(rec.lines)


@pytest.mark.parametrize("field,value", [("page", "home<script>"), ("client_ts", "jane doe")])
def test_page_and_client_ts_are_format_checked(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    c, store, _ = make(data, monkeypatch)
    assert c.post("/v1/feedback", json=GOOD | {field: value}, headers=H).status_code == 422
    assert all_stored(store, "feedback") == []


# --- default ref for codeless records -----------------------------------------------------


def test_missing_or_empty_ref_stored_as_email_batch_1(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MAUDESIGNAL_DEFAULT_REF", raising=False)
    c, store, _ = make(data, monkeypatch)
    no_ref = {k: v for k, v in GOOD.items() if k != "ref"}
    assert c.post("/v1/feedback", json=no_ref, headers=H).status_code == 201
    assert c.post("/v1/feedback", json=GOOD | {"ref": ""}, headers=H).status_code == 201
    assert c.post("/v1/visit", json={"page": "signals"}, headers=H).status_code == 204
    assert c.post("/v1/visit", json={"page": "signals", "ref": ""}, headers=H).status_code == 204
    assert {r["ref"] for r in all_stored(store, "feedback")} == {"email-batch-1"}
    assert {r["ref"] for r in all_stored(store, "visits")} == {"email-batch-1"}
    summary = c.get("/v1/admin/summary", headers=A).json()
    assert [x["ref"] for x in summary["by_ref"]] == ["email-batch-1"]
    csv_text = c.get("/v1/admin/export?kind=visits&format=csv", headers=A).text
    assert "email-batch-1" in csv_text


def test_default_ref_env_override(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_DEFAULT_REF", "email-batch-2")
    c, store, _ = make(data, monkeypatch)
    c.post("/v1/feedback", json={k: v for k, v in GOOD.items() if k != "ref"}, headers=H)
    c.post("/v1/visit", json={"page": "signals"}, headers=H)
    assert all_stored(store, "feedback")[0]["ref"] == "email-batch-2"
    assert all_stored(store, "visits")[0]["ref"] == "email-batch-2"


def test_invalid_default_ref_env_falls_back(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAUDESIGNAL_DEFAULT_REF", "not valid!")
    c, store, _ = make(data, monkeypatch)
    c.post("/v1/visit", json={"page": "signals"}, headers=H)
    assert all_stored(store, "visits")[0]["ref"] == "email-batch-1"


def test_explicit_ref_is_unchanged(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_DEFAULT_REF", "email-batch-2")
    c, store, _ = make(data, monkeypatch)
    c.post("/v1/feedback", json=GOOD, headers=H)
    c.post("/v1/visit", json={"ref": "abc", "page": "signals"}, headers=H)
    assert all_stored(store, "feedback")[0]["ref"] == "dr-smith_1"
    assert all_stored(store, "visits")[0]["ref"] == "abc"


# --- widened ref codes, invalid-code, no names, by-code admin, delete-test ----------------


class DeletingStore(MemoryStore):
    """MemoryStore plus the delete a real store needs for the TEST cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete(self, ref: BlobRef) -> None:
        self.deleted.append(ref.pathname)
        with self._lock:
            del self._items[ref.pathname]


def test_ref_pattern_is_url_safe_unreserved_up_to_64() -> None:
    import re

    assert REF_PATTERN == r"^[A-Za-z0-9._~-]{1,64}$"
    for good in ("a", "Dr.Smith_1~x-2", "x" * 64):
        assert re.fullmatch(REF_PATTERN, good)
    for bad in ("", "x" * 65, "a b", "a/b", "a%20b", "a@b", "a?b"):
        assert not re.fullmatch(REF_PATTERN, bad)


@pytest.mark.parametrize("code", ["Dr.Smith_1~x-2", "x" * 64, "TEST1"])
def test_widened_codes_are_kept(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    c, store, _ = make(data, monkeypatch)
    assert c.post("/v1/feedback", json=GOOD | {"ref": code}, headers=H).status_code == 201
    assert c.post("/v1/visit", json={"ref": code, "page": "signals"}, headers=H).status_code == 204
    assert all_stored(store, "feedback")[0]["ref"] == code
    assert all_stored(store, "visits")[0]["ref"] == code


@pytest.mark.parametrize("bad", ["bad code!", "x" * 65, "a/b", "a@b.com", "<script>", 12, ["x"]])
def test_invalid_ref_is_kept_as_invalid_code_never_raw(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    c, store, _ = make(data, monkeypatch)
    assert c.post("/v1/feedback", json=GOOD | {"ref": bad}, headers=H).status_code == 201
    assert c.post("/v1/visit", json={"ref": bad, "page": "signals"}, headers=H).status_code == 204
    [fb] = all_stored(store, "feedback")
    [vi] = all_stored(store, "visits")
    assert fb["ref"] == "invalid-code" and vi["ref"] == "invalid-code"
    raw = json.dumps([fb, vi]) + c.get("/v1/admin/export?kind=visits", headers=A).text
    assert str(bad) not in raw if isinstance(bad, str) else True


def test_name_is_accepted_but_never_stored_exported_or_emailed(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, nt = make(data, monkeypatch)
    payload = GOOD | {"name": "Zed Quillfeather"}
    assert c.post("/v1/feedback", json=payload, headers=H).status_code == 201
    [rec] = all_stored(store, "feedback")
    assert "name" not in rec and "Quillfeather" not in json.dumps(rec)
    assert rec["role"] == "RA lead"
    assert "name" not in FEEDBACK_COLUMNS
    assert "Quillfeather" not in json.dumps(nt.sent) and "name" not in nt.sent[0]
    csv_text = c.get("/v1/admin/export?kind=feedback&format=csv", headers=A).text
    assert "Quillfeather" not in csv_text
    assert "Quillfeather" not in c.get("/v1/admin/export?kind=feedback&format=json", headers=A).text
    summary = c.get("/v1/admin/summary", headers=A)
    assert "Quillfeather" not in summary.text
    from maudesignal.connector.notify import _body

    assert "Quillfeather" not in _body(nt.sent[0])


def test_old_stored_records_with_name_do_not_leak_through_admin(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ = make(data, monkeypatch)
    old = GOOD | {"id": "old1", "received_utc": "2026-10-01T00:00:00+00:00", "name": "Old Name"}
    store.put_json("feedback/2026-10-01/old1.json", old)
    for url in (
        "/v1/admin/export?kind=feedback&format=json",
        "/v1/admin/export?kind=feedback&format=csv",
        "/v1/admin/summary",
    ):
        assert "Old Name" not in c.get(url, headers=A).text


def test_phi_guard_also_covers_role(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store, _ = make(data, monkeypatch)
    r = c.post("/v1/feedback", json=GOOD | {"role": "jo@example.com"}, headers=H)
    assert r.status_code == 422 and all_stored(store, "feedback") == []


def test_summary_codes_grouped_sorted_and_labelled(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ = make(data, monkeypatch)

    def put(kind: str, n: int, rec: dict[str, Any]) -> None:
        stamp = f"2026-10-30T12:{n:02d}:00+00:00"
        store.put_json(f"{kind}/2026-10-30/r{n}.json", rec | {"id": f"r{n}", "received_utc": stamp})

    put("visits", 0, {"ref": "Alice1", "page": "signals"})
    put("visits", 1, {"ref": "Alice1", "page": "trends"})
    put("visits", 2, {"ref": "Alice1", "page": "signals"})
    put("visits", 3, {"ref": "email-batch-1", "page": "signals"})
    put("visits", 4, {"ref": "test9", "page": "recalls"})
    put("visits", 5, {"ref": "invalid-code", "page": "signals"})
    put("feedback", 6, GOOD | {"ref": "Alice1", "consent": "no_quote"} | {"name": None})
    body = c.get("/v1/admin/summary", headers=A).json()
    assert body["totals"] == {"visits": 6, "feedback": 1}
    assert {"by_ref", "by_page"} <= set(body)
    codes = body["codes"]
    assert [x["code"] for x in codes] == ["Alice1", "invalid-code", "test9", "email-batch-1"]
    assert codes[0]["last_seen_utc"] == "2026-10-30T12:06:00+00:00"
    alice = codes[0]
    assert alice["label"] == "" and alice["visits"] == 3
    assert alice["pages_opened"] == ["signals", "trends"]
    assert alice["first_seen_utc"] < alice["last_seen_utc"]
    [fb] = alice["feedback"]
    assert set(fb) == {
        "received_utc",
        "page",
        "rating",
        "comment",
        "blocker",
        "one_thing",
        "role",
        "consent",
    }
    assert fb["consent"] == "no_quote" and fb["role"] == "RA lead" and fb["rating"] == 4
    labels = {x["code"]: x["label"] for x in codes}
    assert labels == {
        "Alice1": "",
        "invalid-code": "invalid code",
        "test9": "test",
        "email-batch-1": "email batch 1",
    }


def test_label_test_prefix_is_case_insensitive() -> None:
    from maudesignal.connector.feedback import code_label

    assert code_label("TEST1") == "test" and code_label("Test-x") == "test"
    assert code_label("email-batch-1") == "email batch 1"
    assert code_label("invalid-code") == "invalid code"
    assert code_label("alice") == ""


def test_admin_page_by_code_section_and_safe_text(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    page = c.get("/admin").text
    assert "No names, emails or IP addresses are stored." in page
    assert "By code" in page and 'id="hide"' in page and "Hide TEST codes" in page
    assert "Delete TEST entries" in page and "confirm(" in page
    for words in (
        "Quote by name and role (confirm name with them)",
        "Quote anonymously",
        "Do not quote",
    ):
        assert words in page
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page


def test_delete_test_removes_only_test_entries(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DeletingStore()
    c, _, _ = make(data, monkeypatch, store=store)
    for code in ("TEST1", "test-two", "Alice1", "attest", "invalid-code"):
        c.post("/v1/visit", json={"ref": code, "page": "signals"}, headers=H)
        c.post("/v1/feedback", json=GOOD | {"ref": code}, headers=H)
    c.post("/v1/visit", json={"page": "signals"}, headers=H)
    r = c.post("/v1/admin/delete-test", headers=A)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"deleted": {"visits": 2, "feedback": 2}}
    assert len(store.deleted) == 4
    left = {x["ref"] for x in all_stored(store, "visits") + all_stored(store, "feedback")}
    assert left == {"Alice1", "attest", "invalid-code", "email-batch-1"}
    again = c.post("/v1/admin/delete-test", headers=A)
    assert again.json() == {"deleted": {"visits": 0, "feedback": 0}}


def test_delete_test_needs_admin_key(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    store = DeletingStore()
    c, _, _ = make(data, monkeypatch, store=store)
    c.post("/v1/visit", json={"ref": "TEST1", "page": "signals"}, headers=H)
    assert c.post("/v1/admin/delete-test").status_code == 401
    assert c.post("/v1/admin/delete-test", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert store.deleted == [] and len(all_stored(store, "visits")) == 1
    c2, _, _ = make(data, monkeypatch, store=store, admin=None)
    assert c2.post("/v1/admin/delete-test", headers=A).status_code == 503
    assert store.deleted == []
    assert c.get("/v1/admin/delete-test", headers=A).status_code == 405


def test_delete_test_without_store_support_is_501_and_hidden(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _ = make(data, monkeypatch)
    c.post("/v1/visit", json={"ref": "TEST1", "page": "signals"}, headers=H)
    assert c.post("/v1/admin/delete-test", headers=A).status_code == 501
    assert len(all_stored(store, "visits")) == 1
    assert "delete-test" not in json.dumps(c.get("/openapi.json").json())
