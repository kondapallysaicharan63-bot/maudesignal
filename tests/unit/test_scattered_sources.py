"""Tests for the openFDA recall / 510(k) fetcher and PubMed abstract fetch (HACKATHON-BUILT).

No network: openFDA is served by an ``httpx.MockTransport`` with payloads shaped
like live responses (field names checked against api.fda.gov on 2026-10-27).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from maudesignal.gate.loader import store_from_database
from maudesignal.sources.openfda_sources import (
    K510_ENDPOINT,
    RECALL_ENDPOINT,
    OpenFDASourceFetcher,
    k510_url,
    recall_url,
)
from maudesignal.sources.pubmed import PubMedFetcher, parse_abstracts_xml
from maudesignal.storage.database import Database

RECALL = {
    "cfres_id": "189064",
    "product_res_number": "Z-0012-2022",
    "event_date_initiated": "2021-08-12",
    "recall_status": "Terminated",
    "res_event_number": "88595",
    "product_code": "LLZ",
    "k_numbers": ["K182419"],
    "product_description": "Centricity Universal Viewer 7.0",
    "reason_for_recall": "Study changes are not propagated to the archive.",
    "recalling_firm": "GE Healthcare, LLC",
    "address_1": "3000 N Grandview Blvd",
    "openfda": {"k_number": ["K" + str(i) for i in range(500)]},
}
K510 = {
    "k_number": "K182419",
    "applicant": "GE Healthcare",
    "device_name": "Centricity Universal Viewer",
    "product_code": "LLZ",
    "decision_date": "2018-12-14",
    "decision_code": "SESE",
    "statement_or_summary": "Summary",
    "openfda": {"registration_number": ["1"]},
}


def _transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        search = request.url.params.get("search", "")
        meta = {"last_updated": "2026-10-24", "results": {"total": 1}}
        if request.url.path.endswith("recall.json"):
            if "POK" in search:
                return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
            return httpx.Response(200, json={"meta": meta, "results": [RECALL, {"x": 1}]})
        return httpx.Response(200, json={"meta": meta, "results": [K510, {"k_number": ""}]})

    return httpx.MockTransport(handler)


def test_fetch_recalls_and_510k_store_trimmed_rows(tmp_path: Path) -> None:
    db = Database(tmp_path / "s.db")
    seen: list[httpx.Request] = []
    fetcher = OpenFDASourceFetcher(db, client=httpx.Client(transport=_transport(seen)))

    rec = fetcher.fetch_recalls("LLZ")
    assert (rec.matching_total, rec.stored, rec.last_updated) == (1, 1, "2026-10-24")
    assert seen[0].url.params["search"] == "product_code:LLZ"
    assert seen[0].url.params["sort"] == "event_date_initiated:desc"
    assert str(seen[0].url).startswith(RECALL_ENDPOINT)

    assert fetcher.fetch_recalls("POK").stored == 0  # openFDA 404 = no matches

    k = fetcher.fetch_510k(["k182419", "K182419", " "])
    assert k.stored == 1 and seen[-1].url.params["search"] == "k_number:(K182419)"
    recent = fetcher.fetch_510k_for_product("LLZ", limit=5)
    assert recent.stored == 1 and seen[-1].url.params["sort"] == "decision_date:desc"
    assert str(seen[-1].url).startswith(K510_ENDPOINT)
    fetcher.close()

    (row,) = db.list_external_sources(source_type="fda_recall")
    raw = json.loads(row.raw_json)
    assert "openfda" not in raw and "address_1" not in raw  # trimmed to keep the DB small
    assert row.source_id == "Z-0012-2022" and row.url == recall_url("189064")
    (k_row,) = db.list_external_sources(source_type="fda_510k")
    assert k_row.url == k510_url("K182419") and k_row.authors == "GE Healthcare"

    store = store_from_database(db)
    assert store.recalls[0].k_numbers == ("K182419",)
    assert store.clearance("K182419") is not None
    assert recall_url(None) is None


def test_fetch_510k_chunks_and_api_key(tmp_path: Path) -> None:
    db = Database(tmp_path / "s.db")
    seen: list[httpx.Request] = []
    fetcher = OpenFDASourceFetcher(
        db, api_key="test-key", client=httpx.Client(transport=_transport(seen))
    )
    fetcher.fetch_510k([f"K{i:06d}" for i in range(120)])
    assert len(seen) == 3  # 50 + 50 + 20
    assert all(r.url.params["api_key"] == "test-key" for r in seen)
    assert db.count_external_sources(source_type="fda_510k") == 1  # api_key never stored
    assert "test-key" not in db.list_external_sources(source_type="fda_510k")[0].raw_json


EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle><MedlineCitation><PMID>111</PMID><Article><Abstract>
  <AbstractText Label="BACKGROUND">AI <i>triage</i> tools
   miss some events.</AbstractText>
  <AbstractText Label="RESULTS">F1-score=85%.</AbstractText>
 </Abstract></Article></MedlineCitation></PubmedArticle>
 <PubmedArticle><MedlineCitation><PMID>222</PMID><Article>
  <Abstract><AbstractText>Plain abstract.</AbstractText></Abstract>
 </Article></MedlineCitation></PubmedArticle>
 <PubmedArticle><MedlineCitation><PMID>333</PMID><Article/></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_parse_abstracts_xml() -> None:
    out = parse_abstracts_xml(EFETCH_XML)
    assert out == {
        "111": "BACKGROUND: AI triage tools miss some events. RESULTS: F1-score=85%.",
        "222": "Plain abstract.",
    }


def _resp(payload: Any = None, text: str = "", status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def test_pubmed_fetch_with_abstracts(tmp_path: Path) -> None:
    db = Database(tmp_path / "p.db")
    fetcher = PubMedFetcher(db=db)
    summary_calls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params", {})
        if "esearch" in url:
            return _resp({"esearchresult": {"idlist": ["111", "222", "333"]}})
        if "efetch" in url:
            assert params["id"] == "111,222,333" and params["retmode"] == "xml"
            return _resp(text=EFETCH_XML)
        pmid = params["id"]
        summary_calls.append(pmid)
        if pmid == "222" and summary_calls.count("222") == 1:
            return _resp(status=429)  # rate-limited once, then retried
        return _resp({"result": {pmid: {"title": f"T{pmid}", "pubdate": "2024 Jan"}}})

    fetcher._client.get = fake_get  # type: ignore[method-assign,assignment]
    with patch("time.sleep"):
        arts = fetcher.fetch(query="q", product_code="QIH", with_abstracts=True)
    assert [a.pmid for a in arts] == ["111", "222"]  # 333 has no abstract → skipped
    assert "333" not in summary_calls and summary_calls.count("222") == 2
    store = store_from_database(db)
    art = store.article("111")
    assert art is not None and art.year == 2024 and "F1-score=85%" in art.abstract
    assert fetcher.fetch_abstracts([]) == {}


def test_pubmed_fetch_abstracts_error_is_empty(tmp_path: Path) -> None:
    fetcher = PubMedFetcher(db=Database(tmp_path / "p.db"), api_key="k")

    def boom(url: str, **kwargs: Any) -> MagicMock:
        raise httpx.ConnectError("down")

    fetcher._client.get = boom  # type: ignore[method-assign,assignment]
    assert fetcher.fetch_abstracts(["1"]) == {}
