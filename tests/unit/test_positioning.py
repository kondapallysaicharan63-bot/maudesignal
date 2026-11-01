"""The product headline is one sentence, identical wherever it is stated (PRD v2.3 section 11b)."""

from __future__ import annotations

import json
from pathlib import Path

from maudesignal.connector.registry import GUIDANCE, HEADLINE

ROOT = Path(__file__).resolve().parents[2]
OLD = "Every morning"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_headline_text() -> None:
    assert HEADLINE == (
        "MaudeSignal cuts the time to investigate a complaint against FDA data and to prepare "
        "PMS evidence, and keeps every fact traceable for audit."
    )
    assert GUIDANCE.startswith(HEADLINE)


def test_web_headline_matches() -> None:
    assert HEADLINE in _read("web/src/positioning.ts")
    assert HEADLINE in _read("web/index.html")


def test_headline_in_docs_and_generated_files() -> None:
    for rel in ("README.md", "CLAUDE.md", "HACKATHON.md", "api/docs.html"):
        assert HEADLINE in _read(rel), rel
    assert json.loads(_read("api/mcp-manifest.json"))["description"].startswith(HEADLINE)
    assert HEADLINE in json.loads(_read("api/openapi.json"))["info"]["description"]


def _flat(rel: str) -> str:
    """The file text with string-literal glue and whitespace removed, so wrapped copies compare."""
    text = _read(rel)
    for junk in ('"\n', "\n", '"', "'", "(", ")", "  "):
        text = text.replace(junk, " ")
    return " ".join(text.split())


def test_headline_copies_in_code_are_the_same_sentence() -> None:
    flat = " ".join(HEADLINE.split())
    for rel in (
        "src/maudesignal/cli.py",
        "src/maudesignal/__init__.py",
        "scripts/release/e2e_web.py",
    ):
        assert flat in _flat(rel), rel


def test_legal_page_uses_the_constant() -> None:
    assert "HEADLINE" in _read("src/maudesignal/connector/legal_pages.py")


def test_old_headline_is_gone() -> None:
    for rel in ("README.md", "CLAUDE.md", "HACKATHON.md"):
        assert OLD not in _read(rel), rel


def test_measurements_file_is_empty_until_recorded() -> None:
    data = json.loads(_read("web/public/data/measurements.json"))
    assert data["schema"] == 1
    for m in data["measurements"]:
        assert all(str(m.get(k, "")).strip() for k in ("id", "task", "who", "when", "how"))
