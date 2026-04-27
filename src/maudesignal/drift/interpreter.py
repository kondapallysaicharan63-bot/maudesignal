"""Skill #5 wrapper: compute drift stats + run LLM interpretation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from maudesignal.config import Config
from maudesignal.drift.calculator import ks_test, psi_calculator
from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.storage.database import Database

SKILL_NAME = "drift-analysis-interpreter"


def interpret_drift(
    *,
    metric_name: str,
    baseline_values: Sequence[float],
    current_values: Sequence[float],
    cohort_label: str,
    extractor: Extractor,
    skills_root: Path,
) -> dict[str, Any]:
    """Compute drift stats then run Skill #5 to produce a regulator-readable verdict."""
    bv = float(np.mean(baseline_values)) if len(baseline_values) > 0 else 0.0
    cv = float(np.mean(current_values)) if len(current_values) > 0 else 0.0
    ks_stat, ks_p = ks_test(baseline_values, current_values)
    psi = psi_calculator(baseline_values, current_values)

    skill_input = {
        "metric_name": metric_name,
        "baseline_value": bv,
        "current_value": cv,
        "ks_statistic": ks_stat,
        "ks_p_value": ks_p,
        "psi": psi,
        "n_baseline": len(baseline_values),
        "n_current": len(current_values),
        "cohort_label": cohort_label,
    }

    skill = SkillLoader(skills_root).load(SKILL_NAME)
    result = extractor.run(skill, skill_input)
    return dict(result.output)


def build_runtime(config: Config) -> tuple[Extractor, Database, Path]:
    """Helper for the CLI: build extractor + db + skills root from config."""
    db = Database(config.db_path)
    extractor = Extractor(config=config, db=db)
    return extractor, db, config.project_root / "skills"
