"""Verification questions (Skill ``verification-questions``) with a fake client, no network."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest

from maudesignal.company import load_company
from maudesignal.company.constants import PROJECT_ROOT, contains_forbidden
from maudesignal.company.questions import (
    CONFIDENCE_CAP,
    LABEL,
    draft_questions,
    load_questions,
    load_skill,
    patterns_input,
    question_problem,
    validate_questions,
)

SCRIPT = PROJECT_ROOT / "scripts" / "record_company_questions.py"
SKILL = PROJECT_ROOT / "skills" / "verification-questions"
GOOD_QS = [
    "Does our device have a comparable function that could stop responding?",
    "Does a test record already cover this behavior?",
]


def _reply(items: list[dict[str, Any]]) -> str:
    return json.dumps({"patterns": items})


def _item(pid: str, qs: list[str] | None = None, conf: float = 0.8) -> dict[str, Any]:
    return {"pattern_id": pid, "questions": qs or GOOD_QS, "confidence_score": conf}


class FakeClient:
    """OpenAI-compatible fake; answers with the given builder and records calls."""

    def __init__(self, build: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._build = build
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        ids = [p["pattern_id"] for p in json.loads(kw["messages"][1]["content"])["patterns"]]
        msg = SimpleNamespace(content=self._build(ids))
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("record_company_questions", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── skill folder ─────────────────────────────────────────────────────────────


def test_skill_folder_complete_and_loads() -> None:
    sk = load_skill()
    assert sk.version == "1.0.0"
    assert (SKILL / "schemas" / "output.schema.json").is_file()
    assert len(sk.good_examples) >= 2 and len(sk.bad_examples) >= 3
    jsonschema.Draft202012Validator.check_schema(sk.output_schema)
    assert "Suggested by Muse Spark" in sk.system_prompt


def test_skill_text_has_no_forbidden_words() -> None:
    for path in [SKILL / "SKILL.md", *(SKILL / "examples").glob("*.jsonl")]:
        text = path.read_text(encoding="utf-8")
        # bad.jsonl quotes the banned wording on purpose, as examples of what not to write
        if path.name == "bad.jsonl":
            continue
        if path.name == "SKILL.md":  # rule 7 names the banned words so the model avoids them
            text = "\n".join(ln for ln in text.splitlines() if not ln.startswith(("7.", '   "FDA')))
        assert not contains_forbidden(text), path.name


def test_good_examples_validate_and_pass_checks() -> None:
    sk = load_skill()
    for ex in sk.good_examples:
        out = ex["expected_output"]
        jsonschema.validate(out, sk.output_schema)
        ids = {p["pattern_id"] for p in ex["input"]["patterns"]}
        res = validate_questions(json.dumps(out), ids)
        assert res.error is None and not res.dropped
        assert len(res.accepted) == len(out["patterns"])


def test_skill_listed_in_claude_md() -> None:
    text = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`verification-questions`" in text


# ── schema ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        {"patterns": [_item("P-1", GOOD_QS[:1])]},  # one question
        {"patterns": [_item("P-1", GOOD_QS + GOOD_QS + GOOD_QS[:1])]},  # four
        {"patterns": [_item("P-1", conf=1.0)]},  # confidence 1.0
        {"patterns": [_item("P-1", ["Not a question at all.", "Another statement here."])]},
        {"patterns": [{"pattern_id": "P-1", "questions": GOOD_QS}]},  # no confidence
        {"patterns": [], "extra": 1},
        {"nope": []},
    ],
)
def test_schema_rejects(bad: dict[str, Any]) -> None:
    res = validate_questions(json.dumps(bad), {"P-1"})
    assert res.error and not res.accepted


def test_not_json_is_an_error_not_a_crash() -> None:
    assert validate_questions("here are some questions", {"P-1"}).error
    assert validate_questions("", {"P-1"}).error


# ── deterministic checks ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "Is the device safe to keep using?",
        "Is our process compliant with the rules?",
        "Has our validated workflow been checked again?",
        "Did the 7 reports involve our device?",
        "Should we mark this as Already covered?",
        "Is this Not applicable to our device?",
        "Is a CAPA open for this problem?",
        "Do we need to file a report with FDA about this?",
        "Which status fits this problem best?",
        "Does anyone recommend a fix for this?",
    ],
)
def test_question_problem_refuses(q: str) -> None:
    assert question_problem(q) is not None


def test_question_problem_accepts_plain_questions() -> None:
    for q in GOOD_QS:
        assert question_problem(q) is None


def test_validate_drops_bad_pattern_keeps_good() -> None:
    reply = _reply(
        [
            _item("P-1"),
            _item("P-2", ["Is the device safe?", "Does a test cover this?"]),
            _item("P-3"),  # unknown id
            _item("P-1"),  # duplicate
            _item("P-4", [GOOD_QS[0], GOOD_QS[0]]),  # repeated
        ]
    )
    res = validate_questions(reply, {"P-1", "P-2", "P-4"})
    assert [a.pattern_id for a in res.accepted] == ["P-1"]
    assert {pid for pid, _ in res.dropped} == {"P-2", "P-3", "P-4", "P-1"}


def test_accepted_questions_hold_no_status_or_forbidden_words() -> None:
    res = validate_questions(_reply([_item("P-1")]), {"P-1"})
    for a in res.accepted:
        assert a.confidence_score <= CONFIDENCE_CAP and a.confidence_score < 1.0
        for q in a.questions:
            assert q.endswith("?") and not contains_forbidden(q)


# ── model call and recording ─────────────────────────────────────────────────


def test_draft_questions_uses_temperature_zero_and_standard_tier() -> None:
    view = load_company()
    patterns = [p for d in view.devices for p in d.code_patterns.patterns if p.gate_count == "pass"]
    if not patterns:
        pytest.skip("no stored patterns in this checkout")
    client = FakeClient(lambda ids: _reply([_item(i) for i in ids]))
    draft = draft_questions(client, patterns[:2])
    assert client.calls[0]["temperature"] == 0.0
    assert draft.skill_version == "1.0.0" and draft.cost_usd > 0
    sent = json.loads(client.calls[0]["messages"][1]["content"])
    assert set(sent) == {"patterns"}
    assert set(sent["patterns"][0]) == {"pattern_id", "label", "report_count", "quotes"}
    with pytest.raises(ValueError):
        draft_questions(client, patterns[:1], model="muse-spark-contributor")


def test_patterns_input_sends_only_gated_facts() -> None:
    view = load_company()
    for d in view.devices:
        for p in d.code_patterns.patterns:
            item = patterns_input([p])["patterns"][0]
            assert item["report_count"] == p.count
            assert len(item["quotes"]) <= 2


def test_record_writes_questions_json(tmp_path: Path) -> None:
    folder = tmp_path / "company"
    shutil.copytree(PROJECT_ROOT / "demo" / "company", folder)
    (folder / "questions.json").unlink(missing_ok=True)
    mod = _script()
    client = FakeClient(lambda ids: _reply([_item(i) for i in ids]))
    doc = mod.record(client, folder)
    path = folder / "questions.json"
    assert path.is_file()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["label"] == LABEL == "Suggested by Muse Spark — your team decides"
    assert stored["banner"].startswith("Simulated company — sample data.")
    assert stored == json.loads(json.dumps(doc))
    assert not contains_forbidden(path.read_text(encoding="utf-8"))
    loaded = load_questions(folder)
    for code, body in stored["codes"].items():
        assert set(loaded.get(code, {})) == set(body["patterns"])
    # at most one model call per distinct product code
    assert len(client.calls) <= len({d.product_code for d in load_company(folder).devices})


def test_record_withholds_bad_reply(tmp_path: Path) -> None:
    folder = tmp_path / "company"
    shutil.copytree(PROJECT_ROOT / "demo" / "company", folder)
    (folder / "questions.json").unlink(missing_ok=True)
    mod = _script()
    client = FakeClient(lambda ids: "Sure! Here are some thoughts.")
    doc = mod.record(client, folder)
    for body in doc["codes"].values():
        assert body["patterns"] == {} and body["error"]
    assert load_questions(folder) == {}


def test_load_questions_rechecks_stored_text(tmp_path: Path) -> None:
    doc = {
        "schema": "company-questions/1",
        "codes": {
            "AAA": {
                "patterns": {
                    "AAA-1": {"questions": GOOD_QS},
                    "AAA-2": {"questions": ["Is the device safe?", GOOD_QS[0]]},
                }
            }
        },
    }
    (tmp_path / "questions.json").write_text(json.dumps(doc), encoding="utf-8")
    assert load_questions(tmp_path) == {"AAA": {"AAA-1": GOOD_QS}}


def test_main_without_key_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    assert _script().main([]) == 2


# ── workflow and request file ────────────────────────────────────────────────


def test_workflow_triggers_only_on_request_file() -> None:
    text = (PROJECT_ROOT / ".github" / "workflows" / "company-questions.yml").read_text(
        encoding="utf-8"
    )
    assert "branches: [track-a-company]" in text
    assert "demo/company/QUESTIONS_REQUEST" in text
    assert "workflow_dispatch" in text
    assert "secrets.META_MODEL_API_KEY" in text
    assert "schedule:" not in text and "pull_request" not in text
    assert (PROJECT_ROOT / "demo" / "company" / "QUESTIONS_REQUEST").read_text().strip() == "0"
