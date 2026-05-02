"""Integration test: HarnessExecutor returns permission_denied when PermissionGate DENYs."""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.runtime.harness.contracts import ActionSpec, ActionState
from hi_agent.runtime.harness.evidence_store import EvidenceStore
from hi_agent.runtime.harness.executor import HarnessExecutor
from hi_agent.runtime.harness.governance import GovernanceEngine
from hi_agent.runtime.harness.permission_rules import (
    DenialCounter,
    PermissionAction,
    PermissionDecision,
    PermissionGate,
    PermissionGateDecision,
    ToolPermissionRule,
    ToolPermissionRules,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_spec(
    action_id: str = "act-001",
    capability_name: str = "bash",
    payload: dict | None = None,
) -> ActionSpec:
    """Return a minimal ActionSpec that passes governance (READ_ONLY, no approval)."""
    from agent_kernel.kernel.contracts import EffectClass, SideEffectClass

    return ActionSpec(
        action_id=action_id,
        action_type="read",
        capability_name=capability_name,
        payload=payload or {"command": "rm -rf /"},
        effect_class=EffectClass.READ_ONLY,
        side_effect_class=SideEffectClass.READ_ONLY,
        approval_required=False,
    )


def _make_deny_gate() -> PermissionGate:
    """Return a PermissionGate that always denies any tool call."""
    deny_rule = ToolPermissionRule(
        name="deny-all",
        tool_name=None,  # matches any tool
        input_field=None,  # matches any input
        glob_pattern=None,
        action=PermissionAction.DENY,
        reason="All tool calls blocked by policy.",
    )
    rules = ToolPermissionRules([deny_rule])
    counter = DenialCounter(escalation_threshold=5)
    return PermissionGate(rules=rules, denial_counter=counter)


def _make_mock_deny_gate() -> MagicMock:
    """Return a mock PermissionGate whose check() always returns a DENY decision."""
    mock_gate = MagicMock(spec=PermissionGate)
    deny_decision = PermissionDecision(
        action=PermissionAction.DENY,
        rule_name="mock-deny-rule",
        reason="Denied by mock gate.",
        tool_name="bash",
    )
    mock_gate.check.return_value = PermissionGateDecision(
        escalated=False,
        permission_decision=deny_decision,
        denial_count=1,
        escalation_reason=None,
    )
    return mock_gate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHarnessExecutorPermissionGateDeny:
    """HarnessExecutor must short-circuit with permission_denied on DENY gate."""

    def test_harness_executor_denies_when_gate_denies(self) -> None:
        """When PermissionGate returns DENY, execute() must return error_code='permission_denied'.

        The check happens before governance (Step 0 in the executor pipeline),
        so no capability_invoker is needed and no governance rules are hit.
        """
        # --- Arrange ---
        mock_gate = _make_mock_deny_gate()
        governance = GovernanceEngine()
        executor = HarnessExecutor(
            governance=governance,
            capability_invoker=None,  # must not be reached
            permission_gate=mock_gate,
            evidence_store=EvidenceStore(),
        )
        spec = _make_simple_spec()

        # --- Act ---
        result = executor.execute(spec)

        # --- Assert ---
        assert result.error_code == "permission_denied", (
            f"Expected error_code='permission_denied', got {result.error_code!r}"
        )
        assert result.state == ActionState.FAILED
        mock_gate.check.assert_called_once_with(
            run_id="",  # metadata["run_id"] defaults to ""
            tool_name=spec.capability_name,
            tool_input=spec.payload,
        )

    def test_harness_executor_denies_via_real_gate(self) -> None:
        """Same assertion using a real PermissionGate (not a mock)."""
        gate = _make_deny_gate()
        governance = GovernanceEngine()
        executor = HarnessExecutor(
            governance=governance,
            capability_invoker=None,
            permission_gate=gate,
            evidence_store=EvidenceStore(),
        )
        spec = _make_simple_spec(capability_name="bash", payload={"command": "ls"})

        result = executor.execute(spec)

        assert result.error_code == "permission_denied"
        assert result.state == ActionState.FAILED
        assert result.error_message is not None and len(result.error_message) > 0

    def test_harness_executor_allows_when_gate_allows(self) -> None:
        """When PermissionGate returns ALLOW, execution proceeds past the gate.

        A missing capability_invoker will cause a RuntimeError on dispatch,
        but that means the gate was passed — we assert error_code is NOT
        'permission_denied'.
        """
        allow_rule = ToolPermissionRule(
            name="allow-all",
            tool_name=None,
            input_field=None,
            glob_pattern=None,
            action=PermissionAction.ALLOW,
            reason="All allowed.",
        )
        rules = ToolPermissionRules([allow_rule])
        counter = DenialCounter()
        gate = PermissionGate(rules=rules, denial_counter=counter)

        governance = GovernanceEngine()
        executor = HarnessExecutor(
            governance=governance,
            capability_invoker=None,  # will fail at dispatch — intentional
            permission_gate=gate,
            evidence_store=EvidenceStore(),
        )
        spec = _make_simple_spec()

        result = executor.execute(spec)

        # Gate was passed, but dispatch raised RuntimeError → harness_execution_failed
        assert result.error_code != "permission_denied", (
            "ALLOW gate must not produce permission_denied"
        )
        assert result.error_code == "harness_execution_failed"

    def test_harness_executor_no_gate_proceeds_to_governance(self) -> None:
        """When no permission_gate is provided, the executor proceeds to governance."""
        governance = GovernanceEngine()
        executor = HarnessExecutor(
            governance=governance,
            capability_invoker=None,
            permission_gate=None,  # no gate
            evidence_store=EvidenceStore(),
        )
        spec = _make_simple_spec()

        result = executor.execute(spec)

        # Without gate, governance passes (READ_ONLY spec), then dispatch fails
        assert result.error_code != "permission_denied"
        assert result.error_code == "harness_execution_failed"

    def test_permission_denied_error_message_is_gate_reason(self) -> None:
        """The error_message in a DENY result must match the gate's denial reason."""
        deny_reason = "Blocked by security policy: rm -rf detected."
        mock_gate = MagicMock(spec=PermissionGate)
        deny_decision = PermissionDecision(
            action=PermissionAction.DENY,
            rule_name="security-rule",
            reason=deny_reason,
            tool_name="bash",
        )
        mock_gate.check.return_value = PermissionGateDecision(
            escalated=False,
            permission_decision=deny_decision,
            denial_count=1,
        )

        governance = GovernanceEngine()
        executor = HarnessExecutor(
            governance=governance,
            capability_invoker=None,
            permission_gate=mock_gate,
            evidence_store=EvidenceStore(),
        )
        spec = _make_simple_spec()

        result = executor.execute(spec)

        assert result.error_message == deny_reason
