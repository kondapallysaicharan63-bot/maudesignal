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
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.connector.blob_store import BlobRef, ObjectGoneError, RecordStore, StoreError
from maudesignal.connector.security import RateLimiter
from maudesignal.copilot.spend import DailyLedger
from maudesignal.storage.database import Database

logger = get_logger(__name__)

URL_ENV = "UPSTASH_REDIS_REST_URL"
TOKEN_ENV = "UPSTASH_REDIS_REST_TOKEN"
GENESIS = "GENESIS"
NAMESPACE = "maudesignal:connector"
MAX_TRACKED_IDS = 50_000
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
    """Per-id count per UTC day, in this instance's memory (resets on a cold start).

    The id is only ever a salted hash or a key id made by the caller; the counter never sees a
    raw address or key. Counts are per server instance, not shared across instances.
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


_UP_HOLDS: ContextVar[tuple[tuple[int, float, float], ...]] = ContextVar(
    "maudesignal_upstash_holds", default=()
)


class UpstashLedger(DailyLedger):
    """Daily spend of one API key in Redis (shared by every instance)."""

    def __init__(
        self,
        client: UpstashClient,
        key_id: str,
        *,
        today: Callable[[], date] | None = None,
        keep_holds: bool = False,
    ) -> None:
        """Create the ledger of ``key_id`` (a non-secret id).

        With ``keep_holds`` (the global ledger) a hold is never given back: the day's total
        is the sum of ``max(hold, actual)`` per request, so a paid call whose cost was never
        recorded (timeout, Redis error after the call) still counts its hold. Only the part
        of a real cost above its hold is added. Without it (a per-key ledger) a hold is
        released and the real cost added, as before.
        """
        super().__init__(Path(os.devnull), today=today)
        self._client, self._key_id = client, key_id
        self._keep_holds = keep_holds
        self._broken = False  # an excess over a hold could not be recorded: no more holds

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

    def _push_hold(self, hold: float) -> None:
        if self._keep_holds:
            _UP_HOLDS.set((*_UP_HOLDS.get(), (id(self), hold, 0.0)))

    def _pop_hold(self) -> tuple[float, float] | None:
        items = list(_UP_HOLDS.get())
        for i in range(len(items) - 1, -1, -1):
            if items[i][0] == id(self):
                _, hold, actual = items.pop(i)
                _UP_HOLDS.set(tuple(items))
                return hold, actual
        return None

    def reserve(self, usd: float, daily_cap: float) -> bool:
        """Hold ``usd`` of today's budget before a model call (atomic INCRBYFLOAT).

        Returns False, with nothing held, when the hold would take today's total over
        ``daily_cap``. Concurrent instances therefore cannot all pass a read-only check.
        Raises ``UpstashError`` if Redis is unreachable.
        """
        if self._broken:
            raise UpstashError("an earlier cost could not be recorded")
        total = float(self._client.command("INCRBYFLOAT", self._key("usd"), repr(float(usd))))
        self._client.command("EXPIRE", self._key("usd"), 3 * 86_400)
        if total > daily_cap + 1e-9:
            self._client.command("INCRBYFLOAT", self._key("usd"), repr(-float(usd)))
            return False
        self._push_hold(float(usd))
        return True

    def release(self, usd: float) -> None:
        """Close a hold from :meth:`reserve`.

        Per-key ledger: give the hold back (the real cost was added by ``add``). Global
        ledger (``keep_holds``): keep the hold and add only the cost above it, if any.
        """
        if self._keep_holds:
            closed = self._pop_hold()
            if closed is None:
                return
            hold, actual = closed
            excess = round(actual - hold, 6)
            if excess > 0:
                try:
                    self._add_usd(excess)
                except UpstashError:
                    self._broken = True
                    logger.critical("connector_spend_excess_not_recorded", excess_usd=excess)
            return
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
        if self._keep_holds:
            items = list(_UP_HOLDS.get())
            for i in range(len(items) - 1, -1, -1):
                if items[i][0] == id(self):  # inside a held request: settled in ``release``
                    _, hold, actual = items[i]
                    actual = round(actual + float(usd), 6)
                    items[i] = (id(self), hold, actual)
                    _UP_HOLDS.set(tuple(items))
                    return actual
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


LEDGER_PREFIX = "ledger"
_RESERVATIONS: ContextVar[tuple[tuple[int, _Reservation], ...]] = ContextVar(
    "maudesignal_blob_reservations", default=()
)


#: Threads used to read the day's ledger objects in parallel.
_SUM_WORKERS = 8


class BlobLedgerError(UpstashError):
    """The Blob ledger could not be read or written.

    Callers treat it like a Redis failure (a recorded answer, never a spend without a cap).
    The message holds no token.
    """


@dataclass
class _Reservation:
    """One request's own ledger object, as this request knows it."""

    day: str
    pathname: str
    hold_usd: float
    actual_usd: float = 0.0


