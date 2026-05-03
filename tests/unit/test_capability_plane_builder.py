import pytest
from hi_agent.config.capability_plane_builder import CapabilityPlaneBuilder
from hi_agent.config.trace_config import TraceConfig


@pytest.fixture(autouse=True)
def _dev_posture(monkeypatch):
    """W33-E.1: Posture.resolve_runtime_mode() defaults to 'prod' (fail-closed)
    when neither HI_AGENT_POSTURE nor HI_AGENT_ENV is set. This unit test
    builds the capability registry without LLM credentials, which only
    succeeds under dev posture (heuristic fallback). Pin dev explicitly.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    yield


@pytest.fixture
def builder(tmp_path):
    cfg = TraceConfig()
    cfg.episodic_storage_dir = str(tmp_path / "episodes")
    return CapabilityPlaneBuilder(cfg, llm_gateway=None)


def test_capability_registry(builder):
    assert builder.build_capability_registry() is not None


def test_capability_registry_singleton(builder):
    assert builder.build_capability_registry() is builder.build_capability_registry()


def test_artifact_registry(builder):
    assert builder.build_artifact_registry() is not None


def test_harness(builder):
    assert builder.build_harness() is not None


def test_no_llm_gateway_call():
    import inspect

    import hi_agent.config.capability_plane_builder as m

    src = inspect.getsource(m)
    assert "build_llm_gateway" not in src, "Must not call build_llm_gateway internally"


def test_system_builder_delegates(tmp_path):
    from hi_agent.config.builder import SystemBuilder

    cfg = TraceConfig()
    cfg.episodic_storage_dir = str(tmp_path / "episodes")
    assert SystemBuilder(cfg).build_capability_registry() is not None
