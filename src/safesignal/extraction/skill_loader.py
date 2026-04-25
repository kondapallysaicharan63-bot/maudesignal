"""Skill loader — turns SKILL.md files into runtime objects.

A Skill is a versioned folder containing:
    skills/<skill-name>/
        SKILL.md                 — the behavior contract (system prompt)
        VERSION                  — semver string on one line
        schemas/output.schema.json   — JSON Schema the output must validate against
        examples/good.jsonl      — optional few-shot good cases
        examples/bad.jsonl       — optional adversarial cases

This module reads those files at runtime and exposes a typed object the
Extractor can consume. Keeping the loading separate from the invocation
preserves the principle that "behavior lives in SKILL.md, not Python"
(Doc 5 D3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safesignal.common.exceptions import SkillLoadError
from safesignal.common.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LoadedSkill:
    """A Skill loaded into memory, ready to be invoked.

    Attributes:
        name: Skill folder name (e.g., "maude-narrative-extractor").
        version: Semver string from VERSION file.
        system_prompt: The SKILL.md content used as Claude's system prompt.
        output_schema: Parsed JSON Schema for validating outputs.
        good_examples: Optional list of {input, expected_output} dicts.
        bad_examples: Optional list of {input, forbidden_output} dicts.
        skill_root: Absolute path to the skill's root folder.
    """

    name: str
    version: str
    system_prompt: str
    output_schema: dict[str, Any]
    good_examples: list[dict[str, Any]]
    bad_examples: list[dict[str, Any]]
    skill_root: Path


class SkillLoader:
    """Load Skills from the ``skills/`` directory."""

    def __init__(self, skills_root: Path) -> None:
        """Create a loader rooted at the given skills directory.

        Args:
            skills_root: Path to the project's ``skills/`` folder.
        """
        if not skills_root.exists() or not skills_root.is_dir():
            raise SkillLoadError(
                f"Skills root does not exist or is not a directory: {skills_root}"
            )
        self._root = skills_root

    def load(self, skill_name: str) -> LoadedSkill:
        """Load a single Skill by folder name.

        Args:
            skill_name: Folder name under ``skills/``.

        Returns:
            A fully populated LoadedSkill.

        Raises:
            SkillLoadError: If required files are missing or malformed.
        """
        skill_dir = self._root / skill_name
        if not skill_dir.is_dir():
            raise SkillLoadError(f"Skill folder not found: {skill_dir}")

        # --- SKILL.md (required) ---
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.is_file():
            raise SkillLoadError(f"Missing SKILL.md in {skill_dir}")
        system_prompt = skill_md_path.read_text(encoding="utf-8").strip()

        # --- VERSION (required) ---
        version_path = skill_dir / "VERSION"
        if not version_path.is_file():
            raise SkillLoadError(f"Missing VERSION file in {skill_dir}")
        version = version_path.read_text(encoding="utf-8").strip()
        if not _looks_like_semver(version):
            raise SkillLoadError(
                f"Invalid semver in {version_path}: {version!r}"
            )

        # --- Output schema (required) ---
        schema_path = skill_dir / "schemas" / "output.schema.json"
        if not schema_path.is_file():
            raise SkillLoadError(f"Missing output schema at {schema_path}")
        try:
            output_schema: dict[str, Any] = json.loads(
                schema_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise SkillLoadError(f"Invalid JSON schema in {schema_path}: {exc}") from exc

        # --- Examples (optional but recommended) ---
        good_examples = _load_jsonl(skill_dir / "examples" / "good.jsonl")
        bad_examples = _load_jsonl(skill_dir / "examples" / "bad.jsonl")

        logger.info(
            "skill_loaded",
            skill=skill_name,
            version=version,
            good_examples=len(good_examples),
            bad_examples=len(bad_examples),
        )

        return LoadedSkill(
            name=skill_name,
            version=version,
            system_prompt=system_prompt,
            output_schema=output_schema,
            good_examples=good_examples,
            bad_examples=bad_examples,
            skill_root=skill_dir,
        )


def _looks_like_semver(value: str) -> bool:
    """Return True if value looks like a semver string (e.g., "1.0.0")."""
    parts = value.split(".")
    if len(parts) != 3:
        return False
    return all(p.isdigit() for p in parts)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file into a list of dicts. Missing file = empty list."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SkillLoadError(
                    f"Invalid JSON on line {line_num} of {path}: {exc}"
                ) from exc
    return records
