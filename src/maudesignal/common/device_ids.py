"""Dependency-free helpers for device identifiers and names.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Standard library only, so the Vercel connector function (see ``api/requirements.txt``) can use
them without Pillow or the rest of the vision stack. ``vision/label.py``, ``vision/verify.py``
and ``vision/fda_pdf.py`` re-export these names.
"""

from __future__ import annotations

import re
import unicodedata

_K_RE = re.compile(r"^K\d{6}$")
_CORP = re.compile(
    r"\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|b\.?v|"
    r"s\.?a|s\.?l|ag|plc|pty|kk|ab|oy|srl|spa|nv)\b"
)


def normalize_k_number(value: str) -> str:
    """Return ``K`` + 6 digits, or raise.

    Raises:
        ValueError: Not a 510(k) number.
    """
    k = re.sub(r"[\s\-]", "", value or "").upper()
    if not _K_RE.match(k):
        raise ValueError(f"not a 510(k) number: {value!r}")
    return k


def gtin_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check digit for GTIN-8/12/13/14."""
    d = re.sub(r"\D", "", digits or "")
    if len(d) not in (8, 12, 13, 14):
        return False
    body, check = d[:-1], int(d[-1])
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def parse_udi(udi: str) -> dict[str, str]:
    """Split a human-readable GS1 UDI ``(01)...(17)...`` into application identifiers."""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"\((\d{2,4})\)([^(]*)", udi)}


def norm_text(value: str) -> str:
    """Casefold, unify unicode, drop marks like ® ™, rejoin hyphenated words, collapse space."""
    t = unicodedata.normalize("NFKC", value or "")
    t = t.replace("®", " ").replace("™", " ").replace("©", " ")
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)  # "detec- tion" -> "detection"
    t = t.casefold()
    t = re.sub(r"[‘’“”\"'`]", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def norm_company(value: str) -> str:
    """Company name without punctuation and corporate suffixes."""
    t = unicodedata.normalize("NFKC", value or "").casefold()
    t = re.sub(r"[.,]", " ", t)
    t = _CORP.sub(" ", t)
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())
