"""Tests for G-3: SkillBuilder workspace-relative skill loading."""
import pytest
from pathlib import Path


def test_workspace_skill_overrides_global(tmp_path):
    """Workspace SKILL.md takes precedence over global on same skill_id."""
    global_dir = tmp_path / "global_skills"
    ws_dir = tmp_path / "workspace_skills"
    # Create same skill_id in both
    (global_dir / "lit-review").mkdir(parents=True)
    (global_dir / "lit-review" / "SKILL.md").write_text(
        "# lit-review\nversion: 1\n\nGlobal content\n"
    )
    (ws_dir / "lit-review").mkdir(parents=True)
    (ws_dir / "lit-review" / "SKILL.md").write_text(
        "# lit-review\nversion: 2\n\nWorkspace content\n"
    )

    from hi_agent.config.skill_builder import SkillBuilder
    builder = SkillBuilder(
        global_skill_dirs=[str(global_dir)],
        workspace_skill_dirs=[str(ws_dir)],
    )
    skills = builder.build()
    lit = next(
        (s for s in skills if "lit-review" in (s.skill_id or "").lower() or "lit-review" in (s.name or "").lower()),
        None,
    )
    assert lit is not None, f"lit-review not found in {[s.skill_id for s in skills]}"
    # Workspace version wins — content from workspace file
    content_str = lit.raw_content if hasattr(lit, "raw_content") else getattr(lit, "content", str(lit))
    if content_str is None:
        content_str = str(lit)
    assert "version: 2" in content_str or getattr(lit, "version", None) == "2" or getattr(lit, "source", None) == "workspace", (
        f"Expected workspace version to win, got content={content_str!r}, source={getattr(lit, 'source', None)!r}"
    )
    assert getattr(lit, "source", None) == "workspace"


def test_global_skill_used_when_no_workspace_override(tmp_path):
    """Global skill is returned when workspace has no override."""
    global_dir = tmp_path / "global_skills"
    (global_dir / "analysis").mkdir(parents=True)
    (global_dir / "analysis" / "SKILL.md").write_text(
        "# analysis\nversion: 1\n\nAnalysis skill\n"
    )

    from hi_agent.config.skill_builder import SkillBuilder
    builder = SkillBuilder(global_skill_dirs=[str(global_dir)], workspace_skill_dirs=[])
    skills = builder.build()
    assert len(skills) >= 1
    analysis = next(
        (s for s in skills if "analysis" in (s.skill_id or "").lower() or "analysis" in (s.name or "").lower()),
        None,
    )
    assert analysis is not None
    assert getattr(analysis, "source", None) == "global"


def test_workspace_only_skill_included(tmp_path):
    """Workspace-only skills (no global counterpart) are included."""
    ws_dir = tmp_path / "workspace_skills"
    (ws_dir / "ws-only-skill").mkdir(parents=True)
    (ws_dir / "ws-only-skill" / "SKILL.md").write_text(
        "# ws-only-skill\nversion: 1\n\nWorkspace only\n"
    )

    from hi_agent.config.skill_builder import SkillBuilder
    builder = SkillBuilder(global_skill_dirs=[], workspace_skill_dirs=[str(ws_dir)])
    skills = builder.build()
    ws_skill = next(
        (s for s in skills if "ws-only-skill" in (s.skill_id or "").lower() or "ws-only-skill" in (s.name or "").lower()),
        None,
    )
    assert ws_skill is not None
    assert getattr(ws_skill, "source", None) == "workspace"


def test_build_with_config_falls_back_to_no_workspace(tmp_path):
    """SkillBuilder constructed with only a TraceConfig still works (no workspace dirs)."""
    from hi_agent.config.skill_builder import SkillBuilder
    from hi_agent.config.trace_config import TraceConfig
    cfg = TraceConfig(skill_storage_dir=str(tmp_path / "skills"))
    # Original single-arg constructor should still work
    builder = SkillBuilder(config=cfg)
    skills = builder.build()
    assert isinstance(skills, list)
