"""Integration tests for KernelAdapter backend delegation behavior."""

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.errors import (
    IllegalStateTransitionError,
    RuntimeAdapterBackendError,
)
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter


class _BackendSpy:
    """Backend spy that captures delegation calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(f"open:{stage_id}")

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        self.calls.append(f"mark:{stage_id}:{target}")

    def record_task_view(self, task_view_id: str, content: dict[str, object]) -> str:
        _ = content
        self.calls.append(f"tv:{task_view_id}")
        return task_view_id


class _FailingOpenBackend:
    """Backend that fails during open stage."""

    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"boom:{stage_id}")


def test_kernel_adapter_backend_success_path() -> None:
    """KernelAdapter should delegate supported hooks to backend."""
    backend = _BackendSpy()
    adapter = KernelAdapter(strict_mode=True, backend=backend)

    adapter.open_stage("S1_understand")
    adapter.mark_stage_state("S1_understand", StageState.ACTIVE)
    adapter.record_task_view("tv-1", {"x": 1})

    assert backend.calls == [
        "open:S1_understand",
        "mark:S1_understand:active",
        "tv:tv-1",
    ]


def test_kernel_adapter_wraps_backend_exception() -> None:
    """Backend exceptions should be normalized as runtime adapter errors."""
    adapter = KernelAdapter(strict_mode=True, backend=_FailingOpenBackend())

    with pytest.raises(RuntimeAdapterBackendError) as exc_info:
        adapter.open_stage("S1_understand")

    assert exc_info.value.operation == "open_stage"
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert adapter.stages["S1_understand"] == StageState.PENDING
    assert adapter.get_events_of_type("StageOpened")


def test_kernel_adapter_strict_mode_illegal_transition_still_rejected() -> None:
    """Illegal transition in strict mode should fail before backend write call."""
    backend = _BackendSpy()
    adapter = KernelAdapter(strict_mode=True, backend=backend)

    adapter.open_stage("S1_understand")

    with pytest.raises(IllegalStateTransitionError):
        adapter.mark_stage_state("S1_understand", StageState.COMPLETED)

    assert backend.calls == ["open:S1_understand"]
