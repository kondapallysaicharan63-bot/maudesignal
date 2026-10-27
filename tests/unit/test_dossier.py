"""Tests for the Signal Evaluation & CAPA dossier and its AI reviewer (HACKATHON-BUILT).

No network: models are scripted fakes, the image API is a fake HTTP client.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.copilot.actions import decide_capa, draft_capa
from maudesignal.copilot.tools import deadline_check
from maudesignal.dossier import build_dossier, render_html, verify_html
from maudesignal.dossier.builder import DossierError, top_worsening_signal
from maudesignal.dossier.figures import (
    check_figure,
    const_figure,
    count_figure,
    derived_figure,
    extract_sentences,
    recompute,
    records_figure,
    verify_figures,
)
from maudesignal.dossier.illustration import (
    IllustrationError,
    generate_illustration,
    prompt_for,
)
from maudesignal.dossier.model import MDR_STAMP, Illustration
from maudesignal.dossier.narrative import (
    NarrativeRecording,
    draft_narrative,
    gate_narrative,
    load_recording,
    save_recording,
)
from maudesignal.dossier.render import pdf_page_png, template_context
from maudesignal.dossier.review import (
    ReviewError,
    html_to_text,
    load_review,
    parse_findings,
    record_review,
    review_dossier,
    save_review,
)
from maudesignal.dossier.service import produce
from maudesignal.gate import claim_from_dict, verify_sentence
from maudesignal.storage.database import Database

PC = "QIH"
FIXED_TS = datetime(2026, 10, 27, 12, 0, 0)

# (report id, date_received, event type, narrative)
ROWS = [
    ("9000001", "20260729", "Malfunction", "Baseline: worklist did not refresh after login."),
    ("9000002", "20260805", "Malfunction", "Baseline: notification arrived late by one hour."),
    ("9000003", "20260812", "Injury", "Baseline: delayed review of a positive study."),
    ("9000004", "20260819", "Malfunction", "Baseline: viewer froze while scrolling."),
    ("9000011", "20260825", "Malfunction", "Triage alert was not sent after a server update."),
    ("9000012", "20260826", "Malfunction", "Study failed to load; the app crashed on open."),
    ("9000013", "20260827", "Malfunction", "Alert was not sent for a flagged study."),
    ("9000014", "20260828", "Malfunction", "The mobile app crashed when opening the study."),
    ("9000015", "20260830", "Injury", "Delayed notification of a large vessel occlusion."),
    ("9000016", "20260831", "Malfunction", "Server update stopped all alerts for two hours."),
]
CURRENT_IDS = [r[0] for r in ROWS[4:]]


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "d.db")
    for rid, d, et, text in ROWS:
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code=PC,
            date_received=d,
            date_of_event=None,
            raw_payload={
                "report_number": f"3001234-2026-{rid[-5:]}",
                "pma_pmn_number": "K999001",
                "device": [
                    {
                        "brand_name": "ACME TRIAGE",
                        "generic_name": "RADIOLOGICAL COMPUTER-ASSISTED TRIAGE SOFTWARE",
                        "manufacturer_d_name": "ACME AI INC.",
                        "manufacturer_d_city": "BOSTON",
                        "manufacturer_d_state": "MA",
                        "manufacturer_d_country": "US",
                        "model_number": "AT-2",
                        "openfda": {
                            "device_name": "Radiological Computer-Assisted Triage Software",
                            "regulation_number": "892.2080",
                            "device_class": "2",
                        },
                    }
                ],
                "patient": [{"patient_age": "should never be read"}],
            },
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code=PC,
            event_type=et,
            event_date=None,
            narrative=text,
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Triage",
        )
    return db


def _capa(db: Database) -> str:
    row = draft_capa(
        db,
        product_code=PC,
        title="QIH alert failures",
        problem_statement="Alerts were not sent after a server update.",
        report_ids=CURRENT_IDS,
        actor="copilot:muse-spark",
    )
    return row.capa_id


def _resp(content: str, pin: int = 1000, pout: int = 200) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=pin, completion_tokens=pout),
    )


class FakeClient:
    """Scripted OpenAI-compatible client; an Exception in the script is raised."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_html_contains_every_required_section(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, capa_id=_capa(db), awareness_date=date(2026, 10, 27))
    html = render_html(b.data)
    assert re.fullmatch(r"SER-QIH-20260831-\d{3}", b.data.doc_id)
    for heading in (
        "1. Document control",
        "2. Signal evaluation",
        "3. Evidence — supporting MAUDE reports",
        "4. CAPA record (ISO 13485:2016 §8.5.2 / §8.5.3",
        "4.1 (a) Review of nonconformities, including complaints",
        "4.2 (b) Determination of the cause(s) of nonconformity",
        "4.3 (c) Evaluation of the need for action",
        "4.4 (d) Planning, documenting and implementing action",
        "4.5 (e) Verification that the action does not adversely affect",
        "4.6 (f) Review of the effectiveness",
        "Preventive action (§8.5.3)",
        "5. MDR assessment worksheet (FDA Form 3500A map)",
        "6. Narrative summary",
        "Appendix A. Audit trail",
    ):
        assert heading in html, heading
    for item in ("D1", "D2a", "D2b", "D3", "D4", "G3", "G4", "G8", "H1", "H10", "803.52(c)"):
        assert f"<td>{item}</td>" in html, item
    # page furniture
    assert 'counter(page) " of " counter(pages)' in html
    assert "@top-center" in html and b.data.doc_id in html
    assert "To be completed by CAPA owner" in html
    assert "Not a 21 CFR Part 11 signature" in html
    assert "820.100" in html and "superseded" in html  # cited only to say it is not used
    # openFDA pre-fills
    assert "ACME TRIAGE" in html and "K999001" in html and "AT-2" in html
    # evidence table: every cited report, MAUDE link, ≤300-char excerpt
    for rid in CURRENT_IDS:
        assert f"mdrfoi__id={rid}" in html
    assert "should never be read" not in html  # patient fields are never read


