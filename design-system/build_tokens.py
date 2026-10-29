"""Generate design-system/tokens.css from design-system/tokens.json.

Usage:
    python3.12 design-system/build_tokens.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HEADER = (
    "/* MaudeSignal — generated from tokens.json. Do not edit by hand; edit tokens.json. */\n"
    '/* Themes: data-theme="light" (Paper, default) | "dark" (Night) '
    '| "contrast" (High contrast) | "black" | "pink". */'
)


def _value(value: Any, theme: str, first: str) -> str:
    """Resolve a token value for one theme, falling back to the first theme."""
    resolved = value if isinstance(value, str) else str(value.get(theme, value[first]))
    if resolved.startswith("{") and resolved.endswith("}"):
        return f"var(--{resolved[1:-1]})"
    return resolved


def _theme_block(tokens: dict[str, Any], theme: str, first: str, indent: str) -> str:
    """Return the custom-property lines for one colour theme."""
    rows = tokens["color"]["tokens"] + tokens.get("shadow", {}).get("tokens", [])
    return "\n".join(f"{indent}--{t['name']}: {_value(t['value'], theme, first)};" for t in rows)


def build(tokens: dict[str, Any]) -> str:
    """Compile the tokens object into a stylesheet."""
    themes = [t["id"] for t in tokens["color"]["themes"]]
    first = themes[0]
    schemes = {"dark": "dark", "black": "dark"}
    parts = [HEADER]
    for theme in themes:
        selector = (
            f':root,\n[data-theme="{theme}"]' if theme == first else f'[data-theme="{theme}"]'
        )
        body = _theme_block(tokens, theme, first, "  ")
        parts.append(f"{selector} {{\n{body}\n  color-scheme: {schemes.get(theme, 'light')};\n}}")
    if "dark" in themes:
        body = _theme_block(tokens, "dark", first, "    ")
        parts.append(
            "@media (prefers-color-scheme: dark) {\n  :root:not([data-theme]) {\n"
            f"{body}\n    color-scheme: dark;\n  }}\n}}"
        )
    scale = [
        f"  --{t['name']}: {t['value']};"
        for family in ("spacing", "radius")
        for t in tokens.get(family, {}).get("tokens", [])
    ]
    fonts = [f"  --font-{key}: {stack};" for key, stack in tokens["type"]["families"].items()]
    parts.append(":root {\n" + "\n".join(scale + fonts) + "\n}")
    styles = []
    for group in tokens["type"]["groups"]:
        for style in group["styles"]:
            family = style.get("family", group["family"])
            rule = (
                f".t-{style['name']} {{ font: {style['fontWeight']} "
                f"{style['fontSize']}/{style['lineHeight']} var(--font-{family});"
            )
            if "letterSpacing" in style:
                rule += f" letter-spacing: {style['letterSpacing']};"
            if style["name"] == "kicker":
                rule += " text-transform: uppercase;"
            styles.append(rule + " }")
    parts.append("/* Type styles */\n" + "\n".join(styles))
    return "\n\n".join(parts) + "\n"


def main() -> None:
    """Read tokens.json and write tokens.css next to it."""
    tokens = json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))
    (HERE / "tokens.css").write_text(build(tokens), encoding="utf-8")


if __name__ == "__main__":
    main()
