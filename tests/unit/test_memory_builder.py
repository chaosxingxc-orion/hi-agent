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
    assert mb.build_short_term_store() is not None


def test_build_mid_term_store_returns_object(mb):
    assert mb.build_mid_term_store() is not None


def test_build_long_term_graph_returns_object(mb):
    assert mb.build_long_term_graph() is not None


def test_build_retrieval_engine_returns_object(mb):
    obj = mb.build_retrieval_engine()
    assert obj is not None


def test_build_memory_lifecycle_manager_returns_object(mb):
    obj = mb.build_memory_lifecycle_manager()
    assert obj is not None


def test_memory_builder_profile_id_param(mb):
    """profile_id parameter changes storage path."""
    s1 = mb.build_short_term_store(profile_id="")
    s2 = mb.build_short_term_store(profile_id="test_profile")
    # Different profile_id → different objects (no caching on profile_id)
    assert s1 is not s2


def test_memory_builder_does_not_require_builder_ref():
    sig = inspect.signature(MemoryBuilder.__init__)
    params = list(sig.parameters.keys())
    assert "builder" not in params
    assert "config" in params
