"""Unit tests for SkillBuilder — extracted from SystemBuilder in W6-003."""

import pytest
from hi_agent.config.skill_builder import SkillBuilder
from hi_agent.config.trace_config import TraceConfig


@pytest.fixture(scope="module")
def skill_builder():
    return SkillBuilder(config=TraceConfig())


def test_build_skill_registry_returns_object(skill_builder):
    obj = skill_builder.build_skill_registry()
    assert obj is not None


def test_build_skill_loader_is_singleton(skill_builder):
    assert skill_builder.build_skill_loader() is skill_builder.build_skill_loader()


def test_build_skill_observer_returns_object(skill_builder):
    assert skill_builder.build_skill_observer() is not None


def test_build_skill_version_manager_returns_object(skill_builder):
    assert skill_builder.build_skill_version_manager() is not None


def test_build_skill_evolver_is_singleton(skill_builder):
    e1 = skill_builder.build_skill_evolver()
    e2 = skill_builder.build_skill_evolver()
    assert e1 is e2


def test_skill_builder_does_not_require_builder_ref():
    """SkillBuilder takes only TraceConfig — no SystemBuilder dependency."""
    import inspect

    sig = inspect.signature(SkillBuilder.__init__)
    params = list(sig.parameters.keys())
    assert "builder" not in params
    assert "config" in params
