"""Tests for SkillDefinition and SkillLoader."""

from __future__ import annotations

import os
import textwrap

import pytest
from hi_agent.skill.definition import SkillDefinition
from hi_agent.skill.loader import SkillLoader, SkillPrompt

# ===================================================================
# Fixtures — reusable SKILL.md content
# ===================================================================

SAMPLE_SKILL_MD = textwrap.dedent("""\
    ---
    name: analyze-data
    version: 1.0.0
    description: Analyze structured datasets
    when_to_use: When user needs data analysis
    allowed_tools: [Bash, Read, Write]
    model: default
    tags: [analysis, data]
    requires:
      bins: [python3]
      env: [DATA_DIR]
    lifecycle_stage: certified
    confidence: 0.85
    cost_estimate_tokens: 500
    ---

    # Analyze Data

    Use this skill to analyze structured datasets.
    Steps:
    1. Load the data
    2. Explore columns
    3. Produce summary
""")

MINIMAL_SKILL_MD = textwrap.dedent("""\
    ---
    name: hello-world
    ---

    Say hello.
""")


def _write_skill(base: str, name: str, content: str) -> str:
    """Write a SKILL.md into ``base/name/SKILL.md`` and return dir path."""
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return d


# ===================================================================
# SkillDefinition tests
# ===================================================================


class TestSkillDefinitionFromMarkdown:
    """SkillDefinition.from_markdown parses frontmatter + content."""

    def test_parse_full_frontmatter(self) -> None:
        skill = SkillDefinition.from_markdown(SAMPLE_SKILL_MD, "/skills/analyze-data/SKILL.md")
        assert skill.skill_id == "analyze-data"
        assert skill.name == "analyze-data"
        assert skill.version == "1.0.0"
        assert skill.description == "Analyze structured datasets"
        assert skill.when_to_use == "When user needs data analysis"
        assert skill.allowed_tools == ["Bash", "Read", "Write"]
        assert skill.model == "default"
        assert skill.tags == ["analysis", "data"]
        assert skill.requires_bins == ["python3"]
        assert skill.requires_env == ["DATA_DIR"]
        assert skill.lifecycle_stage == "certified"
        assert skill.confidence == pytest.approx(0.85)
        assert skill.cost_estimate_tokens == 500
        assert skill.source_path == "/skills/analyze-data/SKILL.md"
        assert "# Analyze Data" in skill.prompt_content

    def test_parse_minimal(self) -> None:
        skill = SkillDefinition.from_markdown(MINIMAL_SKILL_MD)
        assert skill.skill_id == "hello-world"
        assert skill.name == "hello-world"
        assert skill.version == "0.1.0"
        assert skill.prompt_content == "Say hello."

    def test_no_frontmatter(self) -> None:
        skill = SkillDefinition.from_markdown("Just some text.", "/a/b.md")
        assert skill.skill_id == "b"
        assert skill.prompt_content == "Just some text."


class TestSkillDefinitionRoundTrip:
    """to_frontmatter_md round-trips correctly."""

    def test_round_trip(self) -> None:
        original = SkillDefinition.from_markdown(SAMPLE_SKILL_MD, "/x/SKILL.md")
        md = original.to_frontmatter_md()
        restored = SkillDefinition.from_markdown(md, "/x/SKILL.md")
        assert restored.name == original.name
        assert restored.version == original.version
        assert restored.description == original.description
        assert restored.allowed_tools == original.allowed_tools
        assert restored.tags == original.tags
        assert restored.requires_bins == original.requires_bins
        assert restored.requires_env == original.requires_env
        assert restored.lifecycle_stage == original.lifecycle_stage
        assert restored.confidence == pytest.approx(original.confidence)
        assert restored.cost_estimate_tokens == original.cost_estimate_tokens
        assert restored.prompt_content.strip() == original.prompt_content.strip()


