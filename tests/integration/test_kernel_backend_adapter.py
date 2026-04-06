"""Integration tests for KernelBackend + KernelAdapter behavior."""

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_adapter import KernelAdapter
from hi_agent.runtime_adapter.kernel_backend import KernelBackend


class _ClientSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def open_stage(self, payload: dict[str, object]) -> None:
        self.calls.append(("open_stage", payload))

    def mark_stage_state(self, payload: dict[str, object]) -> None:
        self.calls.append(("mark_stage_state", payload))

    def record_task_view(self, payload: dict[str, object]) -> str:
        self.calls.append(("record_task_view", payload))
        return str(payload["task_view_id"])


class _ClientOpenFails:
    def open_stage(self, payload: dict[str, object]) -> None:
        raise ValueError(f"boom:{payload['stage_id']}")


def test_kernel_backend_forwards_normalized_payloads_via_adapter() -> None:
    """Adapter + backend should forward normalized dict payloads to the client."""
    client = _ClientSpy()
    backend = KernelBackend(client=client)
    adapter = KernelAdapter(strict_mode=True, backend=backend)

    adapter.open_stage("S1_understand")
    adapter.mark_stage_state("S1_understand", StageState.ACTIVE)
    adapter.record_task_view("tv-1", {"x": 1})

    assert client.calls == [
        ("open_stage", {"stage_id": "S1_understand"}),
        (
            "mark_stage_state",
            {"stage_id": "S1_understand", "target": "active"},
        ),
        ("record_task_view", {"task_view_id": "tv-1", "content": {"x": 1}}),
    ]


def test_kernel_backend_client_exception_is_wrapped_by_adapter() -> None:
    """Adapter should wrap client exceptions surfaced by KernelBackend."""
    backend = KernelBackend(client=_ClientOpenFails())
    adapter = KernelAdapter(strict_mode=True, backend=backend)

    with pytest.raises(RuntimeAdapterBackendError) as exc_info:
        adapter.open_stage("S1_understand")

    assert exc_info.value.operation == "open_stage"
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_kernel_backend_missing_client_raises_clear_error() -> None:
    """Missing client should raise clear RuntimeError wrapped by adapter."""
    adapter = KernelAdapter(strict_mode=True, backend=KernelBackend())

    with pytest.raises(RuntimeAdapterBackendError) as exc_info:
        adapter.open_stage("S1_understand")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "client is not configured" in str(exc_info.value.__cause__)
