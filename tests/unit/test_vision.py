"""Tests for the Meta vision features (HACKATHON-BUILT).

510(k) summary reader + accuracy check, SAM 3.1 client/parser, label flow, dashboard
page. The model is a scripted fake OpenAI-compatible client and every HTTP call goes
to ``httpx.MockTransport``: no network, no credits. PDF rasterization tests need
poppler-utils and are skipped without it.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from PIL import Image

from maudesignal.storage.database import Database
from maudesignal.vision import (
    DEMO_K_NUMBERS,
    fda_pdf,
    images,
    label,
    pipeline,
    reader,
    sam,
    spark,
    verify,
)
from maudesignal.vision.openfda510k import Fda510kRecord, OpenFda510k, OpenFdaError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vision"
LABEL_PNG = FIXTURES / "synthetic_label.png"
HAS_POPPLER = all(shutil.which(t) for t in ("pdftoppm", "pdftotext", "pdfinfo"))
needs_poppler = pytest.mark.skipif(not HAS_POPPLER, reason="poppler-utils not installed")

INDICATIONS = (
    "ExampleCAD Lung is intended to assist radiologists in the detection of pulmonary "
    "nodules on chest CT examinations of adults."
)

# Documented SAM output examples (https://dev.meta.ai/docs/sam/reading-segmentation).
SAM_VIDEO_LINE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,"
    "~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>,1<|box;x1=155;y1=228;"
    "x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./"
    "x#:/`S_GnD`=o3?X{emCgO$y@|>"
)
SAM_IMAGE_LINE = (
    "<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,101,~...|>,"
    "1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,81,~...|>,"
    "2<|box;x1=516;y1=117;x2=536;y2=150;w=537;h=561|><|mask;x=0;y=0;data=34,21,~...|>"
)
SAM_CONF_LINE = (
    "<0f>1<|box;x1=444;y1=625;x2=679;y2=850;w=1800;h=1200;c=0.9609375|>"
    "<|mask;x=0;y=0;c=0.9609375;data=226,236,!...|>"
)


# ---------------------------------------------------------------------------
# Fakes and builders
# ---------------------------------------------------------------------------


class FakeClient:
    """Scripted OpenAI-compatible client: each create() returns the next JSON payload."""

    def __init__(self, payloads: list[Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        p = self.payloads.pop(0)
        if isinstance(p, Exception):
            raise p
        content = p if isinstance(p, str) else json.dumps(p)
        return SimpleNamespace(
            model="muse-spark-1.3",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=3000, completion_tokens=400),
        )


def fr(value: Any, page: int = 1, legibility: str = "clear") -> dict[str, Any]:
    return {"value": value, "page": page, "legibility": legibility}


NP = {"value": "", "page": 0, "legibility": "not_present"}


def doc_payload(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "k_number": fr("K990001"),
        "applicant": fr("Example Imaging Labs, Inc."),
        "device_name": fr("ExampleCAD Lung"),
        "product_code": fr("QIH"),
        "regulation_number": fr("21 CFR 892.2050"),
        "decision_date": dict(NP),
        "predicate_devices": fr(["K980000"], 2),
        "indications_for_use": fr(INDICATIONS, 1),
        "intended_use": dict(NP),
        "technology_summary": fr("Software that marks candidate nodules on chest CT.", 2),
    }
    fields.update(over)
    return {"fields": fields}


def label_payload(**over: Any) -> dict[str, Any]:
    def lf(v: str, leg: str = "clear") -> dict[str, str]:
        return {"value": v, "legibility": leg}

    fields: dict[str, Any] = {
        "device_name": lf("DemoScan AI Viewer"),
        "manufacturer": lf("Fictional Devices Test Co."),
        "model_number": lf("DSV-100"),
        "k_number": lf("K990001"),
        "udi": lf("(01)00812345678901(17)270101(10)TESTLOT1"),
        "gtin": lf("00812345678901"),
        "lot": lf("TESTLOT1"),
        "serial": {"value": "", "legibility": "not_present"},
    }
    fields.update(over)
    return {"fields": fields, "overall_legibility": "clear"}


def ofda_row(k: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "k_number": k,
        "applicant": "Example Imaging Labs Inc",
        "device_name": "EXAMPLECAD LUNG",
        "product_code": "QIH",
        "decision_date": "2026-01-02",
        "statement_or_summary": "Summary",
        "openfda": {"regulation_number": "892.2050"},
    }
    row.update(over)
    return row


def openfda_transport(
    rows: list[dict[str, Any]], seen: list[str] | None = None
) -> httpx.MockTransport:
    """Mock openFDA: answers k_number / name searches from ``rows``; 404 when none match."""

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.query.decode()
        if seen is not None:
            seen.append(query)
        search = unquote(query.split("search=", 1)[1].split("&", 1)[0])
        hits = []
        for r in rows:
            if f"k_number:{r['k_number']}" in search:
                hits.append(r)
            elif "device_name:" in search and "k_number:" not in search:
                hits.append(r)
        if not hits:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(200, json={"results": hits})

    return httpx.MockTransport(handler)


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (Helvetica)."""
    ops = ["BT", "/F1 11 Tf", "14 TL", "60 740 Td"]
    for ln in lines:
        esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def image_pdf(pages: int = 2) -> bytes:
    """An image-only ("scanned") PDF made with Pillow — no text layer."""
    imgs = [Image.new("RGB", (400, 520), (255 - 30 * i, 255, 255)) for i in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def page(n: int, size: tuple[int, int] = (800, 1000)) -> fda_pdf.PageImage:
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format="PNG")
    return fda_pdf.PageImage(n, buf.getvalue(), size[0], size[1])


def sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def sam_transport(
    by_prompt: dict[str, str], seen: list[dict[str, Any]] | None = None, status: int = 200
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append({"body": body, "headers": dict(request.headers)})
        if status != 200:
            return httpx.Response(status, json={"error": {"code": "bad", "message": "nope"}})
        prompt = body["input"][0]["content"][0]["text"]
        text = by_prompt.get(prompt, "")
        events: list[dict[str, Any]] = [{"type": "response.created"}]
        if text:
            events.append({"type": "response.output_text.delta", "delta": text})
        events.append({"type": "response.completed", "response": {"usage": {"images": 1}}})
        return httpx.Response(
            200, content=sse(*events), headers={"content-type": "text/event-stream"}
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Skills + strict schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["fda-document-reader", "device-label-reader"])
def test_skill_schemas_are_strict_subset_and_examples_validate(name: str) -> None:
    import jsonschema

    skill = spark.load_skill(name)
    assert skill.version == "1.0.0"
    schema = spark.strict_schema(skill.output_schema)
    assert "$schema" not in schema
    assert spark.check_strict_subset(schema) == []
    for ex in skill.good_examples:
        jsonschema.validate(ex["expected_output"], schema)


def test_check_strict_subset_flags_violations() -> None:
    bad = {
        "type": "object",
        "oneOf": [],
        "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}},
        "required": [],
    }
    problems = spark.check_strict_subset(bad)
    assert any("oneOf" in p for p in problems)
    assert any("additionalProperties" in p for p in problems)
    assert any("required" in p for p in problems)
    assert spark.check_strict_subset({"anyOf": []}) == ["$: anyOf at the root"]


def test_parse_json_object_tolerates_fences_and_rejects_prose() -> None:
    assert spark.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(spark.VisionModelError):
        spark.parse_json_object("no json here")
    with pytest.raises(spark.VisionModelError):
        spark.parse_json_object("{bad json}")


# ---------------------------------------------------------------------------
# fda_pdf
# ---------------------------------------------------------------------------


def test_k_number_helpers() -> None:
    assert fda_pdf.normalize_k_number(" k 191171 ") == "K191171"
    assert fda_pdf.is_k_number("K-191171")
    assert not fda_pdf.is_k_number("P190001")
    with pytest.raises(ValueError):
        fda_pdf.normalize_k_number("K12345")
    assert fda_pdf.find_k_numbers("predicates K191171 and k 210666; again K191171") == [
        "K191171",
        "K210666",
    ]
    assert fda_pdf.pdf_url("K031779").endswith("/cdrh_docs/pdf3/K031779.pdf")
    assert fda_pdf.pdf_url("K261677").endswith("/cdrh_docs/pdf26/K261677.pdf")
    assert fda_pdf.pdf_folder("K981234") == "pdf"


def test_download_cache_miss_then_hit(tmp_path: Path) -> None:
    calls: list[str] = []
    pdf = image_pdf(1)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith(".pdf") and "redir" not in str(request.url):
            return httpx.Response(302, headers={"location": str(request.url) + "?redir=1"})
        return httpx.Response(200, content=pdf)

    t = httpx.MockTransport(handler)
    p = fda_pdf.download_510k_pdf("K210666", tmp_path, transport=t)
    assert p.read_bytes() == pdf and len(calls) == 2  # followed the redirect
    assert calls[0] == "https://www.accessdata.fda.gov/cdrh_docs/pdf21/K210666.pdf"
    fda_pdf.download_510k_pdf("K210666", tmp_path, transport=t)
    assert len(calls) == 2  # cache hit: no request


@pytest.mark.parametrize(
    ("handler", "match"),
    [
        (
            lambda r: (
                httpx.Response(302, headers={"location": "/apology_objects/abuse.html"})
                if "apology" not in str(r.url)
                else httpx.Response(200, text="<html>sorry</html>")
            ),
            "access-denied",
        ),
        (lambda r: httpx.Response(200, text="<html>not a pdf</html>"), "did not return a PDF"),
        (lambda r: httpx.Response(404), "HTTP 404"),
    ],
)
def test_download_errors(
    tmp_path: Path, handler: Callable[[httpx.Request], httpx.Response], match: str
) -> None:
    with pytest.raises(fda_pdf.FdaPdfError, match=match):
        fda_pdf.download_510k_pdf("K190442", tmp_path, transport=httpx.MockTransport(handler))
    assert not (tmp_path / "K190442.pdf").exists()


def test_text_layer_rules() -> None:
    assert not fda_pdf.has_text_layer([])
    assert not fda_pdf.page_has_text("   \n 12 ")
    long = "word " * 40
    assert fda_pdf.has_text_layer([long, ""])
    assert not fda_pdf.has_text_layer([long, "", ""])


@needs_poppler
def test_rasterize_and_text_layer_on_generated_pdfs(tmp_path: Path) -> None:
    scanned = tmp_path / "scan.pdf"
    scanned.write_bytes(image_pdf(3))
    pages = fda_pdf.rasterize(scanned, max_pages=2, dpi=40)
    assert [p.page for p in pages] == [1, 2]
    assert pages[0].png[:4] == b"\x89PNG" and pages[0].width > 0
    assert fda_pdf.page_count(scanned) == 3
    assert not fda_pdf.has_text_layer(fda_pdf.extract_text_pages(scanned, 2))

    typed = tmp_path / "typed.pdf"
    typed.write_bytes(text_pdf(["Indications for Use:", INDICATIONS[:70], INDICATIONS[70:]]))
    text = fda_pdf.extract_text_pages(typed)
    assert len(text) == 1 and fda_pdf.has_text_layer(text)
    assert "ExampleCAD Lung" in text[0]


def test_rasterizer_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(fda_pdf.RasterizerUnavailableError, match="poppler"):
        fda_pdf.page_count(tmp_path / "x.pdf")


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------


def test_read_510k_summary_request_format() -> None:
    client = FakeClient([doc_payload()])
    r = reader.read_510k_summary(client, [page(1), page(2)], label="B", reverse=True, max_side=500)
    call = client.calls[0]
    assert call["temperature"] == 0.0
    rf = call["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "fda_document_reader"
    assert call["messages"][0]["role"] == "system"
    assert "fda-document-reader" in call["messages"][0]["content"]
    parts = call["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "image 1 = page 2; image 2 = page 1"}
    img_url = parts[1]["image_url"]["url"]
    assert parts[1]["type"] == "image_url" and img_url.startswith("data:image/png;base64,")
    sent = Image.open(io.BytesIO(base64.b64decode(img_url.split(",", 1)[1])))
    assert max(sent.size) == 500  # downscaled
    assert r.page_order == [2, 1] and r.label == "B"
    assert r.fields["k_number"].value == "K990001"
    assert r.fields["predicate_devices"].value == ["K980000"]
    assert r.cost_usd == pytest.approx(3000 * 1.25e-6 + 400 * 4.25e-6)


def test_reader_drops_pages_never_sent_and_rejects_bad_output() -> None:
    client = FakeClient([doc_payload(device_name=fr("X", page=9))])
    r = reader.read_510k_summary(client, [page(1)])
    assert r.fields["device_name"].page == 0
    with pytest.raises(spark.VisionModelError, match="schema"):
        reader.read_510k_summary(FakeClient([{"fields": {}}]), [page(1)])
    with pytest.raises(spark.VisionModelError, match="call failed"):
        reader.read_510k_summary(FakeClient([RuntimeError("boom")]), [page(1)])
    with pytest.raises(ValueError, match="Contributor"):
        reader.read_510k_summary(FakeClient([]), [page(1)], model="muse-spark-1.3-contributor")
    with pytest.raises(ValueError, match="no pages"):
        reader.read_510k_summary(FakeClient([]), [])


def test_read_twice_is_two_independent_passes() -> None:
    client = FakeClient([doc_payload(), doc_payload()])
    a, b = reader.read_twice(client, [page(1), page(2), page(3)])
    assert (a.label, b.label) == ("A", "B")
    assert a.page_order == [1, 2, 3] and b.page_order == [3, 2, 1]
    assert (a.max_side, b.max_side) == (1600, 1100)
    assert reader.Reading.from_dict(a.to_dict()).fields == a.fields


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "iso"),
    [
        ("2026-01-02", "2026-01-02"),
        ("20260102", "2026-01-02"),
        ("01/02/2026", "2026-01-02"),
        ("1/2/26", "2026-01-02"),
        ("January 2, 2026", "2026-01-02"),
        ("Sept. 9, 2003", "2003-09-09"),
        ("2 Jan 2026", "2026-01-02"),
        ("not a date", ""),
        ("02/30/2026", ""),
    ],
)
def test_norm_date(raw: str, iso: str) -> None:
    assert verify.norm_date(raw) == iso


def test_normalizers() -> None:
    assert verify.norm_company("Example Imaging Labs, Inc.") == "example imaging labs"
    assert verify.norm_company("EXAMPLE IMAGING LABS INC") == "example imaging labs"
    assert verify.norm_regulation("21 CFR § 892.2050") == "892.2050"
    assert verify.norm_text("Example® detec- tion") == "example detection"
    assert verify.norm_predicates(["K980000", "Predicate Viewer", "k 980000"]) == [
        "K980000",
        "predicate viewer",
    ]


def _reading(label_: str, payload: dict[str, Any]) -> reader.Reading:
    return reader.Reading(
        label=label_,
        fields={n: reader.FieldReading.from_dict(payload["fields"][n]) for n in reader.READ_FIELDS},
        page_order=[1, 2],
        max_side=1600,
        cost_usd=0.01,
    )


def _record() -> Fda510kRecord:
    return Fda510kRecord.from_api(ofda_row("K990001"))


def test_verify_agree_verified_with_openfda_and_text_layer() -> None:
    a = _reading("A", doc_payload())
    b = _reading("B", doc_payload(applicant=fr("EXAMPLE IMAGING LABS INC")))
    s = verify.verify_readings(
        a,
        b,
        k_number="K990001",
        openfda=_record(),
        text_pages=[f"Indications for Use: {INDICATIONS}"],
        predicate_lookup=lambda ks: set(ks),
        page_count=6,
        pdf_url="u",
    )
    st = {f.name: f.status for f in s.fields}
    assert st["k_number"] == st["applicant"] == st["product_code"] == "VERIFIED"
    assert st["regulation_number"] == st["indications_for_use"] == "VERIFIED"
    assert st["predicate_devices"] == "VERIFIED"
    assert st["decision_date"] == st["intended_use"] == "UNVERIFIABLE"  # not on pages
    assert s.field("decision_date").checks[0].outcome == "n/a"  # openFDA shown as reference
    assert st["technology_summary"] == "VERIFIED"
    assert "two independent reads" in s.field("technology_summary").note
    assert s.field("indications_for_use").basis == "two_reads + text_layer"
    assert s.agreement_pct == 100.0
    assert s.product_code == "QIH"
    assert s.cost_usd == pytest.approx(0.02)


def test_verify_conflict_shows_both_reads_and_is_not_resolved() -> None:
    a = _reading("A", doc_payload())
    b = _reading("B", doc_payload(k_number=fr("K990007"), device_name=fr("ExampleCAD Liver")))
    s = verify.verify_readings(a, b, k_number="K990001", openfda=None, text_pages=None)
    k = s.field("k_number")
    assert k.status == "CONFLICT" and k.value is None
    assert (k.read_a.value, k.read_b.value) == ("K990001", "K990007")
    assert verify.HUMAN_CHECK in k.note
    assert s.field("device_name").status == "CONFLICT"
    assert s.agreement_pct == pytest.approx(round(100 * 6 / 8, 1))
    assert s.count("CONFLICT") == 2


def test_verify_reads_agree_but_sources_disagree() -> None:
    a = _reading("A", doc_payload(product_code=fr("LLZ")))
    b = _reading("B", doc_payload(product_code=fr("LLZ")))
    s = verify.verify_readings(
        a,
        b,
        k_number="K990001",
        openfda=_record(),
        text_pages=["a completely different page of text " * 5],
        predicate_lookup=lambda ks: set(),
    )
    pc = s.field("product_code")
    assert pc.status == "CONFLICT" and pc.reads_agree is True and "openFDA" in pc.note
    assert s.field("indications_for_use").status == "CONFLICT"
    assert "text layer" in s.field("indications_for_use").note
    assert s.field("predicate_devices").status == "CONFLICT"


def test_verify_illegible_and_partly_legible() -> None:
    a = _reading(
        "A",
        doc_payload(
            applicant=fr("", 1, "illegible"),
            technology_summary=fr("Software that marks nodules.", 2, "partly_legible"),
        ),
    )
    b = _reading(
        "B", doc_payload(technology_summary=fr("Software that marks nodules.", 2, "clear"))
    )
    s = verify.verify_readings(a, b, k_number="K990001", openfda=None, text_pages=None)
    assert s.field("applicant").status == "UNVERIFIABLE"
    assert s.field("technology_summary").status == "UNVERIFIABLE"  # partly + no source
    both = _reading("B", doc_payload(applicant=fr("", 0, "illegible")))
    s2 = verify.verify_readings(both, both, k_number="K990001", openfda=None, text_pages=None)
    assert s2.field("applicant").note == "illegible on the pages read"


def test_verify_scanned_pdf_text_layer_check_is_na() -> None:
    a = _reading("A", doc_payload())
    s = verify.verify_readings(a, a, k_number="K990001", openfda=None, text_pages=None)
    ind = s.field("indications_for_use")
    assert ind.status == "VERIFIED"
    assert [c.outcome for c in ind.checks if c.source == "text_layer"] == ["n/a"]


def test_summary_roundtrip_and_storage(tmp_path: Path) -> None:
    a = _reading("A", doc_payload())
    s = verify.verify_readings(a, a, k_number="K990001", openfda=_record(), text_pages=None)
    s.thumbnails = [images.thumbnail_data_url(page(1).png)]
    back = verify.VerifiedSummary.from_dict(json.loads(json.dumps(s.to_dict())))
    assert [f.status for f in back.fields] == [f.status for f in s.fields]
    assert back.openfda == s.openfda and back.agreement_pct == s.agreement_pct

    path = pipeline.save_summary(s, tmp_path)
    assert path.name == "510k-K990001.json"
    (tmp_path / "510k-BROKEN.json").write_text("{not json")
    assert [x.k_number for x in pipeline.load_recorded_summaries(tmp_path)] == ["K990001"]

    db = Database(tmp_path / "v.db")
    rid = verify.store_summary(db, s)
    rec = db.list_external_sources(source_type=verify.SOURCE_TYPE)[0]
    assert rid == rec.record_id == "510k_summary_reading:K990001"
    assert rec.product_code == "QIH" and rec.title == "ExampleCAD Lung"
    assert "thumbnails" not in json.loads(rec.raw_json)
    verify.store_summary(db, s)  # idempotent
    assert db.count_external_sources(source_type=verify.SOURCE_TYPE) == 1


# ---------------------------------------------------------------------------
# openFDA client
# ---------------------------------------------------------------------------


def test_openfda_client_queries() -> None:
    seen: list[str] = []
    rows = [ofda_row("K990001"), ofda_row("K990005", product_code="LLZ")]
    with OpenFda510k(api_key="k", transport=openfda_transport(rows, seen)) as c:
        rec = c.get("k990001")
        assert rec is not None and rec.regulation_number == "892.2050"
        assert c.get("K999999") is None
        assert set(c.get_many(["K990001", "K990005", ""])) == {"K990001", "K990005"}
        assert c.get_many([]) == {}
        found = c.search(device_name="DemoScan AI Viewer!", applicant="Fictional Co.")
        assert len(found) == 2
        assert c.search() == []
    assert "k_number:K990001+k_number:K990005" in seen[2]  # literal '+', not %2B
    assert 'device_name:"DemoScan+AI+Viewer"+AND+applicant:"Fictional+Co."' in unquote(seen[3])
    assert "api_key=k" in seen[0]


def test_openfda_client_errors() -> None:
    t = httpx.MockTransport(lambda r: httpx.Response(500))
    with pytest.raises(OpenFdaError, match="500"), OpenFda510k(transport=t) as c:
        c.get("K990001")
    t2 = httpx.MockTransport(lambda r: httpx.Response(200, text="nope"))
    with pytest.raises(OpenFdaError, match="non-JSON"), OpenFda510k(transport=t2) as c:
        c.get("K990001")


# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------


def test_sam_parser_on_documented_examples() -> None:
    recs = sam.parse_segmentation(SAM_VIDEO_LINE)
    assert [(r.frame, r.object_id) for r in recs] == [(0, 0), (0, 1)]
    assert recs[0].box.as_tuple() == (211, 228, 270, 254) and recs[0].box.w == 320
    assert recs[0].mask is not None and (recs[0].mask.height, recs[0].mask.width) == (27, 60)
    assert recs[0].mask.encoding == "lossless" and recs[0].mask.payload.endswith("x(")

    img = sam.parse_segmentation(SAM_IMAGE_LINE)
    assert [r.object_id for r in img] == [0, 1, 2]
    assert img[2].box.as_tuple() == (516, 117, 536, 150)

    conf = sam.parse_segmentation(SAM_CONF_LINE)[0]
    assert conf.box.confidence == pytest.approx(0.9609375)
    assert conf.mask is not None and conf.mask.encoding == "one_bit"
    assert conf.mask.confidence == pytest.approx(0.9609375)


def test_sam_parser_frames_sparse_ids_empty_and_errors() -> None:
    video = SAM_VIDEO_LINE + "\n" + SAM_VIDEO_LINE.replace("<0f>0<", "<2f>4<")
    recs = sam.parse_segmentation(video)
    assert [(r.frame, r.object_id) for r in recs] == [(0, 0), (0, 1), (2, 4), (2, 1)]
    # A payload that contains "<5f>" must not be mistaken for a frame marker.
    tricky = SAM_CONF_LINE.replace("!...", "!ab<5f>cd")
    assert [r.frame for r in sam.parse_segmentation(tricky)] == [0]
    assert sam.parse_segmentation("") == []
    with pytest.raises(sam.SamError, match="frame marker"):
        sam.parse_segmentation("garbage")
    with pytest.raises(sam.SamError, match="no parseable record"):
        sam.parse_segmentation("<0f>nonsense")
    with pytest.raises(sam.SamError, match="malformed box"):
        sam.parse_segmentation("<0f>0<|box;x1=1;y1=2|><|mask;x=0;y=0;data=1,1,~a|>")
    best = sam.best_record(sam.parse_segmentation(SAM_IMAGE_LINE))
    assert best is not None and best.object_id == 0  # largest box when no confidence
    assert sam.best_record([]) is None


def test_sam_box_scaling() -> None:
    b = sam.SamBox(100, 50, 199, 149, 400, 300)
    assert b.area == 100 * 100
    s = b.scaled_to(800, 600)
    assert s.as_tuple() == (200, 100, 398, 298) and (s.w, s.h) == (800, 600)


def test_read_sse_text_and_stream_errors() -> None:
    lines = [
        "event: response.output_text.delta",
        'data: {"type":"response.output_text.delta","delta":"<0f>0<|box"}',
        'data: {"type":"response.output_text.delta","delta":";x1=1|>"}',
        "data: not json",
        'data: {"type":"response.completed","response":{"usage":{"images":1}}}',
        'data: {"type":"response.output_text.delta","delta":"after completion"}',
    ]
    text, usage = sam.read_sse_text(lines)
    assert "after" not in text and usage == {"images": 1}
    with pytest.raises(sam.SamError, match="response.failed"):
        sam.read_sse_text(
            ['data: {"type":"response.failed","response":{"message":"model overloaded"}}']
        )


def test_sam_client_request_and_errors() -> None:
    seen: list[dict[str, Any]] = []
    enc = images.encode(Image.new("RGB", (64, 48)), fmt="PNG")
    with sam.SamClient(
        "secret-key", transport=sam_transport({"label": SAM_CONF_LINE}, seen)
    ) as client:
        res = client.segment(enc, "label")
        assert "secret-key" not in repr(client)
    body, headers = seen[0]["body"], seen[0]["headers"]
    assert body["model"] == "sam-3.1" and body["stream"] is True
    assert body["metadata"] == {"include_confidence": "true"}  # string, as documented
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "label"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert headers["authorization"] == "Bearer secret-key"
    assert headers["accept"] == "text/event-stream"
    assert len(res.records) == 1 and res.cost_usd == pytest.approx(0.0025)
    assert res.usage == {"images": 1}

    with sam.SamClient("k", transport=sam_transport({}, status=400)) as client:
        with pytest.raises(sam.SamError, match="HTTP 400") as ei:
            client.segment(enc, "label")
        assert ei.value.status_code == 400 and not ei.value.retryable
    with pytest.raises(sam.SamError, match="empty"):
        sam.SamClient("")


# ---------------------------------------------------------------------------
# Label flow
# ---------------------------------------------------------------------------

LABEL_BOX = "<0f>0<|box;x1=150;y1=120;x2=749;y2=479;w=900;h=600;c=0.93|><|mask;x=0;y=0;c=0.93;data=2,2,!ab|>,1<|box;x1=10;y1=10;x2=19;y2=19;w=900;h=600;c=0.99|><|mask;x=0;y=0;data=1,1,!a|>"  # noqa: E501


def test_gtin_and_udi() -> None:
    assert label.gtin_check_digit_ok("00812345678901")
    assert not label.gtin_check_digit_ok("00812345678906")
    assert not label.gtin_check_digit_ok("123")
    assert label.parse_udi("(01)00812345678901(17)270101(10)TESTLOT1") == {
        "01": "00812345678901",
        "17": "270101",
        "10": "TESTLOT1",
    }


def test_label_flow_end_to_end_with_k_number(tmp_path: Path) -> None:
    data = LABEL_PNG.read_bytes()
    client = FakeClient([label_payload()])
    seen: list[dict[str, Any]] = []
    with (
        sam.SamClient("k", transport=sam_transport({"label": LABEL_BOX}, seen)) as s,
        OpenFda510k(
            transport=openfda_transport(
                [
                    ofda_row(
                        "K990001",
                        device_name="DemoScan AI Viewer",
                        applicant="Fictional Devices Test Co",
                        product_code="LLZ",
                    )
                ]
            )
        ) as ofda,
    ):
        res = label.read_device_label(
            data, client=client, sam=s, openfda=ofda, catalog_k_numbers={"K990001"}
        )
    assert res.sam_prompt == "label" and len(seen) == 1
    # The speck (1% rule) is dropped; the label box is chosen and cropped with a margin.
    assert [b.as_tuple() for b in res.sam_boxes] == [(150, 120, 749, 479)]
    assert res.crop_box == (114, 98, 786, 502)
    sent = client.calls[0]["messages"][1]["content"][0]["image_url"]["url"]
    crop = Image.open(io.BytesIO(base64.b64decode(sent.split(",", 1)[1])))
    assert crop.size == (672, 404)
    assert res.k_number == "K990001" and res.k_status == "verified"
    assert res.product_code == "LLZ" and res.match_basis == "k_number"
    assert res.gtin == "00812345678901" and res.gtin_valid is True
    outcomes = {c.source: c.outcome for c in res.checks}
    assert outcomes["catalog"] == "pass" and outcomes["label_vs_openfda"] == "pass"
    assert res.cost_usd == pytest.approx(res.spark_cost_usd + 0.0025)

    stored = res.to_dict()
    assert "lot" not in stored["fields"] and "serial" not in stored["fields"]
    assert "TESTLOT1" not in json.dumps({k: v for k, v in stored.items() if k != "fields"})
    assert "lot" in res.to_dict(include_session_fields=True)["fields"]
    back = label.LabelResult.from_dict(json.loads(json.dumps(stored)))
    assert back.product_code == "LLZ" and back.chosen_box == res.chosen_box
    assert back.crop_box == res.crop_box and "lot" not in back.fields


def test_label_flow_name_search_ambiguous_never_autopicks() -> None:
    client = FakeClient([label_payload(k_number={"value": "", "legibility": "not_present"})])
    rows = [ofda_row("K990005", product_code="LLZ"), ofda_row("K990006", product_code="QIH")]
    with (
        sam.SamClient("k", transport=sam_transport({"text": LABEL_BOX})) as s,
        OpenFda510k(transport=openfda_transport(rows)) as ofda,
    ):
        res = label.read_device_label(LABEL_PNG.read_bytes(), client=client, sam=s, openfda=ofda)
    assert res.sam_prompts_tried == ["label", "text"] and res.sam_prompt == "text"
    assert res.k_status == "not_printed" and res.k_number is None
    assert res.match_basis == "ambiguous" and res.needs_human_pick
    assert res.product_code is None and len(res.candidates) == 2


def test_label_flow_single_name_match_and_unknown_k() -> None:
    client = FakeClient([label_payload(k_number={"value": "K990009", "legibility": "clear"})])
    rows = [ofda_row("K990005", product_code="MYN")]
    with OpenFda510k(transport=openfda_transport(rows)) as ofda:
        res = label.read_device_label(LABEL_PNG.read_bytes(), client=client, sam=None, openfda=ofda)
    assert "SAM not configured" in res.sam_note and res.crop_box is None
    assert res.k_status == "not_in_openfda"
    assert res.match_basis == "single_name_match" and res.product_code == "MYN"


def test_label_flow_partly_legible_name_never_sets_a_product_code() -> None:
    """2026-10-28 label run: "Tube Assembly", partly legible, matched another maker's tube."""
    client = FakeClient(
        [
            label_payload(
                device_name={"value": "Tube Assembly", "legibility": "partly_legible"},
                k_number={"value": "", "legibility": "not_present"},
            )
        ]
    )
    rows = [ofda_row("K990005", product_code="ITY"), ofda_row("K990006", product_code="ITY")]
    with OpenFda510k(transport=openfda_transport(rows)) as ofda:
        res = label.read_device_label(LABEL_PNG.read_bytes(), client=client, sam=None, openfda=ofda)
    assert res.product_code is None and res.match_basis == "ambiguous" and res.needs_human_pick
    assert len(res.candidates) == 2
    assert "not clearly legible" in res.checks[-1].detail


def test_label_flow_sam_finds_nothing_or_fails_reads_full_photo() -> None:
    client = FakeClient([label_payload(gtin={"value": "", "legibility": "not_present"})] * 2)
    with sam.SamClient("k", transport=sam_transport({})) as s:
        res = label.read_device_label(LABEL_PNG.read_bytes(), client=client, sam=s, openfda=None)
    assert res.sam_prompts_tried == list(label.SAM_PROMPTS) and res.sam_prompt is None
    assert "found no label / text / barcode" in res.sam_note
    assert res.cost_usd == pytest.approx(res.spark_cost_usd + 3 * 0.0025)
    assert res.gtin == "00812345678901"  # taken from the UDI's (01)
    assert res.match_basis == "none" and res.k_status == "not_printed"
    with sam.SamClient("k", transport=sam_transport({}, status=404)) as s:
        res2 = label.read_device_label(LABEL_PNG.read_bytes(), client=client, sam=s, openfda=None)
    assert res2.sam_note.startswith("SAM failed")


def test_verify_label_bad_format_illegible_and_inconsistent() -> None:
    def res_with(**over: Any) -> label.LabelResult:
        fields = {
            k: label.LabelField(v["value"], v["legibility"])
            for k, v in label_payload(**over)["fields"].items()
        }
        return label.LabelResult(100, 100, fields, "clear")

    r = label.verify_label(res_with(k_number={"value": "K12", "legibility": "clear"}), openfda=None)
    assert r.k_status == "bad_format"
    r = label.verify_label(
        res_with(k_number={"value": "", "legibility": "illegible"}), openfda=None
    )
    assert r.k_status == "illegible"
    other = ofda_row("K990001", device_name="Totally Other", applicant="Other Corp")
    with OpenFda510k(transport=openfda_transport([other])) as ofda:
        r = label.verify_label(res_with(), openfda=ofda)
    assert {c.source: c.outcome for c in r.checks}["label_vs_openfda"] == "fail"
    down = httpx.MockTransport(lambda req: httpx.Response(503))
    with OpenFda510k(transport=down) as ofda:
        r = label.verify_label(res_with(), openfda=ofda)
    assert any("openFDA unavailable" in c.detail for c in r.checks)


def test_images_helpers() -> None:
    with pytest.raises(images.ImageInputError):
        images.open_image(b"")
    with pytest.raises(images.ImageInputError):
        images.open_image(b"not an image")
    with pytest.raises(images.ImageInputError):
        images.to_data_url(b"x", "image/tiff")
    img = Image.new("RGB", (100, 50))
    assert images.fit(img, 200).size == (100, 50)
    crop, box = images.crop_with_margin(img, (60, 10, 50, 20), 0.0)
    assert box == (0, 0, 100, 50)  # inverted box falls back to the full image
    drawn = images.draw_boxes(img, [(1, 1, 10, 10), (20, 20, 30, 30)], highlight=1)
    assert drawn.getpixel((20, 25)) == (24, 119, 242)
    jpg = images.prepare(images.encode(img).data, max_side=40, fmt="JPEG")
    assert jpg.mime == "image/jpeg" and (jpg.width, jpg.height) == (40, 20)


# ---------------------------------------------------------------------------
# Pipeline (end to end on a generated PDF)
# ---------------------------------------------------------------------------


@needs_poppler
def test_read_and_verify_510k_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "K990001.pdf").write_bytes(
        text_pdf(
            ["510(k) Summary K990001", "Indications for Use:", INDICATIONS[:70], INDICATIONS[70:]]
        )
    )
    client = FakeClient([doc_payload(), doc_payload()])
    with OpenFda510k(transport=openfda_transport([_record_row()])) as ofda:
        s = pipeline.read_and_verify_510k(
            "K990001", client=client, openfda=ofda, cache_dir=tmp_path, max_pages=4
        )
    assert s.has_text_layer and s.page_count == 1 and s.pages_read == 1
    assert s.field("indications_for_use").status == "VERIFIED"
    assert s.field("predicate_devices").status == "CONFLICT"  # K980000 not in mock openFDA
    assert len(s.thumbnails) == 1 and s.thumbnails[0].startswith("data:image/jpeg")
    assert len(client.calls) == 2


