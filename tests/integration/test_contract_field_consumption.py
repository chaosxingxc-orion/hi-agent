"""Contract field consumption tests.

Verify that TaskContract fields with consumption level ACTIVE actually
influence run execution outcomes.  Also explicitly document which fields
are PASSTHROUGH so the boundary is unambiguous.

Design principle: each test must prove a field has observable effect on the
run outcome — not just that it was accepted by the endpoint.

These tests use MockKernel (consistent with other integration tests) so they
run without external dependencies.  The server default factory tests in
test_server_default_factory_e2e.py cover the same fields through the real
builder path.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from hi_agent.contracts import TaskContract
from hi_agent.contracts.requests import RunResult
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(
    *,
    accept_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    deadline: str | None = None,
) -> AgentServer:
    """Create a server whose executor factory builds from MockKernel."""

    def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
        task_id = run_data.get("task_id") or run_data.get("run_id") or uuid.uuid4().hex[:12]
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", "test goal"),
            constraints=run_data.get("constraints") or constraints or [],
            acceptance_criteria=run_data.get("acceptance_criteria") or accept_criteria or [],
            deadline=run_data.get("deadline") or deadline,
        )
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
        return executor.execute

    server = AgentServer()
    server.executor_factory = factory
    return server


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    terminal = {"completed", "failed", "aborted"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data.get("state") in terminal:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id!r} did not finish within {timeout:.1f}s")


def _direct_execute(
    *,
    constraints: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    deadline: str | None = None,
) -> RunResult:
    """Execute a run directly (CLI-path equivalent) and return RunResult."""
    contract = TaskContract(
        task_id=uuid.uuid4().hex[:12],
        goal="test goal",
        constraints=constraints or [],
        acceptance_criteria=acceptance_criteria or [],
        deadline=deadline,
    )
    return RunExecutor(contract, MockKernel(), raw_memory=RawMemoryStore()).execute()


# ---------------------------------------------------------------------------
# acceptance_criteria — ACTIVE
# ---------------------------------------------------------------------------


class TestAcceptanceCriteriaConsumption:
    """acceptance_criteria with supported patterns must affect the final outcome."""

    def test_required_stage_nonexistent_causes_failure(self) -> None:
        """required_stage:<nonexistent> must downgrade completed to failed."""
        result = _direct_execute(acceptance_criteria=["required_stage:STAGE_DOES_NOT_EXIST_XYZ"])
        assert result.status == "failed", (
            f"Expected failed when required stage is absent, got {result.status!r}"
        )
        assert result.failure_code is not None

    def test_required_artifact_nonexistent_causes_failure(self) -> None:
        """required_artifact:<nonexistent> must downgrade completed to failed."""
        result = _direct_execute(
            acceptance_criteria=["required_artifact:artifact://does-not-exist"]
        )
        assert result.status == "failed", (
            f"Expected failed when required artifact absent, got {result.status!r}"
        )

    def test_empty_acceptance_criteria_does_not_affect_outcome(self) -> None:
        """Empty acceptance_criteria list must not affect a normal completed run."""
        result = _direct_execute(acceptance_criteria=[])
        assert result.status == "completed"

    def test_acceptance_criteria_enforced_via_server(self) -> None:
        """acceptance_criteria must be enforced when submitted via POST /runs."""
        server = AgentServer()

        def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
            task_id = run_data.get("run_id") or uuid.uuid4().hex[:12]
            contract = TaskContract(
                task_id=task_id,
                goal=run_data.get("goal", ""),
                acceptance_criteria=run_data.get("acceptance_criteria") or [],
            )
            return RunExecutor(contract, MockKernel(), raw_memory=RawMemoryStore()).execute

        server.executor_factory = factory
        client = TestClient(server.app, raise_server_exceptions=False)

        resp = client.post(
            "/runs",
            json={
                "goal": "test",
                "acceptance_criteria": ["required_stage:NONEXISTENT"],
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]
        final = _wait_terminal(client, run_id)

        assert final["state"] == "failed", (
            f"Run submitted with unsatisfied acceptance_criteria must fail, "
            f"got state={final['state']!r}"
        )
        result = final.get("result", {})
        assert isinstance(result, dict)
        assert result.get("status") == "failed"


# ---------------------------------------------------------------------------
# constraints — ACTIVE (built-in prefixes)
# ---------------------------------------------------------------------------


class TestConstraintsConsumption:
    """Built-in constraint prefixes must be parsed and affect execution."""

    def test_fail_action_constraint_causes_failure(self) -> None:
        """fail_action:<stage> constraint must cause that stage to fail."""
        # MockKernel's behavior: fail_action constraints are parsed by
        # RunExecutor._parse_forced_fail_actions() and cause action dispatch to fail.
        result = _direct_execute(constraints=["fail_action:analyze_goal"])
        # With fail_action, the run should fail (stage action always raises)
        assert result.status == "failed", (
            f"Expected failed with fail_action constraint, got {result.status!r}"
        )
        assert result.failed_stage_id is not None, "Failed run must report failed_stage_id"

    def test_action_max_retries_constraint_is_parsed(self) -> None:
        """action_max_retries:<n> constraint must be accepted without error."""
        # We can't easily observe retry count externally, but we can verify
        # the constraint doesn't crash the run.
        result = _direct_execute(constraints=["action_max_retries:3"])
        # Rule 7: an accepted constraint on a normal MockKernel run must complete.
        assert result.status == "completed", (
            f"expected completed with action_max_retries constraint, got {result.status!r}"
        )

    def test_unrecognized_constraint_does_not_crash(self) -> None:
        """Unrecognized constraints must be stored/returned but not crash the run."""
        result = _direct_execute(constraints=["custom_business_constraint:value"])
        # Rule 7: an unrecognized constraint must not crash AND must not
        # silently fail — MockKernel has no reason to fail on it.
        assert result.status == "completed", (
            f"unrecognized constraint must not cause failure, got {result.status!r}"
        )


# ---------------------------------------------------------------------------
# deadline — ACTIVE
# ---------------------------------------------------------------------------


class TestDeadlineConsumption:
    """deadline must be checked and cause failure when already past."""

    def test_past_deadline_causes_failure(self) -> None:
        """A deadline in the past must cause run failure."""
        result = _direct_execute(deadline="2000-01-01T00:00:00Z")
        assert result.status == "failed", (
            f"Expected failed when deadline is in the past, got {result.status!r}"
        )

    def test_future_deadline_does_not_affect_outcome(self) -> None:
        """A deadline far in the future must not affect a normal run."""
        result = _direct_execute(deadline="2099-12-31T23:59:59Z")
        assert result.status == "completed", (
            f"Expected completed with far-future deadline, got {result.status!r}"
        )


# ---------------------------------------------------------------------------
# PASSTHROUGH fields — document that they are stored but not consumed
# ---------------------------------------------------------------------------


class TestPassthroughFieldsDocumented:
    """PASSTHROUGH fields must be stored/returned but must not crash execution.

    These tests document the current boundary explicitly.  They do NOT assert
    that the fields affect outcomes — they assert the platform is transparent
    about accepting and returning them.
    """

    def test_environment_scope_accepted_and_returned(self) -> None:
        """environment_scope is PASSTHROUGH — must be accepted without error."""
        server = AgentServer()

        captured_env_scope: list[list[str]] = []

        def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
            task_id = run_data.get("run_id") or uuid.uuid4().hex[:12]
            env_scope = run_data.get("environment_scope") or []
            captured_env_scope.append(env_scope)
            contract = TaskContract(
                task_id=task_id,
                goal=run_data.get("goal", ""),
                environment_scope=env_scope,
            )
            return RunExecutor(contract, MockKernel(), raw_memory=RawMemoryStore()).execute

        server.executor_factory = factory
        client = TestClient(server.app, raise_server_exceptions=False)

        resp = client.post(
            "/runs",
            json={
                "goal": "test",
                "environment_scope": ["staging", "sandbox"],
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]
        final = _wait_terminal(client, run_id)

        # Must complete without error (Rule 7: PASSTHROUGH must not fail the run).
        assert final["state"] == "completed", (
            f"environment_scope passthrough must not fail the run, got {final['state']!r}"
        )
        # The field must have been received by the factory
        assert len(captured_env_scope) > 0
        assert captured_env_scope[0] == ["staging", "sandbox"], (
            "environment_scope was not passed through to the executor factory"
        )

    def test_input_refs_accepted_and_passed_through(self) -> None:
        """input_refs is PASSTHROUGH — must reach the executor contract."""
        captured_refs: list[list[str]] = []

        def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
            task_id = run_data.get("run_id") or uuid.uuid4().hex[:12]
            refs = run_data.get("input_refs") or []
            captured_refs.append(refs)
            contract = TaskContract(
                task_id=task_id,
                goal=run_data.get("goal", ""),
                input_refs=refs,
            )
            return RunExecutor(contract, MockKernel(), raw_memory=RawMemoryStore()).execute

        server = AgentServer()
        server.executor_factory = factory
        client = TestClient(server.app, raise_server_exceptions=False)

        resp = client.post(
            "/runs",
            json={
                "goal": "test",
                "input_refs": ["artifact://abc", "s3://bucket/key"],
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]
        _wait_terminal(client, run_id)

        assert captured_refs[0] == ["artifact://abc", "s3://bucket/key"], (
            "input_refs must be passed through to executor factory"
        )

    def test_parent_task_id_accepted_without_crash(self) -> None:
        """parent_task_id is PASSTHROUGH — must not crash the run."""
        result = RunExecutor(
            TaskContract(
                task_id=uuid.uuid4().hex[:12],
                goal="subtask",
                parent_task_id="parent-task-001",
            ),
            MockKernel(),
            raw_memory=RawMemoryStore(),
        ).execute()
        # Rule 7: parent_task_id is PASSTHROUGH and must not cause failure.
        assert result.status == "completed", (
            f"parent_task_id passthrough must not fail the run, got {result.status!r}"
        )
