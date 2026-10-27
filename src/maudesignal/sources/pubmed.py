"""PubMed fetcher using NCBI E-utilities (Phase 4).

Uses the free NCBI E-utilities API — no API key required for low-volume usage
(≤3 requests/second). Higher rate limits are available with an NCBI API key
via the NCBI_API_KEY env var.

API docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET  # noqa: N817 - stdlib idiom; parses NCBI's own XML
from dataclasses import dataclass, replace
from typing import Any

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.storage.database import Database

logger = get_logger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_DEFAULT_MAX_RESULTS = 20
_REQUEST_DELAY_S = 0.34  # ~3 req/s limit for unauthenticated
_RETRY_AFTER_429_S = 2.0


@dataclass(frozen=True)
class PubMedArticle:
    """Parsed PubMed article summary."""

    pmid: str
    title: str
    authors: str
    publication_date: str
    abstract: str
    url: str
    raw: dict[str, Any]


class PubMedFetcher:
    """Fetch PubMed articles related to a search query or product code."""

    def __init__(self, *, db: Database, api_key: str | None = None) -> None:
        """Initialize with a Database instance and optional NCBI API key."""
        self._db = db
        self._api_key = api_key
        self._client = httpx.Client(timeout=30.0)

    def fetch(
        self,
        *,
        query: str,
        product_code: str | None = None,
        max_results: int = _DEFAULT_MAX_RESULTS,
        with_abstracts: bool = False,
    ) -> list[PubMedArticle]:
        """Search PubMed and store results; return fetched articles.

        Args:
            query: PubMed search query (e.g. "AI radiology adverse event").
            product_code: Optional product code to tag stored records.
            max_results: Maximum number of articles to fetch.
            with_abstracts: Also fetch the real abstract text (one batched
                EFetch call) instead of storing only "Source: <journal>".
                Articles without an abstract are then skipped. Added during the
                Meta Global AI Developer Hackathon (Oct 2026) so the copilot can
                quote abstracts and the gate can verify the quotes.
        """
        pmids = self._esearch(query=query, max_results=max_results)
        if not pmids:
            logger.info("pubmed_no_results", query=query)
            return []

        abstracts: dict[str, str] = {}
        if with_abstracts:
            time.sleep(_REQUEST_DELAY_S)
            abstracts = self.fetch_abstracts(pmids)

        articles: list[PubMedArticle] = []
        for pmid in pmids:
            if with_abstracts and not abstracts.get(pmid):
                continue
            time.sleep(_REQUEST_DELAY_S)
            article = self._efetch_summary(pmid)
            if article is None:
                continue
            if with_abstracts:
                article = replace(article, abstract=abstracts[pmid])
            record_id = _record_id("pubmed", pmid)
            self._db.upsert_external_source(
                record_id=record_id,
                source_type="pubmed",
                source_id=pmid,
                product_code=product_code,
                title=article.title,
                authors=article.authors,
                publication_date=article.publication_date,
                abstract=article.abstract,
                url=article.url,
                raw_payload=article.raw,
            )
            articles.append(article)

        logger.info(
            "pubmed_fetch_complete",
            query=query,
            fetched=len(articles),
            product_code=product_code,
        )
        return articles

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def fetch_abstracts(self, pmids: list[str]) -> dict[str, str]:
        """Return ``{pmid: abstract text}`` via one EFetch XML call (empty on error)."""
        if not pmids:
            return {}
        params: dict[str, str] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            resp = self._client.get(_EFETCH_URL, params=params)
            resp.raise_for_status()
            return parse_abstracts_xml(resp.text)
        except Exception as exc:
            logger.error("pubmed_efetch_abstracts_failed", error=str(exc))
            return {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _esearch(self, *, query: str, max_results: int) -> list[str]:
        """Run ESearch and return a list of PMIDs."""
        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            resp = self._client.get(_ESEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            id_list: list[str] = data.get("esearchresult", {}).get("idlist", [])
            return id_list
        except Exception as exc:
            logger.error("pubmed_esearch_failed", query=query, error=str(exc))
            return []

    def _efetch_summary(self, pmid: str) -> PubMedArticle | None:
        """Fetch article summary for a single PMID."""
        params: dict[str, str] = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            resp = self._client.get(_ESUMMARY_URL, params=params)
            if resp.status_code == 429:  # keyless NCBI rate limit: back off once
                time.sleep(_RETRY_AFTER_429_S)
                resp = self._client.get(_ESUMMARY_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            article_data = result.get(pmid, {})
            if not article_data:
                return None

            title = article_data.get("title", "")
            authors_list = [a.get("name", "") for a in article_data.get("authors", [])]
            authors = "; ".join(authors_list[:5])
            if len(authors_list) > 5:
                authors += " et al."

            pub_date = article_data.get("pubdate", "")
            source = article_data.get("source", "")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            return PubMedArticle(
                pmid=pmid,
                title=title,
                authors=authors,
                publication_date=pub_date,
                abstract=f"Source: {source}",
                url=url,
                raw=article_data,
            )
        except Exception as exc:
            logger.error("pubmed_efetch_failed", pmid=pmid, error=str(exc))
            return None


def parse_abstracts_xml(xml_text: str) -> dict[str, str]:
    """Parse PubMed EFetch XML into ``{pmid: abstract}``.

    Structured abstracts keep their section labels (``"METHODS: ..."``).
    """
    out: dict[str, str] = {}
    root = ET.fromstring(xml_text)
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find("MedlineCitation/PMID")
        pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""
        if not pmid:
            continue
        parts: list[str] = []
        for el in art.findall("MedlineCitation/Article/Abstract/AbstractText"):
            text = " ".join("".join(el.itertext()).split())
            if not text:
                continue
            label = el.get("Label")
            parts.append(f"{label}: {text}" if label else text)
        if parts:
            out[pmid] = " ".join(parts)
    return out


def _record_id(source_type: str, source_id: str) -> str:
    """Generate a stable record ID for a source record."""
    digest = hashlib.sha256(f"{source_type}:{source_id}".encode()).hexdigest()[:16]
    return f"{source_type}-{digest}"
