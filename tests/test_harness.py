"""Tests for the Harness governance and execution subsystem."""

from __future__ import annotations

import pytest
from hi_agent.harness.contracts import (
    ActionSpec,
    ActionState,
    EffectClass,
    EvidenceRecord,
    SideEffectClass,
)
from hi_agent.harness.evidence_store import EvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_only_spec(action_id: str = "act-1") -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        action_type="read",
        capability_name="search",
        payload={"q": "test"},
    )


def _irreversible_spec(
    action_id: str = "act-irr",
    approval: bool = False,
    idempotency_key: str = "key-1",
) -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        action_type="submit",
        capability_name="deploy",
        payload={"target": "prod"},
        effect_class=EffectClass.IRREVERSIBLE_WRITE,
        side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
        approval_required=approval,
        idempotency_key=idempotency_key,
    )


def _external_write_spec(
    action_id: str = "act-ext",
    idempotency_key: str = "",
) -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        action_type="mutate",
        capability_name="api_call",
        payload={"url": "/update"},
        effect_class=EffectClass.IDEMPOTENT_WRITE,
        side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        idempotency_key=idempotency_key,
    )


def _compensatable_spec(
    action_id: str = "act-comp",
    action_type: str = "mutate",
) -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        action_type=action_type,
        capability_name="transfer",
        payload={"amount": 100},
        effect_class=EffectClass.COMPENSATABLE_WRITE,
        side_effect_class=SideEffectClass.LOCAL_WRITE,
    )


class _MockInvoker:
    """Mock capability invoker for testing."""

    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        fail_times: int = 0,
    ) -> None:
        self.responses = responses or {}
        self.fail_times = fail_times
        self.call_count = 0

    def invoke(self, name: str, payload: dict) -> dict:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise RuntimeError(f"Simulated failure #{self.call_count}")
        return self.responses.get(name, {"status": "ok"})


# ===========================================================================
# GovernanceEngine.validate
# ===========================================================================

class TestGovernanceValidate:
    """Test governance validation rules."""

    def test_read_only_passes(self) -> None:
        gov = GovernanceEngine()
        assert gov.validate(_read_only_spec()) == []

    def test_irreversible_write_without_approval_fails(self) -> None:
        gov = GovernanceEngine()
        spec = ActionSpec(
            action_id="x",
            action_type="submit",
            capability_name="deploy",
            payload={},
            effect_class=EffectClass.IRREVERSIBLE_WRITE,
            side_effect_class=SideEffectClass.LOCAL_WRITE,
            approval_required=False,
        )
        violations = gov.validate(spec)
        assert any("IRREVERSIBLE_WRITE" in v for v in violations)

    def test_irreversible_submit_without_approval_fails(self) -> None:
        gov = GovernanceEngine()
        spec = ActionSpec(
            action_id="x",
            action_type="submit",
            capability_name="deploy",
            payload={},
            effect_class=EffectClass.READ_ONLY,
            side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
            approval_required=False,
            idempotency_key="k",
        )
        violations = gov.validate(spec)
        assert any("IRREVERSIBLE_SUBMIT" in v for v in violations)

    def test_external_write_without_idempotency_key_fails(self) -> None:
        gov = GovernanceEngine()
        spec = _external_write_spec(idempotency_key="")
        violations = gov.validate(spec)
        assert any("idempotency_key" in v for v in violations)

    def test_external_write_with_idempotency_key_passes(self) -> None:
        gov = GovernanceEngine()
        spec = _external_write_spec(idempotency_key="key-123")
        assert gov.validate(spec) == []

    def test_compensatable_without_handler_fails(self) -> None:
        gov = GovernanceEngine()
        spec = _compensatable_spec()
        violations = gov.validate(spec)
        assert any("compensation" in v.lower() for v in violations)

    def test_compensatable_with_handler_passes(self) -> None:
        gov = GovernanceEngine()
        gov.register_compensation("mutate", lambda x: None)
        spec = _compensatable_spec()
        assert gov.validate(spec) == []

    def test_irreversible_both_dimensions_two_violations(self) -> None:
        """Both effect_class and side_effect_class irreversible, no approval, no key."""
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=False, idempotency_key="")
        violations = gov.validate(spec)
        assert len(violations) >= 2


