"""Integration tests for runner recovery hook wiring."""

from hi_agent.contracts import TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.recovery import RecoveryOrchestrationResult
from hi_agent.recovery.compensator import CompensationExecutionReport, CompensationPlan
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def _latest_event_payload(executor: RunExecutor, event_type: str) -> dict:
    """Return payload of the latest event with matching type."""
    payloads = [
        event.payload for event in executor.event_emitter.events if event.event_type == event_type
    ]
    assert payloads, f"missing event: {event_type}"
    return payloads[-1]


def test_runner_uses_orchestrator_as_default_recovery_executor() -> None:
    """Runner should wire orchestrator as the default recovery executor."""
    contract = TaskContract(
        task_id="int-recovery-default-001",
        goal="failure triggers default orchestrator",
        constraints=["fail_action:build_draft"],
    )
    kernel = MockKernel(strict_mode=True)

    executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

    result = executor.execute()

    assert result == "failed"
    payload = _latest_event_payload(executor, "RecoveryCompleted")
    assert payload["success"] is True
    assert payload["should_escalate"] is True
    assert payload["failed_stage_count"] >= 1


class RecordingRecoveryExecutor:
    """Record recovery invocation details for assertions."""

    def __init__(self) -> None:
        """Initialize execution capture state."""
        self.calls: list[tuple] = []

    def __call__(self, events: tuple, handlers: dict | None = None) -> dict:
        """Capture recovery call arguments and return a success report."""
        self.calls.append((events, handlers))
        return {
            "success": True,
            "actions": [],
        }


def test_runner_invokes_recovery_hook_and_emits_events_on_failure() -> None:
    """Runner should trigger recovery only when execution fails."""
    contract = TaskContract(
        task_id="int-recovery-001",
        goal="failure triggers recovery",
        constraints=["fail_action:build_draft"],
    )
    kernel = MockKernel(strict_mode=True)
    recovery_executor = RecordingRecoveryExecutor()
    recovery_handlers = {"retry_failed_actions": lambda plan, events: "ok"}

    executor = RunExecutor(
        contract,
        kernel,
        recovery_executor=recovery_executor,
        recovery_handlers=recovery_handlers,
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "failed"
    assert len(recovery_executor.calls) == 1
    consumed_events, consumed_handlers = recovery_executor.calls[0]
    assert isinstance(consumed_events, tuple)
    assert consumed_handlers is recovery_handlers
    assert any(event.event_type == "RecoveryTriggered" for event in executor.event_emitter.events)
    assert any(event.event_type == "RecoveryCompleted" for event in executor.event_emitter.events)


def test_runner_does_not_invoke_recovery_hook_on_success() -> None:
    """Runner should not trigger recovery when run completes successfully."""
    contract = TaskContract(task_id="int-recovery-002", goal="success skips recovery")
    kernel = MockKernel(strict_mode=True)
    recovery_executor = RecordingRecoveryExecutor()

    executor = RunExecutor(
        contract, kernel, recovery_executor=recovery_executor, raw_memory=RawMemoryStore()
    )

    result = executor.execute()

    assert result == "completed"
    assert recovery_executor.calls == []
    assert all(
        event.event_type not in {"RecoveryTriggered", "RecoveryCompleted"}
        for event in executor.event_emitter.events
    )


def test_runner_emits_recovery_completed_with_orchestrator_metadata() -> None:
    """Recovery completion event should include orchestration metadata."""
    contract = TaskContract(
        task_id="int-recovery-003",
        goal="failure emits rich recovery payload",
        constraints=["fail_action:build_draft"],
    )
    kernel = MockKernel(strict_mode=True)

    class SyntheticOrchestrationExecutor:
        def __call__(
            self, events: tuple, handlers: dict | None = None
        ) -> RecoveryOrchestrationResult:
            del events, handlers
            report = CompensationExecutionReport(
                plan=CompensationPlan(
                    actions=["escalate_to_human"],
                    reason="dead_end_detected",
                    failed_stages=["S3_build", "S4_synthesize"],
                ),
                results=[],
                succeeded_actions=[],
                failed_actions=["escalate_to_human"],
                skipped_actions=[],
                success=False,
            )
            return RecoveryOrchestrationResult(
                execution_report=report,
                should_escalate=True,
                failed_stages=["S3_build", "S4_synthesize"],
                action_status_map={"escalate_to_human": "failed"},
            )

    executor = RunExecutor(
        contract,
        kernel,
        recovery_executor=SyntheticOrchestrationExecutor(),
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "failed"
    payload = _latest_event_payload(executor, "RecoveryCompleted")
    assert payload["success"] is False
    assert payload["should_escalate"] is True
    assert payload["failed_stage_count"] == 2
