"""One text, three places: MUSE_CONNECTOR.md (Data questionnaire), web/public/privacy and the API /privacy page."""

# ruff: noqa: E501

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "hackathon" / "MUSE_CONNECTOR.md"
PAGE = ROOT / "web" / "public" / "privacy" / "index.html"


def _rows() -> list[tuple[str, str]]:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## Data questionnaire", 1)[1].split("\n## ", 1)[0]
    out = []
    for line in section.splitlines():
        if line.startswith("|") and not line.startswith("| Question") and not line.startswith("|---"):
            q, a = (c.strip() for c in line.strip().strip("|").split(" | ", 1))
            out.append((q, a))
    return out


def _plain(s: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", s)  # markdown code spans
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def test_questionnaire_rows_are_found() -> None:
    assert len(_rows()) >= 8


def test_web_privacy_page_repeats_every_answer_word_for_word() -> None:
    page = _plain(PAGE.read_text(encoding="utf-8"))
    for q, a in _rows():
        assert _plain(q) in page, q
        assert _plain(a) in page, q


def test_subprocessor_answer_names_upstash_and_the_meta_model_api() -> None:
    answer = dict(_rows())["Who else handles data (subprocessors)?"]
    for needle in ("Vercel", "Meta Model API", "Upstash", "openFDA"):
        assert needle in answer


def test_no_personal_email_in_the_doc_or_the_page() -> None:
    for p in (DOC, PAGE):
        assert re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", p.read_text(encoding="utf-8")) is None, p


def test_api_privacy_page_uses_the_same_answers() -> None:
    legal = pytest.importorskip("maudesignal.connector.legal_pages", reason="connector lives on track-c-live")
    doc = DOC.read_text(encoding="utf-8")
    for question, answer in legal.STATIC_ANSWERS:
        assert answer in doc, question
    assert {q for q, _ in legal.STATIC_ANSWERS} <= {q for q, _ in _rows()}
