"""Unit tests for the Skill loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from maudesignal.common.exceptions import SkillLoadError
from maudesignal.extraction.skill_loader import SkillLoader


@pytest.fixture
def skills_root() -> Path:
    """Return the path to the real skills/ folder in the repo."""
    return Path(__file__).resolve().parents[2] / "skills"


def test_load_citation_verifier(skills_root: Path) -> None:
    """Real SKILL.md for regulatory-citation-verifier loads cleanly."""
    loader = SkillLoader(skills_root)
    skill = loader.load("regulatory-citation-verifier")

    assert skill.name == "regulatory-citation-verifier"
    assert skill.version == "1.0.0"
    assert "Skill: regulatory-citation-verifier" in skill.system_prompt
    assert skill.output_schema["title"] == "RegulatoryCitationVerifierOutput"
    assert isinstance(skill.good_examples, list)
    assert isinstance(skill.bad_examples, list)


def test_load_maude_extractor(skills_root: Path) -> None:
    """Real SKILL.md for maude-narrative-extractor loads with examples."""
    loader = SkillLoader(skills_root)
    skill = loader.load("maude-narrative-extractor")

    assert skill.name == "maude-narrative-extractor"
    assert skill.version == "1.0.0"
    assert skill.output_schema["title"] == "MaudeNarrativeExtractorOutput"
    assert (
        len(skill.good_examples) >= 3
    ), "Every Skill must ship with ≥3 good examples per Doc 5 §7.2"
    assert len(skill.bad_examples) >= 2, "Every Skill must ship with ≥2 bad examples per Doc 5 §7.2"


def test_missing_skill_raises(skills_root: Path) -> None:
    """Loading a non-existent Skill fails cleanly."""
    loader = SkillLoader(skills_root)
    with pytest.raises(SkillLoadError, match="not found"):
        loader.load("does-not-exist")


def test_invalid_skills_root_raises(tmp_path: Path) -> None:
    """Pointing loader at a non-directory fails at construction time."""
    with pytest.raises(SkillLoadError):
        SkillLoader(tmp_path / "nowhere")
