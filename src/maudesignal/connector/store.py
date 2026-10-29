"""Optional shared state for the connector: rate limits, spend ledger, cache, audit log.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

When ``UPSTASH_REDIS_REST_URL`` and ``UPSTASH_REDIS_REST_TOKEN`` are both set, the state
lives in that Redis database (Upstash, reached over its REST API) and is shared by every
server instance. Otherwise everything is kept in memory of the one instance, which resets on
a cold start; ``GET /v1/health`` says which of the two is in use.

Audit entries use the chain format of ``copilot/audit_export`` and ``Database``: each entry
holds ``prev_hash`` and ``entry_hash = sha256(prev_hash + json(ts, actor, action, entity_id,
payload))`` and the first entry follows ``GENESIS``. An entry never contains an API key: the
caller is named by the server's peppered key id (an HMAC, the same id the limiter uses).

Failure policy: a failing Redis never turns a request into a bigger problem than it is.
Rate limits fall back to the instance's own memory; the cache is skipped; the spend ledger
raises (so ``ask`` falls back to a recorded answer instead of spending without a cap); an audit
append that fails is logged without the token and the request still answers.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.connector.security import RateLimiter
from maudesignal.copilot.spend import DailyLedger
from maudesignal.storage.database import Database

logger = get_logger(__name__)

URL_ENV = "UPSTASH_REDIS_REST_URL"
TOKEN_ENV = "UPSTASH_REDIS_REST_TOKEN"
GENESIS = "GENESIS"
NAMESPACE = "maudesignal:connector"
MAX_AUDIT_ENTRIES = 5_000
MAX_AUDIT_READ = 200
LOCK_TTL_MS = 5_000
LOCK_TRIES = 25
LOCK_WAIT_SECONDS = 0.04

Backend = Literal["upstash_redis", "in_memory_per_instance"]

_RELEASE_LOCK = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


class UpstashError(Exception):
    """A Redis call failed. The message never holds the token or a response body."""


class UpstashClient:
    """Minimal client for the Upstash Redis REST API (``POST <url>`` with a JSON command)."""

    def __init__(self, url: str, token: str, *, http: httpx.Client | None = None) -> None:
        """Create the client.

        Args:
            url: The REST URL (``https://...upstash.io``).
            token: The REST token. Only ever sent in the Authorization header.
            http: Client to use (tests pass one with a mock transport).
        """
        self._url = url.rstrip("/")
        self._token = token
        self._http = http or httpx.Client(timeout=3.0)

    def command(self, *args: str | int | float) -> Any:
        """Run one Redis command and return its result.

        Raises:
            UpstashError: Network failure, non-200 status or an error reply.
        """
        body = [str(a) for a in args]
        try:
            resp = self._http.post(
                self._url, json=body, headers={"Authorization": f"Bearer {self._token}"}
            )
        except httpx.HTTPError as exc:
            raise UpstashError(f"redis request failed ({type(exc).__name__})") from None
        if resp.status_code != 200:
            raise UpstashError(f"redis request failed (HTTP {resp.status_code})")
        try:
            doc = resp.json()
        except ValueError:
            raise UpstashError("redis reply was not JSON") from None
        if not isinstance(doc, dict) or doc.get("error"):
            raise UpstashError("redis returned an error")
        return doc.get("result")


def _client_from_env(
    env: dict[str, str] | None = None, http: httpx.Client | None = None
) -> UpstashClient | None:
    src = os.environ if env is None else env
    url, token = src.get(URL_ENV, "").strip(), src.get(TOKEN_ENV, "").strip()
    if url.startswith("https://") and token:
        return UpstashClient(url, token, http=http)
    return None


def shared_store_configured(env: dict[str, str] | None = None) -> bool:
    """True when both Upstash variables are set (the URL must be https)."""
    return _client_from_env(env) is not None


class SharedRateLimiter(RateLimiter):
    """Fixed-window limiter kept in Redis, with the in-memory limiter as fallback.

    Fixed windows: around a window boundary up to twice the limit can pass in a short span.
    """

    def __init__(
        self,
        client: UpstashClient,
        name: str,
        limit: int,
        window_seconds: float,
        *,
        wall: Callable[[], float] = time.time,
    ) -> None:
        """Create a limiter.

        Args:
            client: Redis client.
            name: Namespace for this limiter's counters.
            limit: Events allowed per window.
            window_seconds: Window length.
            wall: Wall clock in seconds (tests).
        """
        super().__init__(limit, window_seconds=window_seconds)
        self._client, self._name, self._wall = client, name, wall

    def _key(self, who: str) -> tuple[str, float]:
        now = self._wall()  # read once: the bucket index and the time left must agree
        idx = int(now // self.window)
        return f"{NAMESPACE}:rl:{self._name}:{who}:{idx}", self.window - (now % self.window)

    def _count(self, who: str, *, add: bool) -> tuple[int, int]:
        key, left = self._key(who)
        if add:
            n = int(self._client.command("INCR", key))
            if n == 1:
                self._client.command("EXPIRE", key, int(self.window * 2))
        else:
            n = int(self._client.command("GET", key) or 0)
        return n, max(1, math.ceil(left))

    def blocked(self, key_id: str) -> tuple[bool, int]:
        """Without counting: is ``key_id`` at its limit in this window?"""
        try:
            n, retry = self._count(key_id, add=False)
        except UpstashError as exc:
            logger.warning("connector_redis_fallback", op="rate_blocked", error=str(exc))
            return super().blocked(key_id)
        return (n >= self.limit), (retry if n >= self.limit else 0)

    def record(self, key_id: str) -> None:
        """Count one event for ``key_id``."""
        try:
            self._count(key_id, add=True)
        except UpstashError as exc:
            logger.warning("connector_redis_fallback", op="rate_record", error=str(exc))
            super().record(key_id)

    def check(self, key_id: str) -> tuple[bool, int, int]:
        """Count one request; returns ``(allowed, remaining, retry_after_seconds)``."""
        try:
            n, retry = self._count(key_id, add=True)
        except UpstashError as exc:
            logger.warning("connector_redis_fallback", op="rate_check", error=str(exc))
            return super().check(key_id)
        if n > self.limit:
            return False, 0, retry
        return True, self.limit - n, 0


class UpstashLedger(DailyLedger):
    """Daily spend of one API key in Redis (shared by every instance)."""

    def __init__(
        self, client: UpstashClient, key_id: str, *, today: Callable[[], date] | None = None
    ) -> None:
        """Create the ledger of ``key_id`` (a non-secret id)."""
        super().__init__(Path(os.devnull), today=today)
        self._client, self._key_id = client, key_id

    def _key(self, field: str) -> str:
        return f"{NAMESPACE}:spend:{self._key_id}:{self._today().isoformat()}:{field}"

    def spent_today(self) -> float:
        """USD recorded today (UTC). Raises ``UpstashError`` if Redis is unreachable."""
        return float(self._client.command("GET", self._key("usd")) or 0.0)

    def _add_usd(self, usd: float) -> float:
        """INCRBYFLOAT with one retry (the spend has already happened)."""
        try:
            return float(self._client.command("INCRBYFLOAT", self._key("usd"), repr(float(usd))))
        except UpstashError:
            return float(self._client.command("INCRBYFLOAT", self._key("usd"), repr(float(usd))))

    def reserve(self, usd: float, daily_cap: float) -> bool:
        """Hold ``usd`` of today's budget before a model call (atomic INCRBYFLOAT).

        Returns False, with nothing held, when the hold would take today's total over
        ``daily_cap``. Concurrent instances therefore cannot all pass a read-only check.
        Raises ``UpstashError`` if Redis is unreachable.
        """
        total = float(self._client.command("INCRBYFLOAT", self._key("usd"), repr(float(usd))))
        self._client.command("EXPIRE", self._key("usd"), 3 * 86_400)
        if total > daily_cap + 1e-9:
            self._client.command("INCRBYFLOAT", self._key("usd"), repr(-float(usd)))
            return False
        return True

    def release(self, usd: float) -> None:
        """Give back a hold from :meth:`reserve` (the real cost is added by ``add``)."""
        try:
            self._add_usd(-float(usd))
        except UpstashError as exc:
            logger.critical(
                "connector_spend_hold_not_released",
                usd=round(float(usd), 6),
                day=self._today().isoformat(),
                error=str(exc),
            )

    def add(self, usd: float, calls: int) -> float:
        """Add spend for today and return today's new total."""
        try:
            total = self._add_usd(usd)
        except UpstashError as exc:
            # The model call already happened: this spend is not counted. Say so loudly (no
            # key, no token) so the operator can reconcile it by hand.
            logger.critical(
                "connector_spend_not_recorded",
                usd=round(float(usd), 6),
                calls=int(calls),
                day=self._today().isoformat(),
                error=str(exc),
            )
            raise
        self._client.command("INCRBY", self._key("calls"), int(calls))
        for field in ("usd", "calls"):
            self._client.command("EXPIRE", self._key(field), 3 * 86_400)
        return round(total, 6)


def build_entry(
    *,
    seq: int,
    prev_hash: str,
    ts: datetime,
    actor: str,
    action: str,
    entity_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """One audit entry in the ``audit_export`` shape (naive UTC ``ts``, sorted payload JSON)."""
    payload_json = json.dumps(payload, sort_keys=True)
    return {
        "seq": seq,
        "ts": ts.isoformat(),
        "actor": actor,
        "action": action,
        "entity_id": entity_id,
        "payload_json": payload_json,
        "prev_hash": prev_hash,
        "entry_hash": Database.audit_entry_hash(
            prev_hash, ts, actor, action, entity_id, payload_json
        ),
    }


def verify_chain(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Recompute the hashes of consecutive entries (a tail of the chain is fine).

    The first entry is checked against its own ``prev_hash``; when its ``seq`` is 1 that
    must be ``GENESIS``. Every later entry must link to the one before it.

    Returns:
        ``(ok, first_bad_seq)``.
    """
    prev: str | None = None
    for e in entries:
        if prev is None:
            prev = GENESIS if int(e["seq"]) == 1 else str(e["prev_hash"])
        expected = Database.audit_entry_hash(
            prev,
            datetime.fromisoformat(e["ts"]),
            e["actor"],
            e["action"],
            e["entity_id"],
            e["payload_json"],
        )
        if e["prev_hash"] != prev or e["entry_hash"] != expected:
            return False, int(e["seq"])
        prev = str(e["entry_hash"])
    return True, None


class ConnectorState:
    """Rate limiters, spend ledgers, cache and audit log, shared or in memory."""

    def __init__(
        self,
        client: UpstashClient | None = None,
        *,
        wall: Callable[[], float] = time.time,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Create the state.

        Args:
            client: Redis client; ``None`` keeps everything in this instance's memory.
            wall: Wall clock in seconds (tests).
            now: UTC clock for audit timestamps (tests).
        """
        self._client, self._wall, self._now = client, wall, now
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, str]] = {}
        self._audit: list[dict[str, Any]] = []

    @classmethod
    def from_env(
        cls, env: dict[str, str] | None = None, http: httpx.Client | None = None
    ) -> ConnectorState:
        """Shared when both Upstash variables are set, in memory otherwise."""
        return cls(_client_from_env(env, http))

    @property
    def backend(self) -> Backend:
        """Which store is in use."""
        return "upstash_redis" if self._client else "in_memory_per_instance"

    @property
    def shared(self) -> bool:
        """True when every server instance sees the same state."""
        return self._client is not None

    # -- rate limits and ledger ---------------------------------------------------------

    def rate_limiter(self, name: str, limit: int, window_seconds: float = 60.0) -> RateLimiter:
        """A limiter named ``name`` (Redis counters when shared, memory otherwise)."""
        if self._client:
            return SharedRateLimiter(self._client, name, limit, window_seconds, wall=self._wall)
        return RateLimiter(limit, window_seconds=window_seconds)

    def ledger(self, key_id: str) -> DailyLedger | None:
        """Shared daily ledger for ``key_id``; ``None`` when not shared (a file ledger is used)."""
        return UpstashLedger(self._client, key_id) if self._client else None

    # -- cache ----------------------------------------------------------------------------

    def cache_get(self, key: str) -> str | None:
        """Cached text for ``key`` if it has not expired."""
        if self._client:
            try:
                value = self._client.command("GET", f"{NAMESPACE}:cache:{key}")
                return str(value) if value is not None else None
            except UpstashError as exc:
                logger.warning("connector_redis_fallback", op="cache_get", error=str(exc))
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > self._wall():
                return hit[1]
            self._cache.pop(key, None)
        return None

    def cache_set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Keep ``value`` for ``ttl_seconds``."""
        if self._client:
            try:
                self._client.command("SET", f"{NAMESPACE}:cache:{key}", value, "EX", ttl_seconds)
                return
            except UpstashError as exc:
                logger.warning("connector_redis_fallback", op="cache_set", error=str(exc))
        with self._lock:
            self._cache[key] = (self._wall() + ttl_seconds, value)

    # -- audit ----------------------------------------------------------------------------

    def audit_append(
        self, *, actor: str, action: str, entity_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Append one chained entry and return it.

        Raises:
            UpstashError: Redis is configured but the append failed (nothing was written).
        """
        ts = self._now().replace(tzinfo=None)
        if self._client:
            return self._append_shared(self._client, ts, actor, action, entity_id, payload)
        with self._lock:
            last = self._audit[-1] if self._audit else None
            entry = build_entry(
                seq=int(last["seq"]) + 1 if last else 1,
                prev_hash=str(last["entry_hash"]) if last else GENESIS,
                ts=ts,
                actor=actor,
                action=action,
                entity_id=entity_id,
                payload=payload,
            )
            self._audit.append(entry)
            del self._audit[:-MAX_AUDIT_ENTRIES]
            return entry

    def _append_shared(
        self,
        client: UpstashClient,
        ts: datetime,
        actor: str,
        action: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        lock_key, token = f"{NAMESPACE}:audit:lock", secrets.token_hex(8)
        for _ in range(LOCK_TRIES):
            if client.command("SET", lock_key, token, "NX", "PX", LOCK_TTL_MS):
                break
            time.sleep(LOCK_WAIT_SECONDS)
        else:
            raise UpstashError("audit log is busy")
        try:
            last_raw = client.command("LINDEX", f"{NAMESPACE}:audit:log", -1)
            last = json.loads(last_raw) if last_raw else None
            entry = build_entry(
                seq=int(last["seq"]) + 1 if last else 1,
                prev_hash=str(last["entry_hash"]) if last else GENESIS,
                ts=ts,
                actor=actor,
                action=action,
                entity_id=entity_id,
                payload=payload,
            )
            client.command("RPUSH", f"{NAMESPACE}:audit:log", json.dumps(entry, sort_keys=True))
            client.command("LTRIM", f"{NAMESPACE}:audit:log", -MAX_AUDIT_ENTRIES, -1)
            return entry
        finally:
            with contextlib.suppress(UpstashError):  # else the lock expires after LOCK_TTL_MS
                client.command("EVAL", _RELEASE_LOCK, 1, lock_key, token)

    def audit_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """The last ``limit`` entries (at most 200), oldest first.

        Raises:
            UpstashError: Redis is configured but unreachable.
        """
        n = max(1, min(int(limit), MAX_AUDIT_READ))
        if self._client:
            rows = self._client.command("LRANGE", f"{NAMESPACE}:audit:log", -n, -1) or []
            return [json.loads(r) for r in rows]
        with self._lock:
            return [dict(e) for e in self._audit[-n:]]
