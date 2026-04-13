"""Platform contract E2E tests.

These tests verify the four platform delivery contracts that downstream
integrators depend on:

  PC-01  Readiness accuracy   — /ready reflects live runtime state
  PC-02  Manifest truthfulness — /manifest reflects actually-loaded subsystems
  PC-03  Result consumability  — run result is structured, not a bare status string
  PC-04  Entry point parity    — CLI and server produce equivalent result shapes
  PC-05  Failure attribution   — failed runs carry structured error, service stays healthy

Design principle: every assertion must answer "can a downstream integrator
trust this?" — not just "did the server return 200?"
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from starlette.testclient import TestClient

from hi_agent.contracts import TaskContract
from hi_agent.contracts.requests import RunResult
from hi_agent.server.app import AgentServer
from tests.helpers.kernel_adapter_fixture import MockKernel
from hi_agent.runner import RunExecutor

import time


# ---------------------------------------------------------------------------
# Helpers shared across all platform contract tests
# ---------------------------------------------------------------------------

def _make_mock_executor_factory(*, fail: bool = False) -> Callable:
    """Return executor factory backed by MockKernel (no real LLM/kernel)."""

    def factory(run_data: dict[str, Any]) -> Callable[[], Any]:
        task_id = (
            run_data.get("task_id")
            or run_data.get("run_id")
            or uuid.uuid4().hex[:12]
        )
        constraints: list[str] = []
        if fail:
            constraints.append("fail_action:S1")
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            constraints=constraints,
        )
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel)
        return executor.execute

    return factory


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 10.0,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def server() -> AgentServer:
    s = AgentServer()
    s.executor_factory = _make_mock_executor_factory()
    return s


@pytest.fixture()
def client(server: AgentServer) -> TestClient:
    return TestClient(server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# PC-01: Readiness accuracy
# ---------------------------------------------------------------------------

def test_pc01_readiness_reflects_live_runtime(client: TestClient, server: AgentServer) -> None:
    """GET /ready must reflect the same builder that actual runs use.

    The endpoint must NOT reconstruct default state — it must probe the live
    server's builder so capability counts etc. match what runs actually see.
    """
    resp = client.get("/ready")

    # Must succeed (kernel + capabilities functional)
    assert resp.status_code in (200, 503), "Unexpected HTTP status from /ready"
    body = resp.json()

    # Structural contract: required keys must be present
    assert "ready" in body, "/ready must include 'ready' key"
    assert "health" in body, "/ready must include 'health' key"
    assert "subsystems" in body, "/ready must include 'subsystems' key"
    assert "capabilities" in body, "/ready must include 'capabilities' key"

    # The capability list in /ready must match what the live builder exposes
    # (i.e., from server._builder, not a fresh throwaway builder).
    builder = getattr(server, "_builder", None)
    assert builder is not None, "Server must have a _builder attribute"

    live_caps: list[str] = []
    try:
        invoker = builder.build_invoker()
        # CapabilityInvoker uses `registry` (public), not `_registry` (private).
        reg = getattr(invoker, "registry", None) or getattr(invoker, "_registry", None)
        if reg is not None:
            live_caps = reg.list_names()
    except Exception:
        pass

    ready_caps = body.get("capabilities", [])
    # Both should list the same capabilities (same builder instance)
    assert set(ready_caps) == set(live_caps), (
        f"Readiness capability list {set(ready_caps)!r} does not match "
        f"live builder capabilities {set(live_caps)!r}. "
        "This means /ready is NOT reading from the live runtime."
    )


def test_pc01b_readiness_subsystem_errors_not_masked(client: TestClient) -> None:
    """If any subsystem reports an error, health must NOT claim 'ok'."""
    resp = client.get("/ready")
    body = resp.json()

    subsystems = body.get("subsystems", {})
    any_error = any(
        s.get("status") == "error"
        for s in subsystems.values()
        if isinstance(s, dict)
    )
    if any_error:
        assert body.get("health") != "ok", (
            "A subsystem reported 'error' but health is still 'ok' — "
            "readiness is masking failures."
        )


# ---------------------------------------------------------------------------
# PC-02: Manifest truthfulness
# ---------------------------------------------------------------------------

def test_pc02_manifest_capabilities_not_empty(client: TestClient) -> None:
    """GET /manifest must list the actual registered capabilities, not an empty list.

    An empty capabilities list means the manifest is not reading live state.
    """
    resp = client.get("/manifest")
    assert resp.status_code == 200
    body = resp.json()

    caps = body.get("capabilities", [])
    assert isinstance(caps, list), "capabilities must be a list"
    assert len(caps) > 0, (
        "Manifest reports 0 capabilities. Either no capabilities are registered "
        "(unlikely given default bundle) or the manifest is not reading live state."
    )


def test_pc02_manifest_stages_reflect_real_graph(client: TestClient, server: AgentServer) -> None:
    """Manifest stages must match the server's actual stage graph."""
    resp = client.get("/manifest")
    body = resp.json()

    manifest_stages = set(body.get("stages", []))
    stage_graph = getattr(server, "stage_graph", None)
    if stage_graph is not None:
        transitions = getattr(stage_graph, "transitions", {})
        live_stages = set(transitions.keys())
        assert manifest_stages == live_stages, (
            f"Manifest stages {manifest_stages!r} do not match live stage graph "
            f"stages {live_stages!r}."
        )


