"""Unit tests for Phase 4: external source integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from maudesignal.sources.clinicaltrials import ClinicalTrialsFetcher, _parse_study
from maudesignal.sources.pubmed import PubMedFetcher, _record_id
from maudesignal.storage.database import Database

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _in_memory_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _mock_esearch_response(pmids: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"esearchresult": {"idlist": pmids}}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_esummary_response(pmid: str) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "result": {
            pmid: {
                "title": f"AI adverse event study {pmid}",
                "authors": [{"name": "Smith J"}, {"name": "Jones K"}],
                "pubdate": "2025 Jan",
                "source": "JAMA",
            }
        }
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_ct_response(nct_ids: list[str]) -> MagicMock:
    studies = []
    for nct_id in nct_ids:
        studies.append(
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": nct_id,
                        "briefTitle": f"AI device trial {nct_id}",
                    },
                    "statusModule": {
                        "overallStatus": "RECRUITING",
                        "startDateStruct": {"date": "2024-06"},
                    },
                    "designModule": {"phases": ["PHASE2"]},
                    "conditionsModule": {"conditions": ["AI-related device failure"]},
                    "armsInterventionsModule": {
                        "interventions": [{"name": "AI-assisted diagnosis"}]
                    },
                }
            }
        )
    resp = MagicMock()
    resp.json.return_value = {"studies": studies}
    resp.raise_for_status = MagicMock()
    return resp


# ──────────────────────────────────────────────────────────────────────────────
# _record_id
# ──────────────────────────────────────────────────────────────────────────────


class TestRecordId:
    def test_stable_for_same_inputs(self) -> None:
        a = _record_id("pubmed", "12345678")
        b = _record_id("pubmed", "12345678")
        assert a == b

    def test_different_for_different_source_ids(self) -> None:
        a = _record_id("pubmed", "12345678")
        b = _record_id("pubmed", "99999999")
        assert a != b

    def test_different_for_different_source_types(self) -> None:
        a = _record_id("pubmed", "12345678")
        b = _record_id("clinicaltrials", "12345678")
        assert a != b

    def test_prefix_matches_source_type(self) -> None:
        rid = _record_id("pubmed", "12345")
        assert rid.startswith("pubmed-")


# ──────────────────────────────────────────────────────────────────────────────
# PubMedFetcher
# ──────────────────────────────────────────────────────────────────────────────


class TestPubMedFetcher:
    def test_fetch_stores_articles(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = PubMedFetcher(db=db)

        call_count = 0

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if "esearch" in url:
                return _mock_esearch_response(["11111111", "22222222"])
            return _mock_esummary_response(kwargs.get("params", {}).get("id", "11111111"))

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        with patch("time.sleep"):
            articles = fetcher.fetch(query="AI adverse event", product_code="QIH")

        assert len(articles) == 2
        stored = db.list_external_sources(source_type="pubmed")
        assert len(stored) == 2
        assert all(s.product_code == "QIH" for s in stored)

    def test_empty_search_returns_no_articles(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = PubMedFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            return _mock_esearch_response([])

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        articles = fetcher.fetch(query="nonexistent query xyz")
        assert articles == []
        assert db.list_external_sources(source_type="pubmed") == []

    def test_fetch_is_idempotent(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = PubMedFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            if "esearch" in url:
                return _mock_esearch_response(["11111111"])
            return _mock_esummary_response("11111111")

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        with patch("time.sleep"):
            fetcher.fetch(query="test")
        with patch("time.sleep"):
            fetcher.fetch(query="test")

        stored = db.list_external_sources(source_type="pubmed")
        assert len(stored) == 1  # idempotent upsert

    def test_api_error_returns_empty(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = PubMedFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            raise httpx.RequestError("connection refused")

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        articles = fetcher.fetch(query="test query")
        assert articles == []

    def test_no_product_code_stores_none(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = PubMedFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            if "esearch" in url:
                return _mock_esearch_response(["33333333"])
            return _mock_esummary_response("33333333")

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        with patch("time.sleep"):
            fetcher.fetch(query="test")

        stored = db.list_external_sources(source_type="pubmed")
        assert stored[0].product_code is None


# ──────────────────────────────────────────────────────────────────────────────
# _parse_study
# ──────────────────────────────────────────────────────────────────────────────


class TestParseStudy:
    def test_parses_valid_study(self) -> None:
        study = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000001",
                    "briefTitle": "AI Device Safety Study",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2024-01"},
                },
                "designModule": {"phases": ["PHASE3"]},
                "conditionsModule": {"conditions": ["Radiology"]},
                "armsInterventionsModule": {"interventions": [{"name": "AI CAD system"}]},
            }
        }
        trial = _parse_study(study)
        assert trial is not None
        assert trial.nct_id == "NCT00000001"
        assert trial.title == "AI Device Safety Study"
        assert trial.status == "RECRUITING"
        assert trial.phase == "PHASE3"
        assert "Radiology" in trial.conditions
        assert trial.url == "https://clinicaltrials.gov/study/NCT00000001"

    def test_returns_none_for_missing_nct_id(self) -> None:
        study = {"protocolSection": {"identificationModule": {}}}
        assert _parse_study(study) is None

    def test_handles_missing_optional_fields(self) -> None:
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT99999999", "briefTitle": "Test"}
            }
        }
        trial = _parse_study(study)
        assert trial is not None
        assert trial.nct_id == "NCT99999999"
        assert trial.status == ""
        assert trial.phase == "N/A"


# ──────────────────────────────────────────────────────────────────────────────
# ClinicalTrialsFetcher
# ──────────────────────────────────────────────────────────────────────────────


class TestClinicalTrialsFetcher:
    def test_fetch_stores_trials(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = ClinicalTrialsFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            return _mock_ct_response(["NCT00000001", "NCT00000002"])

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        trials = fetcher.fetch(query="AI radiology", product_code="QIH")
        assert len(trials) == 2
        stored = db.list_external_sources(source_type="clinicaltrials")
        assert len(stored) == 2
        assert all(s.product_code == "QIH" for s in stored)

    def test_fetch_is_idempotent(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = ClinicalTrialsFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            return _mock_ct_response(["NCT00000001"])

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        fetcher.fetch(query="test")
        fetcher.fetch(query="test")

        stored = db.list_external_sources(source_type="clinicaltrials")
        assert len(stored) == 1

    def test_api_error_returns_empty(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        fetcher = ClinicalTrialsFetcher(db=db)

        def _fake_get(url: str, **kwargs: object) -> MagicMock:
            raise httpx.RequestError("timeout")

        fetcher._client.get = _fake_get  # type: ignore[method-assign]

        trials = fetcher.fetch(query="test")
        assert trials == []


# ──────────────────────────────────────────────────────────────────────────────
# DB: ExternalSourceRecord
# ──────────────────────────────────────────────────────────────────────────────


class TestExternalSourceDB:
    def test_upsert_and_list(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        db.upsert_external_source(
            record_id="pubmed-abc123",
            source_type="pubmed",
            source_id="12345678",
            product_code="QIH",
            title="AI safety study",
            authors="Smith J; Jones K",
            publication_date="2025 Jan",
            abstract="This study examines AI adverse events.",
            url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
            raw_payload={"pmid": "12345678"},
        )
        records = db.list_external_sources()
        assert len(records) == 1
        r = records[0]
        assert r.source_id == "12345678"
        assert r.product_code == "QIH"

    def test_upsert_overwrites_existing(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for title in ["Old Title", "New Title"]:
            db.upsert_external_source(
                record_id="pubmed-abc123",
                source_type="pubmed",
                source_id="12345678",
                product_code="QIH",
                title=title,
                authors=None,
                publication_date=None,
                abstract=None,
                url=None,
                raw_payload={},
            )
        records = db.list_external_sources()
        assert len(records) == 1
        assert records[0].title == "New Title"

    def test_filter_by_source_type(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for st, sid in [("pubmed", "pm1"), ("clinicaltrials", "ct1")]:
            db.upsert_external_source(
                record_id=f"{st}-{sid}",
                source_type=st,
                source_id=sid,
                product_code=None,
                title=None,
                authors=None,
                publication_date=None,
                abstract=None,
                url=None,
                raw_payload={},
            )
        pm = db.list_external_sources(source_type="pubmed")
        assert len(pm) == 1
        assert pm[0].source_type == "pubmed"

    def test_count_external_sources(self, tmp_path: Path) -> None:
        db = _in_memory_db(tmp_path)
        for i in range(3):
            db.upsert_external_source(
                record_id=f"pubmed-r{i}",
                source_type="pubmed",
                source_id=f"pmid{i}",
                product_code=None,
                title=None,
                authors=None,
                publication_date=None,
                abstract=None,
                url=None,
                raw_payload={},
            )
        assert db.count_external_sources() == 3
        assert db.count_external_sources(source_type="pubmed") == 3
        assert db.count_external_sources(source_type="clinicaltrials") == 0
