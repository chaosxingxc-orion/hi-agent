"""Integration tests for RunExecutor retry behavior."""

from hi_agent.contracts import StageState, TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class FlakyInvoker:
    """Test invoker that fails first N attempts per action, then succeeds."""

    def __init__(self, fail_attempts_by_action: dict[str, int]) -> None:
        """Store how many attempts each action should fail before success."""
        self.fail_attempts_by_action = fail_attempts_by_action

    def invoke(self, capability_name: str, payload: dict) -> dict:
        """Return failed result until threshold is exceeded for this action."""
        attempt = int(payload.get("attempt", 1))
        fail_attempts = self.fail_attempts_by_action.get(capability_name, 0)
        if attempt <= fail_attempts:
            return {"success": False, "score": 0.0, "reason": "flaky_failure"}
        return {
            "success": True,
            "score": 1.0,
            "reason": "ok",
            "evidence_hash": f"ev_{payload.get('stage_id', 'unknown')}",
        }


def test_runner_retries_once_then_recovers_and_completes() -> None:
    """Runner should continue when a retried action succeeds."""
    contract = TaskContract(task_id="int-retry-001", goal="retry recovery")
    kernel = MockKernel(strict_mode=True)
    invoker = FlakyInvoker({"build_draft": 1})
    executor = RunExecutor(
        contract, kernel, invoker=invoker, action_max_retries=1, raw_memory=RawMemoryStore()
    )

    result = executor.execute()

    assert result == "completed"
    kernel.assert_stage_state("S3_build", StageState.COMPLETED)
    build_events = [
        event
        for event in executor.event_emitter.events
        if event.event_type == "ActionExecuted"
        and event.payload.get("action_kind") == "build_draft"
    ]
    assert [event.payload["attempt"] for event in build_events] == [1, 2]
    assert [event.payload["success"] for event in build_events] == [False, True]


def test_runner_retries_exhausted_then_stage_fails() -> None:
    """Runner should fail stage when all retries are exhausted."""
    contract = TaskContract(task_id="int-retry-002", goal="retry exhausted")
    kernel = MockKernel(strict_mode=True)
    invoker = FlakyInvoker({"build_draft": 99})
    executor = RunExecutor(
        contract, kernel, invoker=invoker, action_max_retries=1, raw_memory=RawMemoryStore()
    )

    result = executor.execute()

    assert result == "failed"
    kernel.assert_stage_state("S3_build", StageState.FAILED)
    build_events = [
        event
        for event in executor.event_emitter.events
        if event.event_type == "ActionExecuted"
        and event.payload.get("action_kind") == "build_draft"
    ]
    assert [event.payload["attempt"] for event in build_events] == [1, 2]
    assert all(event.payload["success"] is False for event in build_events)
