"""PI-D E2E — Multistage + ``dispatch_subrun``.

Pattern:
  * Parent run dispatches a child run mid-stage via ``dispatch_subrun``.
  * The delegation target is a real ``DelegationManager`` wired to the
    ``InProcessKernelStub`` fixture — a minimal real implementation of
    the ``RuntimeAdapter`` delegation surface (not a Mock).
  * Assertions cover Rule 13 ID uniqueness (parent/child distinct),
    Rule 14 fallback signals (empty), and observable consumption of the
    sub-run output in the parent stage.

Mirrors ``tests/integration/test_journeys.py::journey-5``; the PI-D test
adds a test-scoped ``profile_id`` on the contract for Rule 13 parity.
"""

from __future__ import annotations

import uuid

import pytest
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events
from hi_agent.runner import RunExecutor, SubRunHandle
from hi_agent.task_mgmt.delegation import DelegationConfig, DelegationManager
from hi_agent.trajectory.stage_graph import StageGraph

from tests.e2e.conftest import REAL_LLM_AVAILABLE, make_contract, make_mock_kernel
from tests.fixtures.in_process_kernel import ChildOutcome, InProcessKernelStub


@pytest.mark.integration
def test_pi_d_dispatch_subrun_and_consume_output(profile_id_for_test: str) -> None:
    """PI-D: parent dispatches a sub-run, awaits it, and consumes the output."""
    child_kernel = InProcessKernelStub(
        default_outcome=ChildOutcome(
            lifecycle_state="completed",
            output="PI-D subrun produced this real output",
        ),
    )
    delegation_mgr = DelegationManager(
        kernel=child_kernel,
        config=DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01),
    )

    artifact_store: dict[str, object] = {}

    class SubrunDispatchingInvoker:
        """Dispatches a sub-run on stage pi_d_s1 and consumes the result.

        The runner may invoke the capability more than once across
        branches; the PI-D invariant is simply that at least one sub-run
        is spawned and its output is consumed by the parent.
        """

        def invoke(
            self,
            capability_name: str,
            payload: dict,
            role: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            stage_id = payload.get("stage_id", capability_name)
            if stage_id == "pi_d_s1":
                handle = executor.dispatch_subrun(
                    agent="research",
                    profile_id=f"{profile_id_for_test}-child",
                    goal="PI-D child task goal",
                )
                assert isinstance(handle, SubRunHandle)
                sr = executor.await_subrun(handle)
                artifact_store["subrun_success"] = sr.success
                artifact_store["subrun_output"] = sr.output
            return {"success": True, "score": 1.0, "evidence_hash": f"ev_{stage_id}"}

    graph = StageGraph()
    graph.add_edge("pi_d_s1", "pi_d_s2")

    contract = make_contract(profile_id_for_test, goal="PI-D subrun dispatch")
    kernel = make_mock_kernel()
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=graph,
        invoker=SubrunDispatchingInvoker(),
        delegation_manager=delegation_mgr,
    )

    # Pre-assign a real uuid-based parent run_id so clear_fallback_events can
    # pre-clean.  execute() will overwrite this via kernel.start_run; we also
    # re-check against executor.run_id after the run finishes.
    pre_run_id = f"run-pi-d-{uuid.uuid4().hex[:8]}"
    executor._run_id = pre_run_id
    clear_fallback_events(pre_run_id)

    result = executor.execute()

    assert result.status == "completed", (
        f"PI-D expected completed, got {result.status!r}: error={result.error!r}"
    )
    assert artifact_store.get("subrun_success") is True, (
        f"sub-run must have succeeded; got artifact_store={artifact_store!r}"
    )
    assert "PI-D subrun produced" in str(artifact_store.get("subrun_output", "")), (
        f"sub-run output must have reached the parent stage; got {artifact_store!r}"
    )

    # Rule 13 — parent and child run_ids must be distinct.  At least one
    # child spawn happened (the runner may re-invoke the capability across
    # branches, which is orthogonal to PI-D's correctness).
    assert len(child_kernel.spawn_calls) >= 1, (
        f"at least one child spawn expected; got {child_kernel.spawn_calls!r}"
    )
    spawn = child_kernel.spawn_calls[0]
    assert spawn["parent_run_id"] == executor.run_id
    assert spawn["parent_run_id"].strip() != ""
    assert spawn["child_run_id"] != spawn["parent_run_id"]
    assert spawn["child_run_id"].startswith("child-")

    # Rule 14 — no heuristic fallback on the happy path (only meaningful with a real LLM;
    # in heuristic-only mode all capabilities emit capability fallback events by design).
    if REAL_LLM_AVAILABLE:
        _fb = get_fallback_events(executor.run_id)
        assert _fb == [], f"PI-D happy path must not emit fallback events; got {_fb!r}"
        assert result.fallback_events == []
