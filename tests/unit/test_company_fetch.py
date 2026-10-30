"""scripts/fetch_company_evidence.py with fakes (no network), and the fetched-file path.

The reports below are synthetic test data written for these tests; they never leave the
temp folder and are not part of the demo files.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from maudesignal.company import export_company, load_company
from maudesignal.company.constants import PROJECT_ROOT, company_dir
from maudesignal.company.evidence import load_fetched_evidence, missing

SCRIPT = PROJECT_ROOT / "scripts" / "fetch_company_evidence.py"


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("fetch_company_evidence", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _event(rid: str, text: str, problems: list[str], received: str = "20261020") -> dict[str, Any]:
    return {
        "mdr_report_key": rid,
        "date_received": received,
        "event_type": "Malfunction",
        "report_source_code": "Manufacturer report",
        "product_problems": problems,
        "device": [{"brand_name": "TEST BRAND", "manufacturer_d_name": "TEST MAKER"}],
        "mdr_text": [{"text_type_code": "Description of Event or Problem", "text": text}],
        "patient": [{"patient_age": "55"}],  # never stored
    }


EVENTS = [
    _event("9000001", "The software crashed twice during a study review on the workstation.", []),
    _event("9000002", "The application froze and the user had to restart the workstation now.", []),
    _event("9000003", "Unable to load the prior images for the patient study on the server.", []),
    _event("9000004", "A different matter was described here without any listed keyword.", []),
]


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def iter_reports(
        self, product_code: str, start_date: Any = None, end_date: Any = None, limit: Any = None
    ) -> Any:
        self.calls.append(("iter", product_code, start_date, end_date, limit))
        yield from EVENTS

    def total(self, product_code: str, start_date: Any = None, end_date: Any = None) -> int:
        return 250


def fake_http(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if "classification" in url:
        return {"results": [{"device_name": "Test Type Name", "device_class": "2"}]}
    return {
        "meta": {"results": {"total": 2}},
        "results": [
            {
                "product_res_number": "Z-0001-2026",
                "res_event_number": "1",
                "recalling_firm": "TEST FIRM",
                "product_description": "Test product",
                "reason_for_recall": "The software may freeze during image review by the user.",
                "recall_status": "Open, Classified",
                "event_date_initiated": "2026-10-01",
                "cfres_id": "123",
            },
            {"no_number": True},
        ],
    }


def test_fetch_code_document_shape_and_query_urls() -> None:
    mod = _script()
    client = FakeClient()
    doc = mod.fetch_code(
        "ZZZ",
        client=client,
        http_get=fake_http,
        today=date(2026, 10, 30),
        now=datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
    )
    assert client.calls == [("iter", "ZZZ", "20260904", "20261030", 100)]  # 8 weeks, limit 100
    assert doc["window"] == {"date_from": "20260904", "date_to": "20261030", "weeks": 8}
    assert doc["classification"]["device_name"] == "Test Type Name"
    rep = doc["reports"]
    assert rep["matched_total"] == 250 and rep["stored"] == 4
    assert "device.device_report_product_code:ZZZ" in rep["query_url"]
    assert "date_received:[20260904+TO+20261030]" in rep["query_url"]
    assert "api_key" not in json.dumps(doc)
    assert any("250 reports matched" in n for n in doc["notes"])
    assert doc["recalls"]["stored"] == 1 and doc["recalls"]["matched_total"] == 2
    assert doc["recalls"]["records"][0]["date_initiated"] == "20261001"
    first = rep["records"][0]
    assert set(first) == {
        "report_id", "event_type", "date_received", "report_source", "brand_name",
        "manufacturer", "product_problems", "text",
    }  # fmt: skip
    assert "patient_age" not in json.dumps(doc)


def test_fetched_file_flows_into_patterns_and_export(tmp_path: Path) -> None:
    mod = _script()
    for name in ("company.json", "audit.json"):
        shutil.copy(company_dir() / name, tmp_path / name)
    (tmp_path / "evidence").mkdir()
    doc = mod.fetch_code(
        "IYN",
        client=FakeClient(),
        http_get=fake_http,
        today=date(2026, 10, 30),
        now=datetime(2026, 10, 30, tzinfo=UTC),
    )
    (tmp_path / "evidence" / "IYN.json").write_text(json.dumps(doc))
    ev = load_fetched_evidence("IYN", tmp_path / "evidence")
    assert ev.available and len(ev.reports) == 4 and ev.classification_name == "Test Type Name"

    view = load_company(tmp_path)
    dev = next(d for d in view.devices if d.product_code == "IYN")
    assert dev.device_type_name == "Test Type Name"
    labels = {p.label: p.count for p in dev.patterns}
    assert labels["Software freezes, crashes or does not start"] == 2
    # one report alone is not a pattern
    assert "Images or data fail to load, transfer or send" not in labels
    for p in dev.patterns:
        assert p.gate_count == "pass" and p.count >= 2
        for q in p.quotes:
            stored_text = {r["report_id"]: r["text"] for r in doc["reports"]["records"]}
            assert q.text in stored_text[q.report_id]
    out = export_company(view)
    exported = next(d for d in out["devices"] if d["product_code"] == "IYN")
    assert exported["evidence"]["available"] and exported["evidence"]["origin"] == "fetched"
    assert exported["evidence"]["recalls"]["stored"] == 1
    # the other fetched-code devices still say "not fetched yet"
    other = next(d for d in out["devices"] if d["product_code"] == "OTE")
    assert other["evidence"]["available"] is False and other["patterns"] == []


def test_missing_file_means_not_fetched_yet(tmp_path: Path) -> None:
    ev = load_fetched_evidence("IYN", tmp_path)
    assert not ev.available and ev.notes == ("evidence not fetched yet",)
    assert missing("IYN").reports == () and missing("IYN").recalls == ()


def test_codes_to_fetch_skips_codes_the_demo_db_holds() -> None:
    mod = _script()
    codes = mod.codes_to_fetch(company_dir())
    assert codes == ["DQK", "DSI", "IYN", "LNH", "MUD", "MWI", "OTE"]


def test_main_writes_a_file_per_code_and_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _script()

    class Ctx(FakeClient):
        def __init__(self, **_: Any) -> None:
            super().__init__()

        def __enter__(self) -> Ctx:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(mod, "OpenFDAClient", Ctx)
    monkeypatch.setattr(mod, "make_http_get", lambda key: fake_http)
    monkeypatch.setenv("OPENFDA_API_KEY", "")
    assert mod.main(["--codes", "IYN", "OTE", "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["IYN.json", "OTE.json"]

    def boom(*_: Any, **__: Any) -> None:
        raise mod.OpenFDAAPIError("down")

    monkeypatch.setattr(mod, "fetch_code", boom)
    assert mod.main(["--codes", "DSI", "--out", str(tmp_path)]) == 1
    assert not (tmp_path / "DSI.json").exists()