# ===========================================================================
# GovernanceEngine.can_execute
# ===========================================================================

class TestGovernanceCanExecute:
    """Test governance execution gating."""

    def test_read_only_allowed(self) -> None:
        gov = GovernanceEngine()
        allowed, reason = gov.can_execute(_read_only_spec())
        assert allowed is True
        assert reason == ""

    def test_unapproved_irreversible_blocked(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        allowed, reason = gov.can_execute(spec)
        assert allowed is False
        assert "approval" in reason.lower()

    def test_approved_irreversible_allowed(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        gov.approve(spec.action_id)
        allowed, _ = gov.can_execute(spec)
        assert allowed is True

    def test_rejected_action_blocked(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        gov.reject(spec.action_id, "too risky")
        allowed, reason = gov.can_execute(spec)
        assert allowed is False
        assert "rejected" in reason.lower()

    def test_validation_failure_blocks(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=False, idempotency_key="")
        allowed, _ = gov.can_execute(spec)
        assert allowed is False


# ===========================================================================
# GovernanceEngine.approve / reject flow
# ===========================================================================

class TestGovernanceApprovalFlow:
    """Test approval queue management."""

    def test_request_and_approve(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        gov.request_approval(spec)
        assert len(gov.pending_approvals) == 1
        gov.approve(spec.action_id)
        assert len(gov.pending_approvals) == 0
        assert spec.action_id in gov._approved

    def test_request_and_reject(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        gov.request_approval(spec)
        gov.reject(spec.action_id, "denied")
        assert len(gov.pending_approvals) == 0
        assert spec.action_id in gov._rejected


# ===========================================================================
# GovernanceEngine.get_retry_policy
# ===========================================================================

class TestGovernanceRetryPolicy:
    """Test retry policy derivation."""

    def test_irreversible_write_no_retry(self) -> None:
        gov = GovernanceEngine()
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        policy = gov.get_retry_policy(spec)
        assert policy.retryable is False
        assert policy.max_retries == 0

    def test_irreversible_submit_no_retry(self) -> None:
        gov = GovernanceEngine()
        spec = ActionSpec(
            action_id="x",
            action_type="submit",
            capability_name="deploy",
            payload={},
            effect_class=EffectClass.READ_ONLY,
            side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
            approval_required=True,
            idempotency_key="k",
        )
        policy = gov.get_retry_policy(spec)
        assert policy.retryable is False

    def test_read_only_uses_spec_retries(self) -> None:
        gov = GovernanceEngine()
        spec = ActionSpec(
            action_id="x",
            action_type="read",
            capability_name="search",
            payload={},
            max_retries=5,
        )
        policy = gov.get_retry_policy(spec)
        assert policy.retryable is True
        assert policy.max_retries == 5

    def test_compensatable_capped_retries(self) -> None:
        gov = GovernanceEngine()
        spec = _compensatable_spec()
        spec.max_retries = 10
        policy = gov.get_retry_policy(spec)
        assert policy.max_retries <= 2

    def test_idempotent_write_retryable(self) -> None:
        gov = GovernanceEngine()
        spec = _external_write_spec(idempotency_key="k")
        spec.max_retries = 3
        policy = gov.get_retry_policy(spec)
        assert policy.retryable is True
        assert policy.max_retries == 3


# ===========================================================================
# HarnessExecutor.execute
# ===========================================================================

class TestHarnessExecutorExecute:
    """Test full execution pipeline."""

    def test_successful_execution(self) -> None:
        gov = GovernanceEngine()
        invoker = _MockInvoker(responses={"search": {"results": [1, 2]}})
        executor = HarnessExecutor(gov, invoker)

        spec = _read_only_spec()
        result = executor.execute(spec)

        assert result.state == ActionState.SUCCEEDED
        assert result.output == {"results": [1, 2]}
        assert result.evidence_ref is not None
        assert result.attempt == 1

    def test_governance_blocks_execution(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker())

        spec = _irreversible_spec(approval=False, idempotency_key="")
        result = executor.execute(spec)

        assert result.state == ActionState.FAILED
        assert result.error_code == "governance_violation"

    def test_approval_pending_state(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker())

        spec = _irreversible_spec(approval=True, idempotency_key="k")
        result = executor.execute(spec)

        assert result.state == ActionState.APPROVAL_PENDING
        assert executor.get_action_state(spec.action_id) == ActionState.APPROVAL_PENDING

    def test_execute_after_approval(self) -> None:
        gov = GovernanceEngine()
        invoker = _MockInvoker(responses={"deploy": {"deployed": True}})
        executor = HarnessExecutor(gov, invoker)

        spec = _irreversible_spec(approval=True, idempotency_key="k")
        # First attempt: pending
        r1 = executor.execute(spec)
        assert r1.state == ActionState.APPROVAL_PENDING

        # Approve and retry
        gov.approve(spec.action_id)
        r2 = executor.execute(spec)
        assert r2.state == ActionState.SUCCEEDED
        assert r2.output == {"deployed": True}

    def test_no_invoker_fails(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, capability_invoker=None)

        spec = _read_only_spec()
        result = executor.execute(spec)

        assert result.state == ActionState.FAILED
        assert "invoker" in result.error_message.lower()

    def test_retry_on_failure(self) -> None:
        gov = GovernanceEngine()
        invoker = _MockInvoker(
            responses={"search": {"ok": True}},
            fail_times=2,
        )
        executor = HarnessExecutor(gov, invoker)

        spec = _read_only_spec()
        spec.max_retries = 3
        result = executor.execute(spec)

        assert result.state == ActionState.SUCCEEDED
        assert result.attempt == 3  # 2 failures + 1 success
        assert invoker.call_count == 3

    def test_retry_exhausted(self) -> None:
        gov = GovernanceEngine()
        invoker = _MockInvoker(fail_times=100)
        executor = HarnessExecutor(gov, invoker)

        spec = _read_only_spec()
        spec.max_retries = 2
        result = executor.execute(spec)

        assert result.state == ActionState.FAILED
        assert result.error_code == "harness_execution_failed"
        assert result.attempt == 3


# ===========================================================================
# HarnessExecutor evidence collection
# ===========================================================================

class TestHarnessExecutorEvidence:
    """Test evidence collection through executor."""

    def test_evidence_stored_on_success(self) -> None:
        gov = GovernanceEngine()
        store = EvidenceStore()
        invoker = _MockInvoker(responses={"search": {"data": "hello"}})
        executor = HarnessExecutor(gov, invoker, evidence_store=store)

        spec = _read_only_spec()
        result = executor.execute(spec)

        assert result.evidence_ref is not None
        records = executor.get_evidence(spec.action_id)
        assert len(records) == 1
        assert records[0].evidence_ref == result.evidence_ref
        assert records[0].content == {"data": "hello"}

    def test_no_evidence_on_failure(self) -> None:
        gov = GovernanceEngine()
        store = EvidenceStore()
        invoker = _MockInvoker(fail_times=100)
        executor = HarnessExecutor(gov, invoker, evidence_store=store)

        spec = _read_only_spec()
        result = executor.execute(spec)

        assert result.evidence_ref is None
        assert executor.get_evidence(spec.action_id) == []

    def test_evidence_wraps_non_dict_output(self) -> None:
        gov = GovernanceEngine()
        store = EvidenceStore()

        class _StringInvoker:
            def invoke(self, name: str, payload: dict) -> str:
                return "plain text result"

        executor = HarnessExecutor(gov, _StringInvoker(), evidence_store=store)
        spec = _read_only_spec()
        result = executor.execute(spec)

        record = store.get(result.evidence_ref)
        assert record is not None
        assert record.content == {"raw": "plain text result"}


# ===========================================================================
# EvidenceStore CRUD
# ===========================================================================

class TestEvidenceStore:
    """Test evidence store operations."""

    def test_store_and_get(self) -> None:
        store = EvidenceStore()
        record = EvidenceRecord(
            evidence_ref="ev-1",
            action_id="act-1",
            evidence_type="output",
            content={"key": "value"},
            timestamp="2026-01-01T00:00:00Z",
        )
        ref = store.store(record)
        assert ref == "ev-1"
        assert store.get("ev-1") is record

    def test_get_nonexistent_returns_none(self) -> None:
        store = EvidenceStore()
        assert store.get("missing") is None

    def test_get_by_action(self) -> None:
        store = EvidenceStore()
        for i in range(3):
            store.store(EvidenceRecord(
                evidence_ref=f"ev-{i}",
                action_id="act-1",
                evidence_type="output",
            ))
        store.store(EvidenceRecord(
            evidence_ref="ev-other",
            action_id="act-2",
            evidence_type="output",
        ))
        assert len(store.get_by_action("act-1")) == 3
        assert len(store.get_by_action("act-2")) == 1
        assert len(store.get_by_action("act-missing")) == 0

    def test_count(self) -> None:
        store = EvidenceStore()
        assert store.count() == 0
        store.store(EvidenceRecord(
            evidence_ref="ev-1", action_id="a", evidence_type="output"
        ))
        assert store.count() == 1

    def test_empty_ref_raises(self) -> None:
        store = EvidenceStore()
        with pytest.raises(ValueError, match="evidence_ref"):
            store.store(EvidenceRecord(
                evidence_ref="", action_id="a", evidence_type="output"
            ))


# ===========================================================================
# ActionState transitions
# ===========================================================================

class TestActionStateTransitions:
    """Test that executor tracks correct state transitions."""

    def test_success_ends_in_succeeded(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker())
        spec = _read_only_spec()
        executor.execute(spec)
        assert executor.get_action_state(spec.action_id) == ActionState.SUCCEEDED

    def test_failure_ends_in_failed(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker(fail_times=100))
        spec = _read_only_spec()
        executor.execute(spec)
        assert executor.get_action_state(spec.action_id) == ActionState.FAILED

    def test_approval_pending_state_tracked(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker())
        spec = _irreversible_spec(approval=True, idempotency_key="k")
        executor.execute(spec)
        assert executor.get_action_state(spec.action_id) == ActionState.APPROVAL_PENDING

    def test_unknown_action_returns_none(self) -> None:
        gov = GovernanceEngine()
        executor = HarnessExecutor(gov, _MockInvoker())
        assert executor.get_action_state("nonexistent") is None


# ===========================================================================
# Dual-dimension classification combinations
# ===========================================================================

class TestDualDimensionCombinations:
    """Test various effect_class x side_effect_class combinations."""

    @pytest.mark.parametrize(
        "effect, side_effect, approval, idem_key, expect_valid",
        [
            # READ_ONLY x READ_ONLY: always valid
            (EffectClass.READ_ONLY, SideEffectClass.READ_ONLY, False, "", True),
            # IDEMPOTENT_WRITE x LOCAL_WRITE: valid
            (EffectClass.IDEMPOTENT_WRITE, SideEffectClass.LOCAL_WRITE, False, "", True),
            # IDEMPOTENT_WRITE x EXTERNAL_WRITE: needs idem key
            (EffectClass.IDEMPOTENT_WRITE, SideEffectClass.EXTERNAL_WRITE, False, "", False),
            (EffectClass.IDEMPOTENT_WRITE, SideEffectClass.EXTERNAL_WRITE, False, "k", True),
            # IRREVERSIBLE_WRITE x LOCAL_WRITE: needs approval
            (EffectClass.IRREVERSIBLE_WRITE, SideEffectClass.LOCAL_WRITE, False, "", False),
            (EffectClass.IRREVERSIBLE_WRITE, SideEffectClass.LOCAL_WRITE, True, "", True),
            # IRREVERSIBLE_WRITE x IRREVERSIBLE_SUBMIT: needs both
            (EffectClass.IRREVERSIBLE_WRITE, SideEffectClass.IRREVERSIBLE_SUBMIT, False, "", False),
            (EffectClass.IRREVERSIBLE_WRITE, SideEffectClass.IRREVERSIBLE_SUBMIT, True, "k", True),
        ],
    )
    def test_classification_combinations(
        self,
        effect: EffectClass,
        side_effect: SideEffectClass,
        approval: bool,
        idem_key: str,
        expect_valid: bool,
    ) -> None:
        gov = GovernanceEngine()
        spec = ActionSpec(
            action_id="combo-test",
            action_type="mutate",
            capability_name="test",
            payload={},
            effect_class=effect,
            side_effect_class=side_effect,
            approval_required=approval,
            idempotency_key=idem_key,
        )
        violations = gov.validate(spec)
        if expect_valid:
            assert violations == [], f"Expected valid but got: {violations}"
        else:
            assert len(violations) > 0, "Expected violations but got none"
