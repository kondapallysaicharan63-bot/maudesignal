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
from maudesignal.connector.blob_store import BlobRef, RecordStore, StoreError
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
MAX_TRACKED_IDS = 50_000

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


class DailyCounter:
    """Per-address count per UTC day, in this instance's memory (resets on a cold start).

    The address is only ever a salted hash made by the caller; the counter never sees it raw.
    """

    def __init__(self, limit: int, *, today: Callable[[], date] | None = None) -> None:
        """Create a counter allowing ``limit`` hits per id per UTC day."""
        self.limit = limit
        self._today = today or (lambda: datetime.now(UTC).date())
        self._lock = threading.Lock()
        self._day: date | None = None
        self._hits: dict[str, int] = {}

    def _memory_hit(self, who: str) -> tuple[bool, int]:
        with self._lock:
            day = self._today()
            if day != self._day:  # a new UTC day: yesterday's counts are dropped
                self._day, self._hits = day, {}
            if who not in self._hits and len(self._hits) >= MAX_TRACKED_IDS:
                self._hits.clear()  # a flood of distinct ids: start over, stay bounded
            n = self._hits.get(who, 0)
            if n >= self.limit:
                return False, 0
            self._hits[who] = n + 1
            return True, self.limit - n - 1

    def hit(self, who: str) -> tuple[bool, int]:
        """Count one use for ``who``; returns ``(allowed, remaining_today)``."""
        return self._memory_hit(who)


