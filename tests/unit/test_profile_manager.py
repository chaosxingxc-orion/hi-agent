"""Unit tests for ProfileDirectoryManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from hi_agent.profile.manager import ProfileDirectoryManager


class TestProfileDirectoryManager:
    def test_default_home_is_dot_hi_agent(self, monkeypatch):
        """Without env var set, default home is ~/.hi_agent."""
        monkeypatch.delenv("HI_AGENT_HOME", raising=False)
        pdm = ProfileDirectoryManager()
        assert pdm.home == Path.home() / ".hi_agent"

    def test_hi_agent_home_env_var_overrides_default(self, monkeypatch, tmp_path):
        """HI_AGENT_HOME env var takes priority over the default."""
        monkeypatch.setenv("HI_AGENT_HOME", str(tmp_path))
        pdm = ProfileDirectoryManager()
        assert pdm.home == tmp_path.resolve()

    def test_explicit_home_overrides_env_var(self, tmp_path, monkeypatch):
        """Explicit constructor argument takes priority over HI_AGENT_HOME env var."""
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("HI_AGENT_HOME", str(tmp_path))
        pdm = ProfileDirectoryManager(home_dir=str(other))
        assert pdm.home == other.resolve()

    def test_profile_dir_creates_directory(self, tmp_path):
        """profile_dir() creates the directory and returns the correct path."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        result = pdm.profile_dir("my_profile")
        assert result == tmp_path / "profiles" / "my_profile"
        assert result.is_dir()

    def test_episodic_dir_with_profile_id(self, tmp_path):
        """episodic_dir(profile_id) returns <home>/episodes/<profile_id>/."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        result = pdm.episodic_dir("p1")
        assert result == tmp_path / "episodes" / "p1"
        assert result.is_dir()

    def test_episodic_dir_without_profile_id(self, tmp_path):
        """episodic_dir() without a profile_id returns <home>/episodes/."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        result = pdm.episodic_dir()
        assert result == tmp_path / "episodes"
        assert result.is_dir()

    def test_checkpoint_dir(self, tmp_path):
        """checkpoint_dir() returns <home>/checkpoints/ and creates it."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        result = pdm.checkpoint_dir()
        assert result == tmp_path / "checkpoints"
        assert result.is_dir()

    def test_audit_dir(self, tmp_path):
        """audit_dir() returns <home>/audit/ and creates it."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        result = pdm.audit_dir()
        assert result == tmp_path / "audit"
        assert result.is_dir()

    def test_profile_dir_paths_are_isolated_per_profile(self, tmp_path):
        """Different profile IDs produce distinct, non-overlapping directories."""
        pdm = ProfileDirectoryManager(home_dir=str(tmp_path))
        dir_a = pdm.profile_dir("alpha")
        dir_b = pdm.profile_dir("beta")
        assert dir_a != dir_b
        assert dir_a.is_dir()
        assert dir_b.is_dir()
        # Write a sentinel file in each and confirm no cross-contamination
        (dir_a / "sentinel.txt").write_text("alpha")
        assert not (dir_b / "sentinel.txt").exists()