def _record_row() -> dict[str, Any]:
    return ofda_row("K990001")


def test_demo_k_numbers_and_recorded_labels(tmp_path: Path) -> None:
    assert {pc for _, pc in DEMO_K_NUMBERS} == {"LLZ", "QIH", "MYN", "POK"}
    assert all(fda_pdf.is_k_number(k) for k, _ in DEMO_K_NUMBERS)
    (tmp_path / "label-a.json").write_text(json.dumps({"k_number": "K990001"}))
    (tmp_path / "label-b.json").write_text("{oops")
    runs = pipeline.load_recorded_labels(tmp_path)
    assert len(runs) == 1 and runs[0]["_file"] == "label-a.json"


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------


def test_vision_page_helpers(tmp_path: Path) -> None:
    from maudesignal.dashboard import vision_pages as vp

    a = _reading("A", doc_payload())
    b = _reading("B", doc_payload(k_number=fr("K990007")))
    s = verify.verify_readings(a, b, k_number="K990001", openfda=None, text_pages=None)
    out = vp.field_rows_html(s.fields)
    assert "CONFLICT" in out and "K990007" in out and "Read A" in out
    assert "VERIFIED" in vp.pill("VERIFIED")
    db = Database(tmp_path / "p.db")
    verify.store_summary(db, s)
    assert set(vp.stored_summaries(db)) == {"K990001"}
    assert vp.signal_for(db, "QIH") is None  # empty DB: no signals


