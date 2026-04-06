"""Unit tests for KernelAdapter extended lifecycle delegation."""

from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter


def test_kernel_adapter_extended_lifecycle_strict_missing_hook_raises() -> None:
    """Strict mode should fail loudly when backend misses extended hooks."""

    class PartialBackend:
        """Backend intentionally omits `signal_run` and other new hooks."""

        def start_run(self, task_id: str) -> str:
            return f"run-{task_id}"

    adapter = KernelAdapter(strict_mode=True, backend=PartialBackend())
    run_id = adapter.start_run("abc")

    with pytest.raises(RuntimeAdapterBackendError):
        adapter.signal_run(run_id, "human_gate", {"gate_ref": "g-1"})


def test_kernel_adapter_extended_lifecycle_non_strict_tolerates_missing_hook() -> None:
    """Non-strict mode should keep local state when backend hook is missing."""

    class PartialBackend:
        """Backend intentionally omits `submit_plan` hook."""

        def start_run(self, task_id: str) -> str:
            return f"run-{task_id}"

    adapter = KernelAdapter(strict_mode=False, backend=PartialBackend())
    run_id = adapter.start_run("xyz")
    adapter.submit_plan(run_id, {"steps": ["S1_understand"]})
    snapshot = adapter.query_run(run_id)
    assert snapshot["plan"] == {"steps": ["S1_understand"]}

