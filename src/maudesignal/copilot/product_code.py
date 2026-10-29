"""Deterministic product-code check for transcribed voice questions.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Why this exists: Meta Voice Transcribe sometimes mishears an FDA product code
(LLZ heard as LLG or LLC). A language model must NOT be asked to guess which code
was meant: that guess is unverifiable and the claim gate cannot check it. This
module is pure string logic, run before the question reaches the agent.

Rules, in order:

1. Only code-shaped tokens are candidates: exactly three letters, written in
   capitals in the transcript (``LLZ``). Ordinary words ("any", "the", "all",
   "new", "Jan", "pos") are never candidates, so they are never rewritten and
   never trigger a clarify line.
2. A token that is itself a known code is never corrected. Known codes are the
   codes stored in the demo database (device catalog and report rows) plus the
   seed list in ``catalog/fetcher.py`` (``_SEED_PRODUCT_CODES``). There is no
   hand-written list here.
3. A candidate that is not known is corrected only when it is exactly one edit
   from exactly one code *on file* (a code that has records in the demo
   database). A seed code with no stored records is protected from being
   rewritten (rule 2) but is not offered as a correction target, because
   suggesting a code with nothing behind it does not help the analyst. Two close
   codes on file is a tie: nothing is changed.
4. A code-shaped token that is more than one edit from every code is skipped and
   the scan continues; if nothing else is found it is reported as not
   recognised.

The correction is a suggestion. In recorded runs it is applied and shown as a
statement. In live mode the analyst chooses (see ``copilot/voice.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maudesignal.storage.database import Database

# Exactly three capital letters standing alone: LLZ, not "The" or "any".
_CODE_SHAPED_RE = re.compile(r"(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])")


def levenshtein_distance(a: str, b: str) -> int:
    """Classic edit distance (insert/delete/substitute = 1 each)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class CodeSets:
    """The product codes a check works against.

    Attributes:
        on_file: Codes with records in the demo database; the only correction targets.
        known: Every real code the system knows (``on_file`` plus the seed list);
            a token in this set is never rewritten.
    """

    on_file: frozenset[str]
    known: frozenset[str]

    @classmethod
    def of(cls, on_file: Iterable[str], extra_known: Iterable[str] = ()) -> CodeSets:
        """Build from codes on file plus extra known (seed) codes."""
        filed = frozenset(c.upper() for c in on_file)
        return cls(on_file=filed, known=filed | frozenset(c.upper() for c in extra_known))


def code_sets_from_db(db: Database) -> CodeSets:
    """Known codes from the database's device catalog, stored report rows and the seed list."""
    from maudesignal.catalog.fetcher import _SEED_PRODUCT_CODES

    on_file = {d.product_code for d in db.list_catalog_devices()} | set(db.list_product_codes())
    return CodeSets.of(on_file, _SEED_PRODUCT_CODES)


@dataclass(frozen=True)
class ProductCodeCheck:
    """Result of checking one transcribed question for a product code."""

    heard_code: str | None
    suggested_code: str | None
    used_code: str | None
    # "none" | "known" | "corrected" | "ambiguous" | "unknown"
    status: str
    # The question with the suggestion applied (equals the input unless "corrected").
    corrected_text: str

    @property
    def display(self) -> str | None:
        """On-screen statement, or None when no code was found."""
        return describe_check(self.heard_code, self.suggested_code, self.used_code, self.status)

    @property
    def needs_confirmation(self) -> bool:
        """True when live mode must ask the analyst before using the suggestion."""
        return self.status == "corrected" and self.suggested_code is not None


def describe_check(
    heard: str | None, suggested: str | None, used: str | None, status: str | None
) -> str | None:
    """One statement (not a question) describing what was heard and what was asked.

    Shared by live and recorded runs so both read the same way.
    """
    if not heard:
        return None
    if suggested and used and used == suggested and heard != suggested:
        return (
            f"Heard {heard}; asked about {suggested} "
            "(one letter different; the only close code on file)."
        )
    if status == "ambiguous":
        return f"Heard {heard}; two codes on file are one letter away, so it was asked as heard."
    if status == "unknown":
        return f"Heard {heard}; product code not recognised, asked as heard."
    if used:
        return f"Product code: {used}."
    return f"Heard {heard}."


def confirm_prompt(check: ProductCodeCheck) -> tuple[str, str, str] | None:
    """Live-mode confirm step: (question, label for the suggestion, label for as heard).

    Returns None when no confirmation is needed. Nothing is sent to the model until
    the analyst picks one of the two labels.
    """
    if not check.needs_confirmation or check.suggested_code is None:
        return None
    heard, suggested = check.heard_code or "", check.suggested_code
    return (
        f"Heard {heard}. Did you mean {suggested}?",
        f"Ask about {suggested}",
        f"Ask as heard ({heard})",
    )


def check_product_code(text: str, codes: CodeSets) -> ProductCodeCheck:
    """Check a transcribed question for a product code.

    Args:
        text: The transcript text, verbatim from Voice Transcribe.
        codes: Known and on-file codes (see ``code_sets_from_db``).

    Returns:
        A ProductCodeCheck. ``corrected_text`` is identical to ``text`` unless the
        status is "corrected", in which case the heard code is replaced by the suggestion.
    """
    first_far: str | None = None
    for match in _CODE_SHAPED_RE.finditer(text):
        token = match.group(0)
        if token in codes.known:
            return ProductCodeCheck(token, None, token, "known", text)
        close = sorted(c for c in codes.on_file if levenshtein_distance(token, c) == 1)
        if len(close) == 1:
            suggested = close[0]
            fixed = text[: match.start()] + suggested + text[match.end() :]
            return ProductCodeCheck(token, suggested, suggested, "corrected", fixed)
        if len(close) > 1:
            return ProductCodeCheck(token, None, token, "ambiguous", text)
        if first_far is None:
            first_far = token
    if first_far is not None:
        return ProductCodeCheck(first_far, None, first_far, "unknown", text)
    return ProductCodeCheck(None, None, None, "none", text)
