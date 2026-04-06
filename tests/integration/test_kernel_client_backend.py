"""Integration tests for kernel client + backend retry behavior."""

import pytest
from hi_agent.runtime_adapter.kernel_backend import KernelBackend
from hi_agent.runtime_adapter.kernel_client import SimpleKernelClient


def test_backend_retries_once_then_succeeds() -> None:
    """Backend should retry after one transport failure and then return success."""
    calls = {"count": 0}

    def flaky_transport(operation: str, payload: dict[str, object]) -> str:
        calls["count"] += 1
        assert operation == "open_stage"
        assert payload == {"stage_id": "S1_understand"}
        if calls["count"] == 1:
            raise ConnectionError("temporary")
        return "ok"

    backend = KernelBackend(
        client=SimpleKernelClient(flaky_transport),
        max_retries=1,
    )

    result = backend.open_stage("S1_understand")

    assert result == "ok"
    assert calls["count"] == 2


def test_backend_raises_runtime_error_after_exhausted_retries() -> None:
    """Backend should raise RuntimeError with preserved cause after all retries fail."""
    calls = {"count": 0}

    def failing_transport(operation: str, payload: dict[str, object]) -> None:
        _ = operation
        _ = payload
        calls["count"] += 1
        raise ValueError("persistent")

    backend = KernelBackend(
        client=SimpleKernelClient(failing_transport),
        max_retries=2,
    )

    with pytest.raises(RuntimeError) as exc_info:
        backend.open_stage("S1_understand")

    assert "failed after 3 attempt(s)" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert isinstance(exc_info.value.__cause__.__cause__, ValueError)
    assert calls["count"] == 3


def test_backend_zero_retry_only_attempts_once() -> None:
    """`max_retries=0` should execute a single attempt then fail."""
    calls = {"count": 0}

    def failing_transport(operation: str, payload: dict[str, object]) -> None:
        _ = operation
        _ = payload
        calls["count"] += 1
        raise RuntimeError("first-fail")

    backend = KernelBackend(
        client=SimpleKernelClient(failing_transport),
        max_retries=0,
    )

    with pytest.raises(RuntimeError) as exc_info:
        backend.open_stage("S1_understand")

    assert "failed after 1 attempt(s)" in str(exc_info.value)
    assert calls["count"] == 1
