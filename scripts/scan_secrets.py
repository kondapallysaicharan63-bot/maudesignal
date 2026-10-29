"""Fail if a tracked file looks like it holds an API key (CI security check).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Scans every file ``git ls-files`` lists (text files only) for the key shapes the
project's providers use. Keys belong in ``.env`` (git-ignored) or GitHub Actions
secrets, never in the repository.

    python scripts/scan_secrets.py            # exit 1 and list hits if any
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (provider, pattern). Shapes only; a hit is a file:line to inspect, never printed whole.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Groq", re.compile(r"\bgsk_[A-Za-z0-9]{40,}")),
    ("Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "Assigned key",
        re.compile(
            r"(?i)\b(?:META_MODEL_API_KEY|OPENFDA_API_KEY|GROQ_API_KEY|OPENAI_API_KEY|"
            r"ANTHROPIC_API_KEY|GEMINI_API_KEY(?:_\d)?)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{20,})"
        ),
    ),
)

#: Test fixtures hold deliberately fake keys.
ALLOWED_FAKES = ("gsk_fake", "sk-test", "fake")


def tracked_files(root: Path = ROOT) -> list[Path]:
    """Files git tracks under ``root``."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return [root / p for p in out.decode("utf-8").split("\0") if p]


def scan_text(text: str) -> list[tuple[int, str]]:
    """(line number, provider) for every key-shaped string in ``text``."""
    hits: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        for provider, pattern in PATTERNS:
            m = pattern.search(line)
            if m and not any(f in m.group(0).lower() for f in ALLOWED_FAKES):
                hits.append((n, provider))
    return hits


def main() -> int:
    """Scan the tracked files; print ``path:line provider`` per hit."""
    found = 0
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary files (images, PDFs, the demo database)
        for line, provider in scan_text(text):
            print(f"{path.relative_to(ROOT)}:{line} looks like a {provider} key")
            found += 1
    print(f"[secrets] {found} key-shaped string(s) in tracked files")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
