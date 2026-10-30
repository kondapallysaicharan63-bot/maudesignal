"""Problem patterns for one product code, from real FDA reports and recalls.

No model is used. Two deterministic sources of groups:

1. ``weekly-investigator`` groups already recorded in ``demo/investigations`` (LLZ today):
   reused as recorded (label and report ids); the count is recomputed from the listed ids.
2. Keyword rules (``RULES`` below, version ``RULES_VERSION``): a report joins a group when
   one of its MAUDE ``product_problems`` equals a rule problem term (case-insensitive) OR
   its narrative text matches the rule's regular expression. A report can join several
   groups. A group needs ``MIN_PATTERN_REPORTS`` reports to be a pattern. Groups are
   listed largest first, ties by label.

Every pattern count is checked by the claim gate (``GroupCountClaim``: the listed ids are
recounted and must be real reports of the code) and every quote by a ``QuoteClaim``
(verbatim in that report). A quote the gate does not pass is dropped, never shown.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from maudesignal.company.constants import (
    MAUDE_DETAIL_URL,
    MAX_QUOTES,
    MIN_PATTERN_REPORTS,
    QUOTE_MAX_CHARS,
    QUOTE_MIN_CHARS,
    contains_forbidden,
    investigations_dir,
)
from maudesignal.company.evidence import CodeEvidence, EvidenceReport
from maudesignal.gate import (
    CountClaim,
    EvidenceStore,
    GroupCountClaim,
    QuoteClaim,
    RecallCountClaim,
    verify_claim,
)

RULES_VERSION = "1.0"


@dataclass(frozen=True)
class Rule:
    """One keyword rule: MAUDE problem terms and/or a narrative regular expression."""

    rule_id: str
    label: str
    problems: tuple[str, ...]
    text_re: str


RULES: tuple[Rule, ...] = (
    Rule(
        "load-transfer",
        "Images or data fail to load, transfer or send",
        (
            "failure to transmit record",
            "no display/image",
            "intermittent communication failure",
            "loss of data",
        ),
        r"\b(unable|not able|fail\w*|cannot|could not) (to )?(load|fetch|retrieve|transfer|"
        r"transmit|send|import|export|save)\b",
    ),
    Rule(
        "freeze-crash",
        "Software freezes, crashes or does not start",
        ("application program freezes or fails to launch",),
        r"\b(freez\w*|froze|frozen|crash\w*|hang\w*|unresponsive|error state|fail\w* to "
        r"(launch|start|open))\b",
    ),
    Rule(
        "wrong-result",
        "Result or measurement is incorrect or imprecise",
        (
            "incorrect, inadequate or imprecise result or readings",
            "application program problem: parameter calculation error",
        ),
        r"\b(incorrect\w*|inaccurate\w*|wrong|miscalculat\w*|mismeasur\w*|false (positive|"
        r"negative)|missed|overestimat\w*|underestimat\w*)\b",
    ),
    Rule(
        "display-quality",
        "Image display problem or artifact",
        (
            "image display error/artifact",
            "poor quality image",
            "display or visual feedback problem",
            "no display/image",
        ),
        r"\b(artifacts?|blurr\w*|distort\w*|not display\w*|display error|missing image|"
        r"blank (screen|image))\b",
    ),
    Rule(
        "patient-data",
        "Patient data, record or label mix-up",
        (
            "patient data problem",
            "data problem",
            "wrong label",
        ),
        r"\b(wrong patient|mismatch\w*|mislabel\w*|wrong (label|study|patient)|patient data|"
        r"mixed up|incorrect patient)\b",
    ),
    Rule(
        "install-update",
        "Installation, update or compatibility problem",
        (
            "problem with software installation",
            "installation-related problem",
            "computer operating system problem",
        ),
        r"\b(install\w*|upgrad\w*|updat\w*|compatib\w*)\b",
    ),
    Rule(
        "access-security",
        "Log-in, access or security problem",
        ("computer system security problem",),
        r"\b(cyber\w*|security|unauthori[sz]ed|password|log ?in|logon|access denied)\b",
    ),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")
_STOP = frozenset({"describe", "reports", "including", "report", "errors", "error", "unable"})


@dataclass(frozen=True)
class Quote:
    """A short verbatim span of one report's narrative (gate-checked)."""

    report_id: str
    text: str
    url: str


@dataclass(frozen=True)
class Pattern:
    """A group of real reports that describe one kind of problem."""

    pattern_id: str
    label: str
    basis: str  # how the group was made
    report_ids: tuple[str, ...]
    count: int
    quotes: tuple[Quote, ...]
    links: tuple[tuple[str, str], ...]  # (label, url): one MAUDE page per report
    gate_count: str  # "pass" | "block"
    gate_reason: str
    quotes_passed: int
    quotes_withheld: int
    first_received: str | None = None
    last_received: str | None = None


