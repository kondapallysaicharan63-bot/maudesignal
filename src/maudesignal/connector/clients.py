"""Per-client call counts for the private ``/admin`` "Connected clients" panel.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every keyed tool call (REST ``/v1/tools/*`` or an MCP ``tools/call``) is counted. What is kept
of a caller:

* ``client id``: the first 8 hex characters of the server's peppered key id (an HMAC-SHA256 of
  the key under ``MAUDESIGNAL_KEY_PEPPER``). It cannot be turned back into the key, and it is
  not any part of the key itself.
* ``kind``: ``REST``, ``MCP`` or ``demo`` (the public demo key, whatever the transport).
* ``label``: the key's configured label (``label=KEY`` in the key list), if any.
* the UTC time of the call.

Never stored: the key, a prefix of the key, the question or any tool input, the answer, the
caller's address or user agent.

Where the counts live:

* Upstash Redis when it is configured: one hash per client, ``HINCRBY`` on a per-day field
  (atomic, shared by every instance), expiring at the end of 2026-12-31.
* Otherwise the private record store of feedback and visits (Vercel Blob, or memory locally):
  one tiny object per call at ``clients/<YYYY-MM-DD>/<id>/<kind>/<label or ->/<HHMMSS>-<uuid>
  .json``. The admin view only lists object names, day by day, and never reads objects. These
  objects are deleted by 2026-12-31 with the visit records.

Never in the caller's way: :meth:`ClientCounter.record` only puts the count on a bounded
in-process queue and returns at once; a background thread writes it. When the queue is full
the count is dropped (a warning is logged), and a write that fails is dropped too. On a
serverless host a count still queued when the instance is frozen is written when it wakes, or
lost if it is recycled, so counts can be slightly low but never slow a call.

The panel shows the last :data:`WINDOW_DAYS` UTC days (today included). A day whose listing
fails or is longer than the store's page limit is skipped and the result says ``complete:
false``. ``MAUDESIGNAL_CLIENTS_PANEL=0`` (or ``off``, ``false``, ``no``) turns counting off;
the panel then says it is off.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector.blob_store import BlobRef, RecordStore, StoreError
from maudesignal.connector.store import NAMESPACE, UpstashClient, UpstashError

logger = get_logger(__name__)

PANEL_ENV = "MAUDESIGNAL_CLIENTS_PANEL"
OFF_VALUES = frozenset({"0", "off", "false", "no"})
PREFIX = "clients"
CLIENT_ID_CHARS = 8
NO_LABEL = "-"
KINDS: tuple[str, ...] = ("REST", "MCP", "demo")
WINDOW_DAYS = 30
MAX_PENDING = 1000
LIST_WORKERS = 8
FLUSH_SECONDS = 2.0
REDIS_PREFIX = f"{NAMESPACE}:clients"
REDIS_INDEX = f"{REDIS_PREFIX}:index"
#: Redis counts expire with the other stored records (deleted by 2026-12-31).
EXPIRE_AT = int(datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp())

_HEX_ID = re.compile(r"^[0-9a-f]{8}$")
_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})-[0-9a-f]{12}\.json$")


def panel_enabled(env: dict[str, str] | None = None) -> bool:
    """True unless ``MAUDESIGNAL_CLIENTS_PANEL`` is ``0``, ``off``, ``false`` or ``no``."""
    raw = (os.environ if env is None else env).get(PANEL_ENV, "")
    return raw.strip().lower() not in OFF_VALUES


def short_client_id(key_id: str) -> str | None:
    """First 8 hex of the peppered key id, or None when ``key_id`` is not a hex id."""
    head = key_id[:CLIENT_ID_CHARS].lower()
    return head if _HEX_ID.fullmatch(head) else None


def safe_label(label: str | None) -> str:
    """The key label if it is 1 to 32 letters, digits, ``-`` or ``_``; else ``-``."""
    return label if label and _LABEL.fullmatch(label) else NO_LABEL


@dataclass(frozen=True)
class Hit:
    """One counted call (nothing else about it is kept)."""

    client_id: str
    kind: str
    label: str  # NO_LABEL when the key has none
    at: datetime


class _Row:
    """Running totals for one client while a summary is built."""

    def __init__(self) -> None:
        self.labels: set[str] = set()
        self.kinds: set[str] = set()
        self.today = 0
        self.window = 0
        self.last = ""


class ClientCounter:
    """Counts keyed tool calls per client, written in the background."""

    def __init__(
        self,
        store: RecordStore,
        *,
        enabled: bool,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        redis: UpstashClient | None = None,
        max_pending: int = MAX_PENDING,
    ) -> None:
        """Create the counter.

        Args:
            store: The private record store (the one feedback and visits use).
            enabled: False turns counting and the panel off.
            now: UTC clock (tests).
            redis: Upstash client; when given, counts go there instead of ``store``.
            max_pending: Counts waiting to be written; one more is dropped, never waited for.
        """
        self.store = store
        self.redis = redis
        self.enabled = enabled
        self._now = now
        self._queue: queue.Queue[Hit] = queue.Queue(maxsize=max_pending)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self.dropped = 0

    @property
    def backend(self) -> str:
        """Where counts are written."""
        return "upstash_redis" if self.redis is not None else self.store.backend

    # -- writing ------------------------------------------------------------------------

    def record(self, key_id: str, kind: str, label: str | None = None) -> bool:
        """Queue one count and return at once. Never raises and never waits.

        Returns:
            True when the count was queued; False when off, invalid or dropped (queue full).
        """
        if not self.enabled:
            return False
        try:
            cid = short_client_id(key_id)
            if cid is None or kind not in KINDS:
                return False
            hit = Hit(cid, kind, safe_label(label), self._now().astimezone(UTC))
            self._ensure_worker()
            self._queue.put_nowait(hit)
            return True
        except queue.Full:
            self.dropped += 1
            logger.warning("client_count_dropped", reason="queue_full", kind=kind)
        except Exception as exc:  # noqa: BLE001 - counting must never fail the user's call
            logger.warning("client_count_failed", kind=kind, error_type=type(exc).__name__)
        return False

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="client-count", daemon=True)
                self._worker.start()

    def _run(self) -> None:
        while True:
            hit = self._queue.get()
            try:
                self._write(hit)
            except (StoreError, UpstashError):
                logger.warning("client_count_failed", kind=hit.kind)
            except Exception as exc:  # noqa: BLE001 - a bad write must not stop the worker
                logger.warning("client_count_failed", kind=hit.kind, error_type=type(exc).__name__)
            finally:
                self._queue.task_done()

    def _write(self, hit: Hit) -> None:
        day = hit.at.strftime("%Y-%m-%d")
        if self.redis is not None:
            key = f"{REDIS_PREFIX}:{hit.client_id}"
            fields: list[str | int] = [f"kind:{hit.kind}", 1, "last", _iso(hit.at)]
            if hit.label != NO_LABEL:
                fields += [f"label:{hit.label}", 1]
            self.redis.command("SADD", REDIS_INDEX, hit.client_id)
            self.redis.command("HINCRBY", key, f"day:{day}", 1)
            self.redis.command("HSET", key, *fields)
            self.redis.command("EXPIREAT", key, EXPIRE_AT)
            self.redis.command("EXPIREAT", REDIS_INDEX, EXPIRE_AT)
            return
        path = (
            f"{PREFIX}/{day}/{hit.client_id}/{hit.kind}/{hit.label}/"
            f"{hit.at.strftime('%H%M%S')}-{uuid.uuid4().hex[:12]}.json"
        )
        body: dict[str, Any] = {
            "client_id": hit.client_id,
            "kind": hit.kind,
            "label": "" if hit.label == NO_LABEL else hit.label,
            "at_utc": _iso(hit.at),
        }
        self.store.put_json(path, body)

    def flush(self, timeout: float = FLUSH_SECONDS) -> bool:
        """Wait up to ``timeout`` seconds for queued counts to be written (admin view, tests)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    # -- reading ------------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """One row per client seen in the last :data:`WINDOW_DAYS` UTC days, newest first.

        Raises:
            StoreError: Nothing could be read (the store is down).
        """
        today = self._now().astimezone(UTC).date()
        today_s = today.isoformat()
        if not self.enabled:
            return {"enabled": False, "status": "Off", "today_utc": today_s, "clients": []}
        self.flush()
        days = [(today - timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS)]
        if self.redis is not None:
            rows, complete = self._redis_rows(days, today_s), True
        else:
            rows, complete = self._blob_rows(days, today_s)
        clients = [
            {
                "client_id": cid,
                "label": ", ".join(sorted(r.labels)),
                "kind": ", ".join(k for k in KINDS if k in r.kinds),
                "calls_today": r.today,
                "calls_window": r.window,
                "last_seen_utc": r.last,
            }
            for cid, r in rows.items()
            if r.window
        ]
        clients.sort(key=lambda c: (str(c["last_seen_utc"]), str(c["client_id"])), reverse=True)
        return {
            "enabled": True,
            "status": "On",
            "store": self.backend,
            "today_utc": today_s,
            "window_days": WINDOW_DAYS,
            "complete": complete,
            "clients": clients,
        }

    def _blob_rows(self, days: list[str], today: str) -> tuple[dict[str, _Row], bool]:
        def listing(day: str) -> list[BlobRef] | None:
            try:
                return self.store.list_prefix(f"{PREFIX}/{day}/", strict=True)
            except StoreError:
                logger.warning("client_count_list_failed", day=day)
                return None

        with ThreadPoolExecutor(max_workers=LIST_WORKERS) as pool:
            listings = list(pool.map(listing, days))
        if all(x is None for x in listings):
            raise StoreError("client counts could not be listed")
        rows: dict[str, _Row] = {}
        for refs in listings:
            for ref in refs or []:
                parts = ref.pathname.split("/")
                if len(parts) != 6:
                    continue
                _, day, cid, kind, lbl, name = parts
                m = _NAME.fullmatch(name)
                if not (_DAY.fullmatch(day) and _HEX_ID.fullmatch(cid) and kind in KINDS and m):
                    continue
                row = rows.setdefault(cid, _Row())
                if lbl != NO_LABEL and _LABEL.fullmatch(lbl):
                    row.labels.add(lbl)
                row.kinds.add(kind)
                row.window += 1
                row.today += 1 if day == today else 0
                row.last = max(row.last, f"{day}T{m.group(1)}:{m.group(2)}:{m.group(3)}+00:00")
        return rows, all(x is not None for x in listings)

    def _redis_rows(self, days: list[str], today: str) -> dict[str, _Row]:
        assert self.redis is not None
        wanted = set(days)
        rows: dict[str, _Row] = {}
        try:
            members = self.redis.command("SMEMBERS", REDIS_INDEX) or []
            for cid in members:
                if not isinstance(cid, str) or not _HEX_ID.fullmatch(cid):
                    continue
                flat = self.redis.command("HGETALL", f"{REDIS_PREFIX}:{cid}") or []
                row = rows.setdefault(cid, _Row())
                for name, value in zip(flat[::2], flat[1::2], strict=False):
                    field, value = str(name), str(value)
                    if field.startswith("day:") and field[4:] in wanted and value.isdigit():
                        row.window += int(value)
                        row.today += int(value) if field[4:] == today else 0
                    elif field.startswith("kind:") and field[5:] in KINDS:
                        row.kinds.add(field[5:])
                    elif field.startswith("label:") and _LABEL.fullmatch(field[6:]):
                        row.labels.add(field[6:])
                    elif field == "last":
                        row.last = value
        except UpstashError:
            raise StoreError("client counts could not be read") from None
        return rows


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")