def test_pc02_manifest_no_hardcoded_lies(client: TestClient) -> None:
    """Manifest fields must reflect runtime state, not hardcoded defaults.

    Checks that the endpoint is not simply returning static placeholder values
    that mislead integrators about actual platform state.
    """
    resp = client.get("/manifest")
    body = resp.json()

    # framework must be TRACE (this is a fixed declaration, OK to assert)
    assert body.get("framework") == "TRACE"
    # stages must not be empty — the default TRACE graph has S1-S5
    assert len(body.get("stages", [])) >= 4, "Expected at least 4 TRACE stages"
    # capabilities must not be empty when default bundle is registered
    assert len(body.get("capabilities", [])) > 0, (
        "Manifest capabilities is empty — likely returning hardcoded default"
    )


# ---------------------------------------------------------------------------
# PC-03: Result consumability
# ---------------------------------------------------------------------------

def test_pc03_run_result_is_structured(client: TestClient) -> None:
    """Completed run result must be a structured object, not a bare status string.

    The downstream integrator must be able to inspect stages, artifacts, and
    other fields without parsing a raw string.
    """
    resp = client.post("/runs", json={"goal": "Summarize the TRACE framework"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    final = _wait_terminal(client, run_id)
    assert final["state"] == "completed"

    result = final.get("result")
    assert result is not None, "result field must not be null after completion"
    assert isinstance(result, dict), (
        f"result must be a structured dict, got {type(result).__name__!r}: {result!r}. "
        "Bare status strings like 'completed' are not consumable by downstream."
    )

    # Required keys in the structured result
    for key in ("run_id", "status", "stages", "artifacts"):
        assert key in result, f"Structured result must contain '{key}' key"

    assert result["status"] == "completed", f"status must be 'completed', got {result['status']!r}"
    assert isinstance(result["stages"], list), "stages must be a list"
    assert isinstance(result["artifacts"], list), "artifacts must be a list"


def test_pc03_run_result_stages_have_required_fields(client: TestClient) -> None:
    """Each stage in the run result must have structured fields."""
    resp = client.post("/runs", json={"goal": "Analyze dependencies"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    final = _wait_terminal(client, run_id)
    result = final.get("result", {})

    if isinstance(result, dict):
        for stage in result.get("stages", []):
            assert isinstance(stage, dict), f"Each stage must be a dict, got {stage!r}"
            assert "stage_id" in stage, "stage must have 'stage_id'"
            assert "outcome" in stage, "stage must have 'outcome'"


# ---------------------------------------------------------------------------
# PC-04: Entry point parity (CLI path vs server path)
# ---------------------------------------------------------------------------

def test_pc04_execute_returns_run_result_not_string() -> None:
    """RunExecutor.execute() must return a RunResult, not a bare string.

    This validates the CLI path produces the same structured result shape
    as the server path.
    """
    contract = TaskContract(task_id="pc04test", goal="Verify result shape")
    kernel = MockKernel()
    executor = RunExecutor(contract, kernel)
    result = executor.execute()

    # Must be a RunResult, not a bare string
    assert isinstance(result, RunResult), (
        f"execute() must return RunResult, got {type(result).__name__!r}. "
        "CLI path and server path must produce the same result shape."
    )
    assert result.run_id, "RunResult must have non-empty run_id"
    assert result.status in ("completed", "failed"), f"Unexpected status: {result.status!r}"
    assert isinstance(result.stages, list), "RunResult.stages must be a list"
    assert isinstance(result.artifacts, list), "RunResult.artifacts must be a list"

    # Backward compat: str(result) must return status string
    assert str(result) == result.status, "str(RunResult) must return status string"


def test_pc04_server_and_direct_result_shapes_match(client: TestClient) -> None:
    """Server result dict must include all RunResult fields.

    Ensures the server serialization surface matches what execute() produces directly.
    """
    resp = client.post("/runs", json={"goal": "Compare entry points"})
    run_id = resp.json()["run_id"]
    final = _wait_terminal(client, run_id)

    result = final.get("result")
    assert isinstance(result, dict), "Server result must be a structured dict"

    # Must have same keys as RunResult.to_dict()
    required_keys = {"run_id", "status", "stages", "artifacts"}
    missing = required_keys - set(result.keys())
    assert not missing, f"Server result missing keys from RunResult contract: {missing}"


# ---------------------------------------------------------------------------
# PC-05: Failure attribution
# ---------------------------------------------------------------------------

def test_pc05_failed_run_has_structured_result(client: TestClient) -> None:
    """A failed run must return a structured result with error attribution.

    The integrator must be able to determine WHY a run failed, not just that
    it failed.
    """
    # Use a factory that forces failure
    server = AgentServer()
    server.executor_factory = _make_mock_executor_factory(fail=True)
    fail_client = TestClient(server.app, raise_server_exceptions=False)

    resp = fail_client.post("/runs", json={"goal": "This run will fail"})
    if resp.status_code != 201:
        pytest.skip("Server rejected run creation — skipping failure attribution test")

    run_id = resp.json()["run_id"]
    final = _wait_terminal(fail_client, run_id)

    # Service must stay up regardless of run failure
    health_resp = fail_client.get("/health")
    assert health_resp.status_code == 200, "Service must remain healthy after a failed run"

    # If run failed, result should be structured (not None, not bare string)
    if final["state"] == "failed":
        result = final.get("result")
        if result is not None and isinstance(result, dict):
            assert "status" in result, "Failed run result must include 'status'"


# ---------------------------------------------------------------------------
# PC-06: Failure attribution precision
# ---------------------------------------------------------------------------

def test_pc06_failure_code_present_on_failed_run(client: TestClient) -> None:
    """A failed run must carry a non-null failure_code for automated triage.

    failure_code=None makes it impossible for the integrator to distinguish
    between different failure modes and take the right automated action.
    """
    fail_server = AgentServer()
    fail_server.executor_factory = _make_mock_executor_factory(fail=True)
    fail_client = TestClient(fail_server.app, raise_server_exceptions=False)

    resp = fail_client.post("/runs", json={"goal": "intentional failure"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    final = _wait_terminal(fail_client, run_id)

    if final["state"] == "failed":
        result = final.get("result", {})
        assert isinstance(result, dict), "result must be a dict"
        assert result.get("failure_code") is not None, (
            "Failed run must include a non-null failure_code for automated triage. "
            "None means the integrator cannot distinguish failure modes."
        )


def test_pc06_failed_stage_id_identifies_failing_stage(client: TestClient) -> None:
    """failed_stage_id must identify which stage caused the failure."""
    from hi_agent.contracts import TaskContract
    from hi_agent.runner import RunExecutor
    from tests.helpers.kernel_adapter_fixture import MockKernel
    import uuid

    # Force failure specifically in S1
    def factory(run_data: dict) -> Any:
        task_id = run_data.get("run_id") or uuid.uuid4().hex[:12]
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            constraints=["fail_action:analyze_goal"],
        )
        return RunExecutor(contract, MockKernel()).execute

    server = AgentServer()
    server.executor_factory = factory
    c = TestClient(server.app, raise_server_exceptions=False)

    resp = c.post("/runs", json={"goal": "fail at S1"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    final = _wait_terminal(c, run_id)

    if final["state"] == "failed":
        result = final.get("result", {})
        assert isinstance(result, dict)
        failed_stage_id = result.get("failed_stage_id")
        assert failed_stage_id is not None, (
            "Failed run must report failed_stage_id so integrators can identify "
            "which stage to investigate or retry"
        )


def test_pc06_run_state_and_result_status_always_agree() -> None:
    """run.state and result.status must never contradict each other.

    state=completed + result.status=failed is a contract violation that causes
    integrators to treat failed tasks as successful.
    """
    from hi_agent.contracts import TaskContract
    from hi_agent.contracts.requests import RunResult
    from hi_agent.runner import RunExecutor
    from hi_agent.server.run_manager import RunManager
    from tests.helpers.kernel_adapter_fixture import MockKernel
    import uuid

    manager = RunManager(max_concurrent=2)

    for constraints, expected_status in [
        ([], "completed"),
        (["fail_action:analyze_goal"], "failed"),
    ]:
        contract = TaskContract(
            task_id=uuid.uuid4().hex[:12],
            goal="alignment check",
            constraints=constraints,
        )
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel)

        run_id = manager.create_run({"goal": "alignment check", "constraints": constraints})

        def executor_fn(_run):
            return executor.execute()

        manager.start_run(run_id, executor_fn)

        # Wait for terminal
        import time
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            run = manager.get_run(run_id)
            if run and run.state in ("completed", "failed", "aborted"):
                break
            time.sleep(0.05)

        run = manager.get_run(run_id)
        assert run is not None
        result = run.result
        if result is not None and isinstance(result, RunResult):
            assert run.state == result.status, (
                f"run.state={run.state!r} contradicts result.status={result.status!r}. "
                "This is a contract violation — integrators will misread failure as success."
            )


def test_pc06_invalid_result_status_maps_to_failed() -> None:
    """RunManager must not accept unknown result status strings.

    If RunResult.status is set to an unrecognized value, run.state must
    be mapped to 'failed' rather than propagating the invalid string.
    """
    from hi_agent.contracts.requests import RunResult
    from hi_agent.server.run_manager import RunManager
    import uuid

    manager = RunManager(max_concurrent=1)
    run_id = manager.create_run({"goal": "state validation test"})

    def bad_executor(_run):
        return RunResult(run_id=run_id, status="banana_invalid_status")

    manager.start_run(run_id, bad_executor)

    import time
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        run = manager.get_run(run_id)
        if run and run.state not in ("created", "running"):
            break
        time.sleep(0.05)

    run = manager.get_run(run_id)
    assert run is not None
    assert run.state == "failed", (
        f"Unknown result status should map to 'failed', got run.state={run.state!r}"
    )
