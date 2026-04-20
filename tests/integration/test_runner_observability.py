"""Integration tests for RunExecutor observability hook behavior."""

from __future__ import annotations

from hi_agent.contracts import TaskContract
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_runner_emits_observability_signals() -> None:
    """Runner should emit lifecycle signals via observability hook."""
    captured: list[tuple[str, dict[str, object]]] = []

    def _hook(name: str, payload: dict[str, object]) -> None:
        captured.append((name, payload))

    contract = TaskContract(task_id="obs-001", goal="test observability hook")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, observability_hook=_hook)

    result = executor.execute()

    assert result == "completed"
    names = [name for name, _ in captured]
    assert "run_completed" in names
    assert names.count("stage_started") == 5
    assert names.count("stage_completed") == 5
    assert names.count("action_executed") == 5
    assert all(payload.get("run_id") == executor.run_id for _, payload in captured)


def test_runner_ignores_observability_hook_exceptions() -> None:
    """Hook exceptions must not break run execution."""

    def _failing_hook(name: str, payload: dict[str, object]) -> None:
        raise RuntimeError(f"hook failure on {name}")

    contract = TaskContract(task_id="obs-002", goal="hook failures are best-effort")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel, observability_hook=_failing_hook)

    result = executor.execute()

    assert result == "completed"
