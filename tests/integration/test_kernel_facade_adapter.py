"""Integration-style tests for KernelFacadeAdapter using fake facades."""

from __future__ import annotations

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter


class _FakeFacade:
    """Small fake facade implementing required methods."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(("open_stage", (stage_id,)))

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        self.calls.append(("mark_stage_state", (stage_id, target)))

    def start_run(self, task_id: str) -> str:
        self.calls.append(("start_run", (task_id,)))
        return "run-0001"

    def query_run(self, run_id: str) -> dict[str, object]:
        self.calls.append(("query_run", (run_id,)))
        return {"run_id": run_id, "status": "running"}

    def cancel_run(self, run_id: str, reason: str) -> None:
        self.calls.append(("cancel_run", (run_id, reason)))

    def get_manifest(self) -> dict[str, object]:
        self.calls.append(("get_manifest", ()))
        return {"name": "fake", "version": "1"}


def test_kernel_facade_adapter_forwards_runtime_operations() -> None:
    """Adapter should forward supported operations to facade."""
    facade = _FakeFacade()
    adapter = KernelFacadeAdapter(facade)

    run_id = adapter.start_run("task-1")
    adapter.open_stage("S1_understand")
    adapter.mark_stage_state("S1_understand", StageState.ACTIVE)
    run = adapter.query_run(run_id)
    adapter.cancel_run(run_id, "test-cancel")
    manifest = adapter.get_manifest()

    assert run_id == "run-0001"
    assert run["status"] == "running"
    assert manifest["name"] == "fake"
    assert [name for name, _ in facade.calls] == [
        "start_run",
        "open_stage",
        "mark_stage_state",
        "query_run",
        "cancel_run",
        "get_manifest",
    ]


def test_kernel_facade_adapter_raises_for_missing_methods() -> None:
    """Missing required method should raise runtime backend error."""
    adapter = KernelFacadeAdapter(object())
    with pytest.raises(RuntimeAdapterBackendError):
        adapter.get_manifest()