def test_evidence_excerpts_are_capped(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_normalized_event(
        maude_report_id="9000016",
        product_code=PC,
        event_type="Malfunction",
        event_date=None,
        narrative="x " * 400,
        mfr_narrative=None,
        manufacturer="Acme",
        brand_name="Acme Triage",
    )
    b = build_dossier(db, product_code=PC)
    row = next(e for e in b.data.evidence if e.report_id == "9000016")
    assert len(row.excerpt) <= 300 and row.excerpt.endswith("…")


def test_signal_numbers_match_the_monitor(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, product_code=PC)
    s = b.data.signal
    assert s.classification == "spike"
    assert (s.current_count.value, s.baseline_count.value) == (6, 4)
    assert s.baseline_weekly_mean.display == "1.00"
    assert s.spike_ratio is not None and s.spike_ratio.display == "6.00×"
    assert s.current_severe.value == 1 and s.baseline_severe.value == 1
    assert s.current_severe_share is not None and s.current_severe_share.display == "16.7%"
    assert [bar.count.value for bar in s.weekly] == [1, 1, 1, 1, 6]
    assert "<svg" in s.chart_svg and "data-claim" in s.chart_svg
    assert b.data.figures_checked > 10 and b.data.figures_failed == 0


# ---------------------------------------------------------------------------
# Numbers re-verify through the gate
# ---------------------------------------------------------------------------


def test_every_number_in_rendered_html_reverifies_through_gate(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, capa_id=_capa(db))
    html = render_html(b.data)
    report = verify_html(html, b.store)
    assert report.total >= 15
    assert report.failed == []
    kinds = {c.claim["kind"] for c in report.checks}
    assert {"count", "derived"} <= kinds
    # count claims are verified by the gate itself
    counts = [c for c in report.checks if c.claim["kind"] == "count"]
    for c in counts:
        assert verify_sentence(
            f"{c.display} reports", [claim_from_dict(c.claim)], b.store
        ).status == ("pass")


def test_tampered_number_is_caught(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, product_code=PC)
    html = render_html(b.data)
    tampered = re.sub(
        r'(<span class="fig" data-claim="[^"]+">)6(</span>)', r"\g<1>60\2", html, count=1
    )
    assert tampered != html
    report = verify_html(tampered, b.store)
    assert len(report.failed) == 1 and "printed 60" in report.failed[0].reason


def test_figure_helpers() -> None:
    from maudesignal.gate import EvidenceRecord, EvidenceStore

    store = EvidenceStore.from_iterables(
        [EvidenceRecord("1", PC, "malfunction", "20260801", "t"), EvidenceRecord("2", PC)]
    )
    two = count_figure(PC, 2)
    zero = count_figure(PC, 0, event_type="death")
    assert recompute(derived_figure("div", [two, zero], 0, digits=1).claim, store)[0] is None
    assert recompute({"kind": "derived", "op": "nope", "operands": []}, store)[0] is None
    assert recompute({"kind": "bogus"}, store)[0] is None
    assert recompute(const_figure(4).claim, store) == (4.0, "method constant")
    assert recompute(records_figure(["1", "2"], PC).claim, store)[0] == 2
    assert recompute(records_figure(["1", "zz"]).claim, store)[0] is None
    assert not check_figure("three", count_figure(PC, 2).claim, store).ok
    assert verify_figures([two, derived_figure("mul", [two, two], 4, digits=0)], store).passed == 2


# ---------------------------------------------------------------------------
# DRAFT stamp logic
# ---------------------------------------------------------------------------


def test_draft_stamp_then_approval_signature(tmp_path: Path) -> None:
    db = _db(tmp_path)
    capa_id = _capa(db)
    draft = build_dossier(db, capa_id=capa_id, generated_at=FIXED_TS)
    ctx = template_context(draft.data)
    html = render_html(draft.data)
    assert draft.data.revision == "0.2" and draft.data.status == "draft"
    assert ctx["css"]["header_stamp"] == "DRAFT — REQUIRES HUMAN REVIEW"
    assert ctx["css"]["wm_cover"] and ctx["css"]["wm_default"]
    assert "Approved / Rejected" in html  # blank signature line
    assert "Not effective — not approved" in html

    decide_capa(db, capa_id=capa_id, decision="approved", reviewer="Dana QA", note="Open CAPA.")
    approved = build_dossier(db, capa_id=capa_id, generated_at=FIXED_TS)
    ctx2 = template_context(approved.data)
    html2 = render_html(approved.data)
    assert approved.data.revision == "1.0"
    assert ctx2["css"]["wm_cover"] == "" and ctx2["css"]["wm_default"] == ""
    assert "DRAFT — REQUIRES HUMAN REVIEW" not in html2.split("<body>")[0]
    assert "<b>Dana QA</b>" in html2 and "<b>Approved</b>" in html2
    capa = approved.data.capa
    assert capa is not None and capa.decided_at is not None
    assert capa.decided_at.strftime("%Y-%m-%d %H:%M:%S") in html2
    assert capa.decision_audit_seq is not None and f"seq {capa.decision_audit_seq}" in html2
    # the MDR worksheet keeps its stamp after approval
    assert ctx2["css"]["wm_mdr"] and MDR_STAMP in html2
    assert '@top-right { content: "DRAFT WORKSHEET — NOT FOR SUBMISSION"' in html2


def test_rejected_record(tmp_path: Path) -> None:
    db = _db(tmp_path)
    capa_id = _capa(db)
    decide_capa(db, capa_id=capa_id, decision="rejected", reviewer="Dana QA")
    d = build_dossier(db, capa_id=capa_id).data
    html = render_html(d)
    assert d.header_stamp == "REJECTED BY REVIEWER" and d.watermark == "REJECTED"
    assert "<b>Rejected</b>" in html


def test_signal_only_dossier_and_errors(tmp_path: Path) -> None:
    db = _db(tmp_path)
    top = top_worsening_signal(db)
    assert top is not None and top.product_code == PC
    d = build_dossier(db).data
    assert d.status == "no-capa" and d.revision == "0.1" and d.capa is None
    assert "No CAPA draft exists" in render_html(d)
    with pytest.raises(DossierError):
        build_dossier(db, capa_id="CAPA-DRAFT-NOPE")
    with pytest.raises(DossierError):
        build_dossier(db, product_code="ZZZ")
    with pytest.raises(DossierError):
        build_dossier(Database(tmp_path / "empty.db"))


# ---------------------------------------------------------------------------
# MDR worksheet
# ---------------------------------------------------------------------------


def test_mdr_due_dates_reuse_deadline_check(tmp_path: Path) -> None:
    db = _db(tmp_path)
    d = build_dossier(db, capa_id=_capa(db), awareness_date=date(2026, 10, 27)).data
    assert d.mdr.due_30 is not None and d.mdr.due_5 is not None
    assert d.mdr.due_30["due_date"] == deadline_check(None, "20261027")["due_date"] == "20261126"  # type: ignore[arg-type]
    assert d.mdr.due_5["due_date"] == "20261103"
    html = render_html(d)
    assert "2026-11-26" in html and "2026-11-03" in html
    blank = build_dossier(db, product_code=PC).data
    assert blank.mdr.due_30 is None
    assert "enter the date the manufacturer became aware" in render_html(blank)


# ---------------------------------------------------------------------------
# Narrative (Muse Spark behind the gate)
# ---------------------------------------------------------------------------


def _narrative_json() -> str:
    good = {
        "kind": "count",
        "product_code": PC,
        "value": 6,
        "date_from": "20260825",
        "date_to": "20260831",
    }
    return json.dumps(
        {
            "sentences": [
                {"text": "QIH received 6 reports in the current window.", "claims": [good]},
                {
                    "text": "QIH received 40 reports in the current window.",
                    "claims": [{**good, "value": 40}],
                },
                {
                    "text": 'One report said "Triage alert was not sent after a server update".',
                    "claims": [
                        {
                            "kind": "quote",
                            "quote": "Triage alert was not sent after a server update",
                            "report_id": "9000011",
                        }
                    ],
                },
                {"text": "The failure is covered by 21 CFR 820.100.", "claims": []},
                {"text": "Root cause remains open for the CAPA owner.", "claims": []},
            ]
        }
    )


def test_live_narrative_withheld_sentences_rendered(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, capa_id=_capa(db))
    client = FakeClient([_resp(_narrative_json(), 2000, 300)])
    rec = draft_narrative(client, b.data, b.excerpts)
    sent = json.loads(client.calls[0]["messages"][1]["content"])
    assert sent["figures"]["current_count"]["display"] == "6"
    assert client.calls[0]["temperature"] == 0.0
    section = gate_narrative(rec, b.store, source="live")
    assert (section.passed, section.withheld) == (3, 2)
    assert rec.cost_usd == pytest.approx(2000 * 1.25 / 1e6 + 300 * 4.25 / 1e6)
    b.data.narrative = section
    html = render_html(b.data)
    assert html.count(">WITHHELD<") == 2 and html.count(">VERIFIED<") == 3
    assert "claimed 40, records show 6" in html
    assert "21 CFR 820.100 has no regulation claim" in html
    # the gate's verdicts are re-derivable from the HTML alone
    for text, claims, status in extract_sentences(html):
        typed = [claim_from_dict(c) for c in claims]
        assert verify_sentence(text, typed, b.store).status == status


def test_recorded_narrative_is_regated_and_missing_is_omitted(tmp_path: Path) -> None:
    db = _db(tmp_path)
    capa_id = _capa(db)
    first = build_dossier(db, capa_id=capa_id)
    assert not first.data.narrative.available
    assert "Narrative summary omitted" in render_html(first.data)
    rec = NarrativeRecording(
        doc_id=first.data.doc_id,
        model="muse-spark-1.3",
        skill_version="1.0.0",
        created_at="2026-10-27T12:00:00Z",
        raw_output=_narrative_json(),
        input_tokens=10,
        output_tokens=5,
    )
    rdir = tmp_path / "rec"
    save_recording(rec, rdir / f"{first.data.doc_id}-narrative.json")
    loaded = load_recording(rdir / f"{first.data.doc_id}-narrative.json")
    assert loaded is not None and loaded.raw_output == rec.raw_output
    again = build_dossier(db, capa_id=capa_id, recorded_dir=rdir)
    assert again.data.narrative.source == "recorded" and again.data.narrative.withheld == 2
    assert load_recording(tmp_path / "nope.json") is None


def test_unparseable_narrative_is_gated_as_prose(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, product_code=PC)
    rec = NarrativeRecording(b.data.doc_id, "m", "1.0.0", "t", "QIH had 99 reports.")
    section = gate_narrative(rec, b.store, source="recorded")
    assert section.withheld == 1


def test_contributor_models_refused(tmp_path: Path) -> None:
    db = _db(tmp_path)
    b = build_dossier(db, product_code=PC)
    with pytest.raises(ValueError, match="Contributor"):
        draft_narrative(FakeClient([]), b.data, b.excerpts, model="muse-spark-1.3-contributor")
    with pytest.raises(ReviewError, match="Contributor"):
        review_dossier(
            FakeClient([]),
            doc_id=b.data.doc_id,
            html="<p>x</p>",
            pdf=None,
            evidence=[],
            store=b.store,
            model="muse-wonder-1.0-contributor",
        )


# ---------------------------------------------------------------------------
# Reviewer (Muse Wonder)
# ---------------------------------------------------------------------------


def _findings() -> str:
    return (
        "```json\n"
        + json.dumps(
            {
                "findings": [
                    {
                        "section": "6",
                        "statement": "Alerts failed in every report",
                        "issue_type": "unsupported",
                        "evidence_ids": ["9000012"],
                        "severity": "medium",
                        "explanation": "9000012 describes a crash, not an alert failure.",
                    },
                    {
                        "section": "3",
                        "statement": "Report 1234 shows a death",
                        "issue_type": "contradicted",
                        "evidence_ids": ["1234"],
                        "severity": "high",
                    },
                    {
                        "section": "4.2",
                        "statement": "",
                        "issue_type": "missing_required_element",
                        "evidence_ids": [],
                        "severity": "low",
                    },
                    {"section": "x", "issue_type": "made_up", "severity": "high"},
                    "not a dict",
                ]
            }
        )
        + "\n```"
    )


def test_reviewer_sends_pdf_parses_findings_and_records(tmp_path: Path) -> None:
    db = _db(tmp_path)
    out = produce(db, capa_id=_capa(db), narrative_dir=tmp_path, pdf=False)
    pdf = b"%PDF-1.7 fake"
    client = FakeClient([_resp(_findings(), 100_000, 2_000)])
    r = review_dossier(
        client,
        doc_id=out.doc_id,
        html=out.html,
        pdf=pdf,
        evidence=out.cited_records(),
        store=out.build.store,
    )
    call = client.calls[0]
    assert call["model"] == "muse-wonder-1.0" and call["temperature"] == 0.0
    parts = call["messages"][1]["content"]
    assert parts[1]["type"] == "file"
    assert parts[1]["file"]["file_data"] == "data:application/pdf;base64," + base64.b64encode(
        pdf
    ).decode("ascii")
    payload = json.loads(parts[0]["text"])
    assert {e["report_id"] for e in payload["evidence"]} == set(CURRENT_IDS)
    assert "dossier_text" not in payload
    assert r.mode == "pdf" and len(r.findings) == 3
    assert [f.severity for f in r.findings] == ["high", "medium", "low"]
    assert r.findings[0].evidence_check == "unknown ids: 1234"
    assert r.findings[1].evidence_check == "ids exist"
    assert r.findings[2].evidence_check == "no ids"
    assert r.cost_usd == pytest.approx(100_000 * 4 / 1e6 + 2_000 * 20 / 1e6)

    path = tmp_path / f"{out.doc_id}-review.json"
    save_review(r, path)
    again = load_review(path, out.build.store)
    assert again is not None and len(again.findings) == 3
    plain = load_review(path)
    assert plain is not None and plain.findings[0].evidence_ids == ("1234",)
    assert load_review(tmp_path / "missing.json") is None

    record_review(db, r)
    entries = [a for a in db.list_audit() if a.action == "dossier.review"]
    assert len(entries) == 1 and entries[0].entity_id == out.doc_id
    assert db.verify_audit_chain() == (True, None)
    # the review shows up in the dossier's audit appendix, never in its body
    rebuilt = build_dossier(db, capa_id=out.build.data.capa.capa_id)  # type: ignore[union-attr]
    assert any(a.action == "dossier.review" for a in rebuilt.data.audit)
    assert "Alerts failed in every report" not in render_html(rebuilt.data)


def test_reviewer_falls_back_to_text_and_handles_bad_output(tmp_path: Path) -> None:
    db = _db(tmp_path)
    out = produce(db, product_code=PC, narrative_dir=tmp_path, pdf=False)
    client = FakeClient([RuntimeError("file parts unsupported"), _resp("no json here")])
    r = review_dossier(
        client,
        doc_id=out.doc_id,
        html=out.html,
        pdf=b"%PDF",
        evidence=out.cited_records(),
        store=out.build.store,
    )
    assert r.mode == "text" and r.parse_error and r.findings == []
    text_payload = json.loads(client.calls[1]["messages"][1]["content"][0]["text"])
    assert "2. Signal evaluation" in text_payload["dossier_text"]
    assert "@page" not in text_payload["dossier_text"]
    with pytest.raises(ReviewError):
        parse_findings('{"nope": 1}', out.build.store)
    with pytest.raises(ReviewError):
        parse_findings("{bad json", out.build.store)
    with pytest.raises(ReviewError):
        review_dossier(
            FakeClient([]),
            doc_id="x",
            html="",
            pdf=None,
            evidence=[],
            store=out.build.store,
            mode="video",
        )


def test_html_to_text_drops_styles_and_svg() -> None:
    text = html_to_text(
        "<html><head><style>p{color:red}</style></head><body><h2>Title</h2>"
        "<svg><text>99</text></svg><table><tr><td>a</td><td>b</td></tr></table></body></html>"
    )
    assert "color" not in text and "99" not in text and "Title" in text and "a | b" in text


# ---------------------------------------------------------------------------
# PDF + illustration
# ---------------------------------------------------------------------------


def test_pdf_bytes_and_preview(tmp_path: Path) -> None:
    db = _db(tmp_path)
    out = produce(db, capa_id=_capa(db), narrative_dir=tmp_path)
    assert out.pdf.startswith(b"%PDF")
    png = pdf_page_png(out.pdf, 1, dpi=40)
    if png is not None:  # pdftoppm present
        assert png.startswith(b"\x89PNG")


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode("ascii")


class _FakeHttp:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.body = status, body
        self.sent: dict[str, Any] = {}

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:  # noqa: A002
        self.sent = {"url": url, "json": json, "auth": headers["Authorization"]}
        return SimpleNamespace(status_code=self.status, json=lambda: self.body)


def test_illustration_request_and_cover_only(tmp_path: Path) -> None:
    http = _FakeHttp(200, {"data": [{"b64_json": _PNG}]})
    ill = generate_illustration(api_key="k", classification="Triage Software", http=http)
    assert http.sent["url"].endswith("/v1/images/generations")
    assert http.sent["json"]["model"] == "muse-image-1.0"
    assert http.sent["json"]["n"] == 1 and http.sent["json"]["output_format"] == "png"
    assert "Triage Software" in http.sent["json"]["prompt"]
    assert ill.caption == "AI-generated illustration — not evidence"
    db = _db(tmp_path)
    d = build_dossier(db, product_code=PC, illustration=ill).data
    html = render_html(d)
    cover, rest = html.split('id="sec-signal"', 1)
    assert "AI-generated illustration — not evidence" in cover
    assert "data:image/png" not in rest
    assert "data:image/png" not in render_html(build_dossier(db, product_code=PC).data)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, {}),
        (200, {"data": []}),
        (200, {"data": [{"b64_json": "!!!"}]}),
        (200, {"data": [{"b64_json": base64.b64encode(b"GIF89a").decode()}]}),
    ],
)
def test_illustration_errors(status: int, body: dict[str, Any]) -> None:
    with pytest.raises(IllustrationError):
        generate_illustration(api_key="k", classification="x", http=_FakeHttp(status, body))


