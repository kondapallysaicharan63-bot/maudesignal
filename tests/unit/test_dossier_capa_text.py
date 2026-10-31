"""Pack wording: a report is cited for a phrase only if its stored text holds it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from maudesignal.copilot.actions import draft_capa
from maudesignal.dossier import build_dossier, render_html
from maudesignal.dossier.capa_text import cite_for_problem, display_title, problem_terms
from maudesignal.storage.database import Database
from tests.unit.test_dossier import CURRENT_IDS, PC, _db

TITLE = "QIH Acme Triage error 500 - this week increase"
STATEMENT = "QIH reports suddenly increased with Acme Triage reports describing error 500"
TEXTS = {
    "a": "Unable to finalize report and encounter an error 500.",
    "b": "An  ERROR   500 occurs for one study.",
    "c": "A case needed correction.",
}


def test_terms_are_found_and_normalised() -> None:
    assert problem_terms("describing Error  500 and code 404", "") == ("error 500", "code 404")
    assert problem_terms("nothing numbered here") == ()


def test_only_reports_holding_the_phrase_are_cited() -> None:
    c = cite_for_problem(STATEMENT, ["c", "a", "b"], TEXTS, TITLE)
    assert c.terms == ("error 500",)
    assert c.supporting == ("a", "b")
    assert c.not_supporting == ("c",)


def test_no_checkable_phrase_keeps_every_report() -> None:
    c = cite_for_problem("Alerts were not sent.", ["a", "c"], TEXTS)
    assert c.supporting == ("a", "c") and c.not_supporting == ()


def test_missing_text_does_not_support() -> None:
    assert cite_for_problem("error 500", ["zz"], {}).not_supporting == ("zz",)


def _title(
    title: str = TITLE,
    *,
    product_code: str = "QIH",
    change_label: str = "reports suddenly increased",
    texts: dict[str, str] | None = None,
    brands: list[str] | None = None,
) -> str:
    return display_title(
        title,
        product_code=product_code,
        change_label=change_label,
        texts=TEXTS if texts is None else texts,
        brands=["Acme Triage"] if brands is None else brands,
    )


def test_title_no_longer_implies_an_error_specific_increase() -> None:
    assert _title() == "QIH reports suddenly increased (Acme Triage reports include error 500)"
    assert _title("QIH Acme Triage error 500 – this week increase") == _title()


def test_title_drops_the_parenthesis_when_not_backed() -> None:
    plain = "QIH reports suddenly increased"
    assert _title(texts={"c": "A case needed correction."}) == plain
    assert _title(brands=["Other"]) == plain


def test_title_untouched_for_other_changes_codes_and_wordings() -> None:
    assert _title(change_label="more serious than usual") == TITLE
    assert _title(product_code="LLZ") == TITLE
    assert _title("QIH alert failures") == "QIH alert failures"
    assert _title("") == ""


def _pack(db: Database, title: str, statement: str) -> str:
    return draft_capa(
        db,
        product_code=PC,
        title=title,
        problem_statement=statement,
        report_ids=CURRENT_IDS,
        actor="copilot:muse-spark",
    ).capa_id


def test_dossier_without_a_numbered_phrase_cites_every_report(tmp_path: Path) -> None:
    db = _db(tmp_path)
    cid = _pack(db, "QIH alert failures", "Alerts were not sent after a server update.")
    b = build_dossier(db, capa_id=cid, awareness_date=date(2026, 10, 27))
    assert b.data.capa is not None
    assert b.data.capa.problem_terms == ()
    assert "Reports that contain" not in render_html(b.data)


def test_dossier_prints_checked_title_and_cites_only_supporting_reports(tmp_path: Path) -> None:
    db = _db(tmp_path)
    for rid in ("9000011", "9000013"):
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code=PC,
            event_type="Malfunction",
            event_date=None,
            narrative="Alert failed with an error 500 on the server.",
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Triage",
        )
    cid = _pack(db, TITLE, STATEMENT)
    b = build_dossier(db, capa_id=cid, awareness_date=date(2026, 10, 27))
    capa = b.data.capa
    assert capa is not None
    assert capa.title == TITLE  # as recorded
    assert capa.display_title == (
        "QIH reports suddenly increased (Acme Triage reports include error 500)"
    )
    assert capa.problem_supporting_ids == ("9000011", "9000013")
    assert set(capa.problem_unsupported_ids) == set(CURRENT_IDS) - {"9000011", "9000013"}
    html = render_html(b.data)
    assert "this week increase" not in html
    assert capa.display_title in html
    assert "2 of 6 cited reports" in html
    assert "cover every report of product code QIH" in html
