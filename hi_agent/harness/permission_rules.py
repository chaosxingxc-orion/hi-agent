"""
Tool Permission Rules for hi-agent.

Provides fine-grained per-tool permission rules with glob pattern matching
on tool inputs. A DenialCounter tracks consecutive rejections and
automatically escalates to Human Gate (Gate D: final_approval) when
the threshold is exceeded.

Inspired by Claude Code's deep permission context system.

Usage:
    rules = ToolPermissionRules.from_config([
        {"tool": "bash", "field": "command", "pattern": "rm -rf *", "action": "deny"},
        {"tool": "file_write", "field": "path", "pattern": "/etc/*", "action": "deny"},
        {"tool": "web_search", "action": "allow"},
    ])
    decision = rules.evaluate("bash", {"command": "rm -rf /"})
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PermissionAction(StrEnum):
    """Possible outcomes of a permission rule evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # Pause and wait for human approval (Gate D)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PermissionDecision:
    """Result of evaluating a tool call against permission rules.

    Attributes:
        action: The resolved permission action.
        rule_name: Name of the matched rule, or None if no rule matched.
        reason: Human-readable explanation of the decision.
        tool_name: The tool that was evaluated.
        matched_input_field: The input field that triggered a match, if any.
        matched_pattern: The glob pattern that matched, if any.
    """

    action: PermissionAction
    rule_name: str | None
    reason: str
    tool_name: str
    matched_input_field: str | None = None
    matched_pattern: str | None = None


@dataclass
class ToolPermissionRule:
    """A single permission rule for a tool, optionally scoped by input field and glob pattern.

    Attributes:
        name: Human-readable label used in logs and decisions.
        tool_name: Name of the tool this rule applies to.  None matches all tools.
        input_field: Key in the tool's input dict to inspect.  None skips field matching.
        glob_pattern: fnmatch-style pattern applied to the field value.  None matches any value.
        action: The permission action to apply when this rule matches.
        reason: Explanation surfaced in PermissionDecision.reason.
    """

    name: str
    tool_name: str | None
    input_field: str | None
    glob_pattern: str | None
    action: PermissionAction
    reason: str = ""

    def matches_tool(self, tool_name: str) -> bool:
        """Return True if this rule applies to the given tool name.

        Args:
            tool_name: The name of the tool being evaluated.

        Returns:
            True when tool_name is None (wildcard) or matches case-insensitively.
        """
        if self.tool_name is None:
            return True
        return self.tool_name.lower() == tool_name.lower()

    def matches_input(self, tool_input: dict[str, Any]) -> bool:
        """Return True if the tool input satisfies this rule's field/pattern constraint.

        Args:
            tool_input: The dict of arguments passed to the tool.

        Returns:
            True when no field constraint is defined, or when the field value
            matches the glob pattern (or no pattern is defined).
        """
        if self.input_field is None:
            return True

        field_value = tool_input.get(self.input_field)
        if field_value is None:
            # Field not present in input — no match
            return False

        if self.glob_pattern is None:
            return True

        return fnmatch.fnmatch(str(field_value), self.glob_pattern)


# ---------------------------------------------------------------------------
# ToolPermissionRules — ordered rule list with first-match-wins semantics
# ---------------------------------------------------------------------------


