"""Deterministic inline-SVG bar chart of weekly report counts.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

matplotlib is not a dependency of this project, so the chart is plain SVG
written here. It is generated only from the figures the builder computed —
never an AI image. Each bar label carries the same ``data-claim`` attribute as
the tables, so the gate can re-verify the chart too.
"""

from __future__ import annotations

import math
from html import escape

from maudesignal.dossier.figures import Figure
from maudesignal.dossier.model import WeeklyBar

_W, _H = 640, 250
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 46, 150, 18, 52
_BASE = "#7b8794"
_CUR = "#b3261e"
_INK = "#1c2b33"


def _nice_max(v: float) -> int:
    if v <= 5:
        return 5
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return int(m * mag)
    return int(10 * mag)


def weekly_chart_svg(bars: tuple[WeeklyBar, ...], mean: Figure, threshold: Figure) -> str:
    """Render the weekly-count chart.

    Args:
        bars: Weekly bars, oldest first (baseline weeks then the current window).
        mean: Baseline weekly mean (drawn as a dashed line).
        threshold: Spike threshold (2 × mean; drawn as a dotted line).

    Returns:
        An ``<svg>`` element as a string.
    """
    top = _nice_max(max([b.count.value for b in bars] + [threshold.value, 1.0]))
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def y(v: float) -> float:
        return _PAD_T + plot_h - plot_h * (v / top)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'viewBox="0 0 {_W} {_H}" font-family="Helvetica, Arial, sans-serif" font-size="10">',
        f'<rect x="0" y="0" width="{_W}" height="{_H}" fill="#ffffff"/>',
    ]
    step = top / 5
    for i in range(6):
        v = step * i
        yy = y(v)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{yy:.1f}" x2="{_PAD_L + plot_w}" y2="{yy:.1f}" '
            'stroke="#e3e6ea" stroke-width="1"/>'
        )
        parts.append(
            f'<text class="axis" x="{_PAD_L - 6}" y="{yy + 3:.1f}" text-anchor="end" '
            f'fill="#65676b">{v:g}</text>'
        )
    n = len(bars)
    slot = plot_w / max(n, 1)
    bw = slot * 0.6
    for i, b in enumerate(bars):
        x = _PAD_L + slot * i + (slot - bw) / 2
        yy = y(b.count.value)
        color = _CUR if b.is_current else _BASE
        parts.append(
            f'<rect x="{x:.1f}" y="{yy:.1f}" width="{bw:.1f}" '
            f'height="{_PAD_T + plot_h - yy:.1f}" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{x + bw / 2:.1f}" y="{yy - 4:.1f}" text-anchor="middle" '
            f'fill="{_INK}" font-weight="bold" data-claim=\'{escape(b.count.claim_json)}\'>'
            f"{escape(b.count.display)}</text>"
        )
        parts.append(
            f'<text class="axis" x="{x + bw / 2:.1f}" y="{_PAD_T + plot_h + 14:.1f}" '
            f'text-anchor="middle" fill="{_INK}">{escape(b.label)}</text>'
        )
        parts.append(
            f'<text class="axis" x="{x + bw / 2:.1f}" y="{_PAD_T + plot_h + 26:.1f}" '
            f'text-anchor="middle" fill="#65676b" font-size="8">'
            f"{b.date_from:%m-%d}–{b.date_to:%m-%d}</text>"
        )
    for fig, dash, label in (
        (mean, "6,4", "baseline weekly mean"),
        (threshold, "2,3", "spike threshold (2×)"),
    ):
        yy = y(fig.value)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{yy:.1f}" x2="{_PAD_L + plot_w}" y2="{yy:.1f}" '
            f'stroke="{_INK}" stroke-width="1.2" stroke-dasharray="{dash}"/>'
        )
        parts.append(
            f'<text x="{_PAD_L + plot_w + 6}" y="{yy + 3:.1f}" fill="{_INK}">{label} = '
            f"<tspan data-claim='{escape(fig.claim_json)}'>{escape(fig.display)}</tspan></text>"
        )
    parts.append(
        f'<text class="axis" x="{_PAD_L - 34}" y="{_PAD_T + plot_h / 2:.1f}" fill="#65676b" '
        f'transform="rotate(-90 {_PAD_L - 34} {_PAD_T + plot_h / 2:.1f})" '
        'text-anchor="middle">reports / week (date_received)</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