class BlobLedger(DailyLedger):
    """Global daily spend kept as one small object per request in the private Blob store.

    The ledger is append-only: nothing is ever read, changed and written back as a shared
    counter, so one instance can never erase another's entry. Each paid request owns exactly
    one object, ``ledger/<UTC-day>/<uuid>.json``:

    1. **Reserve** (before the model call): write the object ``{"hold_usd": h}``, then list the
       day's prefix and sum every object, ours included: ``max(hold_usd, actual_usd)`` for
       every object, settled or not.
       If the sum is over the cap, delete our own object and refuse (a recorded answer is
       shown instead). Two requests that reserve at the same moment each write before they
       list, so the later listing sees both. If the list, a read or the write fails, the
       reserve fails closed (:class:`BlobLedgerError`) and no model call is made.
    2. **Settle** (after the call, in :meth:`release`): overwrite only our own object with
       ``{"hold_usd": h, "actual_usd": a, "settled": true}``. The object still counts
       ``max(h, a)``, so settling never lowers it: a request whose cost was never recorded
       (the call errored or timed out after it was sent) keeps its whole hold in the total.
       The spend guard keeps ``a <= h``; if ``a > h`` ever happens and the settle write fails,
       the excess goes into a new append-only object; if that write fails too, the ledger
       refuses every later hold.

    So the day's total is the sum of ``max(hold, actual)`` over all requests: it can only be
    too high, never too low, and a request that dies mid-call keeps its hold for the day.
    The cap passed to :meth:`reserve` is the daily total minus the largest single-request cap
    (see ``globalcap``), so requests that reserve concurrently, and a final
    call that costs a little more than its hold, still end at or under the daily total.

    One instance can serve many requests: each request's object is tracked per execution
    context (thread or task), keyed by this instance.
    """

    def __init__(
        self,
        store: RecordStore,
        name: str = "",
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        """Create the ledger on ``store`` (``name`` is accepted for symmetry and unused)."""
        super().__init__(Path(os.devnull), today=today)
        self._store = store
        self._settled: dict[str, float] = {}  # pathname -> actual USD, settled objects only
        self._broken = False  # a paid call's cost could not be recorded: no more holds

    # -- helpers --------------------------------------------------------------------------

    @staticmethod
    def _prefix(day: str) -> str:
        return f"{LEDGER_PREFIX}/{day}/"

    def _mine(self) -> _Reservation | None:
        """Our innermost open reservation (a voice request opens two: outer, then the ask)."""
        for key, res in reversed(_RESERVATIONS.get()):
            if key == id(self):
                return res
        return None

    def _push(self, res: _Reservation) -> None:
        _RESERVATIONS.set((*_RESERVATIONS.get(), (id(self), res)))

    def _pop(self) -> _Reservation | None:
        """Remove and return our innermost reservation, leaving the outer ones in place."""
        items = list(_RESERVATIONS.get())
        for i in range(len(items) - 1, -1, -1):
            if items[i][0] == id(self):
                res = items.pop(i)[1]
                _RESERVATIONS.set(tuple(items))
                return res
        return None

    def _read_object(self, ref: BlobRef) -> float | None:
        """One object's counted USD (``None`` when it vanished). Settled objects are cached."""
        cached = self._settled.get(ref.pathname)
        if cached is not None:
            return cached
        try:
            raw = json.loads(self._store.get(ref))
        except ObjectGoneError:
            return None  # a refused request took its own hold back after we listed
        except (StoreError, ValueError):
            raise BlobLedgerError("ledger object unreadable") from None
        try:
            hold = float(raw.get("hold_usd", 0.0))
            actual = float(raw.get("actual_usd", 0.0))
            settled = raw.get("settled") is True
        except (TypeError, AttributeError, ValueError):
            raise BlobLedgerError("ledger object unreadable") from None
        if not (math.isfinite(hold) and math.isfinite(actual)) or hold < 0 or actual < 0:
            raise BlobLedgerError("ledger object unreadable")
        # Every object counts max(hold, actual), settled or not. A call that was sent but
        # died before its cost was recorded (timeout, 5xx, dropped connection) is billed
        # anyway, so its hold must stay in the day's total.
        counted = max(hold, actual)
        if settled:
            self._settled[ref.pathname] = counted  # a settled object never changes again
        return counted

    def _sum(self, day: str) -> tuple[float, list[BlobRef]]:
        """The day's total and its objects: ``max(hold, actual)`` summed. Fails closed."""
        try:
            refs = self._store.list_prefix(self._prefix(day), strict=True)
        except StoreError:
            raise BlobLedgerError("ledger store unreachable") from None
        for gone in [k for k in self._settled if not k.startswith(self._prefix(day))]:
            del self._settled[gone]  # an earlier day: no longer needed
        todo = [r for r in refs if r.pathname not in self._settled]
        values: dict[str, float | None] = {}
        if len(todo) > 1:
            with ThreadPoolExecutor(max_workers=min(_SUM_WORKERS, len(todo))) as pool:
                for ref, value in zip(todo, pool.map(self._read_object, todo), strict=True):
                    values[ref.pathname] = value
        total = 0.0
        for ref in refs:
            value = values[ref.pathname] if ref.pathname in values else self._read_object(ref)
            if value is not None:
                total += value
        return round(total, 6), refs

    def _write_new(self, day: str, record: dict[str, Any]) -> str:
        path = f"{self._prefix(day)}{uuid.uuid4().hex}.json"
        try:
            self._store.put_json(path, record)
        except StoreError:
            raise BlobLedgerError("ledger store unreachable") from None
        return path

    def _drop(self, day: str, pathname: str) -> None:
        """Take back our own refused object: delete it; failing that, zero it; else keep it."""
        try:
            ref = next(
                (r for r in self._store.list_prefix(pathname) if r.pathname == pathname), None
            )
            if ref is not None:
                self._store.delete(ref)
                return
        except StoreError:
            pass
        try:  # a refusal started no model call, so lowering our own object is safe
            self._store.overwrite_json(pathname, {"hold_usd": 0.0, "actual_usd": 0.0})
        except StoreError:
            logger.error("connector_spend_refused_hold_kept", day=day)  # only over-counts

    # -- the ledger interface -------------------------------------------------------------

    def spent_today(self) -> float:
        """USD counted today (UTC). Raises ``BlobLedgerError`` when it cannot be read."""
        return self._sum(self._today().isoformat())[0]

    def reserve(self, usd: float, daily_cap: float) -> bool:
        """Hold ``usd`` before a model call. False (nothing held) if the day would pass the cap."""
        if self._broken:
            raise BlobLedgerError("an earlier cost could not be recorded")
        day, hold = self._today().isoformat(), round(float(usd), 6)
        path = self._write_new(day, {"hold_usd": hold})
        try:
            total, refs = self._sum(day)
        except BlobLedgerError:
            self._drop(day, path)
            raise
        if path not in {r.pathname for r in refs}:
            total += hold  # our own write is not listed yet: count it anyway
        if total > daily_cap + 1e-9:
            self._drop(day, path)
            return False
        self._push(_Reservation(day, path, hold))
        return True

    def add(self, usd: float, calls: int) -> float:
        """Count real spend. Inside a reservation it is settled with it; otherwise own object."""
        res = self._mine()
        if res is not None:
            res.actual_usd = round(res.actual_usd + float(usd), 6)
            return res.actual_usd
        day = self._today().isoformat()
        try:
            self._write_new(day, {"hold_usd": 0.0, "actual_usd": round(float(usd), 6)})
        except BlobLedgerError as exc:
            logger.critical(
                "connector_spend_not_recorded",
                usd=round(float(usd), 6),
                calls=int(calls),
                day=day,
                error=str(exc),
            )
            raise
        return round(float(usd), 6)

    def release(self, usd: float) -> None:
        """Settle our innermost reservation: overwrite our own object with hold and real cost.

        The spend guard keeps real cost at or under the hold, so a failed overwrite leaves a
        hold that is at least the cost. If it ever is not (``actual > hold``) the excess is
        written as a new append-only object; if that write fails too, the cost is logged and
        this ledger refuses every later hold (fails closed) so spend cannot continue unseen.
        """
        res = self._pop()
        if res is None:
            return
        record = {"hold_usd": res.hold_usd, "actual_usd": res.actual_usd, "settled": True}
        try:
            self._store.overwrite_json(res.pathname, record)
            return
        except StoreError:
            logger.critical(
                "connector_spend_settle_failed",
                hold_usd=res.hold_usd,
                actual_usd=res.actual_usd,
                day=res.day,
            )
        excess = round(res.actual_usd - res.hold_usd, 6)
        if excess <= 0:
            return  # the unsettled object still counts its hold, which is at least the cost
        try:
            self._write_new(res.day, {"hold_usd": 0.0, "actual_usd": excess, "settled": True})
        except BlobLedgerError:
            self._broken = True
            logger.critical("connector_spend_excess_not_recorded", excess_usd=excess, day=res.day)


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
        self._global_ledgers: dict[tuple[str, int], DailyLedger] = {}

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
        self._global_ledgers.clear()

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
        # One ledger object per (name, clock): its "an unrecordable cost was seen" flag must
        # outlive a single request, and its reservations are tracked per execution context.
        cache_key = (name, id(today) if today is not None else 0)
        cached = self._global_ledgers.get(cache_key)
        if cached is not None:
            return cached
        ledger: DailyLedger
        if self._client:
            ledger = UpstashLedger(self._client, name, today=today, keep_holds=True)
        elif self._blob is not None:
            ledger = BlobLedger(self._blob, name, today=today)
        else:
            return None
        self._global_ledgers[cache_key] = ledger
        return ledger

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
