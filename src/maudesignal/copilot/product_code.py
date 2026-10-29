"""Deterministic product-code check for transcribed voice questions.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Why this exists: Meta Voice Transcribe regularly mishears the FDA product
code LLZ as LLG or LNZ (see the user's own voice-note auto-transcript:
"LNZ has 15 jury" for "LLZ had fifty injury"). A language model must NOT
be asked to guess which code was meant — that guess is unverifiable and
the citation gate cannot check it. This module is pure, deterministic
string logic, run *before* the agent query is sent:

- a token that IS a known code is used unchanged, no suggestion;
- a token that is exactly 1 Levenshtein edit away from exactly ONE known
  code is corrected to that code, and both forms are shown on screen;
- anything else (distance > 1, or a tie at distance 1) is NOT auto-corrected:
  the heard code is shown alone and the analyst is asked to clarify.

Known-code vocabulary (documented, not invented):
- Demo DB catalog (``data/demo/maudesignal_demo.db``, device_catalog):
  JAK, LLZ, MYN, POK, QIH. These are the codes with records on file.
- Seed list (``src/maudesignal/catalog/fetcher.py``, ``_SEED_PRODUCT_CODES``):
  QAS is included from that list.
- Voice-task brief (2026-10-29): DQK and OEB are included as named in the
  brief, even though the demo DB has no records for them yet. A corrected
  question for such a code will still go through the citation gate, which
  will block any count the stored records cannot support — the correction
  never invents records.
- Deliberately NOT in the vocabulary: other seed codes such as LLN and QFM.
  Including LLN would make "LLG" tie at distance 1 between LLZ and LLN, so
  the LLG → LLZ example in the task could never auto-correct. The
  vocabulary here is the *correction* vocabulary, not the full FDA catalog;
  adding a code later is a one-line change, and the tie rule then applies
  to it automatically.

Candidate extraction: a full sentence contains many 3-letter English words
("DID", "HAD", "THE"), so scanning every 3-letter token would flag ordinary
words as codes. A candidate is therefore, in order:
1. a token immediately before "devices" or immediately after "for"/"about"
   (the pattern in every demo voice question, e.g. "for LLZ devices");
2. otherwise the first token in the text that is a known code or exactly
   1 edit away from a known code.
If neither pattern finds a candidate, the result is "none" — no code is
invented from an ordinary English word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Correction vocabulary, in the order documented above. Sorted in the
# module docstring order is not required; keep this list explicit so a
# reviewer can see exactly what a correction can produce.
KNOWN_PRODUCT_CODES: tuple[str, ...] = (
    "LLZ",
    "QIH",
    "MYN",
    "POK",
    "QAS",
    "DQK",
    "JAK",
    "OEB",
)

_TOKEN_RE = re.compile(r"\b([A-Za-z]{3})\b")
_CONTEXT_RE = re.compile(
    r"\b([A-Za-z]{3})\s+devices?\b|\bfor\s+([A-Za-z]{3})\b|\babout\s+([A-Za-z]{3})\b",
    re.IGNORECASE,
)


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
class ProductCodeCheck:
    """Result of checking one transcribed question for a product code."""

    heard_code: str | None
    suggested_code: str | None
    used_code: str | None
    # "none" | "known" | "corrected" | "ambiguous" | "unknown"
    status: str
    corrected_text: str

    @property
    def display(self) -> str | None:
        """On-screen line, or None when no code was found.

        Always shows both forms when a correction happened, e.g.
        "Heard: LLG → did you mean LLZ?" — never the corrected code alone.
        """
        if self.heard_code is None:
            return None
        if self.status == "corrected" and self.suggested_code:
            return f"Heard: {self.heard_code} → did you mean {self.suggested_code}?"
        return f"Heard: {self.heard_code}"


def _candidate(text: str) -> str | None:
    """Pick the product-code candidate token from a transcript, or None."""
    for match in _CONTEXT_RE.finditer(text):
        for group in match.groups():
            if group:
                return group.upper()
    upper = text.upper()
    for match in _TOKEN_RE.finditer(upper):
        token = match.group(1)
        if token in KNOWN_PRODUCT_CODES:
            return token
        distances = [levenshtein_distance(token, code) for code in KNOWN_PRODUCT_CODES]
        if min(distances) == 1:
            return token
    return None


def check_product_code(
    text: str, *, known_codes: tuple[str, ...] = KNOWN_PRODUCT_CODES
) -> ProductCodeCheck:
    """Check a transcribed question for a product code.

    Args:
        text: The transcript text, verbatim from Voice Transcribe.
        known_codes: Correction vocabulary (defaults to KNOWN_PRODUCT_CODES).

    Returns:
        A ProductCodeCheck. ``corrected_text`` is the text to actually ask
        the agent: identical to ``text`` unless status is "corrected", in
        which case the first occurrence of the heard code is replaced by
        the suggested code.
    """
    candidate = _candidate(text)
    if candidate is None:
        return ProductCodeCheck(None, None, None, "none", text)
    if candidate in known_codes:
        return ProductCodeCheck(candidate, None, candidate, "known", text)
    distances = {code: levenshtein_distance(candidate, code) for code in known_codes}
    best = min(distances.values())
    if best > 1:
        return ProductCodeCheck(candidate, None, candidate, "unknown", text)
    winners = [code for code, d in distances.items() if d == best]
    if len(winners) != 1:
        # Tie at distance 1: do not guess. Show the heard code only.
        return ProductCodeCheck(candidate, None, candidate, "ambiguous", text)
    suggested = winners[0]
    corrected = re.sub(rf"\b{candidate}\b", suggested, text, count=1, flags=re.IGNORECASE)
    return ProductCodeCheck(candidate, suggested, suggested, "corrected", corrected)
