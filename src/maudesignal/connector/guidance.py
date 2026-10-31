"""Helpful input errors: short messages that say what to fix, and "did you mean" codes.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every message is fixed text (it never repeats a caller's value, except a three-letter product
code that already passed the letters-only check). Suggestions are the closest product codes the
connector knows by edit distance; they are shown to the person and never applied automatically,
and a code that is known is never corrected.
"""

from __future__ import annotations

from collections.abc import Iterable

from maudesignal.connector.errors import UnknownProductCodeError

MAX_SUGGESTIONS = 3
#: Farthest edit distance still offered as "did you mean" (three-letter codes: 1 is a typo).
MAX_DISTANCE = 2

CODE_HINT = "A product code is three letters, for example LLZ or QIH."
K_HINT = "K-numbers look like K123456 (the letter K and six digits)."
REPORT_ID_HINT = "A report id is letters, digits and dashes, up to 24 characters."
GTIN_HINT = (
    "The GTIN (the digits after (01) in a UDI) does not pass the GS1 check digit test: "
    "its last digit does not match the others. Re-read the digits from the label."
)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two short strings (insert, delete, substitute)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggest_codes(code: str, known: Iterable[str]) -> list[str]:
    """Up to three known codes closest to ``code`` (empty when it is itself known or far).

    Only the closest tier is returned, nearest first, ties in alphabetical order.
    """
    code = code.upper()
    pool = sorted({k.upper() for k in known})
    if code in pool:
        return []
    scored = [(edit_distance(code, k), k) for k in pool]
    scored = [(d, k) for d, k in scored if d <= MAX_DISTANCE]
    if not scored:
        return []
    best = min(d for d, _ in scored)
    return [k for d, k in sorted(scored) if d == best][:MAX_SUGGESTIONS]


def _either(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]


def unknown_code_error(code: str, known: Iterable[str]) -> UnknownProductCodeError:
    """The error for a well-formed code with no stored data and no reports on openFDA."""
    close = suggest_codes(code, known)
    message = f"{code} isn't a product code we know"
    message += f" - did you mean {_either(close)}?" if close else "."
    message += (
        " It is not in the stored data and openFDA returned no reports for it."
        " Check the code with the person, or use lookup_device with the device name."
    )
    return UnknownProductCodeError(message, close)
