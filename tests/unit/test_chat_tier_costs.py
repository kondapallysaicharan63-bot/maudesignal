"""The cost-per-tier report (HACKATHON-BUILT): offline, and in step with CHAT_TIERS.md."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any

from maudesignal.connector.data import ConnectorData

ROOT = Path(__file__).resolve().parents[2]


def load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "chat_tier_costs", ROOT / "scripts/chat_tier_costs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # a dataclass needs its module registered
    spec.loader.exec_module(mod)
    return mod


def test_twenty_questions_priced_only_with_the_recorded_average() -> None:
    mod = load()
    assert len(mod.SAMPLE) == 20 and mod.RECORDED_TYPED_ASK_USD == 0.048
    with tempfile.TemporaryDirectory() as tmp:
        rs = mod.rows(ConnectorData(work_dir=Path(tmp)).known_product_codes())
    assert all(r.before_usd == 0.048 for r in rs)
    assert all(r.after_usd in (0.0, 0.048) for r in rs)
    assert all((r.after_usd == 0.048) == (r.tier == "live") for r in rs)
    assert {r.tier for r in rs} == {"canned", "direct", "cache", "live"}
    after = sum(r.after_usd for r in rs) / len(rs)
    assert after <= 0.02  # the target, even at the upper-bound price for tier 4


def test_doc_table_is_what_the_script_prints() -> None:
    mod = load()
    with tempfile.TemporaryDirectory() as tmp:
        text = mod.table(mod.rows(ConnectorData(work_dir=Path(tmp)).known_product_codes()))
    doc = (ROOT / "docs/hackathon/CHAT_TIERS.md").read_text(encoding="utf-8")
    assert f"{mod.START}\n{text}{mod.END}" in doc
