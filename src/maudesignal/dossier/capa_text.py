"""Deterministic checks of the words a CAPA-need evidence pack uses (title, problem statement).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The copilot drafts the pack's title and problem statement, and it can word them more
narrowly than the evidence supports. Two cases that Muse Wonder's review found on
SER-LLZ-20260831-001:

* the problem statement named "error 500" but cited three reports, of which only two
  mention it (the third mentions a case needing correction);
* the title said "error 500 - this week increase", which reads as an error-500-specific
  increase, while the counts are for every report of the product code.

Nothing here calls a model. A report is cited for a phrase only if the phrase appears in
that report's stored narrative; the title is reworded so the count claim stays about the
whole product code and the phrase is only said to appear among the reports.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# A numbered error ("error 500", "code 404"): a concrete phrase a report either holds or not.
_TERM = re.compile(r"\b(?:error|code)\s+\d{2,4}\b", re.IGNORECASE)
# "<CODE> <brand> <term> - this week increase" (hyphen, en dash or em dash).
_TITLE = re.compile(
    r"^(?P<code>[A-Z0-9]{3})\s+(?P<brand>.+?)\s+(?P<term>(?:error|code)\s+\d{2,4})\s*"
    r"[-–—]\s*this week increase\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProblemCitations:
    """Which cited reports contain the phrases the problem statement quotes."""

    terms: tuple[str, ...]
    #: Cited reports whose stored narrative holds at least one phrase, in pack order.
    supporting: tuple[str, ...]
    #: Cited reports that hold none of the phrases (not cited for them).
    not_supporting: tuple[str, ...]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def problem_terms(*texts: str) -> tuple[str, ...]:
    """Numbered-error phrases (lower case, single spaces) found in the given texts, in order."""
    seen: dict[str, None] = {}
    for text in texts:
        for m in _TERM.finditer(text or ""):
            seen.setdefault(_norm(m.group(0)), None)
    return tuple(seen)


def cite_for_problem(
    statement: str, report_ids: Sequence[str], texts: Mapping[str, str], title: str = ""
) -> ProblemCitations:
    """Split the pack's cited reports into those that contain the quoted phrase and the rest.

    Args:
        statement: The pack's problem statement.
        report_ids: The pack's cited report ids, in order.
        texts: report_id -> stored narrative (full text, not the 300-character excerpt).
        title: The pack's title (its phrases are checked too).

    Returns:
        With no checkable phrase every cited report is kept (nothing to test against);
        otherwise a report is supporting only if some phrase appears in its stored text.
    """
    terms = problem_terms(statement, title)
    if not terms:
        return ProblemCitations((), tuple(report_ids), ())
    ok: list[str] = []
    no: list[str] = []
    for rid in report_ids:
        body = _norm(texts.get(rid, ""))
        (ok if any(t in body for t in terms) else no).append(rid)
    return ProblemCitations(terms, tuple(ok), tuple(no))


def display_title(
    title: str,
    *,
    product_code: str,
    change_label: str,
    texts: Mapping[str, str],
    brands: Sequence[str],
) -> str:
    """Section 4 title with the count claim kept about the whole product code.

    ``"LLZ IntelliSpace Cardiovascular error 500 - this week increase"`` becomes
    ``"LLZ reports suddenly increased (IntelliSpace Cardiovascular reports include error 500)"``
    when the change is a sudden increase, the phrase is in a cited report and the brand is
    named by a cited report. If the phrase or brand is not backed the parenthesis is dropped.
    Any other title is returned unchanged.
    """
    m = _TITLE.match(title.strip())
    if m is None or change_label != "reports suddenly increased":
        return title
    code = m.group("code").upper()
    if code != product_code.upper():
        return title
    term = _norm(m.group("term"))
    brand = m.group("brand").strip()
    base = f"{code} {change_label}"
    phrase_ok = any(term in _norm(t) for t in texts.values())
    brand_ok = any(_norm(brand) == _norm(b) for b in brands)
    if phrase_ok and brand_ok:
        return f"{base} ({brand} reports include {term})"
    return base