@dataclass(frozen=True)
class RecallItem:
    """One stored recall, with a gate-checked verbatim excerpt of its stated reason."""

    recall_number: str
    recalling_firm: str | None
    status: str | None
    date_initiated: str | None
    excerpt: str | None
    url: str | None


@dataclass(frozen=True)
class RecallSummary:
    """Stored recalls for the code: the count (recomputed) and the latest few."""

    stored: int
    matched_total: int | None
    gate_status: str
    gate_reason: str
    latest: tuple[RecallItem, ...]


@dataclass
class CodePatterns:
    """Patterns, recall summary and gate totals for one code."""

    product_code: str
    patterns: list[Pattern] = field(default_factory=list)
    recalls: RecallSummary | None = None
    report_count: int = 0
    report_count_gate: str = "pass"
    report_count_reason: str = ""
    gate_pass: int = 0
    gate_block: int = 0


# ── grouping ─────────────────────────────────────────────────────────────────


def rule_matches(rule: Rule, report: EvidenceReport) -> bool:
    """True when the report's problem terms or narrative match the rule."""
    problems = {p.strip().lower() for p in report.product_problems}
    if problems & set(rule.problems):
        return True
    return bool(re.search(rule.text_re, report.text, re.IGNORECASE)) if report.text else False


def group_by_rules(
    reports: Iterable[EvidenceReport], min_reports: int = MIN_PATTERN_REPORTS
) -> list[tuple[Rule, list[EvidenceReport]]]:
    """Group reports by ``RULES``; groups under ``min_reports`` are dropped."""
    out: list[tuple[Rule, list[EvidenceReport]]] = []
    ordered = sorted(reports, key=lambda r: r.report_id)
    for rule in RULES:
        members = [r for r in ordered if rule_matches(rule, r)]
        if len(members) >= min_reports:
            out.append((rule, members))
    out.sort(key=lambda t: (-len(t[1]), t[0].label))
    return out


