"""End-to-end compliance-officer journey, offline: ingest -> extract -> coverage -> PSUR.

openFDA is replaced by a mock HTTP transport serving real stored MAUDE records,
and the LLM by a provider that answers each Skill with that Skill's own
good-example output, so every step runs the production code and the real Skill
schemas without a network call or a key.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from maudesignal.config import Config
from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.llm_providers.base import LLMMessage, LLMProvider, LLMResponse
from maudesignal.extraction.pipeline import extract_record
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.ingestion.pipeline import ingest_product_code
from maudesignal.report.generator import PSURGenerator
from maudesignal.storage.database import Database

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("maude-narrative-extractor", "severity-triage", "ai-failure-mode-classifier")


def _good_output(skill: str) -> dict[str, Any]:
    line = (ROOT / "skills" / skill / "examples" / "good.jsonl").read_text().splitlines()[0]
    out: dict[str, Any] = json.loads(line)["expected_output"]
    return out


def _schema(skill: str) -> dict[str, Any]:
    path = ROOT / "skills" / skill / "schemas" / "output.schema.json"
    data: dict[str, Any] = json.loads(path.read_text())
    return data


class _SkillProvider(LLMProvider):
    """Answers with the good example of whichever Skill's prompt it receives."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-model"

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        assert temperature == 0.0  # CLAUDE.md §6.6
        prompt = system_prompt.lower()
        # A Skill's own name comes first in its prompt; later ones are cross-references.
        skill = min(SKILLS, key=lambda n: prompt.find(n) if n in prompt else len(prompt))
        self.calls.append(skill)
        m = re.search(r'"maude_report_id":\s*"([^"]+)"', messages[-1].content)
        # Provenance fields a real model fills in from the prompt and its input; each
        # Skill's schema decides which of them (and of the example's keys) it allows.
        filled = {
            "maude_report_id": m.group(1) if m else "unknown",
            "skill_name": skill,
            "skill_version": "1.0.0",
            "model_used": "mock-model",
            "confidence_score": 0.85,
            "extraction_ts": "2026-10-28T00:00:00Z",
            "triage_ts": "2026-10-28T00:00:00Z",
            "classification_ts": "2026-10-28T00:00:00Z",
            "narrative_excerpt": "excerpt",
            "evidence_quotes": [],
            "maude_event_type": "malfunction",
        }
        allowed = _schema(skill)["properties"]
        out = {k: v for k, v in {**_good_output(skill), **filled}.items() if k in allowed}
        return LLMResponse(
            text=json.dumps(out),
            model="mock-model",
            input_tokens=100,
            output_tokens=50,
            provider="mock",
        )

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


def _real_openfda_results(n: int) -> list[dict[str, Any]]:
    con = sqlite3.connect(ROOT / "data/demo/maudesignal_demo.db")
    rows = con.execute(
        "SELECT raw_json FROM raw_reports WHERE product_code='QIH' LIMIT ?", (n,)
    ).fetchall()
    con.close()
    return [json.loads(r[0]) for r in rows]


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    return Config(
        llm_provider="groq",
        groq_api_key="gsk_fake",
        groq_model="mock-model",
        anthropic_api_key=None,
        claude_model_extraction="mock-model",
        claude_model_reasoning="mock-model",
        openai_api_key=None,
        openai_model="mock-model",
        gemini_api_key=None,
        gemini_model="mock-model",
        provider_fallback_order="groq",
        openfda_api_key=None,
        db_path=tmp_path / "journey.db",
        log_level="WARNING",
        cost_ceiling_usd=150.0,
        project_root=ROOT,
    )


def test_ingest_extract_dashboard_psur(config: Config, tmp_path: Path) -> None:
    results = _real_openfda_results(3)
    assert results, "demo database has QIH records"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.fda.gov"
        return httpx.Response(
            200, json={"meta": {"results": {"total": len(results)}}, "results": results}
        )

    db = Database(config.db_path)
    client = OpenFDAClient()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))  # noqa: SLF001
    ingested = ingest_product_code(client=client, db=db, product_code="QIH", limit=3)
    assert db.count_raw_reports("QIH") == len(results)
    assert getattr(ingested, "records_fetched", len(results)) >= 1

    # 1. Start extraction (all three Skills per record, real schemas, mock model).
    loader = SkillLoader(ROOT / "skills")
    provider = _SkillProvider()
    extractor = Extractor(config, db, provider=provider)
    events = db.list_normalized_events(product_code="QIH")
    for ev in events:
        res = extract_record(
            extractor=extractor,
            db=db,
            event=ev,
            skill_extractor=loader.load(SKILLS[0]),
            skill_severity=loader.load(SKILLS[1]),
            skill_classifier=loader.load(SKILLS[2]),
        )
        assert res.any_success and res.errors == []

    # 2. Dashboard coverage metrics read the same rows the pages render.
    from maudesignal.dashboard.app import _extractions_dataframe

    df = _extractions_dataframe(db)
    assert len(df) >= len(events)
    assert set(df["maude_report_id"]) >= {e.maude_report_id for e in events}

    # 3. Export a formatted PSUR (Markdown, plus PDF when WeasyPrint is present).
    rows = db.list_extractions()
    day = rows[0].extraction_ts.strftime("%Y-%m-%d")
    out = PSURGenerator(db).generate("QIH", day, day, output_dir=tmp_path / "psur")
    md = Path(out["markdown_path"]).read_text(encoding="utf-8")
    assert out["record_count"] >= len(events)
    assert "QIH" in md and "#" in md
    if out["pdf_path"]:
        assert Path(out["pdf_path"]).read_bytes()[:4] == b"%PDF"
