"""Scan a built web folder for key-shaped strings and key names with values.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

    python3 scripts/release/bundle_scan.py web/dist --out-dir release-out

The report names the file, the kind of key and the line, never the text matched. A scan that
finds no files to read is a failure (a missing build must not look clean).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from leaks import find_key_shapes  # noqa: E402
from report import FAIL, PASS, Report  # noqa: E402

TEXT_SUFFIXES = {
    ".js",
    ".mjs",
    ".css",
    ".html",
    ".json",
    ".map",
    ".txt",
    ".svg",
    ".xml",
    ".webmanifest",
}


def scan_dir(root: Path) -> tuple[int, list[tuple[str, str, int]]]:
    """``(files read, [(relative path, key kind, line number)])`` for every text file."""
    hits: list[tuple[str, str, int]] = []
    files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files += 1
        text = path.read_text("utf-8", errors="replace")
        rel = path.relative_to(root).as_posix()
        for kind in find_key_shapes(text):
            # Find the line without keeping the text: re-scan line by line.
            line_no = next(
                (n for n, line in enumerate(text.splitlines(), 1) if kind in find_key_shapes(line)),
                0,
            )
            hits.append((rel, kind, line_no))
    return files, hits


def main(argv: list[str] | None = None) -> int:
    """Scan ``root`` and write ``web-bundle-scan.json`` and ``.md``; exit 1 on any hit."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("root", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    args = ap.parse_args(argv)
    rep = Report("web bundle secret scan")
    if not args.root.is_dir():
        rep.add("bundle folder exists", FAIL, f"{args.root} is not a folder")
        rep.write(args.out_dir, "web-bundle-scan")
        return rep.exit_code()
    files, hits = scan_dir(args.root)
    rep.metrics.update(files_scanned=files, hits=len(hits))
    rep.add("files were scanned", PASS if files else FAIL, f"{files} text files in {args.root}")
    for rel, kind, line in hits:
        rep.add(f"no key in {rel}", FAIL, f"{kind} at line {line} (text not shown)")
    if not hits and files:
        rep.add("no key-shaped string or key name with a value", PASS, f"{files} files")
    rep.write(args.out_dir, "web-bundle-scan")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
