"""The "Simulated company checklist" section of the CAPA-need evidence pack PDF.

Checks the section text (banner, devices on the pack's product code, status, patterns), that
no existing pack number changes, and that a pack on a code with no company device has no
section.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from maudesignal.company import BANNER, checklist_for, load_company
from maudesignal.company.constants import FORBIDDEN, PROJECT_ROOT
from maudesignal.dossier.render import render_html
from maudesignal.dossier.service import produce
from maudesignal.storage.database import Database

DEMO_DB = PROJECT_ROOT / "data" / "demo" / "maudesignal_demo.db"


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Database:
    copy = tmp_path_factory.mktemp("pack") / "demo.db"
    shutil.copy(DEMO_DB, copy)
    return Database(copy)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _section(html: str) -> str:
    m = re.search(r'<section class="newpage" id="sec-company">.*?</section>', html, re.S)
    assert m, "company section missing"
    return m.group(0)


def test_section_text_has_banner_devices_statuses_and_patterns(db: Database) -> None:
    out = produce(db, product_code="LLZ", pdf=False)
    sec = _text(_section(out.html))
    assert BANNER in sec
    assert "7. Simulated company checklist" in sec
    view = load_company()
    for d in view.on_code("LLZ"):
        assert d.name in sec and d.model in sec and d.owner in sec
        assert d.status is not None
        assert d.status.to_status in sec and d.status.actor in sec and d.status.date_label in sec
        for p in d.patterns:
            assert f"{p.label} ({p.count})" in sec
    assert "Halcyon ViewStation" in sec and "Halcyon ReportDesk" in sec
    assert "test report TR-104 (sample)" in sec
    assert "chain intact" in sec
    assert not FORBIDDEN.search(sec)
    assert "never by this tool" in sec
    assert 'href="#sec-company"' in out.html  # listed in the contents


def test_existing_pack_content_is_unchanged_by_the_section(db: Database) -> None:
    out = produce(db, product_code="LLZ", pdf=False)
    with_section = out.html
    out.build.data.company_checklist = None
    without = render_html(out.build.data)
    stripped = with_section.replace(_section(with_section), "")
    stripped = re.sub(r"\s*<li><a href=\"#sec-company\">.*?</li>", "", stripped)
    stripped = re.sub(r"\{# =+ 7\..*?#\}", "", stripped)
    assert re.sub(r"\s+", " ", stripped).strip() == re.sub(r"\s+", " ", without).strip()
    # the printed figures (counts, shares) are exactly those of the pack without the section
    assert out.build.data.figures_failed == 0


def test_checklist_exists_only_for_codes_with_a_company_device(db: Database) -> None:
    assert checklist_for("ZZZ") is None
    out = produce(db, product_code="QIH", pdf=False)
    assert out.build.data.company_checklist is not None  # the company has a QIH device
    html = produce(db, product_code="MYN", pdf=False).html
    assert "Not applicable to our device" in _text(_section(html))


def test_pdf_text_carries_the_banner(db: Database, tmp_path: Path) -> None:
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        pytest.skip("pdftotext not installed")
    try:
        out = produce(db, product_code="LLZ", pdf=True)
    except RuntimeError as exc:  # WeasyPrint system libraries missing
        pytest.skip(str(exc))
    pdf = tmp_path / "pack.pdf"
    pdf.write_bytes(out.pdf)
    text = subprocess.run(  # fixed argv, no shell
        [pdftotext, "-layout", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout
    flat = re.sub(r"\s+", " ", text)
    assert BANNER in flat
    assert "7. Simulated company checklist" in flat
    assert "Halcyon ViewStation" in flat and "Halcyon ReportDesk" in flat
    assert "Already covered" in flat and "Testing in progress" in flat
