"""Integration test for production-style KernelAdapter."""

import pytest
from hi_agent.contracts import StageState, TaskContract
from hi_agent.runner import STAGES, RunExecutor
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter


def test_run_executor_works_with_kernel_adapter() -> None:
    """Runner should execute full lifecycle with KernelAdapter."""
    adapter = KernelAdapter(strict_mode=True)
    executor = RunExecutor(TaskContract(task_id="int-004", goal="kernel adapter"), adapter)

    result = executor.execute()

    assert result == "completed"
    for stage_id in STAGES:
        adapter.assert_stage_state(stage_id, StageState.COMPLETED)


def test_kernel_adapter_rejects_illegal_transition_in_strict_mode() -> None:
    """KernelAdapter should enforce transition legality in strict mode."""
    adapter = KernelAdapter(strict_mode=True)
    adapter.open_stage("S1_understand")

    with pytest.raises(IllegalStateTransitionError):
        adapter.mark_stage_state("S1_understand", StageState.COMPLETED)


def test_kernel_adapter_delegates_to_backend_when_provided() -> None:
    """Adapter should forward runtime events to compatible backend."""

    class FakeBackend:
        """Simple backend spy for delegation verification."""

        def __init__(self) -> None:
            self.calls: list[str] = []

        def open_stage(self, stage_id: str) -> None:
            self.calls.append(f"open:{stage_id}")

        def mark_stage_state(self, stage_id: str, target: StageState) -> None:
            self.calls.append(f"mark:{stage_id}:{target}")

        def record_task_view(self, task_view_id: str, content: dict) -> None:
            _ = content
            self.calls.append(f"tv:{task_view_id}")

    backend = FakeBackend()
    adapter = KernelAdapter(strict_mode=True, backend=backend)
    adapter.open_stage("S1_understand")
    adapter.mark_stage_state("S1_understand", StageState.ACTIVE)
    adapter.record_task_view("tv-1", {"x": 1})

    assert backend.calls == [
        "open:S1_understand",
        "mark:S1_understand:active",
        "tv:tv-1",
    ]
