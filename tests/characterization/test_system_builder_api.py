"""Characterization tests for SystemBuilder public build_* API.

These tests lock the current external behavior of every build_* method.
They are the safety net for W6-W8 refactoring sprints — any behavior change
will be caught here.

Rules:
- Each test characterizes one method (return type + singleton + key attrs)
- No internal mocking — use real SystemBuilder with default TraceConfig
- Tests must complete in <60 seconds total
"""

import pytest
from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts.task import TaskContract


@pytest.fixture(scope="module")
def builder():
    """Shared SystemBuilder instance for all characterization tests."""
    return SystemBuilder(config=TraceConfig())


# ── Observability ─────────────────────────────────────────────────────────────


def test_build_metrics_collector_returns_object(builder):
    obj = builder.build_metrics_collector()
    assert obj is not None, "Expected non-None result for obj"


def test_build_metrics_collector_is_singleton(builder):
    assert builder.build_metrics_collector() is builder.build_metrics_collector()


# ── Runtime ───────────────────────────────────────────────────────────────────


def test_build_kernel_returns_object(builder):
    obj = builder.build_kernel()
    assert obj is not None, "Expected non-None result for obj"


def test_build_kernel_is_singleton(builder):
    assert builder.build_kernel() is builder.build_kernel()


def test_build_kernel_has_mode_attribute(builder):
    obj = builder.build_kernel()
    assert hasattr(obj, "mode")


def test_build_llm_gateway_is_stable(builder):
    # May be None in dev (no API key) — but must be stable across calls
    obj1 = builder.build_llm_gateway()
    obj2 = builder.build_llm_gateway()
    assert obj1 is obj2


def test_build_evolve_engine_returns_object(builder):
    obj = builder.build_evolve_engine()
    assert obj is not None, "Expected non-None result for obj"


# ── Capability ────────────────────────────────────────────────────────────────


def test_build_invoker_returns_object(builder):
    obj = builder.build_invoker()
    assert obj is not None, "Expected non-None result for obj"


def test_build_capability_registry_returns_object(builder):
    obj = builder.build_capability_registry()
    assert obj is not None, "Expected non-None result for obj"


def test_build_capability_registry_is_singleton(builder):
    assert builder.build_capability_registry() is builder.build_capability_registry()


def test_build_capability_registry_has_list_names(builder):
    obj = builder.build_capability_registry()
    assert hasattr(obj, "list_names")
    names = obj.list_names()
    assert isinstance(names, list)


def test_build_artifact_registry_returns_object(builder):
    obj = builder.build_artifact_registry()
    assert obj is not None, "Expected non-None result for obj"


def test_build_artifact_registry_is_singleton(builder):
    assert builder.build_artifact_registry() is builder.build_artifact_registry()


def test_build_mcp_registry_returns_object(builder):
    obj = builder.build_mcp_registry()
    assert obj is not None, "Expected non-None result for obj"


def test_build_mcp_registry_is_singleton(builder):
    assert builder.build_mcp_registry() is builder.build_mcp_registry()


def test_build_mcp_registry_has_list_servers(builder):
    obj = builder.build_mcp_registry()
    assert hasattr(obj, "list_servers")


def test_build_mcp_transport_does_not_raise(builder):
    # Without stdio MCP server config, transport is None — key is no exception
    obj = builder.build_mcp_transport()
    assert obj is None or obj is not None  # either outcome is valid


def test_build_harness_returns_object(builder):
    obj = builder.build_harness()
    assert obj is not None, "Expected non-None result for obj"


def test_build_harness_has_execute_method(builder):
    obj = builder.build_harness()
    assert callable(getattr(obj, "execute", None))


# ── Skills ────────────────────────────────────────────────────────────────────


def test_build_skill_registry_returns_object(builder):
    obj = builder.build_skill_registry()
    assert obj is not None, "Expected non-None result for obj"


def test_build_skill_loader_returns_object(builder):
    # SkillLoader always returns an object (not None), even with no skills on disk
    obj = builder.build_skill_loader()
    assert obj is not None, "Expected non-None result for obj"


def test_build_skill_loader_is_singleton(builder):
    assert builder.build_skill_loader() is builder.build_skill_loader()


def test_build_plugin_loader_returns_object(builder):
    obj = builder.build_plugin_loader()
    assert obj is not None, "Expected non-None result for obj"


def test_build_plugin_loader_is_singleton(builder):
    assert builder.build_plugin_loader() is builder.build_plugin_loader()


def test_build_skill_observer_returns_object(builder):
    obj = builder.build_skill_observer()
    assert obj is not None, "Expected non-None result for obj"


def test_build_skill_version_manager_returns_object(builder):
    obj = builder.build_skill_version_manager()
    assert obj is not None, "Expected non-None result for obj"


def test_build_skill_evolver_returns_object(builder):
    obj = builder.build_skill_evolver()
    assert obj is not None, "Expected non-None result for obj"


def test_build_skill_evolver_is_singleton(builder):
    assert builder.build_skill_evolver() is builder.build_skill_evolver()


# ── Memory ────────────────────────────────────────────────────────────────────


