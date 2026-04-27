"""Tests for drift interpreter wrapper (Skill #5)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from maudesignal.drift.interpreter import interpret_drift
from maudesignal.extraction.extractor import ExtractionResult
from maudesignal.extraction.skill_loader import LoadedSkill

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"


def _fake_extractor(output: dict[str, object]) -> MagicMock:
    extractor = MagicMock()
    extractor.run.return_value = ExtractionResult(
        output=output,
        model_used="fake-model",
        provider_used="fake",
        input_tokens=10,
        output_tokens=5,
        cost_estimate_usd=0.0,
        extraction_id="fake-id",
    )
    return extractor


def test_interpret_drift_passes_computed_stats_to_skill() -> None:
    expected_output = {"verdict": "stable", "confidence_score": 0.7}
    extractor = _fake_extractor(expected_output)

    result = interpret_drift(
        metric_name="sensitivity",
        baseline_values=[0.88, 0.89, 0.87, 0.90, 0.88],
        current_values=[0.86, 0.87, 0.85, 0.88, 0.87],
        cohort_label="QIH test",
        extractor=extractor,
        skills_root=SKILLS_ROOT,
    )

    assert result == expected_output
    skill_arg, input_arg = extractor.run.call_args[0]
    assert isinstance(skill_arg, LoadedSkill)
    assert skill_arg.name == "drift-analysis-interpreter"
    assert input_arg["metric_name"] == "sensitivity"
    assert input_arg["n_baseline"] == 5 and input_arg["n_current"] == 5
    assert "ks_statistic" in input_arg and "psi" in input_arg


def test_interpret_drift_handles_empty_arrays() -> None:
    extractor = _fake_extractor({"verdict": "insufficient_data"})
    result = interpret_drift(
        metric_name="sensitivity",
        baseline_values=[],
        current_values=[],
        cohort_label="empty",
        extractor=extractor,
        skills_root=SKILLS_ROOT,
    )
    assert result["verdict"] == "insufficient_data"
    _, input_arg = extractor.run.call_args[0]
    assert input_arg["n_baseline"] == 0 and input_arg["n_current"] == 0


def test_interpret_drift_loads_skill_5() -> None:
    extractor = _fake_extractor({"verdict": "stable"})
    interpret_drift(
        metric_name="m",
        baseline_values=[1.0, 2.0],
        current_values=[1.1, 2.1],
        cohort_label="c",
        extractor=extractor,
        skills_root=SKILLS_ROOT,
    )
    skill_arg, _ = extractor.run.call_args[0]
    assert skill_arg.version == "1.0.0"
    assert "drift" in skill_arg.system_prompt.lower()
