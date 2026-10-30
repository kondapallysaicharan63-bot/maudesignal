"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Deterministic "what changed" digest built from a :class:`DetectionResult`.

The digest is rendered twice — Markdown for humans and JSON for machines
(and for the downstream citation gate, which re-verifies every number
against the stored records). No LLM is involved: every sentence is a fixed
template filled with numbers taken verbatim from the detector.

Headline format: ``"New kind of problem: N · More serious than usual: M ·
Reports suddenly increased: K"`` (``new_signal``, ``severity_escalation`` and
``spike`` product codes, by their primary classification).

Flagged product codes are ranked by a fixed key (see :data:`RANKING_ORDER`)
and every rank carries a sentence saying why, built from the same numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from maudesignal.catalog.names import brand_counts, classification_names, report_brands
from maudesignal.monitor.deterioration import (
    BASELINE_WEEKS,
    CLASSIFICATION_PRECEDENCE,
    CURRENT_WINDOW_DAYS,
    SEVERITY_ESCALATION_PP,
    SEVERITY_MIN_REPORTS,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
    DetectionResult,
    ProductCodeSignal,
)
from maudesignal.monitor.sources import sourced_reports
from maudesignal.storage.database import Database

DIGEST_FOOTER = (
    "Advisory only — B2B regulatory triage aid, not medical advice. "
    "Every item requires human review; nothing is reported to FDA automatically."
)
DIGEST_SCHEMA_VERSION = "1.2"
MAX_EXAMPLE_IDS = 3

#: How flagged product codes are ordered, most urgent first. Each step only
#: breaks ties left by the steps before it.
RANKING_ORDER: tuple[str, ...] = (
    "rule precedence: new kind of problem, then more serious than usual, "
    "then reports suddenly increased",
    "more Injury/Death reports this window",
    "higher ratio of this window's count to the baseline weekly mean",
    "more reports this window",
    "product code, alphabetically",
)

#: Plain words shown to people for each detector classification.
CHANGE_LABELS: dict[str, str] = {
    "new_signal": "new kind of problem",
    "severity_escalation": "more serious than usual",
    "spike": "reports suddenly increased",
    "stable": "no change",
}


@dataclass(frozen=True)
class Digest:
    """A rendered-ready "what changed" digest.

    Attributes:
        result: The detection result the digest summarizes.
        headline: e.g. ``"New kind of problem: 0 · More serious than usual: 0 ·
            Reports suddenly increased: 1"``.
        new_count: Product codes classified ``new_signal``.
        serious_count: Product codes classified ``severity_escalation``
            ("more serious than usual").
        increased_count: Product codes classified ``spike`` ("reports
            suddenly increased").
        stable_count: Product codes classified ``stable``.
        source: Human-readable description of the data source.
        fetch_summary: Optional ``product_code -> records newly stored`` from
            this run's ingestion step (empty when nothing was fetched).
        notes: Optional extra lines (e.g. a fetch warning), rendered verbatim.
        ranked: Flagged (non-stable) signals, most urgent first.
        rank_reasons: ``product_code -> sentence`` saying why it holds its rank.
        device_types: ``product_code -> FDA classification device name`` (only
            codes with a stored name).
        window_brands: ``product_code -> [(brand, reports)]`` for the brand
            names written on this window's reports, most frequent first.
        window_sources: ``product_code -> {source: reports}`` in this window
            (openFDA report source; empty when the sources are not known).
    """

    result: DetectionResult
    headline: str
    new_count: int
    serious_count: int
    increased_count: int
    stable_count: int
    source: str
    fetch_summary: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    ranked: tuple[ProductCodeSignal, ...] = ()
    rank_reasons: dict[str, str] = field(default_factory=dict)
    device_types: dict[str, str] = field(default_factory=dict)
    window_brands: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    window_sources: dict[str, dict[str, int]] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Ranking
# ----------------------------------------------------------------------


def _rank_key(signal: ProductCodeSignal) -> tuple[int, int, float, int, str]:
    ratio = -1.0 if signal.spike_ratio is None else signal.spike_ratio
    return (
        CLASSIFICATION_PRECEDENCE.index(signal.classification),
        -signal.current_severe_count,
        -ratio,
        -signal.current_count,
        signal.product_code,
    )


