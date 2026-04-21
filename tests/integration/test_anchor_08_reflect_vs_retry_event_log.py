"""Anchor 8 regression: reflect(N) and retry(N) produce demonstrably different event logs.

Playbook Anchor 8 requires that the restart policy's ``on_exhausted="reflect"``
path emit a ``ReflectionPrompt`` event (with a real ``stage_id``, never the
string ``"unknown"``) for each reflect decision, while ``on_exhausted="escalate"``
(pure retry + escalate) emits zero ``ReflectionPrompt`` events.

Incidents guarded:
  * P-15 — reflect(N) was wired but not observable in the event log, making it
    impossible to distinguish from a plain retry.
  * R3 D-2 — ReflectionPrompt payload recorded ``stage_id='unknown'`` instead of
    the real stage id.

All mocks in this module are confined to a local flaky invoker — no internal
runtime components are mocked (P3 compliant).
"""

from __future__ import annotations

from typing import Any

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.runner import RunExecutor
from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskRestartPolicy
from hi_agent.trajectory.stage_graph import StageGraph

from tests.helpers.kernel_adapter_fixture import MockKernel


def _two_stage_graph() -> StageGraph:
    g = StageGraph()
    g.add_edge("stage_a", "stage_b")
    return g


class _AlwaysFailsStageAInvoker:
    """Invoker that makes stage_a fail on every attempt but stage_b succeed.

    Mock reason (documented per CLAUDE.md P3): fault injection to force the
    restart policy code path. Only the single ``invoke`` boundary is stubbed;
    the rest of the runtime (RunExecutor, StageOrchestrator, RecoveryCoordinator,
    event emitter, restart policy engine) runs as real code.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, capability_name: str, payload: dict) -> dict:
        stage_id = payload.get("stage_id", capability_name)
        self.calls.append(stage_id)
        if stage_id == "stage_a":
            return {"success": False, "score": 0.0, "reason": "forced_failure_for_anchor_08"}
        return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}


def _make_restart_engine(policy: TaskRestartPolicy, task_id: str) -> RestartPolicyEngine:
    attempt_log: list[Any] = []
    policy_map: dict[str, TaskRestartPolicy] = {task_id: policy}

    def _get_attempts(tid: str) -> list[Any]:
        return [a for a in attempt_log if a.task_id == tid]

    def _get_policy(tid: str) -> TaskRestartPolicy | None:
        return policy_map.get(tid)

    def _update_state(tid: str, state: str) -> None:
        pass

    def _record_attempt(attempt: Any) -> None:
        attempt_log.append(attempt)

    return RestartPolicyEngine(
        get_attempts=_get_attempts,
        get_policy=_get_policy,
        update_state=_update_state,
        record_attempt=_record_attempt,
    )


def _run_with_policy(policy: TaskRestartPolicy, task_id: str, goal: str) -> RunExecutor:
    graph = _two_stage_graph()
    contract = TaskContract(task_id=task_id, goal=goal)
    kernel = MockKernel(strict_mode=False)
    invoker = _AlwaysFailsStageAInvoker()
    engine = _make_restart_engine(policy, task_id)
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        invoker=invoker,
        restart_policy_engine=engine,
    )
    # We don't care whether the overall run ends completed or failed —
    # the assertion is on the event log's differentiating content.
    import contextlib

    with contextlib.suppress(Exception):
        executor.execute()
    return executor


@pytest.mark.integration
def test_reflect_policy_emits_reflection_prompt_events() -> None:
    """reflect(2) produces >=1 ReflectionPrompt events; stage_id must be real."""
    policy = TaskRestartPolicy(max_attempts=2, on_exhausted="reflect")
    executor = _run_with_policy(policy, "anchor-8-reflect", "reflect event log")

    events = executor.event_emitter.events
    reflect_events = [ev for ev in events if ev.event_type == "ReflectionPrompt"]

    assert len(reflect_events) >= 1, (
        "reflect(2) with stage_a failing on every attempt must emit at least one "
        "ReflectionPrompt event; got 0. This is the P-15 regression."
    )

    # R3 D-2: each ReflectionPrompt must carry the real stage_id, not 'unknown'.
    for ev in reflect_events:
        payload_stage_id = ev.payload.get("stage_id")
        assert payload_stage_id == "stage_a", (
            f"ReflectionPrompt payload stage_id={payload_stage_id!r} — "
            "must be the real stage id ('stage_a'), never 'unknown' (R3 D-2)."
        )
        # Reflection prompt text should also name the real stage (not 'unknown').
        prompt_text = ev.payload.get("reflection_prompt", "")
        assert "Stage: unknown" not in prompt_text, (
            f"Reflection prompt contains 'Stage: unknown' — R3 D-2 regression: {prompt_text!r}"
        )


@pytest.mark.integration
def test_retry_policy_emits_no_reflection_prompt_events() -> None:
    """retry-only policy (on_exhausted='escalate') emits zero ReflectionPrompt events."""
    policy = TaskRestartPolicy(max_attempts=2, on_exhausted="escalate")
    executor = _run_with_policy(policy, "anchor-8-retry", "retry event log")

    events = executor.event_emitter.events
    reflect_events = [ev for ev in events if ev.event_type == "ReflectionPrompt"]

    assert len(reflect_events) == 0, (
        f"Retry-only policy must not emit ReflectionPrompt events; got {len(reflect_events)}. "
        "If reflect and retry produce the same log, Anchor 8 is violated."
    )


@pytest.mark.integration
def test_reflect_and_retry_logs_are_distinguishable() -> None:
    """Cross-check: reflect and retry logs for the same workload differ on ReflectionPrompt."""
    reflect_exec = _run_with_policy(
        TaskRestartPolicy(max_attempts=2, on_exhausted="reflect"),
        "anchor-8-cross-reflect",
        "cross reflect",
    )
    retry_exec = _run_with_policy(
        TaskRestartPolicy(max_attempts=2, on_exhausted="escalate"),
        "anchor-8-cross-retry",
        "cross retry",
    )

    reflect_types = {ev.event_type for ev in reflect_exec.event_emitter.events}
    retry_types = {ev.event_type for ev in retry_exec.event_emitter.events}

    # reflect must include ReflectionPrompt; retry must not.
    assert "ReflectionPrompt" in reflect_types
    assert "ReflectionPrompt" not in retry_types
