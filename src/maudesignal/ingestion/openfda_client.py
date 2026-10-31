"""HTTP client for the openFDA Device Event API.

Implements FR-01 (product-code ingestion), FR-02 (date range filtering),
FR-03 (pagination), and FR-04 (retry with backoff).

Caching (FR-05) is handled at the database layer — this client is stateless.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from maudesignal.common.exceptions import (
    OpenFDAAPIError,
    OpenFDAForbiddenError,
    OpenFDARateLimitError,
    OpenFDAUnavailableError,
)
from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

OPENFDA_EVENT_ENDPOINT = "https://api.fda.gov/device/event.json"
DEFAULT_PAGE_SIZE = 100  # openFDA max per page
MAX_RETRIES = 3
#: Sent with every request so openFDA can identify the tool (added during the hackathon).
USER_AGENT = "MaudeSignal (open-source; github.com/kondapallysaicharan63-bot/maudesignal)"


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
        self._client = httpx.Client(timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})

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

    # HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OpenFDARateLimitError, OpenFDAUnavailableError)),
        reraise=True,
    )
    def count_by_date_received(
        self,
        product_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[tuple[str, int]]:
        """Return per-day report counts (openFDA ``count=date_received``).

        One request, no records downloaded. Lets callers fetch whole days
        only, so a capped incremental fetch never leaves a partial day behind.

        Args:
            product_code: FDA 3-character product code.
            start_date: Earliest ``date_received`` (YYYYMMDD). Optional.
            end_date: Latest ``date_received`` (YYYYMMDD). Optional.

        Returns:
            ``(YYYYMMDD, count)`` pairs sorted by date; empty when none match.
        """
        params: dict[str, str | int] = {
            "search": search_param(_build_query(product_code, start_date, end_date)),
            "count": "date_received",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            response = self._client.get(OPENFDA_EVENT_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise OpenFDAAPIError(f"HTTP error contacting openFDA: {exc}") from exc
        if response.status_code == 404:
            return []
        if response.status_code == 429:
            raise OpenFDARateLimitError("openFDA returned 429")
        if response.status_code in (500, 503):
            raise OpenFDAUnavailableError(f"openFDA server error {response.status_code}")
        if response.status_code != 200:
            raise OpenFDAAPIError(f"Unexpected openFDA status {response.status_code}")
        rows = response.json().get("results", [])
        return sorted((str(r["time"]), int(r["count"])) for r in rows)

    # HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OpenFDARateLimitError, OpenFDAUnavailableError)),
        reraise=True,
    )
    def count_field(
        self,
        product_code: str,
        field: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 1000,
    ) -> list[tuple[str, int]]:
        """Return openFDA ``count=<field>`` buckets for a product code (no records downloaded).

        Args:
            product_code: FDA 3-character product code.
            field: Field to count, e.g. ``"event_type.exact"`` or ``"date_received"``.
            start_date: Earliest ``date_received`` (YYYYMMDD). Optional.
            end_date: Latest ``date_received`` (YYYYMMDD). Optional.
            limit: Maximum buckets (openFDA allows up to 1000).

        Returns:
            ``(term, count)`` pairs sorted by term; empty when nothing matches.
        """
        params: dict[str, str | int] = {
            "search": search_param(_build_query(product_code, start_date, end_date)),
            "count": field,
            "limit": min(limit, 1000),
        }
        payload = self._get(params)
        rows = payload.get("results", []) if payload else []
        return sorted((str(r.get("term", r.get("time"))), int(r["count"])) for r in rows)

    # HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OpenFDARateLimitError, OpenFDAUnavailableError)),
        reraise=True,
    )
    def total(
        self,
        product_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Return how many reports match (openFDA ``meta.results.total``; one record fetched).

        Args:
            product_code: FDA 3-character product code.
            start_date: Earliest ``date_received`` (YYYYMMDD). Optional.
            end_date: Latest ``date_received`` (YYYYMMDD). Optional.

        Returns:
            The match count; 0 when nothing matches.
        """
        params: dict[str, str | int] = {
            "search": search_param(_build_query(product_code, start_date, end_date)),
            "limit": 1,
        }
        payload = self._get(params)
        if not payload:
            return 0
        return int(payload.get("meta", {}).get("results", {}).get("total", 0))

    def _get(self, params: dict[str, str | int]) -> dict[str, Any] | None:
        """One GET with the shared status handling; None means openFDA found nothing (404)."""
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            response = self._client.get(OPENFDA_EVENT_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise OpenFDAAPIError(f"HTTP error contacting openFDA: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise OpenFDARateLimitError("openFDA returned 429")
        if response.status_code in (500, 503):
            raise OpenFDAUnavailableError(f"openFDA server error {response.status_code}")
        if response.status_code == 403:
            raise OpenFDAForbiddenError(f"openFDA refused the request (403): {response.text[:200]}")
        if response.status_code != 200:
            raise OpenFDAAPIError(
                f"Unexpected openFDA status {response.status_code}: {response.text[:200]}"
            )
        payload: dict[str, Any] = response.json()
        return payload

    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((OpenFDARateLimitError, OpenFDAUnavailableError)),
        reraise=True,
    )
    def _fetch_page(
        self,
        query: str,
        skip: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch a single page from openFDA. Retries on rate limit or 5xx."""
        params: dict[str, str | int] = {
            "search": search_param(query),
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

        if response.status_code in (500, 503):
            logger.warning("openfda_server_error", status=response.status_code, skip=skip)
            raise OpenFDAUnavailableError(f"openFDA server error {response.status_code}")

        if response.status_code >= 500:
            raise OpenFDAAPIError(f"openFDA server error {response.status_code}")

        if response.status_code != 200:
            raise OpenFDAAPIError(
                f"Unexpected openFDA status {response.status_code}: " f"{response.text[:200]}"
            )

        payload = response.json()
        results: list[dict[str, Any]] = payload.get("results", [])
        return results


def search_param(query: str) -> str:
    """Convert an openFDA query written with URL ``+`` separators to a param value.

    openFDA documents queries as they appear in a URL, where ``+`` means a
    space. httpx percent-encodes a literal ``+`` as ``%2B``, which openFDA
    rejects with HTTP 500 for ``+AND+`` / ``[a+TO+b]`` queries, so the
    separators are sent as spaces (httpx then encodes them as ``+``).
    Fix added during the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

    Args:
        query: Query in openFDA URL syntax, e.g. from :func:`_build_query`.

    Returns:
        The same query with ``+`` replaced by spaces.
    """
    return query.replace("+", " ")


def _build_query(
    product_code: str,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """Build the openFDA ``search`` parameter for product + date range (URL ``+`` syntax)."""
    clauses = [f"device.device_report_product_code:{product_code}"]
    if start_date and end_date:
        clauses.append(f"date_received:[{start_date}+TO+{end_date}]")
    elif start_date:
        clauses.append(f"date_received:[{start_date}+TO+99991231]")
    elif end_date:
        clauses.append(f"date_received:[19900101+TO+{end_date}]")
    return "+AND+".join(clauses)


#: Public name for the query builder (used by ``monitor.live_check`` to show verify links).
build_query = _build_query
