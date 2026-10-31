"""Connector UX tests (HACKATHON-BUILT): tool descriptions, MCP prompts, server instructions and
helpful input errors. No network, no model key. Contract tests: every message is asserted.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AskRuntime  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.guidance import edit_distance, suggest_codes  # noqa: E402
from maudesignal.connector.prompts import PROMPT_SPECS  # noqa: E402
from maudesignal.connector.registry import GUIDANCE, TOOL_SPECS  # noqa: E402
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.monitor.live_check import LiveCheck  # noqa: E402
from tests.unit.test_connector import KEY, fake_check  # noqa: E402
from tests.unit.test_connector_lookup import ROW_802, FakeSearcher  # noqa: E402

H = {"X-API-Key": KEY}
KNOWN = ["QIH", "LLZ", "MYN", "POK", "JAK"]
EXAMPLES = {
    "what_changed_this_week": "What changed for LLZ this week?",
    "check_device_type": "Is anything unusual with QIH right now?",
    "lookup_device": "I photographed a label: Welch Allyn 802 LTR - which FDA records match?",
    "recalls": "Show recalls for LLZ.",
    "get_report": "Show me report 50426770.",
    "ask": "What changed this week for LLZ?",
}


def no_reports(code: str) -> LiveCheck:
    """A live check where openFDA has never seen the code."""
    return replace(
        fake_check(code),
        window=None,
        as_of=None,
        prior_report_count=0,
        current_count=0,
        baseline_count=0,
    )


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("guidance"))


@pytest.fixture
def small(tmp_path: Path) -> ConnectorData:
    """Stored data whose known-code set is the five codes above."""
    d = ConnectorData(work_dir=tmp_path / "small")
    d._known_codes = frozenset(KNOWN)
    return d


def make_client(
    data: ConnectorData,
    tmp_path: Path,
    *,
    empty: bool = False,
    exists: bool | None = False,
) -> TestClient:
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(1000),
        data=data,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led"),
        live_checker=no_reports if empty else fake_check,
        lookup_searcher=FakeSearcher(k510=[ROW_802]),
        code_exists=lambda _code: exists,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def rpc(c: TestClient, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    out: dict[str, Any] = c.post("/mcp", json=body, headers=H).json()
    return out


def tool_error(c: TestClient, name: str, arguments: dict[str, Any]) -> str:
    res = rpc(c, "tools/call", {"name": name, "arguments": arguments})["result"]
    assert res["isError"] is True
    return str(res["content"][0]["text"])


# --- edit distance and suggestions ----------------------------------------------------------


def test_edit_distance_and_suggestions() -> None:
    assert edit_distance("QAH", "QIH") == 1 and edit_distance("LLZ", "LLZ") == 0
    assert suggest_codes("QAH", KNOWN) == ["QIH"]
    assert suggest_codes("qah", KNOWN) == ["QIH"]  # case does not matter
    assert suggest_codes("XXX", KNOWN) == []  # nothing near: no guess
    assert suggest_codes("QIH", KNOWN) == []  # a code that exists is never corrected
    many = suggest_codes("AAA", ["AAB", "AAC", "AAD", "AAE", "ABA"])
    assert many == ["AAB", "AAC", "AAD"]  # closest tier, at most three, alphabetical


# --- unknown product code (REST and MCP) -----------------------------------------------------


def test_unknown_code_rest_and_mcp_say_did_you_mean(small: ConnectorData, tmp_path: Path) -> None:
    c = make_client(small, tmp_path, empty=True)
    for path in ("check_device_type", "what_changed_this_week"):
        r = c.get(f"/v1/tools/{path}", params={"product_code": "QAH"}, headers=H)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "unknown_product_code"
        assert err["message"].startswith("QAH isn't a product code we know - did you mean QIH?")
        assert err["suggestions"] == ["QIH"]
        assert KEY not in r.text
    text = tool_error(c, "check_device_type", {"product_code": "QAH"})
    assert text.startswith("QAH isn't a product code we know - did you mean QIH?")
    # keyless public route uses the same check
    pub = c.get("/v1/public/check_device_type", params={"product_code": "QAH"})
    assert pub.status_code == 422 and pub.json()["error"]["suggestions"] == ["QIH"]


def test_unknown_code_without_close_match_has_no_suggestions(
    small: ConnectorData, tmp_path: Path
) -> None:
    c = make_client(small, tmp_path, empty=True)
    r = c.get("/v1/tools/check_device_type", params={"product_code": "XXX"}, headers=H)
    err = r.json()["error"]
    assert r.status_code == 422 and "suggestions" not in err  # same shape, key only when useful
    assert err["message"].startswith("XXX isn't a product code we know.")
    assert set(err) == {"code", "message"}


def test_real_known_codes_give_at_most_three_suggestions(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make_client(data, tmp_path, empty=True)
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H)
    suggestions = r.json()["error"]["suggestions"]
    assert 1 <= len(suggestions) <= 3 and "QIH" in suggestions
    assert all(edit_distance("QAH", x) == 1 for x in suggestions)
    assert set(suggestions) <= data.known_product_codes()


def test_existing_code_is_passed_through_unchanged(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path, empty=True)
    # QIH is stored: even if openFDA reports nothing for it, it is answered, not corrected
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QIH"}, headers=H)
    assert r.status_code == 200 and "QIH" in r.json()["speakable"]
    # a known code in lower case is only upper-cased
    r = c.get("/v1/tools/check_device_type", params={"product_code": "llz"}, headers=H)
    assert r.status_code == 200 and "LLZ" in r.json()["speakable"]
    assert "LLZ" in data.known_product_codes() and "QIH" in data.known_product_codes()


def test_real_fda_code_with_zero_reports_is_answered_not_corrected(
    small: ConnectorData, tmp_path: Path
) -> None:
    # QAH is in openFDA's classification list but has no reports: 200, no suggestions.
    c = make_client(small, tmp_path, empty=True, exists=True)
    for path in ("check_device_type", "what_changed_this_week"):
        r = c.get(f"/v1/tools/{path}", params={"product_code": "QAH"}, headers=H)
        assert r.status_code == 200
        body = r.json()
        assert "openFDA returned no reports for QAH" in body["speakable"]
        assert "did you mean" not in r.text and "suggestions" not in r.text
        assert any("openFDA" in f["link_label"] for f in body["facts"])
    text = rpc(
        c, "tools/call", {"name": "check_device_type", "arguments": {"product_code": "QAH"}}
    )["result"]["content"][0]["text"]
    assert "no reports for QAH" in text
    pub = c.get("/v1/public/check_device_type", params={"product_code": "QAH"})
    assert pub.status_code == 200


def test_unreachable_classification_list_does_not_call_a_code_unknown(
    small: ConnectorData, tmp_path: Path
) -> None:
    c = make_client(small, tmp_path, empty=True, exists=None)
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H)
    assert r.status_code == 200 and "unknown" not in r.text
    assert "did you mean" not in r.text


def test_default_code_check_asks_the_classification_endpoint(
    small: ConnectorData, tmp_path: Path
) -> None:
    searcher = FakeSearcher(k510=[ROW_802])
    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(1000),
        data=small,
        ask_runtime=AskRuntime(live_enabled=lambda: False, ledger_dir=tmp_path / "led2"),
        live_checker=no_reports,
        lookup_searcher=searcher,
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H)
    assert r.status_code == 200  # the fake lists every code
    assert ("classification", "product_code:QAH") in searcher.calls


def test_recalls_offers_suggestions_without_failing(small: ConnectorData, tmp_path: Path) -> None:
    c = make_client(small, tmp_path)
    r = c.get("/v1/tools/recalls", params={"product_code": "QAH"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert "QAH isn't a product code we know - did you mean QIH?" in body["speakable"]
    assert "QIH" in body["provenance"]["note"] and "not applied" in body["provenance"]["note"]
    known = c.get("/v1/tools/recalls", params={"product_code": "QIH"}, headers=H).json()
    assert "did you mean" not in known["speakable"]


@pytest.mark.parametrize("exists", [True, None])
def test_recalls_never_corrects_a_real_or_unchecked_code(
    small: ConnectorData, tmp_path: Path, exists: bool | None
) -> None:
    # FRN is a real FDA code outside the stored set: FDA lists it (True) or the list could not
    # be read (None). Either way recalls gives no suggestion and no "isn't a product code".
    c = make_client(small, tmp_path, exists=exists)
    r = c.get("/v1/tools/recalls", params={"product_code": "FRN"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert "did you mean" not in body["speakable"]
    assert "isn't a product code" not in body["speakable"]
    assert "not applied" not in (body["provenance"]["note"] or "")
    res = rpc(c, "tools/call", {"name": "recalls", "arguments": {"product_code": "FRN"}})
    assert "isn't a product code" not in json.dumps(res)


def test_every_udi_and_gtin_in_descriptions_passes_the_check_digit() -> None:
    import re

    from maudesignal.connector.lookup import gtin_check_digit_ok

    root = Path(__file__).resolve().parents[2]
    texts = [
        (root / "src/maudesignal/connector/registry.py").read_text(encoding="utf-8"),
        (root / "api/openapi.json").read_text(encoding="utf-8"),
        (root / "api/mcp-manifest.json").read_text(encoding="utf-8"),
    ]
    found = [m for t in texts for m in re.findall(r"\(01\)(\d{8,14})", t)]
    assert found
    assert all(gtin_check_digit_ok(g) for g in found), found


def test_known_set_without_the_sweep_file_still_suggests(tmp_path: Path) -> None:
    # The deployed bundle may lack demo/sweep: suggestions then come from the other sources.
    d = ConnectorData(work_dir=tmp_path / "nosweep")
    d._sweep = tmp_path / "missing.json"
    codes = d.known_product_codes()
    assert codes and suggest_codes("QAH", codes) in (["QIH"], [])


def test_live_code_with_reports_is_not_rejected(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)  # openFDA has reports for any code here
    r = c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H)
    assert r.status_code == 200


# --- malformed input, one message each -------------------------------------------------------

BAD_CODE = "A product code is three letters, for example LLZ or QIH."
BAD_K = "K-numbers look like K123456 (the letter K and six digits)."
BAD_ID = "A report id is letters, digits and dashes, up to 24 characters."


@pytest.mark.parametrize("tool", ["check_device_type", "recalls", "what_changed_this_week"])
@pytest.mark.parametrize("value", ["QA", "LLZZ", "12A"])
def test_bad_product_code_message(
    data: ConnectorData, tmp_path: Path, tool: str, value: str
) -> None:
    c = make_client(data, tmp_path)
    r = c.get(f"/v1/tools/{tool}", params={"product_code": value}, headers=H)
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "invalid_input", "message": BAD_CODE}
    assert tool_error(c, tool, {"product_code": value}) == BAD_CODE


def test_missing_required_argument_is_named(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/recalls", headers=H)
    assert r.status_code == 422
    assert r.json()["error"]["message"].startswith("product_code is required.")
    assert tool_error(c, "recalls", {}).startswith("product_code is required.")
    assert tool_error(c, "get_report", {}).startswith("report_id is required.")
    assert tool_error(c, "ask", {}).startswith("question is required.")
    r = c.get("/v1/tools/get_report", headers=H)
    assert r.json()["error"]["message"].startswith("report_id is required.")
    r = c.post("/v1/tools/ask", json={}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["message"].startswith("question is required.")


def test_question_limits_are_given(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    long_q = "x" * 501
    r = c.post("/v1/tools/ask", json={"question": long_q}, headers=H)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "question is too long: the limit is 500 characters."
    assert tool_error(c, "ask", {"question": long_q}) == (
        "question is too long: the limit is 500 characters."
    )
    short = "ab"
    r = c.post("/v1/tools/ask", json={"question": short}, headers=H)
    assert r.json()["error"]["message"] == "question is too short: it needs at least 3 characters."
    assert tool_error(c, "ask", {"question": short}) == (
        "question is too short: it needs at least 3 characters."
    )


def test_malformed_k_number(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/lookup_device", params={"k_number": "K12"}, headers=H)
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "invalid_input", "message": BAD_K}
    assert tool_error(c, "lookup_device", {"k_number": "K12"}) == BAD_K


def test_malformed_report_id(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/get_report", params={"report_id": "a b!"}, headers=H)
    assert r.json()["error"] == {"code": "invalid_input", "message": BAD_ID}
    assert tool_error(c, "get_report", {"report_id": "a b!"}) == BAD_ID


def test_bad_gtin_check_digit_is_named(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/lookup_device", params={"gtin": "12345678901234"}, headers=H)
    assert r.status_code == 422
    assert "GS1 check digit" in r.json()["error"]["message"]
    text = tool_error(c, "lookup_device", {"udi": "(01)12345678901234(17)261231"})
    assert "GS1 check digit" in text


def test_lookup_with_nothing_names_the_inputs(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/lookup_device", headers=H)
    assert r.status_code == 422
    assert "Give at least one of device_name, model, manufacturer" in r.json()["error"]["message"]


def test_too_long_input_and_unknown_argument(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    r = c.get("/v1/tools/lookup_device", params={"gtin": "1" * 21}, headers=H)
    assert r.json()["error"]["message"] == "gtin is too long: the limit is 20 characters."
    text = tool_error(c, "recalls", {"product_code": "LLZ", "x": "1"})
    assert text == "recalls does not take that input. It takes: product_code."
    assert tool_error(c, "recalls", {"product_code": 5}) == "product_code must be text."
    assert tool_error(c, "recalls", ["x"]).startswith("The arguments of recalls must be")


def test_error_messages_hold_no_key_and_no_forbidden_term(
    data: ConnectorData, tmp_path: Path
) -> None:
    c = make_client(data, tmp_path, empty=True)
    seen = [
        c.get("/v1/tools/check_device_type", params={"product_code": "QAH"}, headers=H).text,
        c.get("/v1/tools/check_device_type", params={"product_code": "Q"}, headers=H).text,
        tool_error(c, "lookup_device", {"k_number": "K1"}),
        tool_error(c, "ask", {"question": "x" * 600}),
    ]
    for text in seen:
        assert KEY not in text and forbidden_in(text) == []


# --- descriptions ----------------------------------------------------------------------------


def test_every_tool_description_says_when_to_use_it_with_example_questions() -> None:
    assert set(EXAMPLES) == {s.name for s in TOOL_SPECS}
    for s in TOOL_SPECS:
        assert s.description.startswith("Use this"), s.name
        assert "Example questions:" in s.description, s.name
        assert EXAMPLES[s.name] in s.description, s.name
        assert "Read-only" in s.description
        assert forbidden_in(s.description) == []


def test_input_schemas_are_unchanged() -> None:
    by = {s.name: s.input_schema() for s in TOOL_SPECS}
    assert by["recalls"]["properties"]["product_code"]["pattern"] == "^[A-Za-z]{3}$"
    assert by["ask"]["properties"]["question"]["minLength"] == 3
    assert by["ask"]["properties"]["question"]["maxLength"] == 500
    assert by["lookup_device"]["properties"]["k_number"]["pattern"].startswith("^\\s*[Kk]")
    assert by["get_report"]["required"] == ["report_id"]
    assert by["what_changed_this_week"]["required"] == []
    assert all(s["additionalProperties"] is False for s in by.values())


# --- instructions ----------------------------------------------------------------------------


def test_server_instructions_in_initialize_and_openapi(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    ins = rpc(c, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
    assert ins == GUIDANCE
    for phrase in (
        "cite the FDA links",
        "not medical advice",
        "nothing is filed with FDA",
        "Confirm the product code with the person before guessing one",
        "lookup_device",
        "say 'recorded'",
        "Never present withheld sentences as fact",
        "A person confirms every device match",
        "Web results are not FDA records.",
    ):
        assert phrase.lower() in ins.lower(), phrase
    assert forbidden_in(ins) == []
    info = c.get("/openapi.json").json()["info"]["description"]
    assert GUIDANCE in info


# --- prompts ---------------------------------------------------------------------------------


def test_prompts_list_and_connect(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    listed = rpc(c, "prompts/list")["result"]["prompts"]
    assert [p["name"] for p in listed] == [
        "morning_brief",
        "check_this_device",
        "does_this_apply_to_us",
    ]
    by = {p["name"]: p for p in listed}
    assert [a["name"] for a in by["morning_brief"]["arguments"]] == ["product_codes"]
    assert [a["name"] for a in by["check_this_device"]["arguments"]] == ["text"]
    does = by["does_this_apply_to_us"]["arguments"]
    assert [(a["name"], a["required"]) for a in does] == [
        ("product_code", True),
        ("our_device_description", False),
    ]
    connect = c.get("/v1/connect").json()
    assert [p["name"] for p in connect["prompts"]] == [s.name for s in PROMPT_SPECS]
    assert connect["instructions"] == GUIDANCE


def get_prompt(c: TestClient, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    return rpc(c, "prompts/get", {"name": name, "arguments": arguments})


def prompt_text(reply: dict[str, Any]) -> str:
    msgs = reply["result"]["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user" and msgs[0]["content"]["type"] == "text"
    return str(msgs[0]["content"]["text"])


def test_morning_brief(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    text = prompt_text(get_prompt(c, "morning_brief", {"product_codes": "llz, QIH ,llz"}))
    assert "LLZ, QIH" in text and "what_changed_this_week" in text
    assert "once for each code" in text and "FDA link" in text


def test_check_this_device(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    text = prompt_text(
        get_prompt(c, "check_this_device", {"text": "Welch Allyn 802 LTR\n K123456"})
    )
    assert "Welch Allyn 802 LTR K123456" in text  # one line, value kept
    assert "lookup_device" in text and "up to 3 possible matches" in text
    assert "ask me to confirm one record, or none" in text


def test_does_this_apply_to_us(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    plain = prompt_text(get_prompt(c, "does_this_apply_to_us", {"product_code": "llz"}))
    with_desc = prompt_text(
        get_prompt(
            c,
            "does_this_apply_to_us",
            {"product_code": "LLZ", "our_device_description": "chest X-ray AI triage"},
        )
    )
    for text in (plain, with_desc):
        for tool in ("check_device_type", "what_changed_this_week", "recalls"):
            assert tool in text
        assert "questions" in text and "Never state a verdict" in text
    assert "chest X-ray AI triage" in with_desc and "chest X-ray" not in plain


def test_every_prompt_carries_the_rules(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)
    calls = {
        "morning_brief": {"product_codes": "LLZ"},
        "check_this_device": {"text": "K123456"},
        "does_this_apply_to_us": {"product_code": "LLZ"},
    }
    for name, args in calls.items():
        text = prompt_text(get_prompt(c, name, args))
        assert "Cite the FDA links" in text
        assert "not medical advice" in text
        assert "say 'recorded'" in text
        assert forbidden_in(text) == []


def test_prompt_errors_name_the_problem(data: ConnectorData, tmp_path: Path) -> None:
    c = make_client(data, tmp_path)

    def err(name: str, args: dict[str, Any] | None) -> str:
        reply = get_prompt(c, name, args)
        assert reply["error"]["code"] == -32602
        return str(reply["error"]["message"])

    assert err("morning_brief", {}) == "product_codes is required for this prompt."
    assert err("morning_brief", {"product_codes": " , "}) == (
        "product_codes is required for this prompt."
    )
    assert err("morning_brief", {"product_codes": "LLZ,Q1"}) == f"product_codes: {BAD_CODE}"
    assert err("morning_brief", {"product_codes": ",".join(["LLZ"] * 11)}) == (
        "product_codes: give at most 10 codes."
    )
    assert err("check_this_device", None) == "text is required for this prompt."
    assert err("check_this_device", {"text": "x" * 501}) == (
        "text is too long: the limit is 500 characters."
    )
    assert err("does_this_apply_to_us", {}) == "product_code is required for this prompt."
    assert err("does_this_apply_to_us", {"product_code": "L"}) == f"product_code: {BAD_CODE}"
    assert err("nope", {}).startswith("Unknown prompt. Available: morning_brief")
    assert err("morning_brief", {"product_codes": "LLZ", "z": "1"}).startswith(
        "morning_brief does not take that argument."
    )
    bad = rpc(c, "prompts/get", {})
    assert bad["error"]["code"] == -32602


def test_manifest_stays_in_step() -> None:
    from maudesignal.connector.manifest import MANIFEST_PATH, build_manifest, render

    assert MANIFEST_PATH.read_text(encoding="utf-8") == render(build_manifest())
    assert json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["description"] == GUIDANCE
