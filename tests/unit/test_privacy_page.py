"""The web /privacy page must be generated from the Data questionnaire, with no personal e-mail."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "build_privacy_page", ROOT / "scripts" / "build_privacy_page.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_page_matches_questionnaire() -> None:
    mod = _load()
    assert mod.TARGET.read_text(encoding="utf-8") == mod.render()


def test_questionnaire_covers_the_meta_questions() -> None:
    rows = dict(_load().questionnaire())
    text = " ".join(rows.values())
    for needle in ("iad1", "Upstash", "GOV.UK", "voice clip", "label photo", "30 November 2026"):
        assert needle in text
    assert "photos" not in rows["Who else handles data (subprocessors)?"].split("Not sent")[-1]


def test_no_personal_email_in_page_or_form_doc() -> None:
    for rel in ("web/public/privacy/index.html", "docs/hackathon/MUSE_CONNECTOR.md"):
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"[\w.+-]+@(gmail|yahoo|outlook|hotmail)\.com", body), rel
