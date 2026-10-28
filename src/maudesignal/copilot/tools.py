"""Tools the copilot model can call.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every tool is deterministic, reads only stored data, and returns plain JSON
with the exact numbers and report ids it used, so the citation gate can
re-verify anything the model repeats. Besides MAUDE, three tools reach the
sources a QA/RA analyst otherwise opens in separate tabs — FDA recalls, 510(k)
clearance records and PubMed abstracts — from copies stored by
``scripts/seed_sources.py``, so the gate can verify those claims too. The only tool that writes is
``draft_capa``, and it can only create a *draft* — approval is a human action
outside the model's reach (see ``copilot.actions``).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from maudesignal.copilot.actions import draft_capa
from maudesignal.gate.cfr import CFR_SECTIONS
from maudesignal.gate.evidence import EvidenceStore
from maudesignal.monitor.deterioration import detect_from_database, parse_yyyymmdd
from maudesignal.monitor.digest import digest_from_database, digest_to_dict
from maudesignal.storage.database import Database

MAX_IDS = 10
EXCERPT_CHARS = 600
ABSTRACT_CHARS = 900

ToolFn = Callable[..., dict[str, Any]]


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


@dataclass
class ToolContext:
    """Everything a tool may read or write."""

    db: Database
    store: EvidenceStore
    actor: str = "copilot:muse-spark"
    created_capas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def overnight_signals(ctx: ToolContext, as_of: str | None = None) -> dict[str, Any]:
    """What changed this week: new kind of problem, more serious, or more reports."""
    latest = detect_from_database(ctx.db).window.as_of
    as_of_date = parse_yyyymmdd(as_of) if as_of else None
    note = None
    if as_of_date is not None and as_of_date > latest:
        # openFDA lags real time by weeks: a window ending "today" holds no reports and
        # would hide the real signal, so the latest stored date is used instead.
        note = (
            f"requested as_of {_ymd(as_of_date)} is after the latest stored report "
            f"({_ymd(latest)}); the window ends on {_ymd(latest)}"
        )
        as_of_date = None
    digest = digest_from_database(ctx.db, detect_from_database(ctx.db, as_of_date))
    d = digest_to_dict(digest)
    w = digest.result.window
    out: dict[str, Any] = {
        "as_of": _ymd(w.as_of),
        "headline": d["headline"],
        "current_window": {"date_from": _ymd(w.current_start), "date_to": _ymd(w.current_end)},
        "baseline_window": {
            "date_from": _ymd(w.baseline_start),
            "date_to": _ymd(w.baseline_end),
        },
        "rules": d["rules"],
        **({"note": note} if note else {}),
        # Flagged codes most urgent first, each with the sentence explaining its rank.
        "ranking": d["ranking"],
        "device_types": d["device_types"],
        "window_brands": d["window_brands"],
        "signals": [],
    }
    order = {r["product_code"]: r["rank"] for r in d["ranking"]}
    for s in sorted(
        d["signals"], key=lambda x: (order.get(x["product_code"], 1_000), x["product_code"])
    ):
        out["signals"].append(
            {
                k: (v[:MAX_IDS] if isinstance(v, list) else v)
                for k, v in s.items()
                if k not in ("baseline_report_ids", "baseline_severe_report_ids")
            }
        )
    return out


def product_summary(
    ctx: ToolContext,
    product_code: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Counts and event-type shares for one product code, plus its 510(k) device."""
    rows = ctx.store.select(product_code=product_code, date_from=date_from, date_to=date_to)
    by_type = Counter((r.event_type or "Unknown") for r in rows)
    total = len(rows)
    devices = [
        {"k_number": d.k_number, "device_name": d.device_name, "company": d.company_name}
        for d in ctx.store.devices
        if d.product_code == product_code
    ]
    dates = sorted(r.date_received for r in rows if r.date_received)
    return {
        "product_code": product_code,
        "date_from": date_from,
        "date_to": date_to,
        "report_count": total,
        "event_type_counts": dict(by_type),
        "event_type_share_pct": {
            k: round(100.0 * v / total, 1) for k, v in by_type.items() if total
        },
        "earliest_date_received": dates[0] if dates else None,
        "latest_date_received": dates[-1] if dates else None,
        "devices_510k": devices,
        "example_report_ids": [r.report_id for r in rows[:MAX_IDS]],
    }


