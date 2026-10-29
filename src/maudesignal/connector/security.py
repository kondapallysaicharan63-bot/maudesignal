"""API-key check and per-key rate limit for the connector (no framework imports).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Keys come from ``MAUDESIGNAL_API_KEYS`` (comma-separated). Each entry is either a
plain key or ``sha256:<64 hex>``; only SHA-256 digests are kept in memory and every
comparison is constant time. A key is never logged or echoed. What logs and the
spend ledger see is a *key id*: the first 12 hex characters of an HMAC-SHA256 of the key
under a server-side pepper (``MAUDESIGNAL_KEY_PEPPER``), so a short id cannot be used to
check key guesses offline without the pepper. Plain keys shorter than 32 characters are
refused.

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

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

KEYS_ENV = "MAUDESIGNAL_API_KEYS"
RATE_ENV = "MAUDESIGNAL_RATE_LIMIT_PER_MIN"
DEFAULT_RATE_PER_MIN = 30
MAX_KEY_CHARS = 256
KEY_ID_CHARS = 12
PEPPER_ENV = "MAUDESIGNAL_KEY_PEPPER"
FAILED_AUTH_ENV = "MAUDESIGNAL_FAILED_AUTH_PER_MIN"
DEFAULT_FAILED_AUTH_PER_MIN = 10
MIN_KEY_CHARS = 32
MAX_TRACKED_CLIENTS = 10_000
WINDOW_SECONDS = 60.0

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(key: str) -> str:
    """SHA-256 of a key as lowercase hex."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyStore:
    """Set of accepted key digests."""

    def __init__(self, digests: list[str], pepper: str | None = None) -> None:
        """Create a store from SHA-256 hex digests.

        Args:
            digests: SHA-256 hex digests of the accepted keys.
            pepper: Server-side secret for key ids. When unset, one is derived from the
                configured digests (never leaves the server).
        """
        self._digests = [d.lower() for d in digests if _HEX64.match(d.lower())]
        material = pepper or "maudesignal-key-id:" + ",".join(sorted(self._digests))
        self._pepper = material.encode("utf-8")

    def key_id(self, key: str) -> str:
        """Non-secret id of a key: truncated HMAC-SHA256 under the pepper."""
        mac = hmac.new(self._pepper, key.encode("utf-8"), hashlib.sha256).hexdigest()
        return mac[:KEY_ID_CHARS]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> KeyStore:
        """Read ``MAUDESIGNAL_API_KEYS`` (plain keys and/or ``sha256:<hex>`` entries)."""
        raw = (os.environ if env is None else env).get(KEYS_ENV, "")
        digests: list[str] = []
        too_short = 0
        for entry in raw.split(","):
            item = entry.strip()
            if not item:
                continue
            if item.lower().startswith("sha256:"):
                digests.append(item[7:].strip())
            elif len(item) < MIN_KEY_CHARS:
                too_short += 1
            else:
                digests.append(sha256_hex(item))
        if too_short:
            logger.warning(
                "connector_keys_rejected_too_short", count=too_short, min_chars=MIN_KEY_CHARS
            )
        pepper = (os.environ if env is None else env).get(PEPPER_ENV) or None
        return cls(digests, pepper)

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
        return self.key_id(presented) if matched else None


class RateLimiter:
    """Sliding window (one minute by default), per key id, in memory (per server instance)."""

    def __init__(
        self,
        limit_per_minute: int = DEFAULT_RATE_PER_MIN,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = WINDOW_SECONDS,
    ) -> None:
        """Create a limiter.

        Args:
            limit_per_minute: Requests one key may make in any window (name kept; the window
                is one minute unless ``window_seconds`` says otherwise).
            clock: Monotonic clock in seconds (tests).
            window_seconds: Length of the sliding window.
        """
        self.limit = limit_per_minute
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        name: str = RATE_ENV,
        default: int = DEFAULT_RATE_PER_MIN,
        window_seconds: float = WINDOW_SECONDS,
    ) -> RateLimiter:
        """Limit from an env var (default ``MAUDESIGNAL_RATE_LIMIT_PER_MIN``, 30)."""
        raw = (os.environ if env is None else env).get(name, "")
        try:
            limit = int(raw)
        except ValueError:
            return cls(default, window_seconds=window_seconds)
        return cls(limit if limit > 0 else default, window_seconds=window_seconds)

    @classmethod
    def failed_auth_from_env(cls, env: dict[str, str] | None = None) -> RateLimiter:
        """Limiter for failed key checks per client address (default 10 per minute)."""
        return cls.from_env(env, name=FAILED_AUTH_ENV, default=DEFAULT_FAILED_AUTH_PER_MIN)

    def blocked(self, key_id: str) -> tuple[bool, int]:
        """Without counting: is ``key_id`` at its limit now? Returns ``(blocked, retry_after)``."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key_id)
            if not hits:
                return False, 0
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return True, max(1, math.ceil(self.window - (now - hits[0])))
            return False, 0

    def record(self, key_id: str) -> None:
        """Count one event (a failed key check) for ``key_id``."""
        now = self._clock()
        with self._lock:
            if len(self._hits) >= MAX_TRACKED_CLIENTS and key_id not in self._hits:
                stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]
                for k in stale:
                    del self._hits[k]
                if len(self._hits) >= MAX_TRACKED_CLIENTS:
                    self._hits.clear()  # flood of distinct addresses: start over, stay bounded
            self._hits.setdefault(key_id, deque()).append(now)

    def check(self, key_id: str) -> tuple[bool, int, int]:
        """Count one request for ``key_id``.

        Returns:
            ``(allowed, remaining, retry_after_seconds)``.
        """
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key_id, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, math.ceil(self.window - (now - hits[0])))
                return False, 0, retry
            hits.append(now)
            return True, self.limit - len(hits), 0