def latest_investigation(
    product_code: str, folder: Path | None = None
) -> tuple[str, list[tuple[str, list[str]]]] | None:
    """Newest recorded weekly-investigator run for a code: ``(run id, [(label, ids)])``."""
    base = folder or investigations_dir()
    best: tuple[str, list[tuple[str, list[str]]]] | None = None
    for path in sorted(base.glob(f"*weekly-{product_code.lower()}.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "weekly-investigator" or doc.get("product_code") != product_code:
            continue
        groups = [
            (str(g["label"]), [str(i) for i in g["report_ids"]])
            for g in doc.get("groups", [])
            if g.get("label") and g.get("report_ids")
        ]
        if groups:
            best = (str(doc.get("id") or path.stem), groups)
    return best


# ── quotes ───────────────────────────────────────────────────────────────────


def _sentences(text: str) -> list[str]:
    return [_WS.sub(" ", s).strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def pick_quote(report: EvidenceReport, keyword_re: re.Pattern[str] | None) -> str | None:
    """A short sentence of the narrative that matches ``keyword_re``, or None.

    A sentence that does not mention the pattern's keywords is never used, so a quote
    always shows the problem the pattern names.
    """
    if keyword_re is None:
        return None
    for s in _sentences(report.text):
        if (
            QUOTE_MIN_CHARS <= len(s) <= QUOTE_MAX_CHARS
            and not contains_forbidden(s)
            and keyword_re.search(s)
        ):
            return s
    return None


def _label_regex(label: str) -> re.Pattern[str] | None:
    words = [w for w in re.findall(r"[a-z]{5,}", label.lower()) if w not in _STOP]
    if not words:
        return None
    return re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)


def _gated_quotes(
    members: list[EvidenceReport],
    keyword_re: re.Pattern[str] | None,
    store: EvidenceStore,
) -> tuple[tuple[Quote, ...], int, int]:
    """Up to ``MAX_QUOTES`` gate-passed quotes from distinct reports; passed, withheld counts."""
    quotes: list[Quote] = []
    withheld = 0
    for rep in members:
        if len(quotes) >= MAX_QUOTES:
            break
        text = pick_quote(rep, keyword_re)
        if text is None:
            continue
        verdict = verify_claim(QuoteClaim(quote=text, report_id=rep.report_id), store)
        if verdict.status == "pass":
            quotes.append(Quote(rep.report_id, text, MAUDE_DETAIL_URL.format(rep.report_id)))
        else:
            withheld += 1
    return tuple(quotes), len(quotes), withheld


def _pattern(
    pattern_id: str,
    label: str,
    basis: str,
    members: list[EvidenceReport],
    keyword_re: re.Pattern[str] | None,
    store: EvidenceStore,
    product_code: str,
) -> Pattern:
    ids = tuple(dict.fromkeys(r.report_id for r in members))
    verdict = verify_claim(
        GroupCountClaim(product_code=product_code, label=label, report_ids=ids, value=len(ids)),
        store,
    )
    quotes, passed, withheld = _gated_quotes(members, keyword_re, store)
    dates = sorted(r.date_received for r in members if r.date_received)
    return Pattern(
        pattern_id=pattern_id,
        label=label,
        basis=basis,
        report_ids=ids,
        count=len(ids),
        quotes=quotes,
        links=tuple((f"MAUDE report {i}", MAUDE_DETAIL_URL.format(i)) for i in ids),
        gate_count=verdict.status,
        gate_reason=verdict.reason,
        quotes_passed=passed,
        quotes_withheld=withheld,
        first_received=dates[0] if dates else None,
        last_received=dates[-1] if dates else None,
    )


def _recall_summary(ev: CodeEvidence, store: EvidenceStore, latest_n: int = 3) -> RecallSummary:
    verdict = verify_claim(
        RecallCountClaim(product_code=ev.product_code, value=len(ev.recalls)), store
    )
    items: list[RecallItem] = []
    for rc in ev.recalls[:latest_n]:
        excerpt: str | None = None
        first = _sentences(rc.reason_for_recall)[:1]
        if first:
            cand = first[0]
            if len(cand) > QUOTE_MAX_CHARS:
                cand = cand[:QUOTE_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
            q = verify_claim(QuoteClaim(quote=cand, source_id=rc.recall_number), store)
            if q.status == "pass" and len(cand) >= QUOTE_MIN_CHARS and not contains_forbidden(cand):
                excerpt = cand
        items.append(
            RecallItem(
                recall_number=rc.recall_number,
                recalling_firm=rc.recalling_firm,
                status=rc.recall_status,
                date_initiated=rc.date_initiated,
                excerpt=excerpt,
                url=rc.url,
            )
        )
    return RecallSummary(
        stored=len(ev.recalls),
        matched_total=ev.recalls_matched_total,
        gate_status=verdict.status,
        gate_reason=verdict.reason,
        latest=tuple(items),
    )


def build_code_patterns(ev: CodeEvidence, investigations: Path | None = None) -> CodePatterns:
    """Patterns, recalls and gate totals for one code. Empty (no numbers) when no evidence."""
    out = CodePatterns(product_code=ev.product_code)
    if not ev.available:
        return out
    store = ev.store()
    code = ev.product_code
    out.report_count = len(ev.reports)
    count_v = verify_claim(CountClaim(product_code=code, value=len(ev.reports)), store)
    out.report_count_gate, out.report_count_reason = count_v.status, count_v.reason

    by_id = {r.report_id: r for r in ev.reports}
    inv = latest_investigation(code, investigations)
    patterns: list[Pattern] = []
    if inv is not None:
        run_id, groups = inv
        usable = [
            (label, [by_id[i] for i in ids if i in by_id])
            for label, ids in groups
            if all(i in by_id for i in ids)
        ]
        for n, (label, members) in enumerate(usable, start=1):
            patterns.append(
                _pattern(
                    f"{code}-inv-{n}",
                    label[:1].upper() + label[1:],
                    f"weekly investigator group, recorded run {run_id}; count recomputed",
                    members,
                    _label_regex(label),
                    store,
                    code,
                )
            )
    if not patterns:
        for rule, members in group_by_rules(ev.reports):
            patterns.append(
                _pattern(
                    f"{code}-{rule.rule_id}",
                    rule.label,
                    f"keyword rules v{RULES_VERSION} ({rule.rule_id})",
                    members,
                    re.compile(rule.text_re, re.IGNORECASE),
                    store,
                    code,
                )
            )
    patterns.sort(key=lambda p: (-p.count, p.label))
    out.patterns = [p for p in patterns if p.gate_count == "pass"]
    out.recalls = _recall_summary(ev, store)
    claims_pass = (
        sum(1 for p in patterns if p.gate_count == "pass")
        + sum(p.quotes_passed for p in patterns)
        + (1 if count_v.status == "pass" else 0)
        + (1 if out.recalls.gate_status == "pass" else 0)
    )
    claims_block = (
        sum(1 for p in patterns if p.gate_count != "pass")
        + sum(p.quotes_withheld for p in patterns)
        + (1 if count_v.status != "pass" else 0)
        + (1 if out.recalls.gate_status != "pass" else 0)
    )
    out.gate_pass, out.gate_block = claims_pass, claims_block
    return out
