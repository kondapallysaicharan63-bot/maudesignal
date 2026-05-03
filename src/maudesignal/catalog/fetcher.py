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

# Known AI/ML product codes seeded from FDA's published list — ensures
# coverage even when keyword search misses devices by brand/trade name.
_SEED_PRODUCT_CODES: list[dict[str, str]] = [
    {
        "product_code": "QIH",
        "device_name": "Radiology Computer-Aided Detection Software",
        "specialty": "Radiology",
    },
    {
        "product_code": "LLZ",
        "device_name": "Surgical Robotics Imaging AI",
        "specialty": "General Hospital",
    },
    {
        "product_code": "QFM",
        "device_name": "Breast Density Assessment AI",
        "specialty": "Radiology",
    },
    {"product_code": "DQA", "device_name": "Digital Pathology AI", "specialty": "Pathology"},
    {
        "product_code": "MWI",
        "device_name": "Wound Care Imaging AI",
        "specialty": "General Hospital",
    },
    {
        "product_code": "PIE",
        "device_name": "AI-Assisted Endoscopy",
        "specialty": "Gastroenterology",
    },
    {
        "product_code": "IYO",
        "device_name": "Ophthalmology AI Imaging",
        "specialty": "Ophthalmology",
    },
    {"product_code": "OZO", "device_name": "Cardiac Monitoring AI", "specialty": "Cardiovascular"},
    {
        "product_code": "KZH",
        "device_name": "Radiology AI — General Imaging",
        "specialty": "Radiology",
    },
    {"product_code": "IOR", "device_name": "Diagnostic Imaging AI", "specialty": "Radiology"},
    {"product_code": "QNO", "device_name": "Bone Density AI", "specialty": "Orthopedic"},
    {"product_code": "MYN", "device_name": "Ophthalmic Disease AI", "specialty": "Ophthalmology"},
    {"product_code": "QCS", "device_name": "Cardiovascular Risk AI", "specialty": "Cardiovascular"},
    {"product_code": "QCG", "device_name": "ECG Analysis AI", "specialty": "Cardiovascular"},
    {
        "product_code": "GZA",
        "device_name": "Clinical Decision Support AI",
        "specialty": "General Hospital",
    },
    {"product_code": "LLN", "device_name": "Neurology Imaging AI", "specialty": "Neurology"},
    {"product_code": "QAS", "device_name": "AI-Assisted Skin Analysis", "specialty": "Dermatology"},
    {"product_code": "QFP", "device_name": "Dental Radiograph AI", "specialty": "Dental"},
]

_OPENFDA_510K_URL = "https://api.fda.gov/device/510k.json"
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
        for seed in _SEED_PRODUCT_CODES:
            pc = seed["product_code"]
            if pc not in seen:
                seen[pc] = {
                    "product_code": pc,
                    "device_name": seed["device_name"],
                    "company_name": None,
                    "specialty": seed.get("specialty"),
                    "decision_date": None,
                    "k_number": None,
                    "source_keyword": "seed_list",
                }

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