class ToolPermissionRules:
    """Ordered collection of ToolPermissionRule instances.

    Rules are evaluated in insertion order; the first matching rule wins.
    If no rule matches, the default decision is ASK (least-privilege).
    """

    def __init__(self, rules: list[ToolPermissionRule] | None = None) -> None:
        """Initialise with an optional list of rules.

        Args:
            rules: Initial rule list.  Order is preserved.
        """
        self._rules: list[ToolPermissionRule] = list(rules or [])

    def evaluate(self, tool_name: str, tool_input: dict[str, Any]) -> PermissionDecision:
        """Evaluate a tool call against all rules (first-match-wins).

        Args:
            tool_name: The tool being invoked.
            tool_input: The arguments passed to the tool.

        Returns:
            PermissionDecision representing the first matching rule, or a
            default ASK decision when no rule matches.
        """
        for rule in self._rules:
            if rule.matches_tool(tool_name) and rule.matches_input(tool_input):
                return PermissionDecision(
                    action=rule.action,
                    rule_name=rule.name,
                    reason=rule.reason or f"Matched rule '{rule.name}'",
                    tool_name=tool_name,
                    matched_input_field=rule.input_field,
                    matched_pattern=rule.glob_pattern,
                )

        # No rule matched — default to ASK (do not silently allow)
        return PermissionDecision(
            action=PermissionAction.ASK,
            rule_name=None,
            reason="No permission rule matched; defaulting to human review.",
            tool_name=tool_name,
        )

    def add_rule(self, rule: ToolPermissionRule) -> None:
        """Append a rule to the end of the rule list.

        Args:
            rule: The rule to add.
        """
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove the first rule whose name matches exactly.

        Args:
            name: The rule name to remove.

        Returns:
            True if a rule was removed, False if no matching rule was found.
        """
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                del self._rules[i]
                return True
        return False

    @classmethod
    def from_config(cls, config_list: list[dict[str, Any]]) -> "ToolPermissionRules":
        """Build a ToolPermissionRules instance from a list of config dicts.

        Supported keys per dict:
            - ``name``    — rule label (auto-generated if omitted)
            - ``tool``    — maps to tool_name
            - ``field``   — maps to input_field
            - ``pattern`` — maps to glob_pattern
            - ``action``  — "allow" | "deny" | "ask"
            - ``reason``  — human-readable explanation

        Args:
            config_list: List of rule configuration dicts.

        Returns:
            ToolPermissionRules with rules in the same order as config_list.
        """
        rules: list[ToolPermissionRule] = []
        for idx, cfg in enumerate(config_list):
            action_str = cfg.get("action", "ask")
            try:
                action = PermissionAction(action_str)
            except ValueError:
                action = PermissionAction.ASK

            name = cfg.get("name") or f"rule-{idx}"
            rules.append(
                ToolPermissionRule(
                    name=name,
                    tool_name=cfg.get("tool"),
                    input_field=cfg.get("field"),
                    glob_pattern=cfg.get("pattern"),
                    action=action,
                    reason=cfg.get("reason", ""),
                )
            )
        return cls(rules)

    @classmethod
    def default_safe_rules(cls) -> "ToolPermissionRules":
        """Return a conservative default rule set for production deployments.

        Included rules:
        - DENY ``rm -rf *`` variants in bash commands
        - DENY ``rm -r *`` variants in bash commands
        - DENY writes to ``/etc/*``
        - DENY writes to ``/boot/*``
        - DENY writes to ``/sys/*``
        - DENY writes to ``/proc/*``
        - DENY writes to ``~/.ssh/*``
        - ASK (default fallback) for any unmatched tool

        Returns:
            ToolPermissionRules pre-loaded with safe default rules.
        """
        rules = [
            ToolPermissionRule(
                name="deny-bash-rm-rf",
                tool_name="bash",
                input_field="command",
                glob_pattern="rm -rf *",
                action=PermissionAction.DENY,
                reason="Recursive force-delete commands are not permitted.",
            ),
            ToolPermissionRule(
                name="deny-bash-rm-rf-slash",
                tool_name="bash",
                input_field="command",
                glob_pattern="rm -rf /*",
                action=PermissionAction.DENY,
                reason="Recursive force-delete of root path is blocked.",
            ),
            ToolPermissionRule(
                name="deny-bash-rm-r",
                tool_name="bash",
                input_field="command",
                glob_pattern="rm -r *",
                action=PermissionAction.DENY,
                reason="Recursive delete commands require human approval.",
            ),
            ToolPermissionRule(
                name="deny-file-write-etc",
                tool_name="file_write",
                input_field="path",
                glob_pattern="/etc/*",
                action=PermissionAction.DENY,
                reason="Writing to /etc/ is not permitted.",
            ),
            ToolPermissionRule(
                name="deny-file-write-boot",
                tool_name="file_write",
                input_field="path",
                glob_pattern="/boot/*",
                action=PermissionAction.DENY,
                reason="Writing to /boot/ is not permitted.",
            ),
            ToolPermissionRule(
                name="deny-file-write-sys",
                tool_name="file_write",
                input_field="path",
                glob_pattern="/sys/*",
                action=PermissionAction.DENY,
                reason="Writing to /sys/ is not permitted.",
            ),
            ToolPermissionRule(
                name="deny-file-write-proc",
                tool_name="file_write",
                input_field="path",
                glob_pattern="/proc/*",
                action=PermissionAction.DENY,
                reason="Writing to /proc/ is not permitted.",
            ),
            ToolPermissionRule(
                name="deny-file-write-ssh",
                tool_name="file_write",
                input_field="path",
                glob_pattern="*/.ssh/*",
                action=PermissionAction.DENY,
                reason="Writing to SSH configuration directories is not permitted.",
            ),
        ]
        return cls(rules)

    @property
    def rules(self) -> list[ToolPermissionRule]:
        """Return a shallow copy of the current rule list."""
        return list(self._rules)


# ---------------------------------------------------------------------------
# DenialRecord
# ---------------------------------------------------------------------------


@dataclass
class DenialRecord:
    """An immutable record of a single tool-call denial event.

    Attributes:
        tool_name: The tool that was denied.
        decision: The PermissionDecision that caused the denial.
        denied_at: ISO 8601 UTC timestamp.
        run_id: Identifier of the run that triggered the denial.
    """

    tool_name: str
    decision: PermissionDecision
    denied_at: str
    run_id: str


# ---------------------------------------------------------------------------
# DenialCounter — per-run consecutive denial tracking
# ---------------------------------------------------------------------------


class DenialCounter:
    """Tracks per-run consecutive tool denials and raises an escalation flag.

    Each run is tracked independently via its ``run_id``.  An approval resets
    the counter for that run.  The counter supports a sliding ``window_size``
    so that a burst of denials within the window triggers escalation even if
    separated by unrelated approvals — however, any single approval call
    performs a full reset (conservative policy matching hi-agent's design).

    Args:
        escalation_threshold: Number of consecutive denials before
            ``should_escalate`` returns True.
        window_size: Maximum recent denials to store per run for
            ``get_recent_denials``.
    """

    def __init__(
        self,
        escalation_threshold: int = 5,
        window_size: int = 10,
    ) -> None:
        self._escalation_threshold = escalation_threshold
        self._window_size = window_size
        # run_id → list of DenialRecord (most recent last)
        self._denials: dict[str, list[DenialRecord]] = {}
        # run_id → consecutive denial count since last approval
        self._consecutive: dict[str, int] = {}

    def record_denial(
        self,
        run_id: str,
        tool_name: str,
        decision: PermissionDecision,
    ) -> None:
        """Record a denial event for the given run.

        Args:
            run_id: Identifier of the current run.
            tool_name: The tool that was denied.
            decision: The PermissionDecision that led to this denial.
        """
        record = DenialRecord(
            tool_name=tool_name,
            decision=decision,
            denied_at=datetime.now(tz=timezone.utc).isoformat(),
            run_id=run_id,
        )
        history = self._denials.setdefault(run_id, [])
        history.append(record)
        # Trim to window_size
        if len(history) > self._window_size:
            self._denials[run_id] = history[-self._window_size :]

        self._consecutive[run_id] = self._consecutive.get(run_id, 0) + 1

    def record_approval(self, run_id: str, tool_name: str) -> None:
        """Record an approval event, resetting the consecutive denial count.

        Args:
            run_id: Identifier of the current run.
            tool_name: The tool that was approved (informational only).
        """
        self._consecutive[run_id] = 0

    def should_escalate(self, run_id: str) -> bool:
        """Return True when consecutive denials meet or exceed the threshold.

        Args:
            run_id: Identifier of the current run.

        Returns:
            True if escalation to Gate D (final_approval) is required.
        """
        return self._consecutive.get(run_id, 0) >= self._escalation_threshold

    def get_denial_count(self, run_id: str) -> int:
        """Return the current consecutive denial count for a run.

        Args:
            run_id: Identifier of the current run.

        Returns:
            Number of consecutive denials since the last approval (or run start).
        """
        return self._consecutive.get(run_id, 0)

    def reset(self, run_id: str) -> None:
        """Fully reset all denial tracking for a run.

        Clears both the history and the consecutive counter.

        Args:
            run_id: Identifier of the run to reset.
        """
        self._denials.pop(run_id, None)
        self._consecutive.pop(run_id, None)

    def get_recent_denials(self, run_id: str, n: int = 5) -> list[DenialRecord]:
        """Return the most recent denial records for a run.

        Args:
            run_id: Identifier of the current run.
            n: Maximum number of records to return (most recent last).

        Returns:
            List of up to *n* DenialRecord instances.
        """
        history = self._denials.get(run_id, [])
        return history[-n:]


# ---------------------------------------------------------------------------
# PermissionGateDecision
# ---------------------------------------------------------------------------


@dataclass
class PermissionGateDecision:
    """Combined outcome from PermissionGate.check().

    Attributes:
        escalated: True when denial count has reached the escalation threshold
            and the call must be routed to Gate D (final_approval).
        permission_decision: The underlying PermissionDecision from the rules.
        denial_count: Consecutive denial count at the time of this decision.
        escalation_reason: Human-readable reason for escalation, or None.
    """

    escalated: bool
    permission_decision: PermissionDecision
    denial_count: int
    escalation_reason: str | None = None


# ---------------------------------------------------------------------------
# PermissionGate — unified Rules + Counter integration
# ---------------------------------------------------------------------------


class PermissionGate:
    """Integrates ToolPermissionRules with DenialCounter.

    On each call to :meth:`check`:

    - The tool call is evaluated against the permission rules.
    - If denied, a denial is recorded and escalation is checked.
    - If allowed or asks for human input (ASK treated as approval-path),
      the consecutive counter is reset.

    The returned :class:`PermissionGateDecision` indicates whether the
    caller must route to Gate D (final_approval).

    Args:
        rules: The permission rule set to evaluate against.
        denial_counter: The counter tracking consecutive denials.
    """

    def __init__(
        self,
        rules: ToolPermissionRules,
        denial_counter: DenialCounter,
    ) -> None:
        self._rules = rules
        self._counter = denial_counter

    def check(
        self,
        run_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PermissionGateDecision:
        """Evaluate a tool call and update denial tracking.

        Args:
            run_id: Identifier of the current run.
            tool_name: The tool being invoked.
            tool_input: The arguments passed to the tool.

        Returns:
            PermissionGateDecision with escalation flag and denial count.
        """
        decision = self._rules.evaluate(tool_name, tool_input)

        if decision.action == PermissionAction.DENY:
            self._counter.record_denial(run_id, tool_name, decision)
            escalated = self._counter.should_escalate(run_id)
            denial_count = self._counter.get_denial_count(run_id)
            escalation_reason: str | None = None
            if escalated:
                escalation_reason = (
                    f"Consecutive denial count ({denial_count}) reached "
                    f"escalation threshold; routing to Gate D (final_approval)."
                )
            return PermissionGateDecision(
                escalated=escalated,
                permission_decision=decision,
                denial_count=denial_count,
                escalation_reason=escalation_reason,
            )

        # ALLOW or ASK — reset consecutive counter
        self._counter.record_approval(run_id, tool_name)
        return PermissionGateDecision(
            escalated=False,
            permission_decision=decision,
            denial_count=self._counter.get_denial_count(run_id),
            escalation_reason=None,
        )
