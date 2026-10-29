"""Dashboard themes: design-system tokens, WCAG contrast, CSS generation (no browser)."""

from __future__ import annotations

import json

import pytest

from maudesignal.dashboard.theme import (
    CONTRAST_PAIRS,
    DESIGN_DIR,
    THEME_IDS,
    THEME_NAMES,
    contrast_ratio,
    normalize_theme,
    theme_css,
    theme_values,
)

THEMES = [tid for tid in THEME_IDS.values() if tid]


def test_selector_offers_the_requested_themes_in_order() -> None:
    assert THEME_NAMES[:5] == ("Light", "Dark", "Black", "System", "Pink")
    assert "High contrast" in THEME_NAMES


@pytest.mark.parametrize("tid", THEMES)
@pytest.mark.parametrize(("fg", "bg", "need"), CONTRAST_PAIRS)
def test_every_text_pair_meets_wcag(tid: str, fg: str, bg: str, need: float) -> None:
    v = theme_values(tid)
    ratio = contrast_ratio(v[fg], v[bg])
    assert ratio >= need, f"{tid}: {fg} on {bg} is {ratio:.2f}:1, needs {need}:1"


def test_pink_is_soft_pink_paper_with_white_cards() -> None:
    v = theme_values("pink")
    r, g, b = (int(v["paper"][i : i + 2], 16) for i in (1, 3, 5))
    assert r > g and r > 240 and b > g  # a light pink
    assert v["surface"].lower() == "#ffffff"


def test_black_is_true_black() -> None:
    assert theme_values("black")["paper"] == "#000000"


def test_every_theme_defines_every_token() -> None:
    data = json.loads((DESIGN_DIR / "tokens.json").read_text(encoding="utf-8"))
    ids = {t["id"] for t in data["color"]["themes"]}
    assert set(THEMES) <= ids
    for t in data["color"]["tokens"]:
        if not isinstance(t["value"], str):
            assert ids <= set(t["value"]), f"{t['name']} misses a theme"


def test_tokens_css_is_regenerated_from_tokens_json() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_tokens", DESIGN_DIR / "build_tokens.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = json.loads((DESIGN_DIR / "tokens.json").read_text(encoding="utf-8"))
    assert mod.build(data) == (DESIGN_DIR / "tokens.css").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("pink", "Pink"),
        ("DARK", "Dark"),
        ("contrast", "High contrast"),
        ("system", "System"),
        ("high contrast", "High contrast"),
        (None, "Light"),
        ("neon", "Light"),
    ],
)
def test_normalize_theme(raw: str | None, label: str) -> None:
    assert normalize_theme(raw) == label


def test_css_puts_imports_first_and_sets_the_theme() -> None:
    css = theme_css("Pink")
    body = css.removeprefix("<style>")
    assert body.startswith("@import")
    assert f"--paper:{theme_values('pink')['paper']}" in css
    assert css.count("@import") == 2  # fonts + icons, both at the top
    first_rule = body.index(":root")
    assert all(body.index(i) < first_rule for i in ("@import url('https://fonts",))


def test_system_switches_on_prefers_color_scheme() -> None:
    css = theme_css("System")
    assert f"--paper:{theme_values('light')['paper']}" in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert f"--paper:{theme_values('dark')['paper']}" in css


def test_no_raw_hex_in_the_bridge() -> None:
    import re

    from maudesignal.dashboard import theme

    bridge = (theme.Path(theme.__file__).with_name("streamlit_bridge.css")).read_text()
    assert re.findall(r"#[0-9a-fA-F]{3,6}\b", bridge) == []
