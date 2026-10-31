"""Per-client call counts for the private ``/admin`` "Connected clients" panel.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every keyed tool call (REST ``/v1/tools/*`` or an MCP ``tools/call``) adds one tiny object to
the same private record store as feedback and visits (Vercel Blob, or memory locally)::

    clients/<YYYY-MM-DD>/<client id>/<kind>/<label or ->/<HHMMSS>-<uuid>.json

The pathname is the whole count (the admin view only lists, it never reads objects), and the
object holds the same four values again. What is kept of a caller:

* ``client id``: the first 8 hex characters of the server's peppered key id (an HMAC-SHA256 of
  the key under ``MAUDESIGNAL_KEY_PEPPER``). It cannot be turned back into the key, and it is
  not any part of the key itself.
* ``kind``: ``REST``, ``MCP`` or ``demo`` (the public demo key, whatever the transport).
* ``label``: the key's configured label (``label=KEY`` in the key list), if any.
* the UTC time of the call.

Never stored: the key, a prefix of the key, the question or any tool input, the answer, the
caller's address or user agent. Records are deleted by 2026-12-31 with the visit records.

Fail-safe: a write that fails or takes longer than :data:`WAIT_SECONDS` is dropped with a
warning and the caller's request goes on. ``MAUDESIGNAL_CLIENTS_PANEL=0`` (or ``off``,
``false``, ``no``) turns counting off; the panel then says "Off".
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any, Literal

from maudesignal.common.logging import get_logger
from maudesignal.connector.blob_store import RecordStore, StoreError

logger = get_logger(__name__)

PANEL_ENV = "MAUDESIGNAL_CLIENTS_PANEL"
OFF_VALUES = frozenset({"0", "off", "false", "no"})
PREFIX = "clients"
CLIENT_ID_CHARS = 8
WAIT_SECONDS = 1.5
NO_LABEL = "-"
ClientKind = Literal["REST", "MCP", "demo"]
KINDS: tuple[str, ...] = ("REST", "MCP", "demo")

_HEX_ID = re.compile(r"^[0-9a-f]{8}$")
_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})-[0-9a-f]{12}\.json$")

# Writes run here so a slow store cannot hold the caller for more than WAIT_SECONDS.
_WRITER = ThreadPoolExecutor(max_workers=4, thread_name_prefix="client-count")


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


class ClientCounter:
    """Counts keyed tool calls per client in the private record store."""

    def __init__(
        self,
        store: RecordStore,
        *,
        enabled: bool,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        wait_seconds: float = WAIT_SECONDS,
    ) -> None:
        """Create the counter.

        Args:
            store: The private record store (the one feedback and visits use).
            enabled: False turns counting and the panel off.
            now: UTC clock (tests).
            wait_seconds: Longest time a call waits for its counter write.
        """
        self.store = store
        self.enabled = enabled
        self._now = now
        self._wait = wait_seconds

    def record(self, key_id: str, kind: str, label: str | None = None) -> bool:
        """Count one call. Never raises; returns True only when the write finished in time."""
        if not self.enabled:
            return False
        try:
            cid = short_client_id(key_id)
            if cid is None or kind not in KINDS:
                return False
            at = self._now().astimezone(UTC)
            day = at.strftime("%Y-%m-%d")
            lbl = safe_label(label)
            path = (
                f"{PREFIX}/{day}/{cid}/{kind}/{lbl}/"
                f"{at.strftime('%H%M%S')}-{uuid.uuid4().hex[:12]}.json"
            )
            body: dict[str, Any] = {
                "client_id": cid,
                "kind": kind,
                "label": "" if lbl == NO_LABEL else lbl,
                "at_utc": at.isoformat(timespec="seconds"),
            }
            _WRITER.submit(self.store.put_json, path, body).result(timeout=self._wait)
            return True
        except FutureTimeout:
            logger.warning("client_count_slow", kind=kind)
        except StoreError:
            logger.warning("client_count_failed", kind=kind)
        except Exception as exc:  # noqa: BLE001 - counting must never fail the user's call
            logger.warning("client_count_failed", kind=kind, error_type=type(exc).__name__)
        return False

    def summary(self) -> dict[str, Any]:
        """One row per client, newest first; reads only the object names.

        Raises:
            StoreError: The store cannot be listed.
        """
        today = self._now().astimezone(UTC).strftime("%Y-%m-%d")
        if not self.enabled:
            return {"enabled": False, "status": "Off", "today_utc": today, "clients": []}
        rows: dict[str, dict[str, Any]] = {}
        for ref in self.store.list_prefix(f"{PREFIX}/"):
            parts = ref.pathname.split("/")
            if len(parts) != 6:
                continue
            _, day, cid, kind, lbl, name = parts
            m = _NAME.fullmatch(name)
            if not (_DAY.fullmatch(day) and _HEX_ID.fullmatch(cid) and kind in KINDS and m):
                continue
            seen = f"{day}T{m.group(1)}:{m.group(2)}:{m.group(3)}+00:00"
            row = rows.setdefault(
                cid,
                {"labels": set(), "kinds": set(), "today": 0, "total": 0, "last": ""},
            )
            if lbl != NO_LABEL and _LABEL.fullmatch(lbl):
                row["labels"].add(lbl)
            row["kinds"].add(kind)
            row["total"] += 1
            row["today"] += 1 if day == today else 0
            row["last"] = max(row["last"], seen)
        clients = [
            {
                "client_id": cid,
                "label": ", ".join(sorted(r["labels"])),
                "kind": ", ".join(k for k in KINDS if k in r["kinds"]),
                "calls_today": r["today"],
                "calls_total": r["total"],
                "last_seen_utc": r["last"],
            }
            for cid, r in rows.items()
        ]
        clients.sort(key=lambda c: (str(c["last_seen_utc"]), str(c["client_id"])), reverse=True)
        return {
            "enabled": True,
            "status": "On",
            "store": self.store.backend,
            "today_utc": today,
            "clients": clients,
        }
