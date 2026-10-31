"""Tests for POST /v1/admin/redact-names (no network: fake stores, mock HTTP)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi")

from maudesignal.connector.blob_store import (  # noqa: E402
    BlobRef,
    MemoryStore,
    StoreError,
    VercelBlobStore,
)
from maudesignal.connector.data import ConnectorData  # noqa: E402
from tests.unit.test_connector_feedback import A, make  # noqa: E402

RN = "/v1/admin/redact-names"
COUNTS_DRY = {"checked": 5, "names_removed": 2, "names_kept_quote_by_name": 1, "failed": 0}


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("redact"))


class OverwriteSpyStore(MemoryStore):
    """MemoryStore that records overwrites and can fail one pathname."""

    def __init__(self, fail_on: str = "") -> None:
        super().__init__()
        self.overwritten: list[str] = []
        self.fail_on = fail_on

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        if pathname == self.fail_on:
            raise StoreError("blob store answered 500")
        self.overwritten.append(pathname)
        super().overwrite_json(pathname, record)


def seed_named(store: MemoryStore) -> dict[str, dict[str, Any]]:
    base = {"rating": 4, "comment": "c", "page": "signals", "ref": "alice"}
    recs = {
        "feedback/2026-10-29/a.json": base | {"id": "a", "name": "Ann Lee", "consent": "no_quote"},
        "feedback/2026-10-29/b.json": base
        | {"id": "b", "name": "Bo Kim", "consent": "quote_name_role"},
        "feedback/2026-10-29/c.json": base | {"id": "c", "consent": "quote_anonymous"},
        "feedback/2026-10-29/d.json": base | {"id": "d", "name": "  ", "consent": "no_quote"},
        "feedback/2026-10-29/e.json": base
        | {"id": "e", "name": "Cy Poe", "consent": "quote_anonymous", "role": "RA lead"},
        "visits/2026-10-29/v.json": {"id": "v", "ref": "alice", "name": "visit-keeps", "page": "x"},
    }
    for path, rec in recs.items():
        store.put_json(path, rec)
    return recs


def stored_by_path(store: MemoryStore) -> dict[str, dict[str, Any]]:
    return {
        r.pathname: json.loads(store.get(r))
        for kind in ("feedback", "visits")
        for r in store.list_prefix(f"{kind}/")
    }


def test_dry_run_changes_nothing(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    store = OverwriteSpyStore()
    c, _, _ = make(data, monkeypatch, store=store)
    seed_named(store)
    before = stored_by_path(store)
    r = c.post(RN, json={"dry_run": True}, headers=A)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == COUNTS_DRY
    assert stored_by_path(store) == before and store.overwritten == []


def test_removes_only_names_and_keeps_quote_by_name(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OverwriteSpyStore()
    c, _, _ = make(data, monkeypatch, store=store)
    seed = seed_named(store)
    r = c.post(RN, json={"dry_run": False}, headers=A)
    assert r.json() == COUNTS_DRY
    after = stored_by_path(store)
    assert sorted(store.overwritten) == ["feedback/2026-10-29/a.json", "feedback/2026-10-29/e.json"]
    assert set(after) == set(seed)  # same paths, nothing added or deleted
    for path in ("feedback/2026-10-29/a.json", "feedback/2026-10-29/e.json"):
        assert after[path] == {k: v for k, v in seed[path].items() if k != "name"}
    for path in set(seed) - set(store.overwritten):
        assert after[path] == seed[path]  # quote_name_role, no name, blank name, visits
    assert after["feedback/2026-10-29/b.json"]["name"] == "Bo Kim"
    assert after["visits/2026-10-29/v.json"]["name"] == "visit-keeps"
    again = c.post(RN, json={"dry_run": False}, headers=A).json()
    assert again["names_removed"] == 0 and again["names_kept_quote_by_name"] == 1


def test_failed_record_is_counted_and_the_rest_carry_on(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OverwriteSpyStore(fail_on="feedback/2026-10-29/a.json")
    c, _, _ = make(data, monkeypatch, store=store)
    seed_named(store)
    r = c.post(RN, json={"dry_run": False}, headers=A)
    assert r.status_code == 200
    assert r.json() == {
        "checked": 5,
        "names_removed": 1,
        "names_kept_quote_by_name": 1,
        "failed": 1,
    }
    after = stored_by_path(store)
    assert after["feedback/2026-10-29/a.json"]["name"] == "Ann Lee"
    assert "name" not in after["feedback/2026-10-29/e.json"]


def test_listing_failure_is_503(data: ConnectorData, monkeypatch: pytest.MonkeyPatch) -> None:
    class NoList(MemoryStore):
        def list_prefix(self, prefix: str) -> list[BlobRef]:
            raise StoreError("down")

    c, _, _ = make(data, monkeypatch, store=NoList())
    assert c.post(RN, json={"dry_run": True}, headers=A).status_code == 503


def test_admin_gate_body_checks_and_hidden_route(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OverwriteSpyStore()
    c, _, _ = make(data, monkeypatch, store=store)
    seed_named(store)
    before = stored_by_path(store)
    assert c.post(RN, json={"dry_run": False}).status_code == 401
    assert c.post(RN, json={"dry_run": False}, headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert c.post(RN, json={}, headers=A).status_code == 422
    assert c.post(RN, content=b"not json", headers=A).status_code == 422
    assert c.post(RN, json={"dry_run": "yes"}, headers=A).status_code == 422
    assert c.get(RN, headers=A).status_code == 405
    assert stored_by_path(store) == before
    c2, _, _ = make(data, monkeypatch, store=store, admin=None)
    assert c2.post(RN, json={"dry_run": False}, headers=A).status_code == 503
    assert stored_by_path(store) == before
    assert "redact-names" not in json.dumps(c.get("/openapi.json").json())


def test_admin_page_button_runs_dry_run_then_confirm(
    data: ConnectorData, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _, _ = make(data, monkeypatch)
    page = c.get("/admin").text
    assert "Remove names (keep only 'quote me by name')" in page
    assert "This will remove " in page and "(quote me by name). Continue?" in page
    assert "dry_run:dry" in page and "redact(true)" in page and "redact(false)" in page
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page


def test_blob_overwrite_sends_allow_overwrite_only_for_overwrite() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={})

    store = VercelBlobStore("tok_fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    store.put_json("feedback/d/a.json", {"a": 1})
    store.overwrite_json("feedback/d/a.json", {"a": 2})
    assert "x-allow-overwrite" not in seen[0].headers
    assert seen[1].headers["x-allow-overwrite"] == "1"
    assert seen[1].headers["x-add-random-suffix"] == "0"
    assert seen[1].url.path == "/feedback/d/a.json" and json.loads(seen[1].content) == {"a": 2}


WORDING = (
    "New feedback stores rating, comments, role, quote consent, referral code, page and time - "
    "no names and no email addresses. Feedback sent before 31 October 2026 could include a name "
    "the person typed; names are removed from those entries except where the person chose to be "
    "quoted by name and role."
)


def test_privacy_page_and_data_questionnaire_use_the_same_wording() -> None:
    from pathlib import Path

    from maudesignal.connector import legal_pages

    doc = Path(__file__).resolve().parents[2] / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
    assert WORDING in " ".join(doc.read_text(encoding="utf-8").split())
    src = Path(legal_pages.__file__).read_text(encoding="utf-8")
    assert WORDING in " ".join(src.split())
