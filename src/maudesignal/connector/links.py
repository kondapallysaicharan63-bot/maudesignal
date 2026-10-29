"""Public links a reader can open to see a fact (no keys in any of them).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

import re
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


def is_report_id(value: str) -> bool:
    """True when ``value`` looks like a MAUDE report id."""
    return bool(_REPORT_ID.match(value))


def claim_link(claim: object) -> tuple[str, str] | None:
    """Link and label for a gate claim (a live answer), or None when it has none."""
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
        if claim.event_type:  # the count link carries no event-type filter, so it would not
            return None  # show this number
        return counts_link(claim.product_code, claim.date_from, claim.date_to), "openFDA count"
    if isinstance(claim, ShareClaim | SourceCountClaim):
        return None  # a share or source-filtered count is not the number the link shows
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


_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december",
        ],
        start=1,
    )
}  # fmt: skip
_DATE_IN_TEXT = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?", re.IGNORECASE
)
_CODE_IN_TEXT = re.compile(r"\b[A-Z]{3}\b")
_RECOMPUTED = re.compile(r"recomputed\s+(\d+)")
_EVENT_WORDS = ("death", "injur", "malfunction", "serious", "source", "manufacturer", "user ")
Window = tuple[str | None, str | None]


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
