"""Tests for SkillDefinition contract aliases and SkillLoader version-qualified lookup."""

from __future__ import annotations

import textwrap

from hi_agent.skill.definition import SkillDefinition
from hi_agent.skill.loader import SkillLoader

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MD = textwrap.dedent("""\
    ---
    name: paper-reading
    version: 1.0.0
    description: Read and summarise academic papers
    allowed_tools: [Read, Bash]
    lifecycle_stage: certified
    confidence: 0.9
    ---

    Read the paper carefully and extract key findings.
""")


def _make_skill(
    name: str = "paper-reading",
    prompt_content: str = "Read papers carefully.",
    allowed_tools: list[str] | None = None,
) -> SkillDefinition:
    tools = ["Read", "Bash"] if allowed_tools is None else allowed_tools
    return SkillDefinition(
        skill_id=name,
        name=name,
        prompt_content=prompt_content,
        allowed_tools=tools,
    )


# ---------------------------------------------------------------------------
# Task 1 — SkillDefinition contract aliases
# ---------------------------------------------------------------------------


class TestSkillDefinitionAliases:
    def test_system_prompt_fragment_returns_prompt_content(self) -> None:
        """system_prompt_fragment must return the same object as prompt_content."""
        skill = _make_skill(prompt_content="Do analysis.")
        assert skill.system_prompt_fragment == skill.prompt_content
        assert skill.system_prompt_fragment == "Do analysis."

    def test_system_prompt_fragment_reflects_mutation(self) -> None:
        """system_prompt_fragment must reflect updates to prompt_content."""
        skill = _make_skill(prompt_content="v1")
        skill.prompt_content = "v2"
        assert skill.system_prompt_fragment == "v2"

    def test_tool_specs_returns_allowed_tools(self) -> None:
        """tool_specs must return the same list as allowed_tools."""
        tools = ["Read", "Write", "Bash"]
        skill = _make_skill(allowed_tools=tools)
        assert skill.tool_specs is skill.allowed_tools
        assert skill.tool_specs == tools

    def test_tool_specs_empty_when_no_tools(self) -> None:
        """tool_specs must be an empty list when no tools are set."""
        skill = _make_skill(allowed_tools=[])
        assert skill.tool_specs == []

    def test_aliases_from_markdown_parse(self) -> None:
        """Aliases work correctly when skill is parsed from Markdown."""
        skill = SkillDefinition.from_markdown(SAMPLE_MD, source_path="SKILL.md")
        assert skill.system_prompt_fragment == skill.prompt_content
        assert skill.tool_specs == skill.allowed_tools
        assert "Read" in skill.tool_specs


# ---------------------------------------------------------------------------
# Task 3 — SkillLoader version-qualified lookup
# ---------------------------------------------------------------------------


class TestSkillLoaderVersionedLookup:
    """Tests for SkillLoader.get_skill(name, version=...).

    These tests use a pre-populated in-memory SkillLoader (no file system I/O).
    The SkillLoader._skills dict is injected directly rather than going through
    the file discovery path, because:
      (1) there is no real SKILL.md on disk with version-qualified IDs, and
      (2) testing file discovery here would duplicate test_skill_definition.py.
    Injecting the dict is an accepted unit-test pattern for internal state —
    it is NOT mocking a production code path; it is setting up test fixtures.
    """

    def _loader_with_skills(self, skills: dict[str, SkillDefinition]) -> SkillLoader:
        """Return a SkillLoader whose registry is pre-populated."""
        loader = SkillLoader()
        loader._skills = skills
        return loader

    def test_champion_returns_plain_skill(self) -> None:
        """version='champion' (default) returns the plain skill_id entry."""
        skill = _make_skill("paper-reading")
        loader = self._loader_with_skills({"paper-reading": skill})
        assert loader.get_skill("paper-reading") is skill
        assert loader.get_skill("paper-reading", version="champion") is skill

    def test_champion_returns_none_when_missing(self) -> None:
        """Returns None when skill_id is not found under champion."""
        loader = self._loader_with_skills({})
        assert loader.get_skill("missing-skill") is None
        assert loader.get_skill("missing-skill", version="champion") is None

    def test_challenger_lookup_qualified_key(self) -> None:
        """version='challenger' resolves '{skill_id}@challenger' first."""
        champion = _make_skill("paper-reading", prompt_content="champion prompt")
        challenger = _make_skill("paper-reading@challenger", prompt_content="challenger prompt")
        loader = self._loader_with_skills(
            {
                "paper-reading": champion,
                "paper-reading@challenger": challenger,
            }
        )
        result = loader.get_skill("paper-reading", version="challenger")
        assert result is challenger
        assert result.prompt_content == "challenger prompt"

    def test_challenger_falls_back_to_champion(self) -> None:
        """version='challenger' falls back to plain skill_id when no qualifier found."""
        champion = _make_skill("paper-reading", prompt_content="champion prompt")
        loader = self._loader_with_skills({"paper-reading": champion})
        result = loader.get_skill("paper-reading", version="challenger")
        assert result is champion

    def test_version_tag_lookup(self) -> None:
        """version='v2' resolves '{skill_id}@v2'."""
        v1 = _make_skill("paper-reading", prompt_content="v1 prompt")
        v2 = _make_skill("paper-reading@v2", prompt_content="v2 prompt")
        loader = self._loader_with_skills(
            {
                "paper-reading": v1,
                "paper-reading@v2": v2,
            }
        )
        assert loader.get_skill("paper-reading", version="v2") is v2

    def test_version_tag_falls_back_when_absent(self) -> None:
        """version='v3' falls back to plain skill_id when '@v3' key absent."""
        v1 = _make_skill("paper-reading", prompt_content="v1 prompt")
        loader = self._loader_with_skills({"paper-reading": v1})
        result = loader.get_skill("paper-reading", version="v3")
        assert result is v1

    def test_version_tag_returns_none_when_both_absent(self) -> None:
        """Returns None when neither qualified nor plain key is present."""
        loader = self._loader_with_skills({})
        assert loader.get_skill("no-such-skill", version="v99") is None