class SharedDailyCounter(DailyCounter):
    """Daily counter kept in Redis (every instance sees it); memory when Redis fails."""

    def __init__(
        self,
        client: UpstashClient,
        name: str,
        limit: int,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        """Create the counter ``name``."""
        super().__init__(limit, today=today)
        self._client, self._name = client, name

    def hit(self, who: str) -> tuple[bool, int]:
        """Count one use for ``who``; returns ``(allowed, remaining_today)``."""
        key = f"{NAMESPACE}:daily:{self._name}:{self._today().isoformat()}:{who}"
        try:
            n = int(self._client.command("INCR", key))
            if n == 1:
                self._client.command("EXPIRE", key, 2 * 86_400)
        except UpstashError as exc:
            logger.warning("connector_redis_fallback", op="daily_hit", error=str(exc))
            return self._memory_hit(who)
        if n > self.limit:
            return False, 0
        return True, self.limit - n


class MemoryLedger(DailyLedger):
    """Daily spend kept in this instance's memory (nothing is written to disk)."""

    def __init__(self, *, today: Callable[[], date] | None = None) -> None:
        """Create an empty ledger."""
        super().__init__(Path(os.devnull), today=today)
        self._mem_lock = threading.Lock()
        self._mem: dict[str, float] = {}

    def spent_today(self) -> float:
        """USD recorded today (UTC)."""
        with self._mem_lock:
            return self._mem.get(self._today().isoformat(), 0.0)

    def add(self, usd: float, calls: int) -> float:
        """Add spend for today and return today's new total."""
        with self._mem_lock:
            day = self._today().isoformat()
            self._mem = {day: round(self._mem.get(day, 0.0) + usd, 6)}
            return self._mem[day]


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


#: Serialises read-modify-write of the Blob ledger inside one process (all instances of the
#: class share it, so two ``BlobLedger`` objects on the same store cannot interleave).
_BLOB_LEDGER_LOCK = threading.Lock()
BLOB_LEDGER_ATTEMPTS = 3
LEDGER_PREFIX = "ledger"


class BlobLedgerError(UpstashError):
    """The Blob ledger could not be read or written.

    Callers treat it like a Redis failure (a recorded answer, never a spend without a cap).
    The message holds no token.
    """


def _bust(url: str) -> str:
    """Add a changing query value so a CDN cannot serve an older copy of the ledger."""
    return f"{url}{'&' if '?' in url else '?'}t={secrets.token_hex(4)}"


class BlobLedger(DailyLedger):
    """Global daily spend kept as one small JSON object per UTC day in the private Blob store.

    Object ``ledger/<name>/<YYYY-MM-DD>.json`` holds ``{"day", "usd", "calls"}``. A reservation
    reads it, adds the hold, writes it back and reads it again to confirm that nobody else
    overwrote it in between (up to three tries). If the object cannot be read, written or
    confirmed, :class:`BlobLedgerError` is raised and the caller answers from a recording: the
    ledger FAILS CLOSED. A missing object is a new day (zero); an object that cannot be parsed
    is an error, never zero.

    Race: Blob has no atomic increment. Two server instances that read at the same moment may
    both reserve; the confirm step catches most of these and retries, and the enforced cap is
    the daily total minus the largest per-request cap (``globalcap``), so a rare undetected
    overlap of two requests still ends at or under the daily total.
    """

    def __init__(
        self,
        store: RecordStore,
        name: str,
        *,
        today: Callable[[], date] | None = None,
        attempts: int = BLOB_LEDGER_ATTEMPTS,
    ) -> None:
        """Create the ledger ``name`` on ``store``."""
        super().__init__(Path(os.devnull), today=today)
        self._store, self._name, self._attempts = store, name, max(1, attempts)

    def _object(self, day: str) -> str:
        return f"{LEDGER_PREFIX}/{self._name}/{day}.json"

    def _load(self, day: str) -> tuple[float, int]:
        path = self._object(day)
        try:
            refs = [r for r in self._store.list_prefix(path) if r.pathname == path]
            if not refs:
                return 0.0, 0
            raw = self._store.get(BlobRef(refs[0].pathname, _bust(refs[0].url)))
        except StoreError:
            raise BlobLedgerError("ledger store unreachable") from None
        try:
            doc = json.loads(raw)
            usd, calls = float(doc["usd"]), int(doc.get("calls", 0))
            if doc.get("day") != day or not math.isfinite(usd) or usd < 0 or calls < 0:
                raise ValueError("bad ledger")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise BlobLedgerError("ledger object unreadable") from None
        return usd, calls

    def _change(
        self, usd: float, calls: int = 0, *, cap: float | None = None
    ) -> tuple[bool, float]:
        """Add ``usd`` (may be negative) and confirm it. Returns ``(applied, total)``."""
        day = self._today().isoformat()
        with _BLOB_LEDGER_LOCK:
            for _ in range(self._attempts):
                have, n = self._load(day)
                total = max(0.0, round(have + usd, 6))
                if cap is not None and total > cap + 1e-9:
                    return False, have
                doc = {"day": day, "usd": total, "calls": n + calls}
                try:
                    self._store.put_json(self._object(day), doc, overwrite=True)
                except StoreError:
                    raise BlobLedgerError("ledger store unreachable") from None
                confirmed, _ = self._load(day)
                if abs(confirmed - total) < 1e-9:
                    return True, total
        raise BlobLedgerError("ledger write could not be confirmed")

    def spent_today(self) -> float:
        """USD recorded today (UTC). Raises ``BlobLedgerError`` when it cannot be read."""
        return self._load(self._today().isoformat())[0]

    def reserve(self, usd: float, daily_cap: float) -> bool:
        """Hold ``usd`` before a model call. False (nothing held) if it would pass the cap."""
        return self._change(float(usd), cap=float(daily_cap))[0]

    def release(self, usd: float) -> None:
        """Give back a hold from :meth:`reserve` (the real cost is added by ``add``)."""
        try:
            self._change(-float(usd))
        except BlobLedgerError as exc:
            logger.critical(
                "connector_spend_hold_not_released",
                usd=round(float(usd), 6),
                day=self._today().isoformat(),
                error=str(exc),
            )

    def add(self, usd: float, calls: int) -> float:
        """Add real spend for today and return today's new total."""
        try:
            return self._change(float(usd), int(calls))[1]
        except BlobLedgerError as exc:
            logger.critical(
                "connector_spend_not_recorded",
                usd=round(float(usd), 6),
                calls=int(calls),
                day=self._today().isoformat(),
                error=str(exc),
            )
            raise


#: Ledgers on which a hold can be placed before a model call (atomic or confirmed).
RESERVING_LEDGERS = (UpstashLedger, BlobLedger)


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
        self._blob: RecordStore | None = None
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

    def daily_counter(
        self, name: str, limit: int, *, today: Callable[[], date] | None = None
    ) -> DailyCounter:
        """A per-id, per-UTC-day counter named ``name`` (Redis when shared, memory otherwise)."""
        if self._client:
            return SharedDailyCounter(self._client, name, limit, today=today)
        return DailyCounter(limit, today=today)

    def ledger(self, key_id: str) -> DailyLedger | None:
        """Shared daily ledger for ``key_id``; ``None`` when not shared (a file ledger is used)."""
        return UpstashLedger(self._client, key_id) if self._client else None

    def attach_blob(self, store: RecordStore) -> None:
        """Offer the private Blob store as the durable global ledger (ignored for memory)."""
        self._blob = store if store.backend == "blob_private" else None

    @property
    def global_mode(self) -> Literal["upstash", "blob", "none"]:
        """Where the global live ledger is kept: Redis, the private Blob store, or nowhere."""
        if self._client:
            return "upstash"
        return "blob" if self._blob is not None else "none"

    def global_ledger(
        self, name: str, *, today: Callable[[], date] | None = None
    ) -> DailyLedger | None:
        """The durable shared ledger ``name`` (Redis, else Blob), or ``None`` when neither."""
        if self._client:
            return UpstashLedger(self._client, name, today=today)
        if self._blob is not None:
            return BlobLedger(self._blob, name, today=today)
        return None

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
