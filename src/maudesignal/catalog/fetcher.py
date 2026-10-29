"""FDA AI/ML device catalog fetcher.

Discovers AI/ML-cleared medical devices by querying the openFDA 510k API
with a battery of AI/ML keyword searches, deduplicates by product_code,
and upserts results into the device_catalog table.

Usage:
    fetcher = CatalogFetcher(db, api_key="...")
    result = fetcher.update()
    print(result.devices_found, result.product_codes_new)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.storage.database import Database

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# AI/ML keyword search terms — cast wide, deduplicate by product_code
# ---------------------------------------------------------------------------

_AI_KEYWORDS: list[str] = [
    "artificial+intelligence",
    "machine+learning",
    "deep+learning",
    "neural+network",
    "computer-aided+detection",
    "computer-aided+diagnosis",
    "computer+aided+detection",
    "computer+aided+diagnosis",
    "automated+detection",
    "image+analysis+software",
    "convolutional",
    "algorithm+detection",
]

# Known AI/ML product codes, so coverage does not depend on keyword hits. Only
# the codes are listed: each code's name comes from the openFDA classification
# endpoint at fetch time, and a code whose lookup fails is skipped rather than
# given a made-up label.
_SEED_PRODUCT_CODES: list[str] = [
    "QIH",
    "LLZ",
    "QFM",
    "DQA",
    "MWI",
    "PIE",
    "IYO",
    "OZO",
    "KZH",
    "IOR",
    "QNO",
    "MYN",
    "QCS",
    "QCG",
    "GZA",
    "LLN",
    "QAS",
    "QFP",
    "POK",
]

_OPENFDA_510K_URL = "https://api.fda.gov/device/510k.json"
_OPENFDA_CLASSIFICATION_URL = "https://api.fda.gov/device/classification.json"
_PAGE_LIMIT = 100
_REQUEST_DELAY = 0.25  # seconds between requests — stay under rate limit


@dataclass
class CatalogUpdateResult:
    """Summary of a catalog update run."""

    devices_found: int = 0
    product_codes_new: int = 0
    product_codes_updated: int = 0
    keywords_searched: int = 0
    errors: list[str] = field(default_factory=list)


class CatalogFetcher:
    """Fetches FDA-cleared AI/ML device metadata from the openFDA 510k API."""

    def __init__(self, db: Database, api_key: str | None = None) -> None:
        """Initialize the fetcher."""
        self._db = db
        self._api_key = api_key

    def update(self) -> CatalogUpdateResult:
        """Run a full catalog update.

        Searches the openFDA 510k API with all AI/ML keywords, then upserts
        the seed list, deduplicating by product_code.

        Returns:
            CatalogUpdateResult with counts of devices found / inserted / updated.
        """
        result = CatalogUpdateResult()
        seen: dict[str, dict[str, Any]] = {}

        for keyword in _AI_KEYWORDS:
            result.keywords_searched += 1
            try:
                devices = self._search_keyword(keyword)
                for d in devices:
                    pc = d.get("product_code", "").strip().upper()
                    if pc and pc not in seen:
                        seen[pc] = {**d, "source_keyword": keyword.replace("+", " ")}
            except Exception as exc:
                msg = f"keyword={keyword!r}: {exc}"
                logger.warning("catalog_fetch_error", error=msg)
                result.errors.append(msg)
            time.sleep(_REQUEST_DELAY)

        # Merge seed list — only add, never overwrite live API data
        for pc in _SEED_PRODUCT_CODES:
            if pc in seen:
                continue
            try:
                classification = self._classification(pc)
            except Exception as exc:
                msg = f"classification={pc}: {exc}"
                logger.warning("catalog_fetch_error", error=msg)
                result.errors.append(msg)
                continue
            if classification is None:
                logger.warning("catalog_seed_code_unresolved", product_code=pc)
                continue
            seen[pc] = classification
            time.sleep(_REQUEST_DELAY)

        result.devices_found = len(seen)

        for pc, d in seen.items():
            is_new = self._db.upsert_catalog_device(
                product_code=pc,
                device_name=d.get("device_name") or "",
                company_name=d.get("company_name") or d.get("applicant"),
                specialty=d.get("specialty") or d.get("advisory_committee_description"),
                decision_date=d.get("decision_date"),
                k_number=d.get("k_number"),
                source_keyword=d.get("source_keyword"),
            )
            if is_new:
                result.product_codes_new += 1
            else:
                result.product_codes_updated += 1

        logger.info(
            "catalog_update_complete",
            devices_found=result.devices_found,
            new=result.product_codes_new,
            updated=result.product_codes_updated,
            errors=len(result.errors),
        )
        return result

    def _classification(self, product_code: str) -> dict[str, Any] | None:
        """Look up one product code's FDA classification name.

        Args:
            product_code: Three-letter FDA product code.

        Returns:
            A catalog row built from the openFDA classification record, or None
            when openFDA has no record for exactly this code.
        """
        params: dict[str, Any] = {"search": f'product_code:"{product_code}"', "limit": 1}
        if self._api_key:
            params["api_key"] = self._api_key
        resp = httpx.get(_OPENFDA_CLASSIFICATION_URL, params=params, timeout=15.0)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            name = (r.get("device_name") or "").strip()
            if (r.get("product_code") or "").strip().upper() == product_code and name:
                return {
                    "product_code": product_code,
                    "device_name": name,
                    "company_name": None,
                    "specialty": r.get("medical_specialty_description") or None,
                    "decision_date": None,
                    "k_number": None,
                    "source_keyword": "openfda_classification",
                }
        return None

    def _search_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """Query openFDA 510k for a single keyword, return raw result dicts."""
        params: dict[str, Any] = {
            "search": f'device_name:"{keyword}"',
            "limit": _PAGE_LIMIT,
        }
        if self._api_key:
            params["api_key"] = self._api_key

        resp = httpx.get(_OPENFDA_510K_URL, params=params, timeout=15.0)
        if resp.status_code == 404:
            return []  # no results for this keyword
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = data.get("results", [])

        devices: list[dict[str, Any]] = []
        for r in results:
            pc = r.get("product_code", "").strip().upper()
            if not pc:
                continue
            devices.append(
                {
                    "product_code": pc,
                    "device_name": r.get("device_name", ""),
                    "company_name": r.get("applicant", ""),
                    "specialty": r.get("advisory_committee_description", ""),
                    "decision_date": r.get("decision_date", ""),
                    "k_number": r.get("k_number", ""),
                }
            )
        logger.info(
            "catalog_keyword_searched",
            keyword=keyword,
            results=len(results),
            unique_codes=len({d["product_code"] for d in devices}),
        )
        return devices
