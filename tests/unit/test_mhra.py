"""MHRA (UK) alert adapter: parsing, storage, gate quotes, tool (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from maudesignal.copilot.tools import ToolContext, call_tool
from maudesignal.gate import QuoteClaim, verify
from maudesignal.gate.loader import store_from_database
from maudesignal.sources.mhra import (
    SEARCH_URL,
    SOURCE_MHRA,
    fetch_mhra_alerts,
    parse_results,
    search_params,
)
from maudesignal.storage.database import Database

PAYLOAD: dict[str, Any] = {
    "results": [
        {
            "title": "Imaging software: risk of mismatched patient studies",
            "description": "Software may display images from a previous study.",
            "link": "/drug-device-alerts/imaging-software-risk-of-mismatched-studies",
            "public_timestamp": "2026-08-20T10:00:00+01:00",
            "issued_date": "2026-08-20",
            "alert_type": [{"value": "medical-device-alert", "label": "Medical device alert"}],
            "medical_specialism": [{"value": "radiology", "label": "Radiology"}],
        },
        {
            "title": "Drug alert: tablets recalled",
            "description": "A batch of tablets.",
            "link": "/drug-device-alerts/drug-alert-tablets",
            "public_timestamp": "2026-08-19T10:00:00+01:00",
            "alert_type": "drugs",
        },
        {"title": "no link", "description": ""},
    ]
}


def test_parse_keeps_device_alerts_only() -> None:
    (a,) = parse_results(PAYLOAD)
    assert a.alert_id == "imaging-software-risk-of-mismatched-studies"
    assert a.url == "https://www.gov.uk" + PAYLOAD["results"][0]["link"]
    assert a.issued == "2026-08-20" and a.alert_type == "medical-device-alert"
    assert a.specialisms == ("radiology",)
    assert len(parse_results(PAYLOAD, devices_only=False)) == 2


def test_search_params_are_bounded() -> None:
    p = search_params("software", count=999)
    assert p["filter_format"] == "medical_safety_alert" and p["count"] == 50
    assert "description" in p["fields"]


def test_fetch_stores_and_the_gate_verifies_quotes(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=PAYLOAD)

    db = Database(tmp_path / "m.db")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        alerts = fetch_mhra_alerts(db, query="imaging software", product_code="LLZ", client=client)
    assert seen["url"].startswith(SEARCH_URL) and len(alerts) == 1
    (row,) = db.list_external_sources(source_type=SOURCE_MHRA)
    assert row.product_code == "LLZ" and row.authors == "MHRA (UK)"
    # Re-fetching the same alert does not duplicate it.
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_mhra_alerts(db, query="imaging software", product_code="LLZ", client=client)
    assert len(db.list_external_sources(source_type=SOURCE_MHRA)) == 1

    store = store_from_database(db)
    aid = alerts[0].alert_id
    good = QuoteClaim("may display images from a previous study", source_id=f"mhra:{aid}")
    bad = QuoteClaim("may delete images", source_id=f"mhra:{aid}")
    unknown = QuoteClaim("may display images from a previous study", source_id="mhra:nope")
    v_good, v_bad, v_unknown = verify([good, bad, unknown], store)
    assert v_good.status == "pass"
    assert v_bad.status == "block" and v_unknown.status == "block"

    ctx = ToolContext(db=db, store=store)
    out = call_tool(ctx, "mhra_alerts", json.dumps({"product_code": "LLZ"}))
    assert out["regulator"] == "MHRA (UK)" and out["alerts"][0]["alert_id"] == aid
    assert "not FDA data" in out["note"]
    assert call_tool(ctx, "mhra_alerts", json.dumps({"query": "tablets"}))["alert_count"] == 0
