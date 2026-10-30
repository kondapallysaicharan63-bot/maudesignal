"""Search protocol: the searches behind an answer or an evidence pack, as rows.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every copilot tool call is stored in the transcript with its tool name, its
arguments and a preview of its result. This module turns that log into rows
``{tool, dataset, filters, date_from, date_to, count, run_at}`` so an auditor can
repeat each search. It is deterministic and calls no model. Only stored values
are used: a value that was not recorded stays ``None`` and is printed as
"not recorded", never estimated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Dataset each read tool searches (fixed by the tool's implementation in tools.py).
TOOL_DATASETS: dict[str, str] = {
    "overnight_signals": "openFDA MAUDE reports (stored copy)",
    "product_summary": "openFDA MAUDE reports (stored copy)",
    "search_reports": "openFDA MAUDE reports (stored copy)",
    "get_report": "openFDA MAUDE reports (stored copy)",
    "report_sources": "openFDA MAUDE reports (stored copy)",
    "compare_signals": "openFDA MAUDE reports (stored copy)",
    "recalls": "openFDA device recalls (stored copy)",
    "device_510k": "510(k) clearance records (stored copy)",
    "literature": "PubMed abstracts (stored copy)",
    "mhra_alerts": "MHRA (UK) device safety alerts (stored copy)",
    "deadline_check": "21 CFR Part 803 deadline table (no report search)",
    "my_device_types": "Device types chosen by a person (stored list)",
}
# Tools that write or are not searches: left out of the protocol.
NOT_SEARCHES = frozenset({"draft_capa"})

# Argument names printed as their own columns, not as filters.
_DATE_ARGS = ("date_from", "date_to")
# Result keys that hold the count of what the search matched, in priority order.
_COUNT_KEYS = ("report_count", "matched", "alert_count")
# Tools whose result has no single matched-count.
_NO_COUNT = frozenset({"overnight_signals", "compare_signals", "deadline_check", "my_device_types"})

NOT_RECORDED = "not recorded"

# Tool names as shown on screen and in documents (one place; the stored name is unchanged).
TOOL_LABELS: dict[str, str] = {
    "overnight_signals": "weekly_signals",
    "draft_capa": "capa_need_evidence",
}


def tool_label(name: str) -> str:
    """Name of a copilot tool as shown on screen."""
    return TOOL_LABELS.get(name, name)


def iso_z(stamp: str | None) -> str | None:
    """A recorded timestamp as UTC ISO text with a ``Z`` suffix (None stays None).

    ``2026-10-28T20:36:53+00:00`` and ``2026-10-28T20:36:53Z`` both print as
    ``2026-10-28T20:36:53Z``. Text that is not a timestamp is returned unchanged.
    """
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds") + "Z"


@dataclass(frozen=True)
class ProtocolRow:
    """One search, with only values stored in the log."""

    tool: str
    dataset: str
    filters: dict[str, Any]
    date_from: str | None
    date_to: str | None
    count: int | None
    run_at: str | None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict."""
        return asdict(self)

    @property
    def label(self) -> str:
        """Search name as shown to a reader (``overnight_signals`` shows as ``weekly_signals``)."""
        return tool_label(self.tool)

    @property
    def filters_text(self) -> str:
        """Filters as ``key=value`` pairs ('none' when there are none)."""
        if not self.filters:
            return "none"
        return "; ".join(f"{k}={_fmt(v)}" for k, v in sorted(self.filters.items()))

    @property
    def count_text(self) -> str:
        """Count, or 'not recorded' when the stored preview did not include it."""
        return NOT_RECORDED if self.count is None else str(self.count)


def _fmt(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def _preview_int(preview: str, key: str) -> int | None:
    """Integer value of ``"key": N`` in a (possibly truncated) JSON preview."""
    m = re.search(rf'"{re.escape(key)}":\s*(-?\d+)\s*[,}}]', preview)
    return int(m.group(1)) if m else None


def _window(preview: str, key: str) -> tuple[str | None, str | None]:
    """``date_from``/``date_to`` of the ``"key": {...}`` window object in the preview."""
    m = re.search(rf'"{re.escape(key)}":\s*(\{{[^{{}}]*\}})', preview)
    if not m:
        return None, None
    try:
        obj = json.loads(m.group(1))
    except ValueError:
        return None, None
    return obj.get("date_from"), obj.get("date_to")


def _count(name: str, preview: str, args: Mapping[str, Any] | None = None) -> int | None:
    if preview.startswith('{"error"'):
        return None  # the search did not run
    if name == "recalls":
        # A keyword search counts its keyword matches; the stored product-code total
        # (``stored_recall_count``) is not the size of what this search matched.
        if (args or {}).get("query"):
            return _preview_int(preview, "matching_recalls")
        return None
    if name == "get_report":
        return 1 if preview.startswith('{"report_id"') else None
    if name in _NO_COUNT:
        return None
    for key in _COUNT_KEYS:
        n = _preview_int(preview, key)
        if n is not None:
            return n
    return None


def row_from_call(call: Mapping[str, Any], run_at: str | None = None) -> ProtocolRow | None:
    """Protocol row for one stored tool call (None for writes such as ``draft_capa``)."""
    name = str(call.get("name", ""))
    if not name or name in NOT_SEARCHES:
        return None
    args: Mapping[str, Any] = call.get("arguments") or {}
    preview = str(call.get("result_preview") or "")
    filters = {k: v for k, v in args.items() if k not in _DATE_ARGS and v not in (None, "", [])}
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from is None and date_to is None:
        # Window the tool itself used, as recorded in its own result.
        date_from, date_to = _window(preview, "current_window")
        if date_from is None:
            date_from, date_to = _window(preview, "window")
    return ProtocolRow(
        tool=name,
        dataset=TOOL_DATASETS.get(name, "stored data (dataset not mapped)"),
        filters=filters,
        date_from=date_from,
        date_to=date_to,
        count=_count(name, preview, args),
        run_at=iso_z(run_at),
    )


def protocol_from_calls(
    calls: Iterable[Mapping[str, Any]], run_at: str | None = None
) -> list[ProtocolRow]:
    """Rows for a list of stored tool calls, in the order they ran."""
    rows = (row_from_call(c, run_at) for c in calls)
    return [r for r in rows if r is not None]


def protocol_from_transcript(transcript: Mapping[str, Any]) -> list[ProtocolRow]:
    """Rows for one stored transcript or investigation.

    ``run_at`` is the time the transcript was recorded (``recorded_at_utc``, or
    ``run_at`` / ``recorded_at`` for other records): calls are not timestamped one by one.
    """
    run_at = next(
        (
            str(transcript[k])
            for k in ("recorded_at_utc", "run_at", "recorded_at")
            if transcript.get(k)
        ),
        None,
    )
    return protocol_from_calls(transcript.get("tool_calls") or [], run_at)


def load_transcripts(directory: Path) -> list[dict[str, Any]]:
    """Stored transcripts (``*.json`` with a ``tool_calls`` list) in name order."""
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool_calls"), list):
            obj.setdefault("_file", path.name)
            out.append(obj)
    return out


def protocol_for_capa(transcripts: Iterable[Mapping[str, Any]], capa_id: str) -> list[ProtocolRow]:
    """Rows of every stored transcript that created the given evidence pack."""
    rows: list[ProtocolRow] = []
    for t in transcripts:
        if capa_id in (t.get("capa_ids") or []):
            rows.extend(protocol_from_transcript(t))
    return rows
