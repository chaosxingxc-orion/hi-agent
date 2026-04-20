"""Harness action executor with full lifecycle tracking."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from hi_agent.harness.contracts import (
    ActionResult,
    ActionSpec,
    ActionState,
    EvidenceRecord,
)
from hi_agent.harness.evidence_store import EvidenceStore
from hi_agent.harness.governance import GovernanceEngine

if TYPE_CHECKING:
    from hi_agent.harness.permission_rules import PermissionGate


class HarnessExecutor:
    """Unified action executor with full lifecycle tracking.

    Wraps the capability invoker with governance, evidence collection,
    and action state management. All external operations flow through
    this executor.
    """

    def __init__(
        self,
        governance: GovernanceEngine,
        capability_invoker: Any | None = None,
        evidence_store: EvidenceStore | None = None,
        permission_gate: PermissionGate | None = None,
        artifact_registry: Any | None = None,
    ) -> None:
        """Initialize executor with governance and optional dependencies.

        Args:
            governance: Governance engine for rule enforcement.
            capability_invoker: Optional capability invoker (from hi_agent.capability).
                Must have an ``invoke(name, payload)`` method.
            evidence_store: Optional evidence store. Created internally if None.
            permission_gate: Optional PermissionGate for fine-grained per-tool
                permission checks before action dispatch. When provided, DENY
                decisions short-circuit execution before governance checks.
            artifact_registry: Optional ArtifactRegistry for typed artifact
                persistence alongside raw evidence records.
        """
        self._governance = governance
        self._invoker = capability_invoker
        self._evidence_store = evidence_store or EvidenceStore()
        self._permission_gate = permission_gate
        self._artifact_registry = artifact_registry
        self._action_states: dict[str, ActionState] = {}
        self._action_results: dict[str, ActionResult] = {}

    def execute(self, spec: ActionSpec) -> ActionResult:
        """Execute action through full harness pipeline.

        Pipeline steps:
        1. Validate governance rules.
        2. Check approval if required.
        3. Generate idempotency_key if missing for external writes.
        4. Dispatch to capability invoker.
        5. Collect evidence.
        6. Track action state.
        7. Handle retries per policy.

        Args:
            spec: The action specification to execute.

        Returns:
            ActionResult with outcome, evidence_ref, and state.
        """
        self._action_states[spec.action_id] = ActionState.PREPARED

        # Step 0: Permission gate check (before governance)
        if self._permission_gate is not None:
            try:
                from hi_agent.harness.permission_rules import PermissionAction

                gate_decision = self._permission_gate.check(
                    run_id=spec.metadata.get("run_id", ""),
                    tool_name=spec.capability_name,
                    tool_input=spec.payload,
                )
                if gate_decision.permission_decision.action == PermissionAction.DENY:
                    self._action_states[spec.action_id] = ActionState.FAILED
                    result = ActionResult(
                        action_id=spec.action_id,
                        state=ActionState.FAILED,
                        error_code="permission_denied",
                        error_message=gate_decision.permission_decision.reason,
                    )
                    self._action_results[spec.action_id] = result
                    return result
            except Exception as _gate_exc:
                # Permission gate internal error: fail-closed to prevent unguarded execution.
                logger.error(
                    "PermissionGate raised an unexpected exception for action_id=%s; "
                    "treating as DENY. Error: %s",
                    spec.action_id,
                    _gate_exc,
                    exc_info=True,
                )
                self._action_states[spec.action_id] = ActionState.FAILED
                result = ActionResult(
                    action_id=spec.action_id,
                    state=ActionState.FAILED,
                    error_code="permission_gate_error",
                    error_message=f"Permission gate internal error: {_gate_exc}",
                )
                self._action_results[spec.action_id] = result
                return result

        # Step 1-2: Governance check
        allowed, reason = self._governance.can_execute(spec)
        if not allowed:
            if spec.approval_required and "not been approved" in reason:
                self._action_states[spec.action_id] = ActionState.APPROVAL_PENDING
                self._governance.request_approval(spec)
                result = ActionResult(
                    action_id=spec.action_id,
                    state=ActionState.APPROVAL_PENDING,
                    error_code="approval_pending",
                    error_message=reason,
                )
            else:
                self._action_states[spec.action_id] = ActionState.FAILED
                result = ActionResult(
                    action_id=spec.action_id,
                    state=ActionState.FAILED,
                    error_code="governance_violation",
                    error_message=reason,
                )
            self._action_results[spec.action_id] = result
            return result

        # Step 3: Generate idempotency key if needed
        if not spec.idempotency_key and spec.side_effect_class.value in (
            "external_write",
            "irreversible_submit",
        ):
            spec.idempotency_key = f"idem-{spec.action_id}-{uuid.uuid4().hex[:8]}"

        # Step 4-7: Dispatch with retry
        retry_policy = self._governance.get_retry_policy(spec)
        max_attempts = (retry_policy.max_retries + 1) if retry_policy.retryable else 1

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            self._action_states[spec.action_id] = ActionState.DISPATCHED
            start_ms = _now_ms()
            try:
                output = self._dispatch(spec)
                duration = _now_ms() - start_ms

                # Step 5: Collect evidence
                evidence_ref, artifact_ids = self._collect_evidence(
                    spec.action_id,
                    output,
                    upstream_artifact_ids=spec.upstream_artifact_ids,
                )

                self._action_states[spec.action_id] = ActionState.SUCCEEDED
                result = ActionResult(
                    action_id=spec.action_id,
                    state=ActionState.SUCCEEDED,
                    output=output,
                    evidence_ref=evidence_ref,
                    duration_ms=duration,
                    attempt=attempt,
                    artifact_ids=artifact_ids,
                )
                self._action_results[spec.action_id] = result
                return result

            except Exception as exc:
                last_error = exc
                duration = _now_ms() - start_ms
                if attempt < max_attempts:
                    continue

        # All retries exhausted
        self._action_states[spec.action_id] = ActionState.FAILED
        result = ActionResult(
            action_id=spec.action_id,
            state=ActionState.FAILED,
            error_code="harness_execution_failed",
            error_message=str(last_error) if last_error else "Unknown error",
            duration_ms=_now_ms() - start_ms if last_error else 0,
            attempt=max_attempts,
        )
        self._action_results[spec.action_id] = result
        return result

    def get_action_state(self, action_id: str) -> ActionState | None:
        """Get the current state of an action.

        Args:
            action_id: The action identifier.

        Returns:
            The current ActionState, or None if unknown.
        """
        return self._action_states.get(action_id)

    def get_evidence(self, action_id: str) -> list[EvidenceRecord]:
        """Get all evidence records for an action.

        Args:
            action_id: The action identifier.

        Returns:
            List of evidence records.
        """
        return self._evidence_store.get_by_action(action_id)

    def _dispatch(self, spec: ActionSpec) -> Any:
        """Dispatch action to capability invoker.

        Args:
            spec: The action specification.

        Returns:
            Output from the capability handler.

        Raises:
            RuntimeError: If no invoker is configured.
        """
        if self._invoker is None:
            raise RuntimeError("No capability invoker configured")
        return self._invoker.invoke(spec.capability_name, spec.payload)

    def _collect_evidence(
        self,
        action_id: str,
        output: Any,
        *,
        upstream_artifact_ids: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        """Create and store an evidence record from action output.

        Args:
            action_id: The action that produced this output.
            output: Raw output from the capability handler.
            upstream_artifact_ids: Artifact IDs from prior actions that fed
                into producing this output.  Passed as ``source_refs`` to
                the artifact adapter so lineage is recorded on each artifact.

        Returns:
            A tuple of (evidence_ref, artifact_ids) where artifact_ids is the
            list of IDs for any typed artifacts persisted during this call.
        """
        evidence_ref = f"ev-{action_id}-{uuid.uuid4().hex[:8]}"
        record = EvidenceRecord(
            evidence_ref=evidence_ref,
            action_id=action_id,
            evidence_type="output",
            content={"raw": output} if not isinstance(output, dict) else output,
            timestamp=_iso_now(),
        )
        self._evidence_store.store(record)

        # Persist typed artifact alongside raw evidence when registry is available.
        artifact_ids: list[str] = []
        if self._artifact_registry is not None and output is not None:
            try:
                from hi_agent.artifacts.adapters import OutputToArtifactAdapter

                adapter = OutputToArtifactAdapter()
                for artifact in adapter.adapt(
                    action_id,
                    output,
                    source_refs=upstream_artifact_ids or [],
                ):
                    self._artifact_registry.store(artifact)
                    artifact_ids.append(artifact.artifact_id)
            except Exception as exc:
                logger.warning(
                    "HarnessExecutor._collect_evidence: artifact persistence failed: %s", exc
                )

        return evidence_ref, artifact_ids


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.monotonic() * 1000)


def _iso_now() -> str:
    """Return current UTC time in ISO-8601 format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
