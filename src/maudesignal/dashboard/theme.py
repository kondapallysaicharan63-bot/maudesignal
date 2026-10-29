"""Dashboard themes, read from the MaudeSignal design system (``design-system/``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``design-system/tokens.json`` is the single source of every colour. This module
turns the chosen theme into CSS custom properties on ``:root`` (Streamlit cannot
set ``data-theme`` on ``<html>``), then adds ``design-system/maudesignal.css``
(the ``.ms-*`` components, Newsreader + Geist) and a bridge that colours
Streamlit's own widgets from the same tokens.

Themes offered in the top navigation: Light (Paper), Dark (Night), Black,
System (follows the OS: Paper or Night), Pink (soft pink paper, white tiles)
and High contrast. The choice is kept in ``st.session_state`` and mirrored to
the ``?theme=`` query parameter.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DESIGN_DIR = Path(__file__).resolve().parents[3] / "design-system"

#: Selector label -> design-system theme id (``None`` = follow the OS).
THEME_IDS: dict[str, str | None] = {
    "Light": "light",
    "Dark": "dark",
    "Black": "black",
    "System": None,
    "Pink": "pink",
    "High contrast": "contrast",
}
THEME_NAMES: tuple[str, ...] = tuple(THEME_IDS)
DEFAULT_THEME = "Light"

#: (text token, background token, minimum WCAG ratio) the dashboard relies on.
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("ink", "paper", 7.0),
    ("ink", "surface", 7.0),
    ("ink-2", "paper", 4.5),
    ("ink-2", "surface", 4.5),
    ("ink-3", "paper", 4.5),
    ("ink-3", "surface", 4.5),
    ("ink-3", "surface-sunk", 4.5),
    ("on-inverse", "inverse", 7.0),
    ("on-inverse-2", "inverse", 4.5),
    ("accent-on-inverse", "inverse", 4.5),
    ("accent", "surface", 4.5),
    ("accent", "paper", 4.5),
    ("accent", "accent-soft", 4.5),
    ("ink", "accent-soft", 7.0),
    ("critical", "surface", 4.5),
    ("critical", "critical-soft", 4.5),
    ("on-critical", "critical", 4.5),
    ("warning", "warning-soft", 4.5),
    ("warning", "surface", 4.5),
    ("success", "success-soft", 4.5),
    ("success", "surface", 4.5),
    ("rule-strong", "surface", 3.0),
    ("warning-mark", "surface", 3.0),
)


def normalize_theme(name: str | None) -> str:
    """A valid selector label (case-insensitive, ids accepted), else :data:`DEFAULT_THEME`."""
    if name:
        key = name.strip().lower()
        for label, tid in THEME_IDS.items():
            if key in (label.lower(), (tid or "system")):
                return label
    return DEFAULT_THEME


@lru_cache(maxsize=1)
def _tokens() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DESIGN_DIR / "tokens.json").read_text(encoding="utf-8"))
    return data


def theme_values(theme_id: str) -> dict[str, str]:
    """``token -> value`` for one design-system theme id (colours and shadows)."""
    tokens = _tokens()
    first = tokens["color"]["themes"][0]["id"]
    rows = tokens["color"]["tokens"] + tokens.get("shadow", {}).get("tokens", [])
    out: dict[str, str] = {}
    for t in rows:
        v = t["value"]
        out[t["name"]] = v if isinstance(v, str) else str(v.get(theme_id, v[first]))
    return out


def _block(theme_id: str) -> str:
    return "".join(f"--{k}:{v};" for k, v in theme_values(theme_id).items())


@lru_cache(maxsize=1)
def _static_css() -> str:
    """Spacing/radius/font tokens from tokens.css (after its colour blocks) + components."""
    tokens_css = (DESIGN_DIR / "tokens.css").read_text(encoding="utf-8")
    scale = tokens_css[tokens_css.rindex(":root {") :]
    components = (DESIGN_DIR / "maudesignal.css").read_text(encoding="utf-8")
    bridge = (Path(__file__).with_name("streamlit_bridge.css")).read_text(encoding="utf-8")
    # @import must open a stylesheet, so the font imports are hoisted to the top.
    lines = (scale + components + "\n" + bridge).split("\n")
    imports = [ln for ln in lines if ln.startswith("@import")]
    return "\n".join(imports + [ln for ln in lines if not ln.startswith("@import")])


# Streamlit draws st.dataframe on a canvas from its own server-wide theme (light), and
# that theme cannot change per browser session. In dark themes the grid is inverted
# instead (hue-rotated so colours keep their meaning), which keeps text readable.
_DARK_GRID = '[data-testid="stDataFrame"] canvas {filter: invert(0.92) hue-rotate(180deg);}'


def _dark_grid(tid: str | None) -> str:
    if tid is None:
        return f"@media (prefers-color-scheme: dark){{{_DARK_GRID}}}"
    return _DARK_GRID if tid in ("dark", "black") else ""


def theme_css(name: str) -> str:
    """The ``<style>`` block for one theme: tokens, components and the Streamlit bridge."""
    label = normalize_theme(name)
    tid = THEME_IDS[label]
    if tid is None:
        colours = (
            f":root{{{_block('light')}color-scheme:light;}}"
            f"@media (prefers-color-scheme: dark){{:root{{{_block('dark')}"
            "color-scheme:dark;}}"
        )
    else:
        scheme = "dark" if tid in ("dark", "black") else "light"
        colours = f":root{{{_block(tid)}color-scheme:{scheme};}}"
    css = _static_css() + _dark_grid(tid)
    cut = css.rfind("@import")
    cut = css.index("\n", cut) + 1 if cut >= 0 else 0
    return f"<style>{css[:cut]}{colours}{css[cut:]}</style>"


def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else float(((c + 0.055) / 1.055) ** 2.4)


def _rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a ``#RRGGBB`` colour."""
    r, g, b = (_channel(x) for x in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two ``#RRGGBB`` colours (1.0 – 21.0)."""
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
