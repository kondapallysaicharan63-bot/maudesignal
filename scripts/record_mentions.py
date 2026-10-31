"""Record outside mentions of device types into ``demo/mentions/<CODE>.json`` (free, no key).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Reads ``demo/mentions/REQUEST``: the codes to record are LLZ plus every three-letter token in
the file; a line ``CODE=term one;term two`` adds device terms for that code. Calls only free public
sources (GDELT, FDA and news feeds) through ``maudesignal.connector.mentions`` and keeps a
mention only when its sentence is found word for word on the fetched page. A code whose
sources were all unreachable is not written (an earlier good file is never overwritten by an
empty failure). The stored file has the live response shape with ``"mode": "recorded"``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from maudesignal.connector.mentions import LABEL, HttpFetcher, search_mentions

#: Terms for the always-recorded code (the words of its FDA product-code name).
DEFAULT_TERMS = {"LLZ": ["radiological image processing"]}


def parse_request(text: str) -> dict[str, list[str]]:
    """``{CODE: terms}`` from the request text (comments start with ``#``)."""
    wanted: dict[str, list[str]] = {"LLZ": list(DEFAULT_TERMS["LLZ"])}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        whole = re.fullmatch(r"([A-Za-z]{3})\s*=\s*(.+)", line)
        if whole:  # "CODE=term one;term two" on a line of its own
            code = whole.group(1).upper()
            terms = [t.strip() for t in whole.group(2).split(";") if t.strip()]
            wanted[code] = terms[:5] or DEFAULT_TERMS.get(code, [])
            continue
        for token in line.split():
            if re.fullmatch(r"[A-Za-z]{3}", token):
                wanted.setdefault(token.upper(), DEFAULT_TERMS.get(token.upper(), []))
    return wanted


def main(argv: list[str] | None = None) -> int:
    """Run the recording; returns the exit code."""
    parser = argparse.ArgumentParser(description="Record outside mentions (free sources).")
    parser.add_argument("--request", type=Path, default=Path("demo/mentions/REQUEST"))
    parser.add_argument("--out", type=Path, default=Path("demo/mentions"))
    args = parser.parse_args(argv)
    text = args.request.read_text(encoding="utf-8") if args.request.is_file() else ""
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for code, terms in parse_request(text).items():
        result = search_mentions(code, terms, HttpFetcher())
        reachable = sum(1 for s in result.sources_tried if s["status"] == "ok")
        print(
            f"{code}: {reachable}/{len(result.sources_tried)} sources reachable, "
            f"{len(result.mentions)} mention(s) kept, dropped {result.dropped}"
        )
        if not result.network_ok:
            print(f"{code}: no source reachable, file not written", file=sys.stderr)
            failed += 1
            continue
        body = result.as_dict() | {"label": LABEL, "mode": "recorded"}
        (args.out / f"{code}.json").write_text(
            json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
