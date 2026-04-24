"""Integration tests for RunExecutor role propagation to capability invoker."""

from __future__ import annotations

from hi_agent.contracts import TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class RoleAwareInvoker:
    """Invoker that records received roles."""

    def __init__(self) -> None:
        """Initialize empty role history."""
        self.roles: list[str | None] = []

    def invoke(self, capability_name: str, payload: dict, role: str | None = None) -> dict:
        """Record role and return a successful capability-like result."""
        _ = capability_name
        self.roles.append(role)
        return {
            "success": True,
            "score": 1.0,
            "reason": "ok",
            "evidence_hash": f"ev_{payload.get('stage_id', 'unknown')}",
        }


class LegacyInvoker:
    """Legacy invoker shape without role parameter."""

    def __init__(self) -> None:
        """Initialize invocation counter."""
        self.calls = 0

    def invoke(self, capability_name: str, payload: dict) -> dict:
        """Increment counter and return a successful capability-like result."""
        _ = capability_name
        self.calls += 1
        return {
            "success": True,
            "score": 1.0,
            "reason": "ok",
            "evidence_hash": f"ev_{payload.get('stage_id', 'unknown')}",
        }


def test_runner_role_defaults_to_none_and_is_forwarded() -> None:
    """Default role should be backward-compatible and forwarded as None."""
    invoker = RoleAwareInvoker()
    executor = RunExecutor(
        TaskContract(task_id="runner-role-default", goal="role default"),
        MockKernel(strict_mode=True),
        invoker=invoker,
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "completed"
    assert len(invoker.roles) > 0
    assert set(invoker.roles) == {None}


def test_runner_role_is_configurable_and_forwarded() -> None:
    """Configured runner_role should be forwarded on every invoke call."""
    invoker = RoleAwareInvoker()
    executor = RunExecutor(
        TaskContract(task_id="runner-role-config", goal="role configured"),
        MockKernel(strict_mode=True),
        runner_role="operator",
        invoker=invoker,
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "completed"
    assert len(invoker.roles) > 0
    assert set(invoker.roles) == {"operator"}


def test_runner_role_keeps_legacy_invoker_compatible() -> None:
    """Legacy two-arg invoker should continue to work without errors."""
    invoker = LegacyInvoker()
    executor = RunExecutor(
        TaskContract(task_id="runner-role-legacy", goal="legacy compatible"),
        MockKernel(strict_mode=True),
        runner_role="operator",
        invoker=invoker,
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "completed"
    assert invoker.calls > 0
