"""Integration tests for KernelBackend retry policy error classification."""

import pytest
from hi_agent.runtime_adapter.kernel_backend import KernelBackend


class _ClientOpenStageSequence:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def open_stage(self, payload: dict[str, object]) -> object:
        _ = payload
        self.calls += 1
        outcome = self._outcomes[self.calls - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_retry_success_for_retriable_exception() -> None:
    """Backend retries a retriable error and returns successful second attempt."""
    client = _ClientOpenStageSequence([TimeoutError("temporary"), "ok"])
    backend = KernelBackend(client=client, max_retries=1)

    result = backend.open_stage("S1_understand")

    assert result == "ok"
    assert client.calls == 2


def test_retry_exhausted_for_retriable_exception() -> None:
    """Backend re-raises retriable error after attempts are exhausted."""
    client = _ClientOpenStageSequence(
        [ConnectionError("attempt-1"), ConnectionError("attempt-2")]
    )
    backend = KernelBackend(client=client, max_retries=1)

    with pytest.raises(ConnectionError, match="attempt-2"):
        backend.open_stage("S1_understand")

    assert client.calls == 2


def test_non_retriable_exception_fails_fast() -> None:
    """Backend fails on first non-retriable error without extra attempts."""
    client = _ClientOpenStageSequence([ValueError("bad-payload"), "ok"])
    backend = KernelBackend(client=client, max_retries=3)

    with pytest.raises(ValueError, match="bad-payload"):
        backend.open_stage("S1_understand")

    assert client.calls == 1