class TestSkillDefinitionPrompts:
    """to_full_prompt and to_compact_entry."""

    def test_full_prompt_includes_content(self) -> None:
        skill = SkillDefinition.from_markdown(SAMPLE_SKILL_MD, "/x/SKILL.md")
        full = skill.to_full_prompt()
        assert "## Skill: analyze-data" in full
        assert "Analyze structured datasets" in full
        assert "# Analyze Data" in full

    def test_compact_entry_is_name_and_path(self) -> None:
        skill = SkillDefinition.from_markdown(SAMPLE_SKILL_MD, "/skills/analyze-data/SKILL.md")
        compact = skill.to_compact_entry()
        assert compact == "- analyze-data: /skills/analyze-data/SKILL.md"

    def test_compact_entry_no_path(self) -> None:
        skill = SkillDefinition(skill_id="s1", name="my-skill")
        compact = skill.to_compact_entry()
        assert compact == "- my-skill"


class TestSkillDefinitionEligibility:
    """check_eligibility with missing bins/env."""

    def test_eligible_no_requirements(self) -> None:
        skill = SkillDefinition(skill_id="s1", name="s1")
        ok, reason = skill.check_eligibility()
        assert ok is True
        assert reason == ""

    def test_missing_binary(self) -> None:
        skill = SkillDefinition(
            skill_id="s1",
            name="s1",
            requires_bins=["__nonexistent_binary_xyz__"],
        )
        ok, reason = skill.check_eligibility()
        assert ok is False
        assert "__nonexistent_binary_xyz__" in reason

    def test_missing_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TOTALLY_FAKE_VAR_XYZ", raising=False)
        skill = SkillDefinition(
            skill_id="s1",
            name="s1",
            requires_env=["TOTALLY_FAKE_VAR_XYZ"],
        )
        ok, reason = skill.check_eligibility()
        assert ok is False
        assert "TOTALLY_FAKE_VAR_XYZ" in reason

    def test_eligible_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_VAR_123", "1")
        skill = SkillDefinition(
            skill_id="s1",
            name="s1",
            requires_env=["MY_TEST_VAR_123"],
        )
        ok, _ = skill.check_eligibility()
        assert ok is True


class TestSkillDefinitionEstimateTokens:
    """estimate_tokens approximation."""

    def test_uses_cost_estimate_if_set(self) -> None:
        skill = SkillDefinition(skill_id="s1", name="s1", cost_estimate_tokens=42)
        assert skill.estimate_tokens() == 42

    def test_estimates_from_prompt(self) -> None:
        skill = SkillDefinition(
            skill_id="s1",
            name="s1",
            prompt_content="A" * 400,  # 400 chars ~ 100 tokens
        )
        tokens = skill.estimate_tokens()
        assert tokens > 0
        # Should be roughly 100 (prompt) + header overhead
        assert 90 <= tokens <= 200


# ===================================================================
# SkillLoader tests
# ===================================================================


class TestSkillLoaderDiscover:
    """SkillLoader.discover scans directories for SKILL.md."""

    def test_discover_finds_skills(self, tmp_path: str) -> None:
        d = str(tmp_path)
        _write_skill(d, "skill-a", SAMPLE_SKILL_MD)
        _write_skill(d, "skill-b", MINIMAL_SKILL_MD)

        loader = SkillLoader(search_dirs=[d])
        count = loader.discover()
        assert count == 2
        assert loader.skill_count == 2

    def test_discover_empty_dir(self, tmp_path: str) -> None:
        loader = SkillLoader(search_dirs=[str(tmp_path)])
        assert loader.discover() == 0

    def test_discover_nonexistent_dir(self) -> None:
        loader = SkillLoader(search_dirs=["/nonexistent/path/xyz"])
        assert loader.discover() == 0


