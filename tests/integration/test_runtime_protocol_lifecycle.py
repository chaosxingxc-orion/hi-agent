"""Protocol-level checks for runtime lifecycle surface."""

import pytest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter
from hi_agent.runtime_adapter.protocol import RuntimeAdapter, RuntimeAdapterBackend


def test_runtime_adapter_protocol_includes_run_lifecycle_methods() -> None:
    """RuntimeAdapter should expose minimal run lifecycle hooks."""
    assert hasattr(RuntimeAdapter, "start_run")
    assert hasattr(RuntimeAdapter, "query_run")
    assert hasattr(RuntimeAdapter, "cancel_run")
    assert hasattr(RuntimeAdapter, "signal_run")
    assert hasattr(RuntimeAdapter, "query_trace_runtime")
    assert hasattr(RuntimeAdapter, "bind_task_view_to_decision")
    assert hasattr(RuntimeAdapter, "open_branch")
    assert hasattr(RuntimeAdapter, "mark_branch_state")
    assert hasattr(RuntimeAdapter, "resume_run")
    assert hasattr(RuntimeAdapter, "get_manifest")
    assert hasattr(RuntimeAdapter, "submit_plan")


def test_runtime_adapter_backend_protocol_includes_optional_run_lifecycle_hooks() -> None:
    """Backend protocol should include lifecycle hook slots."""
    backend_annotations = getattr(RuntimeAdapterBackend, "__annotations__", {})
    assert "start_run" in backend_annotations
    assert "query_run" in backend_annotations
    assert "cancel_run" in backend_annotations
    assert "signal_run" in backend_annotations
    assert "query_trace_runtime" in backend_annotations
    assert "bind_task_view_to_decision" in backend_annotations
    assert "open_branch" in backend_annotations
    assert "mark_branch_state" in backend_annotations
    assert "resume_run" in backend_annotations
    assert "get_manifest" in backend_annotations
    assert "submit_plan" in backend_annotations


def test_kernel_adapter_strict_mode_raises_on_missing_backend_hook() -> None:
    """Strict mode should surface missing backend hooks as explicit adapter errors."""

    class IncompleteBackend:
        """Backend intentionally missing most runtime lifecycle methods."""

        def open_stage(self, _stage_id: str) -> None:
            return None

        def start_run(self, task_id: str) -> str:
            return f"backend-{task_id}"

    adapter = KernelAdapter(strict_mode=True, backend=IncompleteBackend())
    run_id = adapter.start_run("task-kernel-strict")

    with pytest.raises(RuntimeAdapterBackendError):
        adapter.signal_run(run_id, "human_gate", {"gate_ref": "g-1"})
