"""Figures: every number printed in the dossier, paired with the claim that re-verifies it.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A *figure* is a number the dossier shows (a count, a share, a weekly mean, a
ratio). It is never typed by hand or by a model: the builder computes it from
stored records and attaches a claim. The template prints each figure inside an
element carrying ``data-claim='<json>'``, so anyone (the unit tests, an auditor)
can parse the rendered HTML and re-verify every number through the
claim-level gate (:mod:`maudesignal.gate`).

Claim kinds understood here:

* the gate's own kinds (``count``, ``share``, ``record`` …) — verified by
  :func:`maudesignal.gate.verify_claim`;
* ``derived`` — arithmetic over other claims, recomputed here after each
  operand passes the gate. Ops: ``sum``, ``mul``, ``div``, ``pct`` (100·a/b) and
  ``count_records`` (how many of the listed report ids exist);
* ``const`` — a fixed method constant (e.g. the 4 baseline weeks).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from maudesignal.gate import ClaimParseError, EvidenceStore, claim_from_dict, verify_claim

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Figure:
    """One number shown in the dossier.

    Attributes:
        value: The exact value computed by deterministic code.
        display: How it is printed (e.g. ``"33"``, ``"2.9%"``, ``"3.77×"``).
        claim: Claim dict that re-derives ``value`` from stored records.
    """

    value: float
    display: str
    claim: dict[str, Any]

    @property
    def claim_json(self) -> str:
        """Compact JSON of the claim, for the ``data-claim`` attribute."""
        return json.dumps(self.claim, sort_keys=True, separators=(",", ":"))


def _fmt(value: float, digits: int) -> str:
    if digits == 0:
        return str(round(value))
    return f"{value:.{digits}f}"


def count_figure(
    product_code: str,
    value: int,
    *,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Figure:
    """A report count for a product code (optionally by event type and date window)."""
    claim: dict[str, Any] = {"kind": "count", "product_code": product_code, "value": value}
    if event_type is not None:
        claim["event_type"] = event_type
    if date_from is not None:
        claim["date_from"] = date_from
    if date_to is not None:
        claim["date_to"] = date_to
    return Figure(float(value), str(value), claim)


def const_figure(value: float, digits: int = 0) -> Figure:
    """A fixed method constant."""
    return Figure(value, _fmt(value, digits), {"kind": "const", "value": value})


def derived_figure(
    op: str,
    operands: list[Figure],
    value: float,
    *,
    digits: int,
    suffix: str = "",
) -> Figure:
    """Arithmetic over other figures (``sum``, ``mul``, ``div`` or ``pct``)."""
    claim = {
        "kind": "derived",
        "op": op,
        "digits": digits,
        "value": round(value, digits),
        "operands": [f.claim for f in operands],
    }
    return Figure(round(value, digits), _fmt(value, digits) + suffix, claim)


def records_figure(report_ids: list[str], product_code: str | None = None) -> Figure:
    """How many of the listed MAUDE report ids exist in the evidence store."""
    claim: dict[str, Any] = {
        "kind": "derived",
        "op": "count_records",
        "digits": 0,
        "value": len(report_ids),
        "report_ids": list(report_ids),
    }
    if product_code:
        claim["product_code"] = product_code
    return Figure(float(len(report_ids)), str(len(report_ids)), claim)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureCheck:
    """Outcome of re-verifying one printed figure."""

    display: str
    claim: dict[str, Any]
    ok: bool
    reason: str
    recomputed: float | None = None


@dataclass
class FigureReport:
    """Outcome of re-verifying every figure in a dossier."""

    checks: list[FigureCheck] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Figures checked."""
        return len(self.checks)

    @property
    def passed(self) -> int:
        """Figures that re-verified."""
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> list[FigureCheck]:
        """Figures that did not re-verify."""
        return [c for c in self.checks if not c.ok]


def recompute(claim: dict[str, Any], store: EvidenceStore) -> tuple[float | None, str]:
    """Recompute a claim's value from the evidence store.

    Args:
        claim: A figure claim (gate kind, ``derived`` or ``const``).
        store: Evidence store built from stored records.

    Returns:
        ``(value, reason)``; ``value`` is None when the claim cannot be verified.
    """
    kind = claim.get("kind")
    if kind == "const":
        return float(claim["value"]), "method constant"
    if kind == "derived":
        return _recompute_derived(claim, store)
    try:
        typed = claim_from_dict(claim)
    except ClaimParseError as exc:
        return None, str(exc)
    verdict = verify_claim(typed, store)
    if verdict.status != "pass":
        return None, verdict.reason
    if verdict.recomputed is not None:
        return float(verdict.recomputed), verdict.reason
    return 1.0, verdict.reason