def rank_signals(signals: tuple[ProductCodeSignal, ...]) -> tuple[ProductCodeSignal, ...]:
    """Order flagged signals most urgent first (stable codes are left out).

    Args:
        signals: Every product-code signal from a detection run.

    Returns:
        The non-stable signals sorted by :data:`RANKING_ORDER`.
    """
    return tuple(sorted((s for s in signals if not s.is_stable), key=_rank_key))


def _ratio_text(signal: ProductCodeSignal) -> str:
    return "n/a" if signal.spike_ratio is None else f"{signal.spike_ratio:.2f}x"


def rule_evidence(signal: ProductCodeSignal) -> str:
    """One clause stating the rule that fired and the numbers that crossed it.

    Args:
        signal: A non-stable signal.

    Returns:
        e.g. ``"reports suddenly increased: 33 reports this window vs a baseline weekly mean
        of 8.75 (3.77x; the rule needs >= 2x and >= 3 reports)"``.
    """
    if signal.classification == "new_signal":
        if signal.prior_report_count == 0:
            return (
                f"new kind of problem: first {signal.current_count} report(s) ever stored "
                f"for this code"
            )
        return (
            f"new kind of problem: event type(s) never seen before for this code "
            f"({', '.join(signal.new_event_types)}) despite {signal.prior_report_count} "
            f"earlier reports"
        )
    if signal.classification == "severity_escalation":
        delta = signal.severe_share_delta_pp or 0.0
        return (
            f"more serious than usual: Injury/Death share {_pct(signal.current_severe_share)} "
            f"({signal.current_severe_count}/{signal.current_count}) vs baseline "
            f"{_pct(signal.baseline_severe_share)} "
            f"({signal.baseline_severe_count}/{signal.baseline_count}), {delta:+.1f} pp; "
            f"the rule needs >= +{SEVERITY_ESCALATION_PP} pp and >= {SEVERITY_MIN_REPORTS} reports"
        )
    return (
        f"reports suddenly increased: {signal.current_count} reports this window vs a "
        f"baseline weekly mean of {signal.baseline_weekly_mean:.2f} ({_ratio_text(signal)}; "
        f"the rule needs >= {SPIKE_MULTIPLIER}x and >= {SPIKE_MIN_REPORTS} reports)"
    )


def _deciding_step(a: ProductCodeSignal, b: ProductCodeSignal) -> str:
    """Why ``a`` ranks above ``b``: the first ranking step where they differ."""
    ka, kb = _rank_key(a), _rank_key(b)
    if ka[0] != kb[0]:
        return f"{CHANGE_LABELS[a.classification]} outranks {CHANGE_LABELS[b.classification]}"
    if ka[1] != kb[1]:
        return (
            f"more Injury/Death reports this window "
            f"({a.current_severe_count} vs {b.current_severe_count})"
        )
    if ka[2] != kb[2]:
        return f"higher ratio to baseline ({_ratio_text(a)} vs {_ratio_text(b)})"
    if ka[3] != kb[3]:
        return f"more reports this window ({a.current_count} vs {b.current_count})"
    return (
        f"tie on every measure; ordered by product code ({a.product_code} before {b.product_code})"
    )


def rank_reasons(ranked: tuple[ProductCodeSignal, ...], stable_count: int) -> dict[str, str]:
    """Explain each flagged product code's rank in one sentence.

    Args:
        ranked: Output of :func:`rank_signals`.
        stable_count: Product codes that crossed no threshold.

    Returns:
        ``product_code -> reason``.
    """
    n = len(ranked)
    reasons: dict[str, str] = {}
    for i, s in enumerate(ranked):
        parts = [f"Ranked {i + 1} of {n} flagged: {rule_evidence(s)}."]
        if n == 1:
            parts.append(
                f"It is the only product code that crossed a rule threshold; "
                f"{stable_count} other code(s) stayed below every threshold."
            )
        else:
            if i + 1 < n:
                below = ranked[i + 1]
                parts.append(f"Above {below.product_code}: {_deciding_step(s, below)}.")
            if i > 0:
                above = ranked[i - 1]
                parts.append(f"Below {above.product_code}: {_deciding_step(above, s)}.")
        reasons[s.product_code] = " ".join(parts)
    return reasons


