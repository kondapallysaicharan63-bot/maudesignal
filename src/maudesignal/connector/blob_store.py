"""Private record storage for feedback and visits (Vercel Blob REST API, or memory locally).

Records are JSON objects written to a PRIVATE Vercel Blob store at
``feedback/<YYYY-MM-DD>/<id>.json`` and ``visits/<YYYY-MM-DD>/<id>.json``. No route serves
them except the key-protected admin export. Without ``BLOB_READ_WRITE_TOKEN`` (local runs)
an in-memory store is used and ``/v1/health`` says so.

The HTTP layer sits behind the :class:`RecordStore` interface; tests use a fake or an
``httpx.MockTransport``. The token is sent only in the ``Authorization`` header and is never
logged.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

TOKEN_ENV = "BLOB_READ_WRITE_TOKEN"  # noqa: S105 - env var name, not a secret
BLOB_API_URL = "https://blob.vercel-storage.com"
BLOB_API_VERSION = "7"
TIMEOUT_SECONDS = 8.0
LIST_PAGE = 1000
MAX_LIST_PAGES = 20  # at most 20,000 records per kind are read by one export


class StoreError(Exception):
    """The record store failed; the message holds no token and no record text."""


class ObjectGoneError(StoreError):
    """The object was not found (it was deleted, or never existed)."""


@dataclass(frozen=True)
class BlobRef:
    """One stored object: its pathname and where to fetch it."""

    pathname: str
    url: str


class RecordStore(Protocol):
    """What the feedback routes need from storage."""

    backend: str

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        """Write one JSON record (pathnames carry a uuid, so nothing is overwritten).

        ``overwrite=True`` replaces an existing object at the same pathname (the spend ledger
        and the name-redaction step use it; feedback and visits never do).
        """

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        """Replace the record stored at an existing ``pathname`` (same path, new content)."""

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        """Every stored object whose pathname starts with ``prefix``."""

    def get(self, ref: BlobRef) -> bytes:
        """The bytes of one stored object."""

    def delete(self, ref: BlobRef) -> None:
        """Remove one stored object."""


class MemoryStore:
    """In-process store for local runs and tests."""

    backend = "memory"

    def __init__(self) -> None:
        """Create an empty store."""
        self._items: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        """Store a record."""
        data = json.dumps(record, sort_keys=True).encode("utf-8")
        with self._lock:
            self._items[pathname] = data

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        """Replace a record at the same pathname."""
        self.put_json(pathname, record)

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        """Objects under ``prefix``."""
        with self._lock:
            return [BlobRef(p, p) for p in sorted(self._items) if p.startswith(prefix)]

    def get(self, ref: BlobRef) -> bytes:
        """Bytes of one object."""
        with self._lock:
            try:
                return self._items[ref.pathname]
            except KeyError:
                raise ObjectGoneError("object not found") from None

    def delete(self, ref: BlobRef) -> None:
        """Remove one object (absent is not an error)."""
        with self._lock:
            self._items.pop(ref.pathname, None)


class VercelBlobStore:
    """Vercel Blob REST client (private store) over ``httpx``."""

    backend = "blob_private"

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = BLOB_API_URL,
    ) -> None:
        """Create a client.

        Args:
            token: The read/write token (sent only as a bearer header).
            client: An ``httpx.Client`` (tests pass one on a mock transport).
            base_url: Blob API origin.
        """
        self._token = token
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._base = base_url.rstrip("/")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "x-api-version": BLOB_API_VERSION}

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        """PUT one private JSON object, no random suffix (the pathname already has a uuid)."""
        self._put(pathname, record, overwrite=overwrite)

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        """PUT over an existing private object at the same pathname (``x-allow-overwrite``)."""
        self._put(pathname, record, overwrite=True)

    def _put(self, pathname: str, record: dict[str, Any], *, overwrite: bool) -> None:
        body = json.dumps(record, sort_keys=True).encode("utf-8")
        headers = self._auth() | {
            "x-vercel-blob-access": "private",
            "x-add-random-suffix": "0",
            "x-content-type": "application/json",
            "content-type": "application/json",
        }
        if overwrite:
            headers["x-allow-overwrite"] = "1"
        try:
            r = self._client.put(f"{self._base}/{pathname}", content=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("blob_put_failed", error_type=type(exc).__name__)
            raise StoreError("blob store unreachable") from None
        if r.status_code >= 300:
            logger.error("blob_put_failed", status=r.status_code)
            raise StoreError(f"blob store answered {r.status_code}")

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        """List objects under ``prefix`` (follows the cursor)."""
        refs: list[BlobRef] = []
        cursor: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params = {"prefix": prefix, "limit": str(LIST_PAGE)}
            if cursor:
                params["cursor"] = cursor
            try:
                r = self._client.get(f"{self._base}/", params=params, headers=self._auth())
            except httpx.HTTPError as exc:
                logger.error("blob_list_failed", error_type=type(exc).__name__)
                raise StoreError("blob store unreachable") from None
            if r.status_code != 200:
                logger.error("blob_list_failed", status=r.status_code)
                raise StoreError(f"blob store answered {r.status_code}")
            payload = r.json()
            for b in payload.get("blobs", []):
                refs.append(BlobRef(str(b["pathname"]), str(b.get("downloadUrl") or b["url"])))
            cursor = payload.get("cursor")
            if not payload.get("hasMore") or not cursor:
                return refs
        if strict:  # the listing is cut off: a sum over it would be wrong, so fail closed
            raise StoreError("blob listing is longer than the page limit")
        return refs

    def get(self, ref: BlobRef) -> bytes:
        """Fetch one private object with the token."""
        try:
            r = self._client.get(ref.url, headers=self._auth())
        except httpx.HTTPError as exc:
            logger.error("blob_get_failed", error_type=type(exc).__name__)
            raise StoreError("blob store unreachable") from None
        if r.status_code == 404:
            raise ObjectGoneError("object not found")
        if r.status_code != 200:
            logger.error("blob_get_failed", status=r.status_code)
            raise StoreError(f"blob store answered {r.status_code}")
        return r.content

    def delete(self, ref: BlobRef) -> None:
        """Delete one object (``POST {base}/delete`` with its url)."""
        try:
            r = self._client.post(
                f"{self._base}/delete", json={"urls": [ref.url]}, headers=self._auth()
            )
        except httpx.HTTPError as exc:
            logger.error("blob_delete_failed", error_type=type(exc).__name__)
            raise StoreError("blob store unreachable") from None
        if r.status_code >= 300:
            logger.error("blob_delete_failed", status=r.status_code)
            raise StoreError(f"blob store answered {r.status_code}")


def store_from_env(env: dict[str, str] | None = None) -> RecordStore:
    """Blob store when ``BLOB_READ_WRITE_TOKEN`` is set, else the in-memory fallback."""
    token = (os.environ if env is None else env).get(TOKEN_ENV, "").strip()
    if token:
        return VercelBlobStore(token)
    logger.warning("feedback_store_memory", reason="BLOB_READ_WRITE_TOKEN unset")
    return MemoryStore()
