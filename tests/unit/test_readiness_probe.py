"""Unit tests for ReadinessProbe — extracted from SystemBuilder.readiness()."""
import pytest
from hi_agent.config.builder import SystemBuilder
from hi_agent.config.readiness import ReadinessProbe
from hi_agent.config.trace_config import TraceConfig


@pytest.fixture(scope="module")
def builder():
    return SystemBuilder(config=TraceConfig())


def test_readiness_probe_snapshot_returns_dict(builder):
    probe = ReadinessProbe(builder)
    result = probe.snapshot()
    assert isinstance(result, dict)


def test_readiness_probe_snapshot_has_required_keys(builder):
    probe = ReadinessProbe(builder)
    result = probe.snapshot()
    assert {"ready", "health", "execution_mode", "subsystems"}.issubset(set(result.keys()))


def test_readiness_probe_ready_is_bool(builder):
    probe = ReadinessProbe(builder)
    assert isinstance(probe.snapshot()["ready"], bool)


def test_readiness_probe_matches_builder_readiness(builder):
    """ReadinessProbe.snapshot() and builder.readiness() return same shape."""
    probe_result = ReadinessProbe(builder).snapshot()
    builder_result = builder.readiness()
    assert set(probe_result.keys()) == set(builder_result.keys())
    assert probe_result["ready"] == builder_result["ready"]
    assert probe_result["health"] == builder_result["health"]


def test_readiness_probe_does_not_mutate_builder(builder):
    """Calling snapshot() multiple times is idempotent."""
    r1 = ReadinessProbe(builder).snapshot()
    r2 = ReadinessProbe(builder).snapshot()
    assert r1["ready"] == r2["ready"]
    assert r1["health"] == r2["health"]