def example_report_ids(signal: ProductCodeSignal, limit: int = MAX_EXAMPLE_IDS) -> list[str]:
    """Pick up to ``limit`` report ids that best illustrate a signal.

    New signals prefer reports carrying a never-seen event type; severity
    escalations prefer Injury/Death reports; otherwise current-window reports.

    Args:
        signal: The product-code signal.
        limit: Maximum ids to return.

    Returns:
        Sorted report ids (at most ``limit``).
    """
    if signal.classification == "new_signal" and signal.new_event_type_report_ids:
        pool = signal.new_event_type_report_ids
    elif signal.classification == "severity_escalation" and signal.current_severe_report_ids:
        pool = signal.current_severe_report_ids
    else:
        pool = signal.current_report_ids
    return sorted(pool)[:limit]


def build_digest(
    result: DetectionResult,
    *,
    source: str = "openFDA device adverse-event reports stored in the local MaudeSignal database",
    fetch_summary: dict[str, int] | None = None,
    notes: tuple[str, ...] = (),
    device_types: dict[str, str] | None = None,
    report_brands: dict[str, str] | None = None,
    report_sources: dict[str, str] | None = None,
) -> Digest:
    """Summarize a detection result into a :class:`Digest`.

    Args:
        result: Output of :func:`~maudesignal.monitor.deterioration.detect_deterioration`.
        source: Data-source description shown under the headline.
        fetch_summary: Optional per-product-code count of newly stored records.
        notes: Optional extra lines to include verbatim.
        device_types: Optional ``product_code -> FDA device type`` names.
        report_brands: Optional ``report_id -> brand name`` from the stored reports.
        report_sources: Optional ``report_id -> normalized report source``.

    Returns:
        The digest.
    """
    new_count = sum(1 for s in result.signals if s.classification == "new_signal")
    serious = sum(1 for s in result.signals if s.classification == "severity_escalation")
    increased = sum(1 for s in result.signals if s.classification == "spike")
    stable = sum(1 for s in result.signals if s.is_stable)
    ranked = rank_signals(result.signals)
    brands = report_brands or {}
    window_brands = {s.product_code: brand_counts(s.current_report_ids, brands) for s in ranked}
    window_brands = {pc: pairs for pc, pairs in window_brands.items() if pairs}
    window_sources: dict[str, dict[str, int]] = {}
    if report_sources:
        for sig in result.signals:
            counts: dict[str, int] = {}
            for rid in sig.current_report_ids:
                key = report_sources.get(rid) or "unknown"
                counts[key] = counts.get(key, 0) + 1
            if counts:
                window_sources[sig.product_code] = dict(sorted(counts.items()))
    return Digest(
        result=result,
        headline=(
            f"New kind of problem: {new_count} · More serious than usual: {serious} · "
            f"Reports suddenly increased: {increased}"
        ),
        new_count=new_count,
        serious_count=serious,
        increased_count=increased,
        stable_count=stable,
        source=source,
        fetch_summary=dict(sorted((fetch_summary or {}).items())),
        notes=notes,
        ranked=ranked,
        rank_reasons=rank_reasons(ranked, stable),
        device_types={
            pc: name
            for pc, name in sorted((device_types or {}).items())
            if any(s.product_code == pc for s in result.signals)
        },
        window_brands=window_brands,
        window_sources=window_sources,
    )


def digest_from_database(
    db: Database,
    result: DetectionResult,
    *,
    fetch_summary: dict[str, int] | None = None,
    notes: tuple[str, ...] = (),
) -> Digest:
    """Build a digest with device names taken from the same database.

    Args:
        db: Database the detection ran over.
        result: The detection result.
        fetch_summary: Optional per-product-code count of newly stored records.
        notes: Optional extra lines to include verbatim.

    Returns:
        The digest, with FDA device types and report brand names filled in.
    """
    return build_digest(
        result,
        fetch_summary=fetch_summary,
        notes=notes,
        device_types=classification_names(db),
        report_brands=report_brands(db),
        report_sources={r.report_id: r.source for r in sourced_reports(db)},
    )


# ----------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _device_line(
    device_type: str | None, brands: list[tuple[str, int]], current_count: int
) -> str | None:
    parts = []
    if device_type:
        parts.append(f"FDA device type {device_type}")
    if brands:
        named = ", ".join(f"{b} ({n} of {current_count} reports)" for b, n in brands)
        parts.append(f"named on this window's reports: {named}")
    return f"- Device: {'; '.join(parts)}" if parts else None


