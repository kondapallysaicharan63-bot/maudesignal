"""One-shot project rename: SafeSignal → MaudeSignal.

Run from the project root with python3.12. Idempotent — safe to re-run.
Deletes itself after a successful run is not done; the user is expected
to remove the file from the commit if desired.

Replacements (case-sensitive, applied in this order so longer/more
specific patterns are handled before shorter ones):

    SAFESIGNAL_  -> MAUDESIGNAL_   (env var prefix; covers DB_PATH /
                                    COST_CEILING_USD / LOG_LEVEL)
    SAFESIGNAL   -> MAUDESIGNAL    (any remaining bare uppercase)
    SafeSignal   -> MaudeSignal    (brand + class names, e.g.
                                    SafeSignalError -> MaudeSignalError)
    Safesignal   -> Maudesignal    (rare title-case, just in case)
    safe_signal  -> maude_signal   (snake_case)
    safesignal   -> maudesignal    (lowercase: imports, paths, scripts,
                                    db filename, etc.)

Files touched: every regular file under the project root with one of
the included extensions, except those under skip dirs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "data", "__pycache__", "htmlcov", ".pytest_cache",
             ".mypy_cache", ".ruff_cache", "node_modules", "scripts"}

INCLUDE_EXTS = {
    ".py", ".md", ".json", ".jsonl", ".toml", ".yml", ".yaml",
    ".cfg", ".ini", ".txt", ".sh", ".ps1", ".example",
}
INCLUDE_NAMES = {"LICENSE", ".gitignore", ".env.example", "Dockerfile"}

REPLACEMENTS: list[tuple[str, str]] = [
    ("SAFESIGNAL_", "MAUDESIGNAL_"),
    ("SAFESIGNAL", "MAUDESIGNAL"),
    ("SafeSignal", "MaudeSignal"),
    ("Safesignal", "Maudesignal"),
    ("safe_signal", "maude_signal"),
    ("safesignal", "maudesignal"),
]


def should_visit(path: Path) -> bool:
    if path.is_dir():
        return path.name not in SKIP_DIRS
    if path.name in INCLUDE_NAMES:
        return True
    return path.suffix in INCLUDE_EXTS


def rename_in(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def walk(start: Path) -> int:
    changed = 0
    for entry in start.iterdir():
        if not should_visit(entry):
            continue
        if entry.is_dir():
            changed += walk(entry)
            continue
        try:
            raw = entry.read_bytes()
            original = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = rename_in(original)
        if updated != original:
            # Write bytes to preserve original line endings (CRLF vs LF).
            entry.write_bytes(updated.encode("utf-8"))
            print(f"  rewrote: {entry.relative_to(ROOT)}")
            changed += 1
    return changed


def main() -> int:
    print(f"Project root: {ROOT}")
    n = walk(ROOT)
    print(f"\n{n} file(s) rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
