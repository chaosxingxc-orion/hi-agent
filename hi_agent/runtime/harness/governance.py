"""Dual-dimension governance engine for Harness actions."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from hi_agent.runtime.harness.contracts import (
    ActionSpec,
    EffectClass,
    SideEffectClass,
)

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\bmkfs\b"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bcurl\b.*\|\s*bash"),
    re.compile(r"\bwget\b.*\|\s*sh"),
]


@dataclass
class RetryPolicy:
    """Retry policy derived from action governance rules.

    Attributes:
        max_retries: Maximum number of retry attempts.
        backoff_base_ms: Initial backoff duration in milliseconds.
        backoff_max_ms: Maximum backoff duration in milliseconds.
        retryable: Whether the action is eligible for retry at all.
    """

    max_retries: int
    backoff_base_ms: int = 1000
    backoff_max_ms: int = 30000
    retryable: bool = True


class GovernanceEngine:
    """Enforces dual-dimension governance on all actions.

    Rules:
    - IRREVERSIBLE_WRITE or IRREVERSIBLE_SUBMIT actions MUST have
      approval_required=True.
    - Actions with side_effect_class >= EXTERNAL_WRITE require a
      non-empty idempotency_key.
    - Retry policy respects effect_class (no retry for irreversible).
    - COMPENSATABLE_WRITE actions must have a registered compensation
      handler to be executable.
    """

    def __init__(self) -> None:
        """Initialize governance engine with empty state."""
        self._compensation_handlers: dict[str, Callable] = {}
        self._approval_queue: list[ActionSpec] = []
        self._approved: set[str] = set()
        self._rejected: dict[str, str] = {}  # action_id -> reason

    def check_dangerous_command(self, command: str) -> list[str]:
        """Return dangerous command pattern matches for a shell command."""
        hits = []
        for pat in DANGEROUS_PATTERNS:
            if pat.search(command):
                hits.append(f"dangerous pattern: {pat.pattern!r}")
        return hits

    def validate(self, spec: ActionSpec) -> list[str]:
        """Validate action spec against governance rules.

        Args:
            spec: The action specification to validate.

        Returns:
            List of violation descriptions. Empty means valid.
        """
        violations: list[str] = []

        # Rule 1: Irreversible actions require approval
        if spec.effect_class == EffectClass.IRREVERSIBLE_WRITE and not spec.approval_required:
            violations.append("IRREVERSIBLE_WRITE effect_class requires approval_required=True")
        if (
            spec.side_effect_class == SideEffectClass.IRREVERSIBLE_SUBMIT
            and not spec.approval_required
        ):
            violations.append(
                "IRREVERSIBLE_SUBMIT side_effect_class requires approval_required=True"
            )

        # Rule 2: External writes require idempotency key
        _external_side_effects = {
            SideEffectClass.EXTERNAL_WRITE,
            SideEffectClass.IRREVERSIBLE_SUBMIT,
        }
        if spec.side_effect_class in _external_side_effects and not spec.idempotency_key:
            violations.append(
                f"{spec.side_effect_class.value} requires a non-empty idempotency_key"
            )

        # Rule 3: Compensatable writes need registered handler
        if (
            spec.effect_class == EffectClass.COMPENSATABLE_WRITE
            and spec.action_type not in self._compensation_handlers
        ):
            violations.append(
                f"COMPENSATABLE_WRITE requires a registered compensation "
                f"handler for action_type {spec.action_type!r}"
            )

        return violations

    def can_execute(self, spec: ActionSpec) -> tuple[bool, str]:
        """Check if action can proceed right now.

        Args:
            spec: The action specification to check.

        Returns:
            Tuple of (allowed, reason). reason is empty when allowed.
        """
        violations = self.validate(spec)
        if violations:
            return False, "; ".join(violations)

        if spec.approval_required and spec.action_id not in self._approved:
            if spec.action_id in self._rejected:
                reason = self._rejected[spec.action_id]
                return False, f"Action was rejected: {reason}"
            return False, "Action requires approval but has not been approved"

        return True, ""

    def request_approval(self, spec: ActionSpec) -> None:
        """Queue action for human approval.

        Args:
            spec: The action specification awaiting approval.
        """
        self._approval_queue.append(spec)

    def approve(self, action_id: str, *, approver_id: str = "") -> None:
        """Mark an action as approved.

        Args:
            action_id: The action to approve.
            approver_id: Principal approving the action; enforced against submitter for SOC.

        Raises:
            SeparationOfConcernError: If approver is the same as the action submitter.
        """
        # Enforce submitter/approver separation when both are present.
        spec = next((s for s in self._approval_queue if s.action_id == action_id), None)
        submitter_id = spec.submitter_id if spec is not None else ""

        from hi_agent.auth.soc_guard import enforce_submitter_approver_separation

        enforce_submitter_approver_separation(
            submitter=submitter_id,
            approver=approver_id,
            enabled=bool(submitter_id and approver_id),
        )

        self._approved.add(action_id)
        self._approval_queue = [s for s in self._approval_queue if s.action_id != action_id]

    def reject(self, action_id: str, reason: str) -> None:
        """Reject an action with a reason.

        Args:
            action_id: The action to reject.
            reason: Human-readable rejection reason.
        """
        self._rejected[action_id] = reason
        self._approval_queue = [s for s in self._approval_queue if s.action_id != action_id]

    def register_compensation(self, action_type: str, handler: Callable) -> None:
        """Register a compensation handler for an action type.

        Args:
            action_type: The action type this handler compensates.
            handler: Callable that performs compensation.
        """
        self._compensation_handlers[action_type] = handler

    def get_compensation_handler(self, action_type: str) -> Callable | None:
        """Retrieve compensation handler for an action type.

        Args:
            action_type: The action type to look up.

        Returns:
            The handler, or None if not registered.
        """
        return self._compensation_handlers.get(action_type)

    def get_retry_policy(self, spec: ActionSpec) -> RetryPolicy:
        """Derive retry policy from action governance classification.

        Args:
            spec: The action specification.

        Returns:
            RetryPolicy with appropriate settings.
        """
        # Irreversible actions must not be retried
        if spec.effect_class == EffectClass.IRREVERSIBLE_WRITE:
            return RetryPolicy(max_retries=0, retryable=False)
        if spec.side_effect_class == SideEffectClass.IRREVERSIBLE_SUBMIT:
            return RetryPolicy(max_retries=0, retryable=False)

        # Compensatable writes: limited retries
        if spec.effect_class == EffectClass.COMPENSATABLE_WRITE:
            return RetryPolicy(
                max_retries=min(spec.max_retries, 2),
                backoff_base_ms=2000,
                retryable=True,
            )

        # Idempotent writes and reads: use spec max_retries
        return RetryPolicy(
            max_retries=spec.max_retries,
            retryable=spec.max_retries > 0,
        )

    @property
    def pending_approvals(self) -> list[ActionSpec]:
        """Return list of actions pending approval."""
        return list(self._approval_queue)
