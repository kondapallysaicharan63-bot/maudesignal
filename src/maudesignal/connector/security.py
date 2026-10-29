"""API-key check and per-key rate limit for the connector (no framework imports).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Keys come from ``MAUDESIGNAL_API_KEYS`` (comma-separated). Each entry is either a
plain key or ``sha256:<64 hex>``; only SHA-256 digests are kept in memory and every
comparison is constant time. A key is never logged or echoed. What logs and the
spend ledger see is a *key id*: the first 12 hex characters of the key's SHA-256,
which cannot be turned back into the key.

Scope: every key is read-only, because no tool writes anything.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable

KEYS_ENV = "MAUDESIGNAL_API_KEYS"
RATE_ENV = "MAUDESIGNAL_RATE_LIMIT_PER_MIN"
DEFAULT_RATE_PER_MIN = 30
MAX_KEY_CHARS = 256
KEY_ID_CHARS = 12
WINDOW_SECONDS = 60.0

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(key: str) -> str:
    """SHA-256 of a key as lowercase hex."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyStore:
    """Set of accepted key digests."""

    def __init__(self, digests: list[str]) -> None:
        """Create a store from SHA-256 hex digests."""
        self._digests = [d.lower() for d in digests if _HEX64.match(d.lower())]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> KeyStore:
        """Read ``MAUDESIGNAL_API_KEYS`` (plain keys and/or ``sha256:<hex>`` entries)."""
        raw = (os.environ if env is None else env).get(KEYS_ENV, "")
        digests: list[str] = []
        for entry in raw.split(","):
            item = entry.strip()
            if not item:
                continue
            if item.lower().startswith("sha256:"):
                digests.append(item[7:].strip())
            else:
                digests.append(sha256_hex(item))
        return cls(digests)

    @property
    def configured(self) -> bool:
        """True when at least one key is accepted."""
        return bool(self._digests)

    def verify(self, presented: str | None) -> str | None:
        """Return the key id when ``presented`` matches a configured key, else None.

        Every stored digest is compared (no early exit) so timing does not reveal which
        position matched.
        """
        if not presented or len(presented) > MAX_KEY_CHARS:
            return None
        digest = sha256_hex(presented)
        matched = False
        for stored in self._digests:
            matched |= hmac.compare_digest(digest.encode("ascii"), stored.encode("ascii"))
        return digest[:KEY_ID_CHARS] if matched else None


class RateLimiter:
    """Sliding one-minute window, per key id, in memory (per server instance)."""

    def __init__(
        self,
        limit_per_minute: int = DEFAULT_RATE_PER_MIN,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a limiter.

        Args:
            limit_per_minute: Requests one key may make in any 60 seconds.
            clock: Monotonic clock in seconds (tests).
        """
        self.limit = limit_per_minute
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RateLimiter:
        """Limit from ``MAUDESIGNAL_RATE_LIMIT_PER_MIN`` (default 30)."""
        raw = (os.environ if env is None else env).get(RATE_ENV, "")
        try:
            limit = int(raw)
        except ValueError:
            return cls(DEFAULT_RATE_PER_MIN)
        return cls(limit if limit > 0 else DEFAULT_RATE_PER_MIN)

    def check(self, key_id: str) -> tuple[bool, int, int]:
        """Count one request for ``key_id``.

        Returns:
            ``(allowed, remaining, retry_after_seconds)``.
        """
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key_id, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, math.ceil(WINDOW_SECONDS - (now - hits[0])))
                return False, 0, retry
            hits.append(now)
            return True, self.limit - len(hits), 0