def _recompute_derived(claim: dict[str, Any], store: EvidenceStore) -> tuple[float | None, str]:
    op = claim.get("op")
    if op == "count_records":
        ids = [str(i) for i in claim.get("report_ids", [])]
        pc = claim.get("product_code")
        ok = [
            i
            for i in ids
            if (rec := store.record(i)) is not None and (not pc or rec.product_code == pc)
        ]
        if len(ok) != len(ids):
            missing = sorted(set(ids) - set(ok))[:5]
            return None, f"report ids not in evidence store: {', '.join(missing)}"
        return float(len(ok)), f"{len(ok)} report ids exist"
    values: list[float] = []
    for operand in claim.get("operands", []):
        v, reason = recompute(operand, store)
        if v is None:
            return None, f"operand failed: {reason}"
        values.append(v)
    if op == "sum":
        return float(sum(values)), "sum of verified operands"
    if op == "mul" and len(values) == 2:
        return values[0] * values[1], "product of verified operands"
    if op in ("div", "pct") and len(values) == 2:
        if values[1] == 0:
            return None, "division by zero"
        q = values[0] / values[1]
        return (q * 100.0 if op == "pct" else q), f"{op} of verified operands"
    return None, f"unknown derived op {op!r}"


def check_figure(display: str, claim: dict[str, Any], store: EvidenceStore) -> FigureCheck:
    """Re-verify one printed figure: the claim must recompute and match what is printed."""
    value, reason = recompute(claim, store)
    if value is None:
        return FigureCheck(display, claim, False, reason)
    digits = int(claim.get("digits", 0)) if claim.get("kind") == "derived" else 0
    expected = round(value, digits)
    m = _NUM_RE.search(display.replace(",", ""))
    if claim.get("kind") in ("count", "const", "derived", "share"):
        if m is None:
            return FigureCheck(display, claim, False, "no number printed", value)
        printed = float(m.group(0))
        target = float(claim.get("value_pct", expected)) if claim["kind"] == "share" else expected
        if claim["kind"] == "share":
            ok = abs(printed - value) <= 0.5
        else:
            ok = abs(printed - target) < 10 ** (-digits) / 2 + 1e-9
        if not ok:
            return FigureCheck(
                display, claim, False, f"printed {printed}, recomputed {expected}", value
            )
    return FigureCheck(display, claim, True, reason, value)


def verify_figures(figures: list[Figure], store: EvidenceStore) -> FigureReport:
    """Re-verify a list of figures (used by the builder before rendering)."""
    return FigureReport([check_figure(f.display, f.claim, store) for f in figures])


_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)


@dataclass
class _Open:
    """An element being collected (a figure or a narrative sentence)."""

    kind: str  # "fig" | "sent" | "inner"
    payload: Any = None
    status: str = ""
    text: list[str] = field(default_factory=list)


class _ClaimExtractor(HTMLParser):
    """Collect ``(text, data-claim)`` pairs and narrative sentences from rendered HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figures: list[tuple[str, dict[str, Any]]] = []
        self.sentences: list[tuple[str, list[dict[str, Any]], str]] = []
        self._stack: list[_Open] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        a = dict(attrs)
        if a.get("data-claim"):
            self._stack.append(_Open("fig", json.loads(a["data-claim"] or "{}")))
        elif a.get("data-claims") is not None:
            self._stack.append(
                _Open("sent", json.loads(a["data-claims"] or "[]"), a.get("data-status") or "")
            )
        elif self._stack:
            self._stack.append(_Open("inner"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self._stack:
            return
        node = self._stack.pop()
        text = "".join(node.text)
        if node.kind == "fig":
            self.figures.append((text.strip(), node.payload))
        elif node.kind == "sent":
            self.sentences.append((" ".join(text.split()), node.payload, node.status))

    def handle_data(self, data: str) -> None:
        for node in self._stack:
            if node.kind != "inner":
                node.text.append(data)


def extract_figures(html: str) -> list[tuple[str, dict[str, Any]]]:
    """Return every ``(printed text, claim)`` pair tagged in the rendered HTML."""
    p = _ClaimExtractor()
    p.feed(html)
    return p.figures


def extract_sentences(html: str) -> list[tuple[str, list[dict[str, Any]], str]]:
    """Return every gated narrative sentence ``(text, claims, status)`` in the HTML."""
    p = _ClaimExtractor()
    p.feed(html)
    return p.sentences


def verify_html(html: str, store: EvidenceStore) -> FigureReport:
    """Parse rendered dossier HTML and re-verify every tagged figure through the gate."""
    return FigureReport([check_figure(t, c, store) for t, c in extract_figures(html)])