def _signal_section(
    signal: ProductCodeSignal,
    reason: str | None = None,
    device_type: str | None = None,
    brands: list[tuple[str, int]] | None = None,
    sources: dict[str, int] | None = None,
) -> list[str]:
    title = CHANGE_LABELS[signal.classification]
    lines = [f"## {signal.product_code} — {title}", ""]
    device = _device_line(device_type, brands or [], signal.current_count)
    if device:
        lines.append(device)
    if sources:
        filed = ", ".join(f"{src} {n}" for src, n in sources.items())
        lines.append(f"- Filed by (openFDA report source), this window: {filed}")
    if reason:
        lines.append(f"- Why this rank: {reason}")
    if len(signal.triggers) > 1:
        fired = ", ".join(CHANGE_LABELS[t] for t in signal.triggers)
        lines.append(f"- Rules fired: {fired}")

    ratio = (
        "n/a (baseline mean is 0)" if signal.spike_ratio is None else f"{signal.spike_ratio:.2f}x"
    )
    lines.append(
        f"- Reports this window: {signal.current_count} "
        f"(baseline: {signal.baseline_count} over {BASELINE_WEEKS} weeks, "
        f"weekly mean {signal.baseline_weekly_mean:.2f}; ratio {ratio})"
    )
    delta = (
        "n/a" if signal.severe_share_delta_pp is None else f"{signal.severe_share_delta_pp:+.1f} pp"
    )
    lines.append(
        f"- Injury/Death share: this window {_pct(signal.current_severe_share)} "
        f"({signal.current_severe_count}/{signal.current_count}); "
        f"baseline {_pct(signal.baseline_severe_share)} "
        f"({signal.baseline_severe_count}/{signal.baseline_count}); change {delta}"
    )
    if signal.classification == "new_signal":
        if signal.prior_report_count == 0:
            lines.append("- First reports ever stored for this product code.")
        else:
            lines.append(
                f"- Event type(s) never seen before for this code: "
                f"{', '.join(signal.new_event_types)} "
                f"({signal.prior_report_count} earlier reports on file)"
            )
    type_counts = ", ".join(f"{t} {n}" for t, n in signal.current_event_type_counts)
    lines.append(f"- Event types this window: {type_counts or 'none'}")
    lines.append(f"- Example report ids: {', '.join(example_report_ids(signal)) or 'none'}")
    lines.append("")
    return lines


def render_markdown(digest: Digest) -> str:
    """Render the digest as Markdown (deterministic for a given input).

    Args:
        digest: The digest to render.

    Returns:
        Markdown text ending with the fixed advisory footer.
    """
    w = digest.result.window
    lines = [
        f"# MaudeSignal — what changed, data as of {w.as_of.isoformat()}",
        "",
        f"**{digest.headline}**",
        "",
        f"- Current window: {w.current_start.isoformat()} to {w.current_end.isoformat()} "
        f"({CURRENT_WINDOW_DAYS} days, by openFDA `date_received`)",
        f"- Baseline: {w.baseline_start.isoformat()} to {w.baseline_end.isoformat()} "
        f"({BASELINE_WEEKS} weeks)",
        f"- Source: {digest.source}; {digest.result.events_considered} reports considered "
        f"across {len(digest.result.signals)} product codes",
        f"- Rules: new kind of problem = first reports / never-seen event type; "
        f"reports suddenly increased = >= {SPIKE_MULTIPLIER}x baseline weekly mean and "
        f">= {SPIKE_MIN_REPORTS} reports; more serious than usual = Injury/Death share up "
        f">= {SEVERITY_ESCALATION_PP} pp and >= {SEVERITY_MIN_REPORTS} reports",
        f"- Ranking (most urgent first): {'; then '.join(RANKING_ORDER)}",
    ]
    if digest.fetch_summary:
        fetched = ", ".join(f"{pc} {n}" for pc, n in digest.fetch_summary.items())
        lines.append(f"- Newly stored this run: {fetched}")
    lines.extend(f"- Note: {note}" for note in digest.notes)
    lines.append("")

    flagged = digest.ranked or rank_signals(digest.result.signals)
    if flagged:
        for signal in flagged:
            pc = signal.product_code
            lines.extend(
                _signal_section(
                    signal,
                    digest.rank_reasons.get(pc),
                    digest.device_types.get(pc),
                    digest.window_brands.get(pc),
                    digest.window_sources.get(pc),
                )
            )
    else:
        lines.extend(["No product code crossed a rule threshold.", ""])

    stable = [s for s in digest.result.signals if s.is_stable]
    if stable:
        lines.append("## No change")
        lines.append("")
        lines.append(", ".join(f"{s.product_code} ({s.current_count} this window)" for s in stable))
        lines.append("")

    lines.extend(["---", "", DIGEST_FOOTER, ""])
    return "\n".join(lines)


