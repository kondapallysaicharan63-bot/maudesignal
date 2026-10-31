"""Terms no connector response may contain (PRD section 9 and the review list).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One shared list: ``ask`` screens model and recorded text with it, and the tests scan every
dumped answer with it. Matching is case-insensitive and treats a hyphen like a space.
"""

from __future__ import annotations

import re

#: The banned claims and words, in plain form (the tests use this list as written).
FORBIDDEN_TERMS: tuple[str, ...] = (
    "approved",
    "FDA-approved",
    "official",
    "Part 11",
    "Part 11 compliant",
    "validated",
    "overnight",
    "worsening",
    "worsening signals",
    "citation-checked",
    "complaint data",
)

_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:approved|official\w*|part[\s-]*11|validated|overnight|worsening"
    r"|citation[\s-]*checked|complaint[\s-]+data)(?![A-Za-z])",
    re.IGNORECASE,
)


def forbidden_in(text: str) -> list[str]:
    """Forbidden words found in ``text`` (lower-case, empty when clean)."""
    return sorted({m.group(0).lower() for m in _PATTERN.finditer(text)})


def is_clean(text: str) -> bool:
    """True when ``text`` has none of the forbidden terms."""
    return _PATTERN.search(text) is None
