r"""Record Muse Spark verification questions for the simulated company's problem patterns.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

For each distinct product code of the simulated company, take the problem patterns the
company page already shows (counts passed the claim gate) and ask Muse Spark, once per
code, for 2-3 plain verification questions per pattern (Skill ``verification-questions``).
Writes ``demo/company/questions.json``. Spends Meta Model API credit, so it runs in CI only
when ``demo/company/QUESTIONS_REQUEST`` is pushed. Key: ``META_MODEL_API_KEY`` (env only).

    python scripts/record_company_questions.py
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.company import load_company  # noqa: E402
from maudesignal.company.constants import company_dir  # noqa: E402
from maudesignal.company.questions import (  # noqa: E402
    DEFAULT_MODEL,
    QuestionsDraft,
    QuestionsResult,
    draft_questions,
    questions_document,
    questions_path,
    validate_questions,
)


def record(client: Any, folder: Path | None = None, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Ask for questions per product code and write ``questions.json``; returns the document."""
    base = folder or company_dir()
    view = load_company(base)
    per_code: dict[str, tuple[QuestionsDraft, QuestionsResult]] = {}
    for dev in view.devices:
        code = dev.product_code
        if code in per_code:
            continue
        patterns = [p for p in dev.code_patterns.patterns if p.gate_count == "pass"]
        if not patterns:
            continue
        draft = draft_questions(client, patterns, model=model)
        per_code[code] = (
            draft,
            validate_questions(draft.raw_output, {p.pattern_id for p in patterns}),
        )
    doc = questions_document(per_code)
    path = questions_path(base)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; reads the key from the environment and never prints it."""
    key = os.environ.get("META_MODEL_API_KEY", "").strip()
    if not key:
        print("META_MODEL_API_KEY is not set; nothing recorded.", file=sys.stderr)
        return 2
    from maudesignal.copilot.meta_provider import MetaProvider

    model = os.environ.get("META_MODEL_API_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")
    provider = MetaProvider(api_key=key, model=model, base_url=base_url)
    doc = record(provider.client, model=model)
    for code, body in doc["codes"].items():
        print(
            f"{code}: {len(body['patterns'])} patterns with questions, "
            f"{len(body['dropped'])} dropped, error={body['error']}"
        )
    print(f"cost about ${doc['cost_usd']:.4f} -> {questions_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