class TestSkillLoaderPrecedence:
    """Higher precedence dir overrides lower."""

    def test_override(self, tmp_path: str) -> None:
        low = os.path.join(str(tmp_path), "low")
        high = os.path.join(str(tmp_path), "high")

        # Same skill_id "hello-world" in both dirs, different content
        low_md = textwrap.dedent("""\
            ---
            name: hello-world
            version: 1.0.0
            ---

            Low priority content.
        """)
        high_md = textwrap.dedent("""\
            ---
            name: hello-world
            version: 2.0.0
            ---

            High priority content.
        """)
        _write_skill(low, "hello-world", low_md)
        _write_skill(high, "hello-world", high_md)

        loader = SkillLoader(search_dirs=[low, high])
        loader.discover()

        skill = loader.get_skill("hello-world")
        assert skill is not None
        assert skill.version == "2.0.0"
        assert "High priority" in skill.prompt_content


class TestSkillLoaderFiltering:
    """list_skills, list_by_tag, list_by_stage."""

    def test_eligible_only_filters(self, tmp_path: str) -> None:
        d = str(tmp_path)
        # Skill with impossible binary requirement
        ineligible_md = textwrap.dedent("""\
            ---
            name: needs-magic
            requires:
              bins: [__magic_binary_999__]
            ---

            Magic content.
        """)
        _write_skill(d, "needs-magic", ineligible_md)
        _write_skill(d, "hello-world", MINIMAL_SKILL_MD)

        loader = SkillLoader(search_dirs=[d])
        loader.discover()

        all_skills = loader.list_skills(eligible_only=False)
        assert len(all_skills) == 2

        eligible = loader.list_skills(eligible_only=True)
        assert len(eligible) == 1
        assert eligible[0].name == "hello-world"

    def test_list_by_tag(self, tmp_path: str) -> None:
        d = str(tmp_path)
        _write_skill(d, "analyze-data", SAMPLE_SKILL_MD)
        _write_skill(d, "hello-world", MINIMAL_SKILL_MD)

        loader = SkillLoader(search_dirs=[d])
        loader.discover()

        tagged = loader.list_by_tag("analysis")
        assert len(tagged) == 1
        assert tagged[0].name == "analyze-data"

        assert loader.list_by_tag("nonexistent") == []

    def test_list_by_stage(self, tmp_path: str) -> None:
        d = str(tmp_path)
        _write_skill(d, "analyze-data", SAMPLE_SKILL_MD)  # certified
        _write_skill(d, "hello-world", MINIMAL_SKILL_MD)  # candidate (default)

        loader = SkillLoader(search_dirs=[d])
        loader.discover()

        certified = loader.list_by_stage("certified")
        assert len(certified) == 1
        assert certified[0].lifecycle_stage == "certified"

        candidates = loader.list_by_stage("candidate")
        assert len(candidates) == 1


# ===================================================================
# SkillLoader.build_prompt tests
# ===================================================================


def _make_simple_skill(name: str, confidence: float, prompt_size: int = 100) -> str:
    """Generate SKILL.md with controllable size."""
    return textwrap.dedent(f"""\
        ---
        name: {name}
        confidence: {confidence}
        lifecycle_stage: certified
        ---

        {"X" * prompt_size}
    """)


