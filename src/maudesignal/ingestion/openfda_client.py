"""HTTP client for the openFDA Device Event API.

Implements FR-01 (product-code ingestion), FR-02 (date range filtering),
FR-03 (pagination), and FR-04 (retry with backoff).

Caching (FR-05) is handled at the database layer — this client is stateless.
"""

from __future__ import annotations

from typing import Any, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from maudesignal.common.exceptions import (
    OpenFDAAPIError,
    OpenFDARateLimitError,
)
from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

OPENFDA_EVENT_ENDPOINT = "https://api.fda.gov/device/event.json"
DEFAULT_PAGE_SIZE = 100  # openFDA max per page
MAX_RETRIES = 3


class OpenFDAClient:
    """Thin wrapper around the openFDA Device Event API."""

    def __init__(
        self,
        api_key: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Create a client.

        Args:
            api_key: Optional openFDA API key for higher rate limits.
            page_size: Records per page (max 100 per openFDA docs).
            timeout_seconds: HTTP request timeout.
        """
        self._api_key = api_key
        self._page_size = min(page_size, 100)
        self._client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> OpenFDAClient:
        """Context-manager support."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close client on context exit."""
        self.close()

    # ------------------------------------------------------------------

    def iter_reports(
        self,
        product_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield MAUDE reports matching the given filters.

        Args:
            product_code: FDA 3-character product code (e.g., "QIH").
            start_date: Earliest ``date_received`` (YYYYMMDD). Optional.
            end_date: Latest ``date_received`` (YYYYMMDD). Optional.
            limit: Maximum number of records to yield. None = all.

        Yields:
            One report dict per record, in openFDA's native schema.
        """
        query = _build_query(product_code, start_date, end_date)
        yielded = 0
        skip = 0

        while True:
            if limit is not None and yielded >= limit:
                return

            page_size = self._page_size
            if limit is not None:
                remaining = limit - yielded
                page_size = min(page_size, remaining)

            results = self._fetch_page(query=query, skip=skip, limit=page_size)
            if not results:
                return

            for record in results:
                yield record
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

            if len(results) < page_size:
                # We've seen the last page.
                return
            skip += page_size

    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(OpenFDARateLimitError),
        reraise=True,
    )
    def _fetch_page(
        self,
        query: str,
        skip: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch a single page from openFDA. Retries on rate limit."""
        params: dict[str, str | int] = {
            "search": query,
            "limit": limit,
            "skip": skip,
        }
        if self._api_key:
            params["api_key"] = self._api_key

        logger.debug(
            "openfda_fetch",
            endpoint=OPENFDA_EVENT_ENDPOINT,
            skip=skip,
            limit=limit,
            has_api_key=self._api_key is not None,
        )

        try:
            response = self._client.get(OPENFDA_EVENT_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise OpenFDAAPIError(f"HTTP error contacting openFDA: {exc}") from exc

        # 404 from openFDA means "no results", not an error
        if response.status_code == 404:
            logger.info("openfda_no_results", skip=skip)
            return []

        if response.status_code == 429:
            logger.warning("openfda_rate_limit", skip=skip)
            raise OpenFDARateLimitError("openFDA returned 429")

        if response.status_code >= 500:
            raise OpenFDAAPIError(
                f"openFDA server error {response.status_code}"
            )

        if response.status_code != 200:
            raise OpenFDAAPIError(
                f"Unexpected openFDA status {response.status_code}: "
                f"{response.text[:200]}"
            )

        payload = response.json()
        results: list[dict[str, Any]] = payload.get("results", [])
        return results


def _build_query(
    product_code: str,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """Build the openFDA ``search`` parameter for product + date range."""
    clauses = [f"device.device_report_product_code:{product_code}"]
    if start_date and end_date:
        clauses.append(f"date_received:[{start_date}+TO+{end_date}]")
    elif start_date:
        clauses.append(f"date_received:[{start_date}+TO+99991231]")
    elif end_date:
        clauses.append(f"date_received:[19900101+TO+{end_date}]")
    return "+AND+".join(clauses)
