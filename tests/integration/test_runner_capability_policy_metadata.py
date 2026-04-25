"""Integration tests for runner capability policy metadata wiring."""

from __future__ import annotations

from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityPolicy,
    CapabilityRegistry,
    CircuitBreaker,
    register_default_capabilities,
)
from hi_agent.contracts import CTSExplorationBudget, StageState, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


class _MetadataSpyInvoker:
    """Invoker spy that accepts role/metadata and records each call."""

    def __init__(self) -> None:
        """Initialize empty invocation log."""
        self.calls: list[dict] = []

    def invoke(
        self,
        capability_name: str,
        payload: dict,
        role: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Record invocation context and return a successful result."""
        self.calls.append(
            {
                "capability_name": capability_name,
                "payload": payload,
                "role": role,
                "metadata": metadata or {},
            }
        )
        return {"success": True, "score": 1.0, "evidence_hash": "ev_test"}


def _build_policy_invoker(policy: CapabilityPolicy) -> CapabilityInvoker:
    """Build a production-like invoker with default capabilities and policy."""
    registry = CapabilityRegistry()
    register_default_capabilities(registry)
    return CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), policy=policy)


def test_runner_fails_when_stage_action_policy_denies_invocation() -> None:
    """Runner should fail when role is denied for current stage/action pair."""
    policy = CapabilityPolicy()
    policy.allow_action("operator", "S2_gather", "search_evidence")
    invoker = _build_policy_invoker(policy)
    contract = TaskContract(
        task_id="int-polmeta-001",
        goal="deny at first stage",
        constraints=["invoker_role:operator"],
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(
        contract,
        kernel,
        invoker=invoker,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    result = executor.execute()

    assert result == "failed"
    kernel.assert_stage_state("S1_understand", StageState.FAILED)


def test_runner_completes_when_stage_action_policy_allows_all_actions() -> None:
    """Runner should complete when role is allowed for each stage action."""
    policy = CapabilityPolicy()
    policy.allow_action("operator", "S1_understand", "analyze_goal")
    policy.allow_action("operator", "S2_gather", "search_evidence")
    policy.allow_action("operator", "S3_build", "build_draft")
    policy.allow_action("operator", "S4_synthesize", "synthesize")
    policy.allow_action("operator", "S5_review", "evaluate_acceptance")
    invoker = _build_policy_invoker(policy)
    contract = TaskContract(
        task_id="int-polmeta-002",
        goal="allow full run",
        constraints=["invoker_role:operator"],
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(
        contract,
        kernel,
        invoker=invoker,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    result = executor.execute()

    assert result == "completed"
    kernel.assert_stage_state("S5_review", StageState.COMPLETED)


def test_runner_passes_role_and_metadata_to_invoker() -> None:
    """Runner should pass role and rich metadata to invoker.invoke."""
    spy = _MetadataSpyInvoker()
    contract = TaskContract(
        task_id="int-polmeta-003",
        goal="metadata wiring",
        constraints=["invoker_role:auditor"],
    )
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(
        contract,
        kernel,
        invoker=spy,
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    result = executor.execute()

    assert result == "completed"
    first_call = spy.calls[0]
    assert first_call["role"] == "auditor"
    assert first_call["metadata"]["run_id"] == executor.run_id
    assert first_call["metadata"]["stage_id"] == "S1_understand"
    assert first_call["metadata"]["action_kind"] == "analyze_goal"
    assert "branch_id" in first_call["metadata"]
    assert "seq" in first_call["metadata"]
