"""A stored stand-in for openFDA, used for the website's "Recorded example" and for tests.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). Feature F25.

It answers the same :class:`~maudesignal.connector.investigate.Query` objects as the real source,
but from the demo database: the raw openFDA records fetched on 2026-10-27 (``raw_reports``) and
the stored recall and 510(k) rows (``external_sources``). Counts are therefore counts of the
**stored copy**, not of all of openFDA; the investigation labels them so (``source_note``), and
the links still point at the live openFDA query that gives today's number.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from maudesignal.connector.investigate import (
    EventFilter,
    Query,
    Reply,
    narrative_words,
)

_EMPTY = Reply(0, ())


def _narrative(row: dict[str, Any]) -> str:
    parts = [str(t.get("text") or "") for t in row.get("mdr_text") or [] if isinstance(t, dict)]
    return " ".join(parts)


class StoredSource:
    """Serves investigation queries from the demo database (read only)."""

    def __init__(
        self,
        events: list[dict[str, Any]],
        recalls: list[dict[str, Any]] | None = None,
        k510: list[dict[str, Any]] | None = None,
        fetched: str = "",
    ) -> None:
        """Serve the given raw openFDA rows (events, recall rows, 510(k) rows)."""
        self.events = events
        self.recalls = recalls or []
        self.k510 = k510 or []
        self.fetched = fetched

    @classmethod
    def from_db(cls, db_path: Path) -> StoredSource:
        """Load the stored raw reports, recalls and 510(k)s of the database at ``db_path``."""
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            events = [json.loads(r[0]) for r in con.execute("SELECT raw_json FROM raw_reports")]
            recalls = [
                json.loads(r[0])
                for r in con.execute(
                    "SELECT raw_json FROM external_sources WHERE source_type='fda_recall'"
                )
            ]
            k510 = [
                json.loads(r[0])
                for r in con.execute(
                    "SELECT raw_json FROM external_sources WHERE source_type='fda_510k'"
                )
            ]
            fetched = str(
                con.execute("SELECT MIN(fetched_at) FROM raw_reports").fetchone()[0] or ""
            )
        finally:
            con.close()
        return cls(events, recalls, k510, fetched)

    def run(self, query: Query) -> Reply:
        """Answer an event, recall, 510(k) or classification query from the stored rows."""
        params = dict(query.params)
        if query.event is not None:
            return self._events(query.event, params)
        search = params.get("search", "")
        code = search.removeprefix("product_code:")
        limit = int(params.get("limit", "1"))
        if query.endpoint.endswith("recall.json"):
            rows = [r for r in self.recalls if r.get("product_code") == code]
            rows.sort(key=lambda r: str(r.get("event_date_initiated") or ""), reverse=True)
            return Reply(len(rows), tuple(rows[:limit]))
        if query.endpoint.endswith("510k.json"):
            rows = [r for r in self.k510 if r.get("product_code") == code]
            rows.sort(key=lambda r: str(r.get("decision_date") or ""), reverse=True)
            return Reply(len(rows), tuple(rows[:limit]))
        return _EMPTY  # no stored copy of the classification list

    def _events(self, f: EventFilter, params: dict[str, str]) -> Reply:
        words = set(f.keywords)
        hits = [
            r
            for r in self.events
            if any(
                isinstance(d, dict) and d.get("device_report_product_code") == f.product_code
                for d in r.get("device") or []
            )
            and f.start <= str(r.get("date_received") or "") <= f.end
            and (not words or words & narrative_words(_narrative(r)))
            and (not f.sources or str(r.get("report_source_code") or "") in f.sources)
        ]
        count = params.get("count")
        if count == "date_received":
            days: dict[str, int] = {}
            for r in hits:
                day = str(r.get("date_received"))
                days[day] = days.get(day, 0) + 1
            return Reply(len(days), tuple({"time": d, "count": n} for d, n in sorted(days.items())))
        if count == "report_source_code.exact":
            kinds: dict[str, int] = {}
            for r in hits:
                if r.get("report_source_code"):
                    kind = str(r["report_source_code"])
                    kinds[kind] = kinds.get(kind, 0) + 1
            return Reply(
                len(kinds), tuple({"term": k, "count": n} for k, n in sorted(kinds.items()))
            )
        hits.sort(
            key=lambda r: (str(r.get("date_received") or ""), str(r.get("mdr_report_key"))),
            reverse=True,
        )
        return Reply(len(hits), tuple(hits[: int(params.get("limit", "1"))]))
