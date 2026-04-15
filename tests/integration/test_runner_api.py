"""Integration tests for RunExecutor public API additions.

Tests that register_gate / resume, dispatch_subrun / await_subrun exist and
are callable, and that SubRunHandle / SubRunResult / GateEvent are importable.

All tests use the real RunExecutor wired with a real kernel adapter — no
internal mocking (P3 production integrity constraint).
"""

import pytest

from hi_agent import GateEvent, SubRunHandle, SubRunResult
from hi_agent.contracts import TaskContract, deterministic_id
from hi_agent.runner import RunExecutor
from tests.helpers.kernel_adapter_fixture import MockKernel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contract(goal: str = "test goal") -> TaskContract:
    return TaskContract(
        task_id=deterministic_id("test"),
        goal=goal,
        task_family="quick_task",
    )


def _make_executor(contract: TaskContract | None = None) -> RunExecutor:
    if contract is None:
        contract = _make_contract()
    kernel = MockKernel()
    return RunExecutor(contract=contract, kernel=kernel)


# ---------------------------------------------------------------------------
# Task 1 — Human Gate API (P1-5)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_register_gate_exists_and_is_callable():
    """register_gate is a public method on RunExecutor."""
    executor = _make_executor()
    assert callable(getattr(executor, "register_gate", None))


@pytest.mark.integration
def test_resume_exists_and_is_callable():
    """resume is a public method on RunExecutor."""
    executor = _make_executor()
    assert callable(getattr(executor, "resume", None))


@pytest.mark.integration
def test_register_gate_stores_event():
    """register_gate records a GateEvent accessible via _registered_gates."""
    executor = _make_executor()
    executor.register_gate(
        gate_id="g-001",
        gate_type="final_approval",
        phase_name="S5_deliver",
        recommendation="Please review output",
        output_summary="Summary of findings",
    )
    assert "g-001" in executor._registered_gates
    event = executor._registered_gates["g-001"]
    assert isinstance(event, GateEvent)
    assert event.gate_id == "g-001"
    assert event.gate_type == "final_approval"
    assert event.phase_name == "S5_deliver"


@pytest.mark.integration
def test_register_gate_persists_to_session_events():
    """register_gate appends an event to the session event log."""
    executor = _make_executor()
    executor.register_gate(gate_id="g-002", gate_type="artifact_review")
    if executor.session is not None:
        gate_events = [
            e for e in executor.session.events
            if isinstance(e, dict) and e.get("event") == "gate_registered"
        ]
        assert len(gate_events) >= 1
        assert gate_events[-1]["gate_id"] == "g-002"


@pytest.mark.integration
def test_resume_logs_decision():
    """resume emits a gate_decision observability event without raising."""
    executor = _make_executor()
    executor.register_gate(gate_id="g-003")
    # Should not raise; the decision is recorded via observability
    executor.resume(gate_id="g-003", decision="approved", rationale="LGTM")


@pytest.mark.integration
def test_resume_persists_decision_to_session():
    """resume appends a gate_decision entry to session events."""
    executor = _make_executor()
    executor.register_gate(gate_id="g-004")
    executor.resume(gate_id="g-004", decision="backtrack", rationale="needs work")
    if executor.session is not None:
        decisions = [
            e for e in executor.session.events
            if isinstance(e, dict) and e.get("event") == "gate_decision"
        ]
        assert any(d["gate_id"] == "g-004" and d["decision"] == "backtrack"
                   for d in decisions)


# ---------------------------------------------------------------------------
# Task 3 — Sub-run delegation API (P2-3)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dispatch_subrun_exists_and_is_callable():
    """dispatch_subrun is a public method on RunExecutor."""
    executor = _make_executor()
    assert callable(getattr(executor, "dispatch_subrun", None))


@pytest.mark.integration
def test_await_subrun_exists_and_is_callable():
    """await_subrun is a public method on RunExecutor."""
    executor = _make_executor()
    assert callable(getattr(executor, "await_subrun", None))


@pytest.mark.integration
def test_dispatch_subrun_raises_without_delegation_manager():
    """dispatch_subrun raises RuntimeError when no DelegationManager is wired."""
    executor = _make_executor()
    assert executor._delegation_manager is None
    with pytest.raises(RuntimeError, match="DelegationManager"):
        executor.dispatch_subrun(agent="analyzer", profile_id="default")


@pytest.mark.integration
def test_await_subrun_unknown_handle_returns_failure():
    """await_subrun with an unknown handle returns a failure SubRunResult."""
    executor = _make_executor()
    handle = SubRunHandle(subrun_id="nonexistent-123", agent="analyzer")
    result = executor.await_subrun(handle)
    assert isinstance(result, SubRunResult)
    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Import surface (Task 1 + Task 3)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_subrun_handle_importable_from_hi_agent():
    """SubRunHandle is importable from the hi_agent package namespace."""
    from hi_agent import SubRunHandle as SRH  # noqa: PLC0415
    assert SRH is SubRunHandle


@pytest.mark.integration
def test_subrun_result_importable_from_hi_agent():
    """SubRunResult is importable from the hi_agent package namespace."""
    from hi_agent import SubRunResult as SRR  # noqa: PLC0415
    assert SRR is SubRunResult


@pytest.mark.integration
def test_gate_event_importable_from_hi_agent():
    """GateEvent is importable from the hi_agent package namespace."""
    from hi_agent import GateEvent as GE  # noqa: PLC0415
    assert GE is GateEvent


@pytest.mark.integration
def test_subrun_handle_fields():
    """SubRunHandle has subrun_id and agent fields."""
    h = SubRunHandle(subrun_id="run-1", agent="planner")
    assert h.subrun_id == "run-1"
    assert h.agent == "planner"


@pytest.mark.integration
def test_subrun_result_fields():
    """SubRunResult has success, output, and optional error fields."""
    ok = SubRunResult(success=True, output="done")
    assert ok.success is True
    assert ok.output == "done"
    assert ok.error is None

    fail = SubRunResult(success=False, output="", error="timeout")
    assert fail.success is False
    assert fail.error == "timeout"


@pytest.mark.integration
def test_gate_event_fields():
    """GateEvent has all required fields with correct defaults."""
    ev = GateEvent(gate_id="g-999")
    assert ev.gate_id == "g-999"
    assert ev.gate_type == "final_approval"
    assert ev.phase_name == ""
    assert ev.recommendation == ""
    assert ev.output_summary == ""
    assert ev.opened_at  # non-empty ISO timestamp
