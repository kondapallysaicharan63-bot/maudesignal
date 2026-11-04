"""The LLZ keyword measurement file is recomputed from the demo database, never typed in."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "keyword_measurement", ROOT / "scripts" / "keyword_measurement.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_file_matches_a_fresh_recompute() -> None:
    mod = _load()
    fresh = mod.measure()
    committed = json.loads(
        (ROOT / "web" / "public" / "data" / "keyword_measurement.json").read_text()
    )
    assert committed == fresh


def test_counts_add_up_and_every_match_is_labelled() -> None:
    m = _load().measure()
    assert m["matched"] == len(m["rows"]) == len({r["report_id"] for r in m["rows"]})
    assert m["same_problem"] + m["different_image_problem"] + m["mention_only"] == m["matched"]
    assert m["pct_same_problem"] + m["pct_too_broad"] == 100.0
    assert m["adjudicator"].startswith("Claude (AI), not a person")
    assert m["recalls"]["mention_image_any_field"] <= m["recalls"]["stored"]
    assert all(r["reason"] for r in m["rows"])