# ----------------------------------------------------------------------
# JSON
# ----------------------------------------------------------------------


def _signal_to_dict(signal: ProductCodeSignal) -> dict[str, Any]:
    return {
        "product_code": signal.product_code,
        "classification": signal.classification,
        "label": CHANGE_LABELS[signal.classification],
        "triggers": list(signal.triggers),
        "current_count": signal.current_count,
        "current_report_ids": list(signal.current_report_ids),
        "current_severe_count": signal.current_severe_count,
        "current_severe_report_ids": list(signal.current_severe_report_ids),
        "current_severe_share": signal.current_severe_share,
        "baseline_count": signal.baseline_count,
        "baseline_report_ids": list(signal.baseline_report_ids),
        "baseline_weekly_mean": signal.baseline_weekly_mean,
        "baseline_severe_count": signal.baseline_severe_count,
        "baseline_severe_report_ids": list(signal.baseline_severe_report_ids),
        "baseline_severe_share": signal.baseline_severe_share,
        "severe_share_delta_pp": signal.severe_share_delta_pp,
        "spike_ratio": signal.spike_ratio,
        "prior_report_count": signal.prior_report_count,
        "new_event_types": list(signal.new_event_types),
        "new_event_type_report_ids": list(signal.new_event_type_report_ids),
        "current_event_type_counts": dict(signal.current_event_type_counts),
        "example_report_ids": example_report_ids(signal),
    }


def digest_to_dict(digest: Digest) -> dict[str, Any]:
    """Return a JSON-serializable representation of the digest.

    Args:
        digest: The digest.

    Returns:
        A plain dict with every number and report id used.
    """
    w = digest.result.window
    return {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "as_of": w.as_of.isoformat(),
        "headline": digest.headline,
        "counts": {
            "new": digest.new_count,
            "more_serious_than_usual": digest.serious_count,
            "reports_suddenly_increased": digest.increased_count,
            "stable": digest.stable_count,
        },
        "window": {
            "current_start": w.current_start.isoformat(),
            "current_end": w.current_end.isoformat(),
            "baseline_start": w.baseline_start.isoformat(),
            "baseline_end": w.baseline_end.isoformat(),
            "date_field": "date_received",
        },
        "rules": {
            "current_window_days": CURRENT_WINDOW_DAYS,
            "baseline_weeks": BASELINE_WEEKS,
            "spike_multiplier": SPIKE_MULTIPLIER,
            "spike_min_reports": SPIKE_MIN_REPORTS,
            "severity_escalation_pp": SEVERITY_ESCALATION_PP,
            "severity_min_reports": SEVERITY_MIN_REPORTS,
            "severe_event_types": ["death", "injury"],
            "ranking_order": list(RANKING_ORDER),
        },
        "source": digest.source,
        "events_considered": digest.result.events_considered,
        "events_after_as_of": digest.result.events_after_as_of,
        "events_skipped_missing_date": digest.result.events_skipped_missing_date,
        "fetch_summary": digest.fetch_summary,
        "notes": list(digest.notes),
        "signals": [_signal_to_dict(s) for s in digest.result.signals],
        "device_types": digest.device_types,
        "window_brands": {
            pc: [{"brand": b, "reports": n} for b, n in pairs]
            for pc, pairs in digest.window_brands.items()
        },
        "window_sources": digest.window_sources,
        "ranking": [
            {
                "rank": i + 1,
                "product_code": s.product_code,
                "classification": s.classification,
                "label": CHANGE_LABELS[s.classification],
                "reason": digest.rank_reasons.get(s.product_code, ""),
            }
            for i, s in enumerate(digest.ranked)
        ],
        "footer": DIGEST_FOOTER,
    }


def render_json(digest: Digest) -> str:
    """Render the digest as pretty-printed, key-stable JSON.

    Args:
        digest: The digest.

    Returns:
        JSON text with a trailing newline.
    """
    return json.dumps(digest_to_dict(digest), indent=2, ensure_ascii=False) + "\n"