def test_illustration_needs_key_and_prompt_has_no_narrative() -> None:
    with pytest.raises(IllustrationError):
        generate_illustration(api_key="", classification="x", http=_FakeHttp(200, {}))
    p = prompt_for('Evil "prompt" <script>')
    assert "<script>" not in p and "No text" in p
    assert isinstance(Illustration(png_b64=_PNG, model="m").caption, str)


# ---------------------------------------------------------------------------
# Dashboard page (keyless, recorded review)
# ---------------------------------------------------------------------------


def _page_script() -> None:
    import os
    from pathlib import Path

    from maudesignal.dashboard.dossier_pages import page_dossier
    from maudesignal.storage.database import Database

    page_dossier(Database(Path(os.environ["DOSSIER_TEST_DB"])))


def test_dossier_page_renders_keyless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    db = _db(tmp_path)
    capa_id = _capa(db)
    out = produce(db, capa_id=capa_id, narrative_dir=tmp_path, pdf=False)
    review = review_dossier(
        FakeClient([_resp(_findings())]),
        doc_id=out.doc_id,
        html=out.html,
        pdf=None,
        evidence=out.cited_records(),
        store=out.build.store,
        mode="text",
    )
    save_review(review, tmp_path / f"{out.doc_id}-review.json")
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("DOSSIER_TEST_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("MAUDESIGNAL_DOSSIER_DIR", str(tmp_path))
    at = AppTest.from_function(_page_script, default_timeout=60).run()
    assert not at.exception
    labels = at.selectbox[0].options
    assert any(capa_id in o for o in labels) and any("Top worsening signal" in o for o in labels)
    assert any(m.value == out.doc_id for m in at.metric)
    assert len(at.dataframe) == 1  # recorded reviewer findings
    assert any("Recorded run" in c.value for c in at.caption)
