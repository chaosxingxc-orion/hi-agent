"""Integration tests: ExecutionProvenance is populated on RunResult — HI-W1-D3-001.

Uses real RunExecutor + MockKernel (no internal component mocking).
"""
from hi_agent.contracts import TaskContract
from hi_agent.contracts.execution_provenance import CONTRACT_VERSION, ExecutionProvenance
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_executor(task_id: str, goal: str = "test provenance") -> RunExecutor:
    contract = TaskContract(task_id=task_id, goal=goal)
    kernel = MockKernel(strict_mode=True)
    return RunExecutor(contract, kernel)


def test_provenance_present_on_completed_run() -> None:
    """RunResult.execution_provenance must not be None after a completed run."""
    executor = _make_executor("prov-int-001")
    result = executor.execute()

    assert result.execution_provenance is not None


def test_provenance_dict_shape_matches_contract() -> None:
    """to_dict() on execution_provenance must contain exactly the W1 required keys."""
    executor = _make_executor("prov-int-002")
    result = executor.execute()

    assert result.execution_provenance is not None
    d = result.execution_provenance.to_dict()
    expected_keys = {
        "contract_version", "runtime_mode", "llm_mode", "kernel_mode",
        "capability_mode", "mcp_transport", "fallback_used",
        "fallback_reasons", "evidence",
    }
    assert set(d.keys()) == expected_keys


def test_contract_version_stable() -> None:
    """execution_provenance.contract_version must match the module constant."""
    executor = _make_executor("prov-int-003")
    result = executor.execute()

    assert result.execution_provenance is not None
    assert result.execution_provenance.contract_version == CONTRACT_VERSION


def test_provenance_is_execution_provenance_instance() -> None:
    """execution_provenance must be an ExecutionProvenance instance."""
    executor = _make_executor("prov-int-004")
    result = executor.execute()

    assert isinstance(result.execution_provenance, ExecutionProvenance)


def test_run_result_to_dict_includes_provenance() -> None:
    """RunResult.to_dict() must include execution_provenance key."""
    executor = _make_executor("prov-int-005")
    result = executor.execute()

    d = result.to_dict()
    assert "execution_provenance" in d
    assert d["execution_provenance"] is not None
    assert isinstance(d["execution_provenance"], dict)
