"""Public links a reader can open to see a fact (no keys in any of them).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import urlencode

from maudesignal.gate import (
    CountClaim,
    DeviceClaim,
    LiteratureClaim,
    QuoteClaim,
    RecallClaim,
    RecallCountClaim,
    RecordClaim,
    RegulationClaim,
    ShareClaim,
    SourceCountClaim,
)
from maudesignal.gate.evidence import EvidenceStore
from maudesignal.monitor.live_check import verify_url

RECALL_ENDPOINT = "https://api.fda.gov/device/recall.json"
K510_ENDPOINT = "https://api.fda.gov/device/510k.json"
EVENT_ENDPOINT = "https://api.fda.gov/device/event.json"
ECFR_SECTION = "https://www.ecfr.gov/current/title-21/section-"
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"

_RECALL_NO = re.compile(r"^[A-Z]-\d{4}-\d{4}$")
_K_NO = re.compile(r"^[KDkd][Ee]?[Nn]?\d{6}$")
_REPORT_ID = re.compile(r"^[A-Za-z0-9-]{1,24}$")
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)  # fmt: skip
_MONTHS = {m.lower(): i for i, m in enumerate(_MONTH_NAMES, start=1)}


def _one(endpoint: str, search: str) -> str:
    return f"{endpoint}?{urlencode({'search': search, 'limit': 1})}"


def report_link(report_id: str) -> str:
    """Query on openFDA for one MAUDE report."""
    return _one(EVENT_ENDPOINT, f"mdr_report_key:{report_id}")


def recall_link(recall_number: str) -> str:
    """Query on openFDA for one recall number."""
    return _one(RECALL_ENDPOINT, f'product_res_number:"{recall_number}"')


def product_recalls_link(product_code: str) -> str:
    """Query on openFDA for every recall of a product code."""
    return _one(RECALL_ENDPOINT, f"product_code:{product_code}")


def k510_link(k_number: str) -> str:
    """Query on openFDA for one 510(k)."""
    return _one(K510_ENDPOINT, f"k_number:{k_number.upper()}")


def cfr_link(section: str) -> str:
    """The eCFR page for a 21 CFR section."""
    return f"{ECFR_SECTION}{section}"


def pubmed_link(pmid: str) -> str:
    """PubMed page."""
    return f"{PUBMED}{pmid}/"


def counts_link(product_code: str, start: str | None, end: str | None) -> str:
    """Query on openFDA whose ``meta.results.total`` is the report count (YYYYMMDD bounds)."""
    return verify_url(product_code, start, end)


EVENT_TYPE_FIELD = "event_type.exact"


def event_type_counts_link(product_code: str, start: str | None, end: str | None) -> str:
    """Query on openFDA that counts a product code's reports by event type (YYYYMMDD bounds).

    The result lists one count per event type ("Injury", "Malfunction", ...): the count of
    one type, and (summed) the total a share is taken of. An event type with no report is
    absent from the list, which is how openFDA shows a count of 0.
    """
    return verify_url(product_code, start, end, count=EVENT_TYPE_FIELD)


Window = tuple[str | None, str | None]
#: Product code -> the ``date_received`` window of which the stored snapshot holds *every*
#: openFDA report (``(None, None)``: every report of the code).
Coverage = Mapping[str, Window]


def stored_coverage(manifest: Mapping[str, Any], store: EvidenceStore) -> dict[str, Window]:
    """Per product code, the window the stored snapshot holds completely (from the manifest).

    A code is listed only when its seed query is marked complete, stored as many reports as
    openFDA matched at fetch time, and the evidence store holds exactly that many reports of
    the code, all inside the query's window. Only then does an openFDA query over (part of)
    that window count the same reports the gate counted.

    Args:
        manifest: The seed manifest (``data/demo/SEED_MANIFEST.json``).
        store: The evidence store the gate checks against.

    Returns:
        ``{product_code: (start, end)}`` with YYYYMMDD bounds or None for an open end.
    """
    out: dict[str, Window] = {}
    seen: set[str] = set()
    for q in manifest.get("queries") or []:
        if not isinstance(q, dict):
            continue
        code = str(q.get("product_code") or "")
        if code in seen:  # two seed queries for one code: no single window to vouch for
            out.pop(code, None)
            continue
        seen.add(code)
        stored, total = q.get("records_stored"), q.get("matching_total_at_fetch")
        if not code or q.get("complete") is not True or not isinstance(stored, int):
            continue
        if stored != total:
            continue
        start = str(q.get("date_received_start") or "") or None
        end = str(q.get("date_received_end") or "") or None
        in_window = store.select(product_code=code, date_from=start, date_to=end)
        if len(in_window) != stored or len(store.select(product_code=code)) != stored:
            continue
        out[code] = (start, end)
    return out


def scoped_window(
    product_code: str, date_from: str | None, date_to: str | None, coverage: Coverage
) -> Window | None:
    """The part of a claim's window the snapshot holds completely, or None.

    Stored reports of the code exist only inside its covered window, so the stored count for
    the claim's window equals the openFDA count for this intersection.
    """
    if product_code not in coverage:
        return None
    cov_start, cov_end = coverage[product_code]
    start = max((d for d in (date_from, cov_start) if d), default=None)
    end = min((d for d in (date_to, cov_end) if d), default=None)
    if start and end and start > end:
        return None
    return start, end


def _window_words(start: str | None, end: str | None) -> str:
    def spoken(v: str) -> str:
        return f"{_MONTH_NAMES[int(v[4:6]) - 1]} {int(v[6:])}, {v[:4]}"

    if start and end:
        return f", {spoken(start)} to {spoken(end)}"
    if start:
        return f", from {spoken(start)}"
    if end:
        return f", through {spoken(end)}"
    return ""


def _event_type_link(
    product_code: str, date_from: str | None, date_to: str | None, coverage: Coverage | None
) -> tuple[str, str] | None:
    window = scoped_window(product_code, date_from, date_to, coverage or {})
    if window is None:
        return None
    label = f"openFDA count by event type for {product_code}{_window_words(*window)}"
    return event_type_counts_link(product_code, *window), label


def is_report_id(value: str) -> bool:
    """True when ``value`` looks like a MAUDE report id."""
    return bool(_REPORT_ID.match(value))


def claim_link(claim: object, coverage: Coverage | None = None) -> tuple[str, str] | None:
    """Link and label for a gate claim (a live answer), or None when it has none.

    A count by event type and a share are linked to the openFDA count-by-event-type query
    only when ``coverage`` (see :func:`stored_coverage`) shows the snapshot holds every report
    of the code in the claim's window, so the query shows the figure the gate recomputed. A
    plain count of a covered code is scoped the same way.
    """
    if isinstance(claim, QuoteClaim):
        who = claim.attributed_to
        if _RECALL_NO.match(who.upper()):
            return recall_link(who.upper()), "openFDA recall"
        if who.isdigit() and claim.source_id:
            return pubmed_link(who), "PubMed"
        return report_link(who), "openFDA report"
    if isinstance(claim, RecordClaim):
        return report_link(claim.report_id), "openFDA report"
    if isinstance(claim, CountClaim):
        if claim.event_type:
            return _event_type_link(claim.product_code, claim.date_from, claim.date_to, coverage)
        if coverage is not None and claim.product_code in coverage:
            window = scoped_window(claim.product_code, claim.date_from, claim.date_to, coverage)
            if window is None:
                return None
            return counts_link(claim.product_code, *window), "openFDA count"
        return counts_link(claim.product_code, claim.date_from, claim.date_to), "openFDA count"
    if isinstance(claim, ShareClaim):
        return _event_type_link(claim.product_code, claim.date_from, claim.date_to, coverage)
    if isinstance(claim, SourceCountClaim):
        return None  # a source-filtered count is not the number the link shows
    if isinstance(claim, RecallClaim):
        return recall_link(claim.recall_number.upper()), "openFDA recall"
    if isinstance(claim, RecallCountClaim):
        return product_recalls_link(claim.product_code), "openFDA recalls"
    if isinstance(claim, DeviceClaim):
        return k510_link(claim.k_number), "openFDA 510(k)"
    if isinstance(claim, RegulationClaim):
        return cfr_link(claim.section), "eCFR"
    if isinstance(claim, LiteratureClaim):
        return pubmed_link(claim.pmid), "PubMed"
    return None


def recorded_claim_link(claim: dict[str, Any]) -> tuple[str, str] | None:
    """Link for a claim in a stored transcript (it keeps only the kind and evidence ids)."""
    kind = str(claim.get("kind") or "")
    ids = [str(i) for i in claim.get("evidence_ids") or []]
    if kind == "regulation" and ids:
        return cfr_link(ids[0]), "eCFR"
    if kind == "literature" and ids:
        return pubmed_link(ids[0]), "PubMed"
    for ident in ids:
        if _RECALL_NO.match(ident.upper()):
            return recall_link(ident.upper()), "openFDA recall"
        if _K_NO.match(ident):
            return k510_link(ident), "openFDA 510(k)"
        if is_report_id(ident):
            return report_link(ident), "first supporting report on openFDA"
    return None


_DATE_IN_TEXT = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?", re.IGNORECASE
)
_CODE_IN_TEXT = re.compile(r"\b[A-Z]{3}\b")
_RECOMPUTED = re.compile(r"recomputed\s+(\d+)")
_EVENT_WORDS = ("death", "injur", "malfunction", "serious", "source", "manufacturer", "user ")


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _dates_in(text: str) -> list[date]:
    """Dates written like 'August 25 to August 31, 2026' (a missing year comes from the next)."""
    found = [
        (m.group(1).lower(), int(m.group(2)), m.group(3)) for m in _DATE_IN_TEXT.finditer(text)
    ]
    year: int | None = None
    out: list[date] = []
    for month, day, yr in reversed(found):
        year = int(yr) if yr else year
        if year is None:
            continue
        try:
            out.append(date(year, _MONTHS[month], day))
        except ValueError:
            continue
    return list(reversed(out))


def recover_count_links(
    sentence: str,
    claims: list[dict[str, Any]],
    store: EvidenceStore,
    extra_windows: list[Window],
) -> list[tuple[str, str]]:
    """Links for the count claims of a *recorded* sentence (transcripts keep no code or dates).

    The product code(s) and window come from the sentence text and the stored digest, and a
    link is returned only when the stored reports for that code and window number exactly
    what the gate recomputed. So the openFDA count query behind the link shows the same
    number, or no link is given.

    Args:
        sentence: The sentence text.
        claims: Its recorded claims (``kind``, ``status``, ``reason``).
        store: Stored reports.
        extra_windows: Other windows to try (the digest's current and baseline weeks).

    Returns:
        ``(link, label)`` per count claim that could be tied to an openFDA count query.
    """
    low = sentence.lower()
    if any(w in low for w in _EVENT_WORDS):
        return []
    counts = [c for c in claims if c.get("kind") == "count" and c.get("status") == "pass"]
    values = [_RECOMPUTED.search(str(c.get("reason") or "")) for c in counts]
    if not counts or any(v is None for v in values):
        return []
    known = {r.product_code for r in store.records}
    codes = list(dict.fromkeys(c for c in _CODE_IN_TEXT.findall(sentence) if c in known))
    if len(codes) == len(counts):
        per_claim = codes
    elif len(codes) == 1:
        per_claim = codes * len(counts)
    else:
        return []
    dates = _dates_in(sentence)
    windows: list[Window] = []
    if len(dates) >= 2:
        windows.append((_ymd(dates[0]), _ymd(dates[-1])))
    windows += extra_windows + [(None, None)]
    out: list[tuple[str, str]] = []
    for code, match in zip(per_claim, values, strict=True):
        n = int(match.group(1)) if match else -1
        for start, end in windows:
            if len(store.select(product_code=code, date_from=start, date_to=end)) == n:
                out.append((counts_link(code, start, end), f"openFDA count for {code}"))
                break
    return out if len(out) == len(counts) else []
