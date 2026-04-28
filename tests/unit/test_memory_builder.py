"""Unit tests for MemoryBuilder — extracted from SystemBuilder in W6-004."""

import inspect

import pytest
from hi_agent.config.memory_builder import MemoryBuilder
from hi_agent.config.trace_config import TraceConfig


@pytest.fixture(scope="module")
def mb():
    return MemoryBuilder(config=TraceConfig())


def test_build_episodic_store_returns_object(mb):
    assert mb.build_episodic_store() is not None


def test_build_failure_collector_returns_object(mb):
    assert mb.build_failure_collector() is not None


def test_build_watchdog_returns_object(mb):
    assert mb.build_watchdog() is not None


def test_build_short_term_store_returns_object(mb):
    assert mb.build_short_term_store(profile_id="unit-test-profile") is not None


def test_build_mid_term_store_returns_object(mb):
    assert mb.build_mid_term_store(profile_id="unit-test-profile") is not None


def test_build_long_term_graph_returns_object(mb):
    assert mb.build_long_term_graph(profile_id="unit-test-profile") is not None


def test_build_retrieval_engine_returns_object(mb):
    obj = mb.build_retrieval_engine(profile_id="unit-test-profile")
    assert obj is not None, f"Expected non-None result for obj"


def test_build_memory_lifecycle_manager_returns_object(mb):
    obj = mb.build_memory_lifecycle_manager(profile_id="unit-test-profile")
    assert obj is not None, f"Expected non-None result for obj"


def test_memory_builder_profile_id_param(mb):
    """Different profile_id values produce distinct store instances (S3 registry)."""
    s1 = mb.build_short_term_store(profile_id="profile-one")
    s2 = mb.build_short_term_store(profile_id="profile-two")
    # Different profile_id → different cache entries
    assert s1 is not s2


def test_build_short_term_store_rejects_empty_profile_id(mb):
    """Rule 13 (DF-12): empty profile_id with no workspace_key must raise."""
    with pytest.raises(ValueError, match="profile_id"):
        mb.build_short_term_store(profile_id="")


def test_build_mid_term_store_rejects_empty_profile_id(mb):
    """Rule 13 (DF-12): empty profile_id with no workspace_key must raise."""
    with pytest.raises(ValueError, match="profile_id"):
        mb.build_mid_term_store(profile_id="")


def test_build_long_term_graph_rejects_empty_profile_id(mb):
    """Rule 13 (DF-12): empty profile_id with no workspace_key must raise."""
    with pytest.raises(ValueError, match="profile_id"):
        mb.build_long_term_graph(profile_id="")


def test_memory_builder_does_not_require_builder_ref():
    sig = inspect.signature(MemoryBuilder.__init__)
    params = list(sig.parameters.keys())
    assert "builder" not in params
    assert "config" in params