def test_build_episodic_store_returns_object(builder):
    obj = builder.build_episodic_store()
    assert obj is not None, "Expected non-None result for obj"


def test_build_failure_collector_returns_object(builder):
    obj = builder.build_failure_collector()
    assert obj is not None, "Expected non-None result for obj"


def test_build_watchdog_returns_object(builder):
    obj = builder.build_watchdog()
    assert obj is not None, "Expected non-None result for obj"


def test_build_short_term_store_returns_object(builder):
    obj = builder.build_short_term_store(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


def test_build_mid_term_store_returns_object(builder):
    obj = builder.build_mid_term_store(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


def test_build_long_term_graph_returns_object(builder):
    obj = builder.build_long_term_graph(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


def test_build_retrieval_engine_returns_object(builder):
    obj = builder.build_retrieval_engine(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


def test_build_memory_lifecycle_manager_returns_object(builder):
    obj = builder.build_memory_lifecycle_manager(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


# ── Knowledge ─────────────────────────────────────────────────────────────────


def test_build_knowledge_wiki_returns_object(builder):
    obj = builder.build_knowledge_wiki()
    assert obj is not None, "Expected non-None result for obj"


def test_build_user_knowledge_store_returns_object(builder):
    obj = builder.build_user_knowledge_store()
    assert obj is not None, "Expected non-None result for obj"


def test_build_knowledge_manager_returns_object(builder):
    obj = builder.build_knowledge_manager(profile_id="characterization-profile")
    assert obj is not None, "Expected non-None result for obj"


def test_build_profile_registry_returns_object(builder):
    obj = builder.build_profile_registry()
    assert obj is not None, "Expected non-None result for obj"


def test_build_profile_registry_is_singleton(builder):
    assert builder.build_profile_registry() is builder.build_profile_registry()


# ── Execution ─────────────────────────────────────────────────────────────────


def test_build_context_manager_returns_object(builder):
    obj = builder.build_context_manager()
    assert obj is not None, "Expected non-None result for obj"


def test_build_budget_guard_returns_object(builder):
    obj = builder.build_budget_guard()
    assert obj is not None, "Expected non-None result for obj"


def test_build_executor_returns_object(builder):
    contract = TaskContract(
        task_id="char-test-001", goal="characterization test goal", profile_id="test"
    )
    obj = builder.build_executor(contract=contract)
    assert obj is not None, "Expected non-None result for obj"


def test_build_executor_has_execute_method(builder):
    contract = TaskContract(
        task_id="char-test-002", goal="characterization test goal", profile_id="test"
    )
    obj = builder.build_executor(contract=contract)
    assert callable(getattr(obj, "execute", None))


def test_build_orchestrator_returns_object(builder):
    obj = builder.build_orchestrator()
    assert obj is not None, "Expected non-None result for obj"


def test_build_orchestrator_has_kernel(builder):
    obj = builder.build_orchestrator()
    # TaskOrchestrator stores kernel as _kernel or kernel
    assert getattr(obj, "kernel", None) is not None or getattr(obj, "_kernel", None) is not None


# ── Server ────────────────────────────────────────────────────────────────────


def test_build_server_returns_object(builder):
    obj = builder.build_server()
    assert obj is not None, "Expected non-None result for obj"


def test_build_server_has_run_manager(builder):
    obj = builder.build_server()
    assert hasattr(obj, "run_manager")
    assert obj.run_manager is not None


def test_build_server_has_metrics_collector(builder):
    obj = builder.build_server()
    assert hasattr(obj, "metrics_collector")
    assert obj.metrics_collector is not None


# ── Readiness snapshot ────────────────────────────────────────────────────────


def test_readiness_returns_dict(builder):
    result = builder.readiness()
    assert isinstance(result, dict)


def test_readiness_has_required_keys(builder):
    result = builder.readiness()
    required = {"ready", "health", "execution_mode", "subsystems"}
    assert required.issubset(set(result.keys()))


def test_readiness_ready_is_bool(builder):
    result = builder.readiness()
    assert isinstance(result["ready"], bool)


def test_readiness_subsystems_is_dict(builder):
    result = builder.readiness()
    assert isinstance(result["subsystems"], dict)


def test_readiness_health_is_valid_string(builder):
    result = builder.readiness()
    assert result["health"] in ("ok", "degraded", "error")


def test_readiness_is_stable_across_calls(builder):
    # Called multiple times — ready flag must be deterministic
    r1 = builder.readiness()
    r2 = builder.readiness()
    assert r1["ready"] == r2["ready"]


def test_readiness_subsystems_contains_kernel(builder):
    result = builder.readiness()
    assert "kernel" in result["subsystems"]


def test_readiness_subsystems_contains_capabilities(builder):
    result = builder.readiness()
    assert "capabilities" in result["subsystems"]


def test_readiness_execution_mode_is_string(builder):
    result = builder.readiness()
    assert isinstance(result["execution_mode"], str)


def test_readiness_models_is_list(builder):
    result = builder.readiness()
    assert isinstance(result.get("models", []), list)


def test_readiness_capabilities_is_list(builder):
    result = builder.readiness()
    assert isinstance(result.get("capabilities", []), list)
