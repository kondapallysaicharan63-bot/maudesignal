"""Make text safe to read aloud (voice mode) without changing what it says.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

import re
from datetime import date

_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_MD_CHARS = re.compile(r"[*_`#>~|]+")
_BULLET = re.compile(r"^\s*(?:[-+•]|\d+[.)])\s+", re.MULTILINE)
_LONG_DIGITS = re.compile(r"(?<![\d.,])\d{7,}(?![\d.,])")
_RATIO = re.compile(r"(\d(?:\.\d+)?)\s*[x×](?![\w])")
_PCT = re.compile(r"(\d(?:\.\d+)?)\s*%")


def speak_date(value: str | date | None) -> str:
    """'20260831', '2026-08-31' or a date -> 'August 31, 2026' ('' for None)."""
    if value is None:
        return ""
    if isinstance(value, date):
        d = value
    else:
        digits = value.replace("-", "")
        if len(digits) != 8 or not digits.isdigit():
            return value
        d = date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def speak_range(start: str | date, end: str | date) -> str:
    """'August 25, 2026 to August 31, 2026' style range."""
    return f"{speak_date(start)} to {speak_date(end)}"


def plain(text: str) -> str:
    """Strip markdown and links, and write ratios, percents and long ids so a voice reads them.

    Numbers are never changed: ``3.77x`` becomes ``3.77 times``, ``15%`` becomes
    ``15 percent``, and a digit run of seven or more (a report id) is spaced out so it is
    read digit by digit.
    """
    out = _MD_LINK.sub(r"\1", text)
    out = _URL.sub("", out)
    out = _BULLET.sub("", out)
    out = _MD_CHARS.sub("", out)
    out = out.replace("≥", "at least ").replace("≤", "at most ").replace("—", ", ")
    out = _RATIO.sub(r"\1 times", out)
    out = _PCT.sub(r"\1 percent", out)
    out = _LONG_DIGITS.sub(lambda m: " ".join(m.group(0)), out)
    return re.sub(r"\s+", " ", out).strip()


def compose(parts: list[str]) -> str:
    """Join sentences into one speakable string (plain text, each ending in a full stop)."""
    cleaned = []
    for part in parts:
        p = plain(part)
        if p and p[-1] not in ".!?":
            p += "."
        if p:
            cleaned.append(p)
    return " ".join(cleaned)
