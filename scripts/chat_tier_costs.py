"""Cost per chat tier over a fixed sample of 20 questions, before and after the tiers.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Offline and free: no model is called. Each sample question is routed by the real router
(``maudesignal.connector.tiers.route``) over the stored demo data; a question routed to tier 4
that was already asked earlier in the sample is counted as a cache hit (tier 3).

Method (stated in the output too):

* **Before**: every question went to Muse Spark. Each is priced at the recorded average cost
  of a typed ask, ``RECORDED_TYPED_ASK_USD`` ($0.048, the owner's figure from the recorded runs).
* **After**: tiers 1 to 3 cost $0 (no model call). A tier-4 question is priced at the same
  recorded $0.048. That is an upper bound: the cheaper tier-4 settings (compact prompt, low
  reasoning effort, two tool rounds, smaller ``max_tokens``) are not measured here, because
  measuring them needs paid calls. No other cost figure is used or estimated.

Run from the repository root::

    python3.12 scripts/chat_tier_costs.py            # print the table
    python3.12 scripts/chat_tier_costs.py --write    # also update docs/hackathon/CHAT_TIERS.md
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.tiers import normalise, route  # noqa: E402

#: Recorded average cost of one typed Muse Spark ask (owner-provided figure; not estimated here).
RECORDED_TYPED_ASK_USD = 0.048
DOC = ROOT / "docs" / "hackathon" / "CHAT_TIERS.md"
START = "<!-- cost-table:start -->"
END = "<!-- cost-table:end -->"

#: A hand-picked mix of what visitors type (greetings, lookups, open questions, one repeat).
#: It is a sample, not measured traffic.
SAMPLE: tuple[str, ...] = (
    "hi",
    "namaste",
    "What can you do?",
    "What changed this week?",
    "What changed this week for LLZ?",
    "Check product code QIH",
    "Recalls for LLZ",
    "Who filed MYN reports?",
    "show report 19864749",
    "510(k) for K261677",
    "Show the AI device sweep",
    "Is this medical advice?",
    "thanks",
    "Why did LLZ reports increase this week?",
    "Compare LLZ and QIH",
    "What kinds of problems do the LLZ reports describe?",
    "Which recalls are related to the LLZ increase?",
    "why did LLZ reports increase this week",
    "Are there PubMed papers on AI triage failures?",
    "what changed for LLX",
)


@dataclass(frozen=True)
class Row:
    """One sample question: its tier and its cost before and after."""

    question: str
    tier: str
    intent: str
    before_usd: float
    after_usd: float


def rows(known: frozenset[str]) -> list[Row]:
    """Route every sample question; a repeated tier-4 question is a cache hit."""
    seen: set[str] = set()
    out: list[Row] = []
    for q in SAMPLE:
        r = route(q, known)
        tier, intent = r.tier, r.intent
        if tier == "live":
            key = normalise(q)
            if key in seen:
                tier, intent = "cache", "same question earlier"
            seen.add(key)
        after = RECORDED_TYPED_ASK_USD if tier == "live" else 0.0
        out.append(Row(q, tier, intent, RECORDED_TYPED_ASK_USD, after))
    return out


def table(rs: list[Row]) -> str:
    """The Markdown report: per question, per tier, and the totals."""
    n = len(rs)
    before = sum(r.before_usd for r in rs)
    after = sum(r.after_usd for r in rs)
    lines = [
        f"Sample: {n} questions (`scripts/chat_tier_costs.py`). Before: every question goes to "
        f"Muse Spark at the recorded average typed-ask cost of ${RECORDED_TYPED_ASK_USD:.3f}. "
        "After: tiers 1 to 3 cost $0; a tier-4 question is still priced at "
        f"${RECORDED_TYPED_ASK_USD:.3f} (upper bound: the cheaper tier-4 settings are not "
        "measured, which would need paid calls).",
        "",
        "| # | Question | Tier | Why | Before | After |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rs, start=1):
        q = r.question.replace("|", "/")
        lines.append(
            f"| {i} | {q} | {r.tier} | {r.intent} | ${r.before_usd:.3f} | ${r.after_usd:.3f} |"
        )
    lines += ["", "| Tier | Questions | Before | After |", "|---|---|---|---|"]
    for tier in ("canned", "direct", "cache", "live"):
        sub = [r for r in rs if r.tier == tier]
        lines.append(
            f"| {tier} | {len(sub)} | ${sum(r.before_usd for r in sub):.3f} | "
            f"${sum(r.after_usd for r in sub):.3f} |"
        )
    lines += [
        f"| **total** | **{n}** | **${before:.3f}** | **${after:.3f}** |",
        "",
        f"Average per question: before **${before / n:.4f}**, after **${after / n:.4f}** "
        f"(upper bound; target $0.02).",
    ]
    return "\n".join(lines) + "\n"


def write_doc(text: str, doc: Path = DOC) -> None:
    """Replace the generated block of the doc (between the cost-table markers)."""
    body = doc.read_text(encoding="utf-8")
    head, rest = body.split(START, 1)
    _old, tail = rest.split(END, 1)
    doc.write_text(f"{head}{START}\n{text}{END}{tail}", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Print the report; with ``--write`` also put it into CHAT_TIERS.md."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--write", action="store_true", help="update docs/hackathon/CHAT_TIERS.md")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        known = ConnectorData(work_dir=Path(tmp)).known_product_codes()
        text = table(rows(known))
    print(text, end="")
    if args.write:
        write_doc(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
