"""Runtime adapter regressions surfaced by the Rule 15 gate."""

from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter
from hi_agent.runtime_adapter.resilient_kernel_adapter import ResilientKernelAdapter


def test_kernel_facade_adapter_keeps_unknown_branch_failure_as_reason() -> None:
    """Unknown hi-agent failure codes must not be passed as kernel enum values."""
    adapter = KernelFacadeAdapter.__new__(KernelFacadeAdapter)
    captured: dict[str, object] = {}

    def fake_call(method_name: str, request: object) -> None:
        captured["method_name"] = method_name
        captured["request"] = request

    adapter._call = fake_call  # type: ignore[method-assign]  expiry_wave: Wave 17

    adapter.mark_branch_state("run-1", "stage-1", "branch-1", "failed", "acceptance_rejected")

    request = captured["request"]
    assert captured["method_name"] == "mark_branch_state"
    assert request.failure_code is None
    assert request.reason == "acceptance_rejected"


def test_resilient_adapter_wraps_exhausted_failures_with_backend_error() -> None:
    """The resilience wrapper must raise RuntimeAdapterBackendError with a cause."""

    class FailingInner:
        def mark_branch_state(self, *args, **kwargs):
            raise ValueError("backend exploded")

    adapter = ResilientKernelAdapter(
        FailingInner(), max_retries=0, journal=InMemoryConsistencyJournal()
    )

    with pytest.raises(RuntimeAdapterBackendError) as exc_info:
        adapter.mark_branch_state("run-1", "stage-1", "branch-1", "failed")

    assert exc_info.value.operation == "mark_branch_state"
    assert isinstance(exc_info.value.__cause__, ValueError)