def search_reports(
    ctx: ToolContext,
    product_code: str | None = None,
    keyword: str | None = None,
    event_type: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Find reports; returns narrative excerpts that can be quoted verbatim."""
    rows = ctx.store.select(product_code=product_code, event_type=event_type)
    if keyword:
        kw = keyword.lower()
        rows = [r for r in rows if kw in r.text.lower()]
    rows = sorted(rows, key=lambda r: r.date_received or "", reverse=True)
    limit = max(1, min(int(limit), 10))
    return {
        "matched": len(rows),
        "reports": [
            {
                "report_id": r.report_id,
                "product_code": r.product_code,
                "event_type": r.event_type,
                "date_received": r.date_received,
                "brand_name": r.brand_name,
                "narrative_excerpt": r.text[:EXCERPT_CHARS],
            }
            for r in rows[:limit]
        ],
    }


def get_report(ctx: ToolContext, report_id: str) -> dict[str, Any]:
    """Full stored narrative for one MAUDE report."""
    r = ctx.store.record(report_id)
    if r is None:
        return {"error": f"report {report_id} not found"}
    return {
        "report_id": r.report_id,
        "product_code": r.product_code,
        "event_type": r.event_type,
        "date_received": r.date_received,
        "manufacturer": r.manufacturer,
        "brand_name": r.brand_name,
        "narrative": r.text[:3000],
    }


def deadline_check(
    ctx: ToolContext, awareness_date: str, five_day_trigger: bool = False
) -> dict[str, Any]:
    """Advisory MDR clock from the date the manufacturer became aware.

    30 calendar days under 21 CFR 803.50; 5 work days under 21 CFR 803.53 when
    remedial action is needed to prevent an unreasonable risk of substantial
    harm, or when FDA requests it. This does not decide reportability.
    """
    _ = ctx
    start = parse_yyyymmdd(awareness_date)
    if five_day_trigger:
        d, added = start, 0
        while added < 5:
            d += timedelta(days=1)
            if d.weekday() < 5:
                added += 1
        due, section, basis = d, "803.53", "5 work days"
    else:
        due, section, basis = start + timedelta(days=30), "803.50", "30 calendar days"
    return {
        "awareness_date": _ymd(start),
        "due_date": _ymd(due),
        "basis": basis,
        "regulation_section": section,
        "regulation_title": CFR_SECTIONS[section],
        "advisory": "Reportability is a human regulatory decision; this is a clock only.",
    }


def draft_capa_tool(
    ctx: ToolContext,
    product_code: str,
    title: str,
    problem_statement: str,
    report_ids: list[str],
) -> dict[str, Any]:
    """Create a CAPA *draft* (status=draft). A named human must approve it."""
    unknown = [rid for rid in report_ids if ctx.store.record(rid) is None]
    if unknown or not report_ids:
        return {"error": "every report_id must exist in the store", "unknown": unknown}
    row = draft_capa(
        ctx.db,
        product_code=product_code,
        title=title,
        problem_statement=problem_statement,
        report_ids=report_ids,
        actor=ctx.actor,
    )
    ctx.created_capas.append(row.capa_id)
    return {
        "capa_id": row.capa_id,
        "status": row.status,
        "next_step": "Awaiting approval by a named QA/RA reviewer. Nothing has been filed.",
    }


def recalls(
    ctx: ToolContext,
    product_code: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Stored openFDA device recalls for one product code, newest first."""
    rows = ctx.store.select_recalls(product_code=product_code, date_from=date_from, date_to=date_to)
    rows = sorted(rows, key=lambda r: (r.date_initiated or "", r.recall_number), reverse=True)
    limit = max(1, min(int(limit), 20))
    return {
        "product_code": product_code,
        "date_from": date_from,
        "date_to": date_to,
        "stored_recall_count": len(rows),
        "source": "openFDA device/recall.json (stored copy)",
        "recalls": [
            {
                "recall_number": r.recall_number,
                "event_number": r.event_number,
                "recalling_firm": r.recalling_firm,
                "recall_status": r.recall_status,
                "date_initiated": r.date_initiated,
                "k_numbers": list(r.k_numbers),
                "product_description": r.product_description[:300],
                "reason_for_recall": r.reason_for_recall[:EXCERPT_CHARS],
            }
            for r in rows[:limit]
        ],
    }


def device_510k(ctx: ToolContext, k_number: str) -> dict[str, Any]:
    """510(k) record for one K-number (catalog first, then stored openFDA 510(k) data)."""
    k = k_number.strip().upper()
    dev = ctx.store.device(k)
    source = "510(k) AI/ML catalog"
    full = ctx.store.clearance(k)
    if dev is None:
        dev, source = full, "openFDA device/510k.json (stored copy)"
    if dev is None:
        return {"error": f"{k} not in the 510(k) catalog or stored 510(k) records"}
    detail = full or dev
    return {
        "k_number": dev.k_number,
        "source": source,
        "applicant": detail.company_name,
        "device_name": dev.device_name,
        "product_code": dev.product_code,
        "decision_date": detail.decision_date,
        "decision_code": detail.decision_code,
        "statement_or_summary": detail.statement_or_summary,
        "recalls_citing_this_k_number": [
            r.recall_number for r in ctx.store.recalls if k in r.k_numbers
        ][:MAX_IDS],
    }


def literature(
    ctx: ToolContext,
    product_code: str | None = None,
    query: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Stored PubMed articles (by the product code they were fetched for and/or keywords)."""
    rows = list(ctx.store.literature)
    if product_code:
        rows = [a for a in rows if (a.product_code or "").upper() == product_code.upper()]
    if query:
        words = [w for w in query.lower().split() if w]
        rows = [a for a in rows if all(w in a.text.lower() for w in words)]
    rows = sorted(rows, key=lambda a: (a.year or 0, a.pmid), reverse=True)
    limit = max(1, min(int(limit), 10))
    return {
        "matched": len(rows),
        "source": "PubMed via NCBI E-utilities (stored copy)",
        "articles": [
            {
                "pmid": a.pmid,
                "title": a.title,
                "year": a.year,
                "journal": a.journal,
                "abstract_excerpt": a.abstract[:ABSTRACT_CHARS],
            }
            for a in rows[:limit]
        ],
    }


def report_sources(
    ctx: ToolContext,
    product_code: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Who filed the stored reports: counts by source, plus those not filed by a manufacturer."""
    rows = ctx.store.select(product_code=product_code, date_from=date_from, date_to=date_to)
    stored = [r.date_received for r in ctx.store.select(product_code=product_code)]
    latest = max((d for d in stored if d), default=None)
    by_source = Counter(r.source or "unknown" for r in rows)
    others = sorted(
        (r for r in rows if r.source and r.source != "manufacturer"),
        key=lambda r: (r.date_received or "", r.report_id),
        reverse=True,
    )
    return {
        "product_code": product_code,
        "date_from": date_from,
        "date_to": date_to,
        "report_count": len(rows),
        "latest_date_received": latest,
        **(
            {"note": f"no stored {product_code} report is dated after {latest}"}
            if latest and date_from and date_from > latest
            else {}
        ),
        "source_counts": dict(sorted(by_source.items())),
        "non_manufacturer_count": len(others),
        "non_manufacturer_reports": [
            {
                "report_id": r.report_id,
                "date_received": r.date_received,
                "source": r.source,
                "brand_name": r.brand_name,
            }
            for r in others[:MAX_IDS]
        ],
        "claim_hint": "state counts with source_count claims; source is one of manufacturer, "
        "user facility, voluntary, distributor, non-manufacturer",
    }


def my_device_types(ctx: ToolContext) -> dict[str, Any]:
    """The device types a person chose to watch, and their pinned notes (read-only)."""
    from maudesignal.copilot.memory import load_memory

    mem = load_memory(ctx.db).to_dict()
    mem["note"] = (
        "Chosen by a person; the copilot cannot change this list and never decides which "
        "devices are similar."
    )
    return mem


def compare_signals(
    ctx: ToolContext, product_codes: list[str] | None = None, as_of: str | None = None
) -> dict[str, Any]:
    """Side-by-side numbers for the chosen device types (default: the remembered list)."""
    from maudesignal.copilot.memory import load_memory
    from maudesignal.monitor.compare import compare_signals as _compare

    codes = list(product_codes or load_memory(ctx.db).device_types)
    if not codes:
        return {
            "error": "no device types given and none remembered; ask the user which "
            "product codes to compare"
        }
    out = _compare(ctx.db, codes, parse_yyyymmdd(as_of) if as_of else None).to_dict()
    out["claim_hint"] = (
        "state this-week counts with count claims (date_from/date_to = window) and "
        "shares with share claims; label each change with its `change` words"
    )
    return out


def mhra_alerts(
    ctx: ToolContext, product_code: str | None = None, query: str | None = None
) -> dict[str, Any]:
    """Stored MHRA (UK) device safety alerts: regulator context, never FDA evidence."""
    q = (query or "").lower()
    rows = [
        a
        for a in ctx.store.alerts
        if (not product_code or (a.product_code or "").upper() == product_code.upper())
        and (not q or q in a.text.lower())
    ]
    rows.sort(key=lambda a: (a.issued or "", a.alert_id), reverse=True)
    return {
        "regulator": "MHRA (UK)",
        "note": "UK regulator context only: not FDA data, not counted in any MAUDE number. "
        "Quote with a quote claim whose source_id is 'mhra:<alert_id>'.",
        "alert_count": len(rows),
        "alerts": [
            {
                "alert_id": a.alert_id,
                "title": a.title,
                "issued": a.issued,
                "description": a.description[:ABSTRACT_CHARS],
                "url": a.url,
            }
            for a in rows[:MAX_IDS]
        ],
    }


TOOLS: dict[str, ToolFn] = {
    "overnight_signals": overnight_signals,
    "product_summary": product_summary,
    "search_reports": search_reports,
    "get_report": get_report,
    "deadline_check": deadline_check,
    "draft_capa": draft_capa_tool,
    "recalls": recalls,
    "device_510k": device_510k,
    "literature": literature,
    "report_sources": report_sources,
    "my_device_types": my_device_types,
    "compare_signals": compare_signals,
    "mhra_alerts": mhra_alerts,
}

_STR = {"type": "string"}
_YMD = {"type": "string", "description": "YYYYMMDD"}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "overnight_signals",
            "description": "What changed: product codes where reports suddenly increased, "
            "reports are more serious than usual, or there is a new kind of problem (each "
            "signal's `label` gives these plain words), in the 7 days ending on the latest "
            "stored report date vs a 4-week baseline, "
            "with exact counts, report ids and the ranking with its reasons. Omit as_of: "
            "openFDA lags real time, so the default is the latest stored date, not today.",
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "description": "YYYYMMDD; optional, only for an earlier week",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "product_summary",
            "description": "Report counts and event-type shares for one product code "
            "(optionally within a date_received window), plus its 510(k) devices.",
            "parameters": {
                "type": "object",
                "properties": {"product_code": _STR, "date_from": _YMD, "date_to": _YMD},
                "required": ["product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reports",
            "description": "Search stored MAUDE reports; returns narrative excerpts you may "
            "quote verbatim with their report_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": _STR,
                    "keyword": _STR,
                    "event_type": {"type": "string", "enum": ["Malfunction", "Injury", "Death"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_report",
            "description": "Full stored narrative for one MAUDE report id.",
            "parameters": {
                "type": "object",
                "properties": {"report_id": _STR},
                "required": ["report_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deadline_check",
            "description": "Advisory MDR due date from the awareness date (30 calendar days, "
            "or 5 work days when five_day_trigger is true). Does not decide reportability.",
            "parameters": {
                "type": "object",
                "properties": {"awareness_date": _YMD, "five_day_trigger": {"type": "boolean"}},
                "required": ["awareness_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_capa",
            "description": "Record a CAPA-need evidence pack for a named person to review: the "
            "supporting report ids and a factual problem statement. It does not decide that a "
            "CAPA is needed (the company's own CAPA-need form decides). Use only when the user "
            "asks for a CAPA-need evidence pack or a corrective action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": _STR,
                    "title": _STR,
                    "problem_statement": _STR,
                    "report_ids": {"type": "array", "items": _STR, "minItems": 1},
                },
                "required": ["product_code", "title", "problem_statement", "report_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recalls",
            "description": "FDA device recalls (openFDA recall database) for one product code, "
            "newest first: recall numbers, firm, status, date initiated, cited 510(k)s and the "
            "reason for recall (quotable with the recall_number as source_id). "
            "stored_recall_count is the exact count for the filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": _STR,
                    "date_from": {"type": "string", "description": "YYYYMMDD (date initiated)"},
                    "date_to": {"type": "string", "description": "YYYYMMDD (date initiated)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "device_510k",
            "description": "510(k) clearance record for one K-number: applicant, device name, "
            "product code, decision date/code, summary-or-statement, and recalls citing it.",
            "parameters": {
                "type": "object",
                "properties": {"k_number": _STR},
                "required": ["k_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "literature",
            "description": "Published literature (PubMed) stored for a product code and/or "
            "matching keywords: PMID, title, year, journal and an abstract excerpt you may "
            "quote verbatim with the PMID as source_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": _STR,
                    "query": _STR,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_sources",
            "description": "Who filed the stored reports for a product code: counts by "
            "openFDA report source (manufacturer, user facility, voluntary, distributor) and the "
            "reports not filed by a manufacturer (id, date, source, brand).",
            "parameters": {
                "type": "object",
                "properties": {"product_code": _STR, "date_from": _YMD, "date_to": _YMD},
                "required": ["product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_device_types",
            "description": "The device types (FDA product codes) the user chose to watch, "
            "and notes they pinned. Read-only: only a person changes this list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_signals",
            "description": "Compare device types side by side for the current 7-day window: "
            "this week's count, baseline weekly mean, ratio, Injury/Death count and share, "
            "reports not filed by a manufacturer, and the plain-words change. Omit "
            "product_codes to use the device types the user chose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_codes": {"type": "array", "items": _STR},
                    "as_of": _YMD,
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mhra_alerts",
            "description": "Stored MHRA (UK regulator) medical device safety alerts, filtered "
            "by the product code they were fetched for and/or a keyword. UK context only: "
            "never FDA evidence and never counted in MAUDE numbers.",
            "parameters": {
                "type": "object",
                "properties": {"product_code": _STR, "query": _STR},
            },
        },
    },
]


def call_tool(ctx: ToolContext, name: str, arguments_json: str) -> dict[str, Any]:
    """Dispatch a model tool call. Errors are returned to the model, never raised."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            return {"error": "arguments must be a JSON object"}
        return fn(ctx, **args)
    except (TypeError, ValueError, KeyError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
