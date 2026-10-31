"""Tier 3 of the chat: the same question within six hours reuses the earlier live answer.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

* Only live, gate-checked Muse Spark answers are kept (canned, direct and recorded answers
  already cost nothing). A hit costs $0 and does not use the visitor's daily live limit.
* The key is a SHA-256 of the normalised question (``tiers.normalise``) and the chosen product
  code, so "What changed for LLZ?" and "what changed for llz" share one entry. The question
  text itself is never stored; the value is the answer as it was shown, plus the time it was
  made.
* Storage is the connector's existing cache (Upstash Redis when configured, this instance's
  memory otherwise; the same store the public check uses). Entries expire after six hours,
  and an entry older than that is ignored even if the store kept it.
* Fail-safe: any error reading, parsing or writing the cache is a miss, never a failure of the
  request.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector.store import ConnectorState
from maudesignal.connector.tiers import normalise

logger = get_logger(__name__)

TTL = timedelta(hours=6)
TTL_SECONDS = int(TTL.total_seconds())
VERSION = "v1"


def cache_key(namespace: str, question: str, product_code: str | None = None) -> str:
    """Store key for a question: a hash of its normalised text and the product code."""
    basis = f"{normalise(question)}|{(product_code or '').upper()}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
    return f"chat-{VERSION}-{namespace}-{digest}"


@dataclass(frozen=True)
class CachedAnswer:
    """An answer read back from the cache."""

    body: dict[str, Any]
    stored_at: datetime

    @property
    def stored_at_iso(self) -> str:
        """UTC time the answer was made, as ``YYYY-MM-DDTHH:MM:SSZ``."""
        return self.stored_at.strftime("%Y-%m-%dT%H:%M:%SZ")


class AnswerCache:
    """Six-hour answer cache over :class:`ConnectorState` (fail-safe: errors are misses)."""

    def __init__(
        self,
        state: ConnectorState,
        namespace: str,
        *,
        now: Callable[[], datetime] | None = None,
        ttl: timedelta = TTL,
    ) -> None:
        """Create a cache.

        Args:
            state: Connector state whose ``cache_get`` / ``cache_set`` hold the entries.
            namespace: Keeps the website chat and the connector tool apart (``live``, ``tool``).
            now: UTC clock (tests).
            ttl: How long an answer may be reused.
        """
        self._state, self._ns = state, namespace
        self._now = now or (lambda: datetime.now(UTC))
        self._ttl = ttl

    def get(self, question: str, product_code: str | None = None) -> CachedAnswer | None:
        """The stored answer for this question if it is younger than the TTL, else None."""
        try:
            raw = self._state.cache_get(cache_key(self._ns, question, product_code))
            if raw is None:
                return None
            entry = json.loads(raw)
            stored = datetime.fromisoformat(str(entry["stored_at"]))
            if stored.tzinfo is None:
                stored = stored.replace(tzinfo=UTC)
            age = self._now() - stored
            body = entry["body"]
            if not isinstance(body, dict) or age < timedelta(0) or age > self._ttl:
                return None
            return CachedAnswer(body=body, stored_at=stored)
        except Exception as exc:  # noqa: BLE001 - any cache problem is a miss
            logger.warning("chat_cache_miss_on_error", op="get", error_type=type(exc).__name__)
            return None

    def put(self, question: str, product_code: str | None, body: dict[str, Any]) -> bool:
        """Keep ``body`` for this question; returns False (and logs) when it could not be kept."""
        try:
            value = json.dumps({"stored_at": self._now().isoformat(), "body": body})
            ttl = max(1, int(self._ttl.total_seconds()))
            self._state.cache_set(cache_key(self._ns, question, product_code), value, ttl)
            return True
        except Exception as exc:  # noqa: BLE001 - a cache that cannot be written is skipped
            logger.warning("chat_cache_put_failed", error_type=type(exc).__name__)
            return False