def test_vision_page_renders_keyless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    a = _reading("A", doc_payload())
    s = verify.verify_readings(a, a, k_number="K990001", openfda=_record(), text_pages=None)
    s.thumbnails = [images.thumbnail_data_url(page(1).png)]
    vision_dir = tmp_path / "vision"
    pipeline.save_summary(s, vision_dir)
    run = label.LabelResult.from_dict(
        {
            "fields": label_payload()["fields"],
            "image_file": "synthetic_label.png",
            "product_code": "QIH",
            "match_basis": "k_number",
            "k_number": "K990001",
            "k_status": "verified",
            "sam": {"prompt_used": "label", "boxes": [], "chosen_box": None},
        }
    ).to_dict()
    run["image_file"] = "synthetic_label.png"
    (vision_dir / "label-synthetic.json").write_text(json.dumps(run))
    (vision_dir / "labels").mkdir()
    shutil.copy(LABEL_PNG, vision_dir / "labels" / "synthetic_label.png")
    db_path = tmp_path / "app.db"
    Database(db_path)
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MAUDESIGNAL_VISION_DIR", str(vision_dir))
    script = (
        "from pathlib import Path\n"
        "from maudesignal.storage.database import Database\n"
        "from maudesignal.dashboard.vision_pages import page_vision\n"
        f"page_vision(Database(Path({str(db_path)!r})))\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception
    assert any("Live reading needs a Meta Model API key" in i.value for i in at.info)
    assert any(m.label == "Two-read agreement" for m in at.metric)
    assert len(at.dataframe) == 1  # recorded label run: fields table (no lot / serial)
    assert any("K990001" in m.value for m in at.markdown)
    assert any("No stored MAUDE reports for QIH" in c.value for c in at.caption)


def test_load_recorded_labels_skips_label_match_files(tmp_path: Path) -> None:
    (tmp_path / "label-a.json").write_text(json.dumps({"fields": {}}))
    (tmp_path / "label-match-a.json").write_text(json.dumps({"status": "needs_person_to_confirm"}))
    got = pipeline.load_recorded_labels(tmp_path)
    assert [g["_file"] for g in got] == ["label-a.json"]
