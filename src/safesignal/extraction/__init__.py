"""LLM-driven extraction module (Feature F2).

Loads SKILL.md files and uses them as system prompts for Claude API calls.
"""

from safesignal.extraction.extractor import Extractor
from safesignal.extraction.skill_loader import LoadedSkill, SkillLoader

__all__ = ["Extractor", "LoadedSkill", "SkillLoader"]
