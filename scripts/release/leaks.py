"""Find key-shaped strings and copied prompt text in a response, a page or a bundle.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Nothing here ever returns or prints the matched text itself: a hit is a label (the kind of
key) and a position, so a report can never leak what it found.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

#: (label, pattern). Shapes only.
KEY_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI-style key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Groq key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}")),
    ("Google key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("AWS key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{24,}")),
    ("Vercel Blob token", re.compile(r"\bvercel_blob_rw_[A-Za-z0-9_\-]{16,}")),
    (
        "Named key with a value",
        re.compile(
            r"(?i)\b(?:META_MODEL_API_KEY|META_API_KEY|OPENFDA_API_KEY|GROQ_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY(?:_\d)?|MAUDESIGNAL_API_KEYS|"
            r"MAUDESIGNAL_DEMO_KEYS|MAUDESIGNAL_ADMIN_KEY|MAUDESIGNAL_KEY_PEPPER|"
            r"BLOB_READ_WRITE_TOKEN|UPSTASH_REDIS_REST_TOKEN)\b[\"']?\s*[:=]\s*[\"']?"
            r"[A-Za-z0-9_\-./+]{8,}"
        ),
    ),
)

WINDOW = 60  # characters of prompt text that must not be copied into an answer
STEP = 20


def find_key_shapes(text: str) -> list[str]:
    """Labels of the key shapes found in ``text`` (empty when none)."""
    return [label for label, pat in KEY_SHAPES if pat.search(text)]


def contains_any(text: str, secrets: Iterable[str], min_len: int = 8) -> list[int]:
    """Indexes of the ``secrets`` that appear verbatim in ``text`` (short ones are ignored)."""
    return [i for i, s in enumerate(secrets) if len(s) >= min_len and s in text]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def prompt_windows(paths: Iterable[Path], window: int = WINDOW, step: int = STEP) -> set[str]:
    """Overlapping ``window``-character slices of the normalised text of each file."""
    out: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        text = _norm(path.read_text("utf-8", errors="replace"))
        out.update(text[i : i + window] for i in range(0, max(1, len(text) - window + 1), step))
    return {w for w in out if len(w) == window}


def copied_prompt_text(text: str, windows: set[str]) -> int:
    """How many prompt windows appear in ``text``.

    The windows are aligned to the prompt, not to the answer, so a copied passage of at least
    ``WINDOW + STEP`` characters always contains at least one whole window.
    """
    if not windows:
        return 0
    haystack = _norm(text)
    return sum(1 for w in windows if w in haystack)


def skill_files(root: Path, names: Iterable[str]) -> list[Path]:
    """``skills/<name>/SKILL.md`` under ``root`` for each name."""
    return [root / "skills" / n / "SKILL.md" for n in names]
