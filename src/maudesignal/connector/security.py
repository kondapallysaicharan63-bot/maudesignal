"""API-key check and per-key rate limit for the connector (no framework imports).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Keys come from ``MAUDESIGNAL_API_KEYS`` (comma-separated). Each entry is either a
plain key or ``sha256:<64 hex>``; only SHA-256 digests are kept in memory and every
comparison is constant time. A key is never logged or echoed. What logs and the
spend ledger see is a *key id*: the first 12 hex characters of an HMAC-SHA256 of the key
under a server-side pepper (``MAUDESIGNAL_KEY_PEPPER``), so a short id cannot be used to
check key guesses offline without the pepper. Plain keys shorter than 32 characters are
refused.

Several keys may be listed, each revocable by deleting its entry. An entry may carry a
label, ``label=KEY`` or ``label=sha256:<hex>`` (label: 1 to 32 letters, digits, ``-`` or
``_``), so logs and the audit chain show the label next to the key id. Public demo keys come
from ``MAUDESIGNAL_DEMO_KEYS`` (same format): they work on every read tool, have their own lower
limits, and never start a live model call. A demo key is public by design.

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
from dataclasses import dataclass

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

KEYS_ENV = "MAUDESIGNAL_API_KEYS"
DEMO_KEYS_ENV = "MAUDESIGNAL_DEMO_KEYS"
DEMO_RATE_ENV = "MAUDESIGNAL_DEMO_RATE_PER_MIN"
DEFAULT_DEMO_RATE_PER_MIN = 10
DEMO_PER_DAY = 200
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
_LABELLED = re.compile(r"^([A-Za-z0-9_-]{1,32})=(.+)$")


def split_label(item: str) -> tuple[str | None, str]:
    """Split ``label=KEY`` into ``(label, KEY)``; anything else is ``(None, item)``.

    An entry counts as labelled only when the part after ``=`` is a ``sha256:`` digest or
    at least ``MIN_KEY_CHARS`` long, so a plain key that happens to contain ``=`` (base64
    padding, for example) is kept whole instead of being cut at the ``=``.
    """
    m = _LABELLED.match(item)
    if m:
        rest = m.group(2).strip()
        if rest.lower().startswith("sha256:") or len(rest) >= MIN_KEY_CHARS:
            return m.group(1), rest
    return None, item


@dataclass(frozen=True)
class KeyMatch:
    """Who a presented key is: its non-secret id, optional label and whether it is a demo key."""

    key_id: str
    label: str | None = None
    demo: bool = False


def first_plain_key(raw: str) -> str | None:
    """The first entry's plain key (label removed), or None if it is a digest or too short."""
    first = next((e.strip() for e in raw.split(",") if e.strip()), "")
    first = split_label(first)[1]
    if not first or first.lower().startswith("sha256:") or len(first) < MIN_KEY_CHARS:
        return None
    return first


def parse_entries(raw: str) -> tuple[list[tuple[str, str | None]], int]:
    """Split a comma-separated key list into ``(digest, label)`` pairs.

    Returns the pairs and the number of plain keys refused for being too short. Entries are
    ``KEY``, ``sha256:<hex>``, ``label=KEY`` or ``label=sha256:<hex>``.
    """
    out: list[tuple[str, str | None]] = []
    too_short = 0
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        label, item = split_label(item)
        if item.lower().startswith("sha256:"):
            out.append((item[7:].strip().lower(), label))
        elif len(item) < MIN_KEY_CHARS:
            too_short += 1
        else:
            out.append((sha256_hex(item), label))
    return out, too_short


def sha256_hex(key: str) -> str:
    """SHA-256 of a key as lowercase hex."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyStore:
    """Set of accepted key digests (with optional labels) and of public demo key digests."""

    def __init__(
        self,
        digests: list[str],
        pepper: str | None = None,
        *,
        labels: dict[str, str] | None = None,
        demo_digests: list[str] | None = None,
        demo_labels: dict[str, str] | None = None,
        demo_key_hint: str | None = None,
    ) -> None:
        """Create a store from SHA-256 hex digests.

        Args:
            digests: SHA-256 hex digests of the accepted keys.
            pepper: Server-side secret for key ids. When unset, one is derived from the
                configured digests (never leaves the server).
            labels: Optional ``digest -> label`` for ``digests``.
            demo_digests: Digests of public demo keys (lower limits, no live model call).
            demo_labels: Optional ``digest -> label`` for ``demo_digests``.
            demo_key_hint: The first demo key in clear, shown by ``GET /v1/connect``. A demo
                key is public by design; this is never set for a full key.
        """
        self.demo_key_hint = demo_key_hint
        self._digests = [d.lower() for d in digests if _HEX64.match(d.lower())]
        self._demo = [d.lower() for d in (demo_digests or []) if _HEX64.match(d.lower())]
        self._labels = {d.lower(): v for d, v in (labels or {}).items()}
        self._labels |= {d.lower(): v for d, v in (demo_labels or {}).items()}
        material = pepper or "maudesignal-key-id:" + ",".join(sorted(self._digests + self._demo))
        self._pepper = material.encode("utf-8")

    def key_id(self, key: str) -> str:
        """Non-secret id of a key: truncated HMAC-SHA256 under the pepper."""
        mac = hmac.new(self._pepper, key.encode("utf-8"), hashlib.sha256).hexdigest()
        return mac[:KEY_ID_CHARS]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> KeyStore:
        """Read ``MAUDESIGNAL_API_KEYS`` and ``MAUDESIGNAL_DEMO_KEYS`` (see the module text)."""
        src = os.environ if env is None else env
        pairs, too_short = parse_entries(src.get(KEYS_ENV, ""))
        demo_pairs, demo_short = parse_entries(src.get(DEMO_KEYS_ENV, ""))
        if too_short or demo_short:
            logger.warning(
                "connector_keys_rejected_too_short",
                count=too_short + demo_short,
                min_chars=MIN_KEY_CHARS,
            )
        pepper = src.get(PEPPER_ENV) or None
        return cls(
            [d for d, _ in pairs],
            pepper,
            labels={d: lbl for d, lbl in pairs if lbl},
            demo_digests=[d for d, _ in demo_pairs],
            demo_labels={d: lbl for d, lbl in demo_pairs if lbl},
            demo_key_hint=first_plain_key(src.get(DEMO_KEYS_ENV, "")),
        )

    @property
    def configured(self) -> bool:
        """True when at least one key (full or demo) is accepted."""
        return bool(self._digests or self._demo)

    @property
    def demo_configured(self) -> bool:
        """True when at least one public demo key is accepted."""
        return bool(self._demo)

    def match(self, presented: str | None) -> KeyMatch | None:
        """Who ``presented`` is, or None when it matches no configured key.

        Every stored digest is compared (no early exit) so timing does not reveal which
        position matched.
        """
        if not presented or len(presented) > MAX_KEY_CHARS:
            return None
        digest = sha256_hex(presented).encode("ascii")
        found: str | None = None
        demo = False
        for stored in self._digests:
            if hmac.compare_digest(digest, stored.encode("ascii")):
                found = stored
        for stored in self._demo:
            if hmac.compare_digest(digest, stored.encode("ascii")):
                found, demo = stored, True
        if found is None:
            return None
        return KeyMatch(self.key_id(presented), self._labels.get(found), demo)

    def verify(self, presented: str | None) -> str | None:
        """Return the key id when ``presented`` matches a configured key, else None."""
        m = self.match(presented)
        return m.key_id if m else None


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