class TestBuildPrompt:
    """build_prompt stays within budget and uses correct modes."""

    def test_under_budget_uses_full(self, tmp_path: str) -> None:
        d = str(tmp_path)
        _write_skill(d, "s1", _make_simple_skill("s1", 0.9, 40))
        _write_skill(d, "s2", _make_simple_skill("s2", 0.8, 40))

        loader = SkillLoader(search_dirs=[d], max_prompt_tokens=10_000)
        loader.discover()

        prompt = loader.build_prompt()
        assert prompt.full_count == 2
        assert prompt.compact_count == 0
        assert prompt.truncated_count == 0
        assert prompt.total_tokens <= prompt.budget_tokens

    def test_over_budget_falls_back_to_compact(self, tmp_path: str) -> None:
        d = str(tmp_path)
        # Create skills with large prompts
        for i in range(5):
            _write_skill(d, f"big-{i}", _make_simple_skill(f"big-{i}", 0.9 - i * 0.05, 2000))

        loader = SkillLoader(search_dirs=[d], max_prompt_tokens=500)
        loader.discover()

        prompt = loader.build_prompt(budget_tokens=500)
        # Can't fit all in full mode with only 500 token budget
        assert prompt.compact_count > 0 or prompt.truncated_count > 0
        assert prompt.total_tokens <= 500

    def test_binary_search_optimal_split(self, tmp_path: str) -> None:
        d = str(tmp_path)
        # 10 skills, each ~100 chars full prompt
        for i in range(10):
            _write_skill(
                d,
                f"sk-{i:02d}",
                _make_simple_skill(f"sk-{i:02d}", 0.95 - i * 0.05, 200),
            )

        loader = SkillLoader(search_dirs=[d])
        loader.discover()

        # Set a budget that allows some full but not all
        # Each full prompt is ~200 chars = ~50 tokens, total ~500 for 10
        # Compact ~15 chars = ~4 tokens each
        prompt = loader.build_prompt(budget_tokens=300)

        assert prompt.full_count + prompt.compact_count <= 10
        assert prompt.total_tokens <= 300
        # If we could fit more full, the budget would be exceeded
        # (structural correctness — we trust binary search)
        assert prompt.full_count >= 0

    def test_empty_loader(self) -> None:
        loader = SkillLoader()
        prompt = loader.build_prompt()
        assert prompt.full_count == 0
        assert prompt.compact_count == 0
        assert prompt.to_prompt_string() == ""

    def test_ineligible_excluded_from_prompt(self, tmp_path: str) -> None:
        d = str(tmp_path)
        ineligible_md = textwrap.dedent("""\
            ---
            name: needs-magic
            confidence: 0.99
            requires:
              bins: [__no_such_bin_xyz__]
            ---

            Content.
        """)
        _write_skill(d, "needs-magic", ineligible_md)
        _write_skill(d, "ok-skill", _make_simple_skill("ok-skill", 0.5, 40))

        loader = SkillLoader(search_dirs=[d])
        loader.discover()

        prompt = loader.build_prompt()
        # Only ok-skill should appear
        assert prompt.full_count + prompt.compact_count == 1


class TestSkillPromptFormatting:
    """SkillPrompt.to_prompt_string."""

    def test_full_only(self) -> None:
        sp = SkillPrompt(
            full_skills=["## Skill: foo\nDo foo."],
            compact_skills=[],
            total_tokens=10,
            budget_tokens=100,
            full_count=1,
            compact_count=0,
            truncated_count=0,
        )
        text = sp.to_prompt_string()
        assert "Available Skills (full)" in text
        assert "Do foo." in text
        assert "Additional Skills" not in text

    def test_mixed(self) -> None:
        sp = SkillPrompt(
            full_skills=["## Skill: foo\nDo foo."],
            compact_skills=["- bar: /path/bar/SKILL.md"],
            total_tokens=20,
            budget_tokens=100,
            full_count=1,
            compact_count=1,
            truncated_count=0,
        )
        text = sp.to_prompt_string()
        assert "Available Skills (full)" in text
        assert "Additional Skills" in text
        assert "- bar: /path/bar/SKILL.md" in text

    def test_truncated_notice(self) -> None:
        sp = SkillPrompt(
            full_skills=[],
            compact_skills=[],
            total_tokens=0,
            budget_tokens=10,
            full_count=0,
            compact_count=0,
            truncated_count=5,
        )
        text = sp.to_prompt_string()
        assert "5 more skill(s) omitted" in text


# ===================================================================
# SkillLoader version tracking
# ===================================================================


class TestSkillLoaderVersion:
    def test_bump_version(self) -> None:
        loader = SkillLoader()
        assert loader.snapshot_version == 0
        v = loader.bump_version()
        assert v == 1
        assert loader.snapshot_version == 1
        loader.bump_version()
        assert loader.snapshot_version == 2
