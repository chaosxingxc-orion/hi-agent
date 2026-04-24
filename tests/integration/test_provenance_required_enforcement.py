"""Integration test: provenance_required enforcement in HarnessExecutor.

When a capability has provenance_required=True and output carries no provenance,
_collect_evidence must raise CapabilityPolicyError.

Wave 8 / P2.7
"""
from __future__ import annotations

from agent_kernel.kernel.contracts import SideEffectClass
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec
from hi_agent.harness.contracts import ActionSpec
from hi_agent.harness.evidence_store import EvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine


def _make_executor(
    capability_name: str,
    provenance_required: bool,
    output: dict,
) -> tuple[HarnessExecutor, str]:
    """Build a real HarnessExecutor wired with a capability that returns output."""
    registry = CapabilityRegistry()
    descriptor = CapabilityDescriptor(
        name=capability_name,
        provenance_required=provenance_required,
    )
    spec = CapabilitySpec(
        name=capability_name,
        handler=lambda _: output,
        descriptor=descriptor,
    )
    registry.register(spec)
    invoker = CapabilityInvoker(registry=registry, allow_unguarded=True)
    governance = GovernanceEngine()
    evidence_store = EvidenceStore()
    from hi_agent.artifacts.registry import ArtifactRegistry

    artifact_registry = ArtifactRegistry()
    executor = HarnessExecutor(
        governance=governance,
        capability_invoker=invoker,
        evidence_store=evidence_store,
        artifact_registry=artifact_registry,
    )
    return executor, capability_name


def test_provenance_required_with_no_provenance_raises() -> None:
    """Capability with provenance_required=True and output without provenance raises."""
    executor, cap_name = _make_executor(
        capability_name="strict_cap",
        provenance_required=True,
        output={"result": "data"},  # no provenance key
    )
    action_spec = ActionSpec(
        action_id="act-1",
        action_type="read",
        capability_name=cap_name,
        payload={},
        side_effect_class=SideEffectClass.READ_ONLY,
        metadata={},
    )
    result = executor.execute(action_spec)
    # CapabilityPolicyError is re-raised from _collect_evidence.
    # Since it propagates through the retry loop's except clause, it becomes
    # a failed ActionResult with the error message containing "provenance".
    assert result.state.value == "failed"
    assert "provenance" in (result.error_message or "").lower()


def test_provenance_required_with_provenance_succeeds() -> None:
    """Capability with provenance_required=True and output WITH provenance succeeds."""
    executor, cap_name = _make_executor(
        capability_name="strict_cap_ok",
        provenance_required=True,
        output={"result": "data", "provenance": {"source": "test"}},
    )
    action_spec = ActionSpec(
        action_id="act-2",
        action_type="read",
        capability_name=cap_name,
        payload={},
        side_effect_class=SideEffectClass.READ_ONLY,
        metadata={},
    )
    result = executor.execute(action_spec)
    assert result.state.value == "succeeded"


def test_provenance_not_required_no_provenance_succeeds() -> None:
    """Capability with provenance_required=False (default) succeeds without provenance."""
    executor, cap_name = _make_executor(
        capability_name="lax_cap",
        provenance_required=False,
        output={"result": "data"},
    )
    action_spec = ActionSpec(
        action_id="act-3",
        action_type="read",
        capability_name=cap_name,
        payload={},
        side_effect_class=SideEffectClass.READ_ONLY,
        metadata={},
    )
    result = executor.execute(action_spec)
    assert result.state.value == "succeeded"
