"""Deterministic sentences, with claims, from tool results already fetched in this answer.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Used only when the live time budget ends before Muse Spark writes its answer (a model round
timed out or failed, or there is no time left for it). Without this the tool results the
copilot already read were thrown away and the visitor saw "I have no verified answer"
(live site, 2026-11-03/04: model round 2 hit the 25 s per-call timeout after round 1 had
fetched the LLZ counts).

Nothing here is model text and nothing here is trusted: every sentence carries the claims
it makes and goes through the same claim gate (``maudesignal.gate.verify_answer``) as a
model answer. A sentence that does not verify is withheld like any other. This is a fixed
template over stored numbers, not a prompt, so it does not belong in a Skill.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from maudesignal.gate import Claim
from maudesignal.gate.claims import CountClaim, RecordClaim

#: Event types the gate can count (MAUDE's three); anything else is left out of the split.
_EVENT_TYPES = ("Malfunction", "Injury", "Death")
#: Most sentences built (each product_summary gives two, a search gives one).
MAX_SENTENCES = 6
#: Most report ids named from one search.
MAX_IDS_PER_SEARCH = 2

ToolOutput = tuple[str, dict[str, Any], dict[str, Any]]
"""``(tool name, arguments, full result)`` of one tool call."""


def _day(ymd: str | None) -> date | None:
    digits = (ymd or "").replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError:
        return None


def _md(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}"


def span_words(date_from: str | None, date_to: str | None) -> str | None:
    """'from August 25 to August 31, 2026' (None when either date is missing or invalid)."""
    a, b = _day(date_from), _day(date_to)
    if a is None or b is None:
        return None
    if a.year == b.year:
        return f"from {_md(a)} to {_md(b)}, {b.year}"
    return f"from {_md(a)}, {a.year} to {_md(b)}, {b.year}"


def _reports(n: int) -> str:
    return f"{n} report" if n == 1 else f"{n} reports"


def _summary_sentences(out: dict[str, Any]) -> list[tuple[str, list[Claim]]]:
    code = str(out.get("product_code") or "").strip().upper()
    total = out.get("report_count")
    if not code or not isinstance(total, int) or out.get("no_data_for_range"):
        return []
    d_from, d_to = out.get("date_from"), out.get("date_to")
    span = span_words(d_from, d_to)
    if (d_from or d_to) and span is None:
        return []  # an open-ended range cannot be said plainly; leave it out
    where = f" received {span}" if span else " stored"
    lead_claims: list[Claim] = [CountClaim(code, total, None, d_from, d_to)]
    out_list: list[tuple[str, list[Claim]]] = [
        (f"{code} had {_reports(total)}{where}.", lead_claims)
    ]
    counts = out.get("event_type_counts") or {}
    known = {t.lower() for t in _EVENT_TYPES}
    # the stored key is kept as the claim's event type, so the gate recounts the same thing
    parts: list[tuple[str, int]] = [
        (str(t), int(n))
        for t, n in counts.items()
        if str(t).lower() in known and isinstance(n, int) and n > 0
    ]
    if total and parts:
        words = [f"{n} {t.lower()} {'report' if n == 1 else 'reports'}" for t, n in parts]
        listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
        claims: list[Claim] = [CountClaim(code, n, t, d_from, d_to) for t, n in parts]
        out_list.append((f"By event type, these were {listed}.", claims))
    return out_list


def _search_sentences(args: dict[str, Any], out: dict[str, Any]) -> list[tuple[str, list[Claim]]]:
    if out.get("no_data_for_range") or args.get("keyword"):
        return []
    rows = [r for r in out.get("reports") or [] if isinstance(r, dict) and r.get("report_id")]
    if not rows:
        return []
    picked = rows[:MAX_IDS_PER_SEARCH]
    code = str(picked[0].get("product_code") or "").strip().upper()
    # A moved range is named by the gate's "(Dates used: ...)" note, never by the request.
    span = (
        None if out.get("date_adjusted") else span_words(args.get("date_from"), args.get("date_to"))
    )
    ids: list[str] = []
    for r in picked:
        kind = str(r.get("event_type") or "").strip().lower()
        known = kind in {t.lower() for t in _EVENT_TYPES}
        ids.append(f"report {r['report_id']}" + (f" ({kind})" if known else ""))
    where = f"the stored {code} reports" if code else "the stored reports"
    when = f" received {span}" if span else ""
    listed = " and ".join(ids)
    verb = "is" if len(ids) == 1 else "are"
    # ids first: a year right before "report" would read as a count to the gate
    text = f"{listed[0].upper()}{listed[1:]} {verb} among {where}{when}."
    # the gate checks each id is stored (and for this product code)
    claims: list[Claim] = [RecordClaim(str(r["report_id"]), code or None) for r in picked]
    return [(text, claims)]


def sentences_from_tools(outputs: list[ToolOutput]) -> list[tuple[str, list[Claim]]]:
    """Plain sentences with claims for the counts and report ids the tools returned.

    Only ``product_summary`` (report counts, event-type split) and ``search_reports``
    (report ids, no keyword filter) results are used; repeats are dropped. The caller must
    pass the result through the claim gate before showing any of it.
    """
    built: list[tuple[str, list[Claim]]] = []
    seen: set[str] = set()
    for name, args, out in outputs:
        if not isinstance(out, dict) or "error" in out:
            continue
        if name == "product_summary":
            found = _summary_sentences(out)
        elif name == "search_reports":
            found = _search_sentences(args, out)
        else:
            continue
        for text, claims in found:
            if text not in seen:
                seen.add(text)
                built.append((text, claims))
    return built[:MAX_SENTENCES]
