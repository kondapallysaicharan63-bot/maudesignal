"""Schema contract (HACKATHON-BUILT): every tool's real answer must satisfy the schema we advertise.

For each tool the answer is produced with fakes (no network, no model key) over MCP and over
REST. The MCP ``structuredContent`` is validated against the ``outputSchema`` that
``tools/list`` advertises (and the committed manifest); the REST body is validated against the
OpenAPI response schema of that route.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
jsonschema = pytest.importorskip("jsonschema")

from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.manifest import MANIFEST_PATH  # noqa: E402
from maudesignal.connector.openapi import OPENAPI_PATH, build_spec  # noqa: E402
from maudesignal.connector.registry import TOOL_SPECS  # noqa: E402
from tests.unit.test_connector_api import TOOL_CALLS, H, call, make_client  # noqa: E402
from tests.unit.test_connector_guidance import KNOWN  # noqa: E402
from tests.unit.test_connector_guidance import H as GUIDANCE_H  # noqa: E402
from tests.unit.test_connector_guidance import make_client as guidance_client  # noqa: E402
from tests.unit.test_connector_guidance import rpc as guidance_rpc  # noqa: E402
from tests.unit.test_connector_mcp import rpc  # noqa: E402

__all__ = ["data"]


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("schema_contract"))


def _mcp_arguments(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec["json"] if "json" in spec else spec
    return {k: str(v) for k, v in raw.items()}


def _response_schema(openapi: dict[str, Any], tool: str) -> dict[str, Any]:
    op = openapi["paths"][f"/v1/tools/{tool}"]
    op = op["get"] if "get" in op else op["post"]
    schema: dict[str, Any] = op["responses"]["200"]["content"]["application/json"]["schema"]
    return {**schema, "components": openapi["components"]}


def test_every_registered_tool_is_exercised() -> None:
    assert {t for _, t, _ in TOOL_CALLS} == {s.name for s in TOOL_SPECS}


@pytest.mark.parametrize(("method", "tool", "spec"), TOOL_CALLS)
def test_mcp_structured_content_matches_advertised_output_schema(
    data: ConnectorData, tmp_path: Path, method: str, tool: str, spec: dict[str, Any]
) -> None:
    c = make_client(data, tmp_path)
    listed = {t["name"]: t for t in rpc(c, "tools/list").json()["result"]["tools"]}
    manifest = {
        t["name"]: t for t in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["tools"]
    }
    assert listed[tool]["outputSchema"] == manifest[tool]["outputSchema"]
    res = rpc(c, "tools/call", {"name": tool, "arguments": _mcp_arguments(spec)}).json()["result"]
    assert res["isError"] is False, res
    jsonschema.validate(res["structuredContent"], listed[tool]["outputSchema"])


@pytest.mark.parametrize(("method", "tool", "spec"), TOOL_CALLS)
def test_rest_body_matches_openapi_response_schema(
    data: ConnectorData, tmp_path: Path, method: str, tool: str, spec: dict[str, Any]
) -> None:
    r = call(make_client(data, tmp_path), method, tool, spec, headers=H)
    assert r.status_code == 200, r.text
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(r.json(), _response_schema(committed, tool))
    assert _response_schema(build_spec(), tool) == _response_schema(committed, tool)


def test_recalls_advertises_suggestions_and_others_do_not() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for t in manifest["tools"]:
        has = "suggestions" in t["outputSchema"].get("properties", {})
        assert has is (t["name"] == "recalls"), t["name"]


def test_recalls_with_filled_suggestions_matches_both_schemas(tmp_path: Path) -> None:
    """QAH is absent on the faked code check, so ``suggestions`` is a non-empty list."""
    d = ConnectorData(work_dir=tmp_path / "small")
    d._known_codes = frozenset(KNOWN)
    c = guidance_client(d, tmp_path)  # code_exists answers False
    manifest = {
        t["name"]: t for t in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["tools"]
    }
    res = guidance_rpc(c, "tools/call", {"name": "recalls", "arguments": {"product_code": "QAH"}})
    assert res["result"]["isError"] is False
    structured = res["result"]["structuredContent"]
    assert structured["suggestions"] == ["QIH"]
    jsonschema.validate(structured, manifest["recalls"]["outputSchema"])
    r = c.get("/v1/tools/recalls", params={"product_code": "QAH"}, headers=GUIDANCE_H)
    assert r.status_code == 200 and r.json()["suggestions"] == ["QIH"]
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(r.json(), _response_schema(committed, "recalls"))
