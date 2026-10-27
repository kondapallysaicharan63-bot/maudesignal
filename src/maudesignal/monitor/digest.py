"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Deterministic overnight digest built from a :class:`DetectionResult`.

The digest is rendered twice — Markdown for humans and JSON for machines
(and for the downstream citation gate, which re-verifies every number
against the stored records). No LLM is involved: every sentence is a fixed
template filled with numbers taken verbatim from the detector.

Headline format: ``"<N> new, <M> worsening"`` where *new* counts
``new_signal`` product codes and *worsening* counts ``spike`` plus
``severity_escalation`` product codes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from maudesignal.monitor.deterioration import (
    BASELINE_WEEKS,
    CURRENT_WINDOW_DAYS,
    SEVERITY_ESCALATION_PP,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
    DetectionResult,
    ProductCodeSignal,
)

DIGEST_FOOTER = (
    "Advisory only — B2B regulatory triage aid, not medical advice. "
    "Every item requires human review; nothing is reported to FDA automatically."
)
DIGEST_SCHEMA_VERSION = "1.0"
MAX_EXAMPLE_IDS = 3

_TITLES: dict[str, str] = {
    "new_signal": "new signal",
    "severity_escalation": "severity escalation",
    "spike": "volume spike",
    "stable": "stable",
}


@dataclass(frozen=True)
class Digest:
    """A rendered-ready overnight digest.

    Attributes:
        result: The detection result the digest summarizes.
        headline: e.g. ``"3 new, 1 worsening"``.
        new_count: Product codes classified ``new_signal``.
        worsening_count: Product codes classified ``spike`` or
            ``severity_escalation``.
        stable_count: Product codes classified ``stable``.
        source: Human-readable description of the data source.
        fetch_summary: Optional ``product_code -> records newly stored`` from
            this run's ingestion step (empty when nothing was fetched).
        notes: Optional extra lines (e.g. a fetch warning), rendered verbatim.
    """

    result: DetectionResult
    headline: str
    new_count: int
    worsening_count: int
    stable_count: int
    source: str
    fetch_summary: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


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
) -> Digest:
    """Summarize a detection result into a :class:`Digest`.

    Args:
        result: Output of :func:`~maudesignal.monitor.deterioration.detect_deterioration`.
        source: Data-source description shown under the headline.
        fetch_summary: Optional per-product-code count of newly stored records.
        notes: Optional extra lines to include verbatim.

    Returns:
        The digest.
    """
    new_count = sum(1 for s in result.signals if s.classification == "new_signal")
    worsening = sum(
        1 for s in result.signals if s.classification in ("spike", "severity_escalation")
    )
    stable = sum(1 for s in result.signals if s.is_stable)
    return Digest(
        result=result,
        headline=f"{new_count} new, {worsening} worsening",
        new_count=new_count,
        worsening_count=worsening,
        stable_count=stable,
        source=source,
        fetch_summary=dict(sorted((fetch_summary or {}).items())),
        notes=notes,
    )


# ----------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _signal_section(signal: ProductCodeSignal) -> list[str]:
    title = _TITLES[signal.classification]
    lines = [f"## {signal.product_code} — {title}", ""]
    if len(signal.triggers) > 1:
        fired = ", ".join(_TITLES[t] for t in signal.triggers)
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
        f"# MaudeSignal overnight digest — data as of {w.as_of.isoformat()}",
        "",
        f"**{digest.headline}**",
        "",
        f"- Current window: {w.current_start.isoformat()} to {w.current_end.isoformat()} "
        f"({CURRENT_WINDOW_DAYS} days, by openFDA `date_received`)",
        f"- Baseline: {w.baseline_start.isoformat()} to {w.baseline_end.isoformat()} "
        f"({BASELINE_WEEKS} weeks)",
        f"- Source: {digest.source}; {digest.result.events_considered} reports considered "
        f"across {len(digest.result.signals)} product codes",
        f"- Rules: new signal = first reports / never-seen event type; "
        f"spike = >= {SPIKE_MULTIPLIER}x baseline weekly mean and >= {SPIKE_MIN_REPORTS} reports; "
        f"severity escalation = Injury/Death share up >= {SEVERITY_ESCALATION_PP} pp",
    ]
    if digest.fetch_summary:
        fetched = ", ".join(f"{pc} {n}" for pc, n in digest.fetch_summary.items())
        lines.append(f"- Newly stored this run: {fetched}")
    lines.extend(f"- Note: {note}" for note in digest.notes)
    lines.append("")

    flagged = digest.result.non_stable()
    if flagged:
        for signal in flagged:
            lines.extend(_signal_section(signal))
    else:
        lines.extend(["No product code crossed a rule threshold.", ""])

    stable = [s for s in digest.result.signals if s.is_stable]
    if stable:
        lines.append("## Stable")
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
            "worsening": digest.worsening_count,
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
            "severe_event_types": ["death", "injury"],
        },
        "source": digest.source,
        "events_considered": digest.result.events_considered,
        "events_after_as_of": digest.result.events_after_as_of,
        "events_skipped_missing_date": digest.result.events_skipped_missing_date,
        "fetch_summary": digest.fetch_summary,
        "notes": list(digest.notes),
        "signals": [_signal_to_dict(s) for s in digest.result.signals],
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
