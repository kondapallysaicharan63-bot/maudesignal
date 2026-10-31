"""M2c-api fix round (HACKATHON-BUILT): suggestions at distance 1 only, recalls open-world and
structured suggestions, JSON error wording, the voice line and the Vercel bundle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.errors import field_name  # noqa: E402
from maudesignal.connector.guidance import suggest_codes  # noqa: E402
from maudesignal.connector.registry import TOOL_SPECS  # noqa: E402
from tests.unit.test_connector_guidance import (  # noqa: E402
    KNOWN,
    H,
    data,
    make_client,
    rpc,
    small,
)

ROOT = Path(__file__).resolve().parents[2]
__all__ = ["data", "small"]  # fixtures re-exported for pytest


def test_only_distance_one_codes_are_suggested() -> None:
    assert suggest_codes("QAH", ["QIH", "QAQ", "JAK", "LLZ"]) == ["QAQ", "QIH"]  # JAK: 2 away
    assert suggest_codes("AAA", ["ABB", "BBB"]) == []
    assert suggest_codes("XXX", KNOWN) == []


def test_no_distance_one_match_means_no_suggestions(small: ConnectorData, tmp_path: Path) -> None:
    c = make_client(small, tmp_path, empty=True)
    # JAK is one edit from QAK (Q to J), so it is offered
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QAK"}, headers=H)
    assert r.json()["error"]["message"].startswith(
        "QAK isn't a product code we know - did you mean JAK?"
    )
    # QXX is two edits from QIH and farther from the rest: nothing is offered
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QXX"}, headers=H)
    err = r.json()["error"]
    assert err["message"].startswith("QXX isn't a product code we know.")
    assert "did you mean" not in err["message"] and "suggestions" not in err


def test_recalls_is_open_world_everywhere() -> None:
    spec = next(s for s in TOOL_SPECS if s.name == "recalls")
    assert spec.open_world is True and "may check openFDA" in spec.description
    manifest = json.loads((ROOT / "api/mcp-manifest.json").read_text(encoding="utf-8"))
    tool = next(t for t in manifest["tools"] if t["name"] == "recalls")
    assert tool["annotations"]["openWorldHint"] is True
    assert "may check openFDA" in tool["description"]


def test_recalls_returns_structured_suggestions(small: ConnectorData, tmp_path: Path) -> None:
    """QAH is probed with the live classification check faked as absent.

    Not yet confirmed against live openFDA (no network in the build sandbox). Before
    submission run: curl 'https://api.fda.gov/device/classification.json?search=product_code:QAH&limit=1'
    (and the same for ZZZ). Both should return NOT_FOUND; if either exists, change the example.
    """
    c = make_client(small, tmp_path)
    body = c.get("/v1/tools/recalls", params={"product_code": "QAH"}, headers=H).json()
    assert body["suggestions"] == ["QIH"]
    res = rpc(c, "tools/call", {"name": "recalls", "arguments": {"product_code": "QAH"}})["result"]
    assert res["structuredContent"]["suggestions"] == ["QIH"]
    plain = c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=H).json()
    assert plain["suggestions"] == []
    schemas = c.get("/openapi.json").json()["components"]["schemas"]
    assert "suggestions" in schemas["RecallsAnswer"]["properties"]


def test_malformed_json_never_shows_a_position(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.post(
        "/v1/tools/ask", content=b"{not json", headers=H | {"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "The request body is not valid JSON."
    not_json = "The request body is not valid JSON."
    not_obj = "The request body must be a JSON object."
    json_h = H | {"Content-Type": "application/json"}
    for path in ("/v1/tools/ask", "/v1/feedback"):
        cases: list[tuple[dict[str, Any], str]] = [
            ({"content": b"", "headers": json_h}, not_json),
            ({"content": b"hello", "headers": H | {"Content-Type": "text/plain"}}, not_json),
            ({"content": b"hello", "headers": H}, not_json),
            ({"json": [1, 2], "headers": H}, not_obj),
            ({"json": "x", "headers": H}, not_obj),
            ({"content": b"{not json", "headers": json_h}, not_json),
        ]
        for kwargs, expected in cases:
            r = make_client(data, tmp_path).post(path, **kwargs)  # fresh limiter per case
            assert r.status_code == 422, (path, kwargs)
            assert r.json()["error"]["message"] == expected, (path, kwargs)
    r = c.post("/v1/tools/ask", json={"question": 5}, headers=H)
    assert "question" in r.json()["error"]["message"]


def test_field_name_skips_indexes_and_sections() -> None:
    assert field_name(("body", 1)) == "" and field_name(("body",)) == ""
    assert field_name(("body", "question")) == "question" and field_name(None) == ""
    assert field_name(("body", "items", 3)) == "items"


def test_initialize_instructions_keep_the_voice_line(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    ins = rpc(c, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
    line = "Speak the text content; every fact in structuredContent has an openFDA or record link."
    assert line in ins


def test_vercel_bundle_includes_the_sweep_the_known_codes_come_from() -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    include = cfg["functions"]["api/index.py"]["includeFiles"]
    assert "demo/sweep" in include and (ROOT / "demo" / "sweep").is_dir()


def test_documented_unknown_code_examples_match_shipped_data(
    data: ConnectorData, tmp_path: Path
) -> None:
    """Probe of the shipped known-code set: docs/hackathon/MUSE_CONNECTOR.md quotes these."""
    c = make_client(data, tmp_path, empty=True)
    near = c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H)
    err = near.json()["error"]
    assert err["message"].startswith("QAH isn't a product code we know - did you mean ")
    assert err["suggestions"] == ["QAQ", "QAS", "QIH"]
    assert "did you mean QAQ, QAS or QIH?" in err["message"]
    far = c.get("/v1/tools/check_device_type", params={"product_code": "ZZZ"}, headers=H)
    assert far.json()["error"]["message"].startswith("ZZZ isn't a product code we know.")
    assert "suggestions" not in far.json()["error"]
