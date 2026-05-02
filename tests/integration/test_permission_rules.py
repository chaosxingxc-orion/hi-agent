"""Tests for hi_agent.harness.permission_rules.

Covers ToolPermissionRule matching, ToolPermissionRules evaluation,
DenialCounter tracking and escalation, PermissionGate integration,
and the default safe rule set.
"""

from __future__ import annotations

from hi_agent.runtime.harness.permission_rules import (
    DenialCounter,
    DenialRecord,
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


def _deny_rule(
    name: str = "test-deny",
    tool_name: str | None = "bash",
    input_field: str | None = "command",
    glob_pattern: str | None = "rm -rf *",
    reason: str = "Test deny rule.",
) -> ToolPermissionRule:
    return ToolPermissionRule(
        name=name,
        tool_name=tool_name,
        input_field=input_field,
        glob_pattern=glob_pattern,
        action=PermissionAction.DENY,
        reason=reason,
    )


def _allow_rule(
    name: str = "test-allow",
    tool_name: str | None = "web_search",
    input_field: str | None = None,
    glob_pattern: str | None = None,
) -> ToolPermissionRule:
    return ToolPermissionRule(
        name=name,
        tool_name=tool_name,
        input_field=input_field,
        glob_pattern=glob_pattern,
        action=PermissionAction.ALLOW,
        reason="Explicitly allowed.",
    )


def _make_decision(
    action: PermissionAction = PermissionAction.DENY,
    tool_name: str = "bash",
) -> PermissionDecision:
    return PermissionDecision(
        action=action,
        rule_name="test-rule",
        reason="Test reason",
        tool_name=tool_name,
    )


# ---------------------------------------------------------------------------
# ToolPermissionRule — matches_tool
# ---------------------------------------------------------------------------


class TestToolPermissionRuleMatchesTool:
    def test_rule_matches_tool_by_name(self) -> None:
        """A rule with a specific tool_name matches that tool exactly."""
        rule = _deny_rule(tool_name="bash")
        assert rule.matches_tool("bash") is True

    def test_rule_does_not_match_different_tool(self) -> None:
        """A rule with a specific tool_name does not match a different tool."""
        rule = _deny_rule(tool_name="bash")
        assert rule.matches_tool("file_write") is False

    def test_rule_matches_all_tools_when_tool_none(self) -> None:
        """A rule with tool_name=None matches any tool name."""
        rule = _deny_rule(tool_name=None)
        assert rule.matches_tool("bash") is True
        assert rule.matches_tool("web_search") is True
        assert rule.matches_tool("file_write") is True

    def test_rule_matches_tool_case_insensitive(self) -> None:
        """Tool name matching is case-insensitive."""
        rule = _deny_rule(tool_name="Bash")
        assert rule.matches_tool("bash") is True
        assert rule.matches_tool("BASH") is True


# ---------------------------------------------------------------------------
# ToolPermissionRule — matches_input
# ---------------------------------------------------------------------------


class TestToolPermissionRuleMatchesInput:
    def test_rule_matches_input_field_glob(self) -> None:
        """'rm -rf *' glob pattern matches 'rm -rf /home'."""
        rule = _deny_rule(input_field="command", glob_pattern="rm -rf *")
        assert rule.matches_input({"command": "rm -rf /home"}) is True

    def test_rule_no_match_different_pattern(self) -> None:
        """'rm -rf *' glob pattern does not match 'ls -la'."""
        rule = _deny_rule(input_field="command", glob_pattern="rm -rf *")
        assert rule.matches_input({"command": "ls -la"}) is False

    def test_rule_matches_when_no_field_constraint(self) -> None:
        """input_field=None means any input matches."""
        rule = _allow_rule(input_field=None, glob_pattern=None)
        assert rule.matches_input({"anything": "value"}) is True
        assert rule.matches_input({}) is True

    def test_rule_no_match_when_field_absent(self) -> None:
        """When the specified field is missing from input, no match."""
        rule = _deny_rule(input_field="command", glob_pattern="rm -rf *")
        assert rule.matches_input({"path": "/tmp/foo"}) is False

    def test_rule_matches_when_pattern_none(self) -> None:
        """glob_pattern=None means any field value matches."""
        rule = _deny_rule(input_field="command", glob_pattern=None)
        assert rule.matches_input({"command": "ls -la"}) is True

    def test_rule_matches_wildcard_glob(self) -> None:
        """'/etc/*' pattern matches '/etc/passwd'."""
        rule = ToolPermissionRule(
            name="deny-etc",
            tool_name="file_write",
            input_field="path",
            glob_pattern="/etc/*",
            action=PermissionAction.DENY,
        )
        assert rule.matches_input({"path": "/etc/passwd"}) is True
        assert rule.matches_input({"path": "/tmp/passwd"}) is False


# ---------------------------------------------------------------------------
# ToolPermissionRules — evaluate
# ---------------------------------------------------------------------------


class TestToolPermissionRulesEvaluate:
    def test_permission_rules_evaluate_first_match_wins(self) -> None:
        """The first matching rule takes precedence over subsequent rules."""
        rules = ToolPermissionRules(
            [
                _deny_rule(
                    name="deny-rm-rf",
                    tool_name="bash",
                    input_field="command",
                    glob_pattern="rm -rf *",
                ),
                _allow_rule(
                    name="allow-bash", tool_name="bash", input_field=None, glob_pattern=None
                ),
            ]
        )
        decision = rules.evaluate("bash", {"command": "rm -rf /tmp"})
        assert decision.action == PermissionAction.DENY
        assert decision.rule_name == "deny-rm-rf"

    def test_permission_rules_evaluate_second_rule_when_first_no_match(self) -> None:
        """When the first rule does not match, the second rule is tried."""
        rules = ToolPermissionRules(
            [
                _deny_rule(
                    name="deny-rm-rf",
                    tool_name="bash",
                    input_field="command",
                    glob_pattern="rm -rf *",
                ),
                _allow_rule(
                    name="allow-bash-ls", tool_name="bash", input_field=None, glob_pattern=None
                ),
            ]
        )
        decision = rules.evaluate("bash", {"command": "ls -la"})
        assert decision.action == PermissionAction.ALLOW
        assert decision.rule_name == "allow-bash-ls"

    def test_permission_rules_evaluate_no_match_returns_ask(self) -> None:
        """When no rule matches, the default decision is ASK."""
        rules = ToolPermissionRules(
            [
                _deny_rule(
                    name="deny-rm-rf",
                    tool_name="bash",
                    input_field="command",
                    glob_pattern="rm -rf *",
                ),
            ]
        )
        decision = rules.evaluate("web_search", {"query": "hello"})
        assert decision.action == PermissionAction.ASK
        assert decision.rule_name is None

    def test_permission_rules_evaluate_empty_rules_returns_ask(self) -> None:
        """An empty rule set always returns ASK."""
        rules = ToolPermissionRules([])
        decision = rules.evaluate("bash", {"command": "echo hi"})
        assert decision.action == PermissionAction.ASK

    def test_permission_rules_evaluate_sets_tool_name(self) -> None:
        """The returned PermissionDecision carries the evaluated tool_name."""
        rules = ToolPermissionRules([_deny_rule()])
        decision = rules.evaluate("bash", {"command": "rm -rf /tmp"})
        assert decision.tool_name == "bash"

    def test_permission_rules_evaluate_records_matched_pattern(self) -> None:
        """Matched field and pattern are surfaced in the decision."""
        rules = ToolPermissionRules([_deny_rule(input_field="command", glob_pattern="rm -rf *")])
        decision = rules.evaluate("bash", {"command": "rm -rf /"})
        assert decision.matched_input_field == "command"
        assert decision.matched_pattern == "rm -rf *"


# ---------------------------------------------------------------------------
# ToolPermissionRules — from_config
# ---------------------------------------------------------------------------


class TestToolPermissionRulesFromConfig:
    def test_permission_rules_from_config(self) -> None:
        """Dict list with tool/field/pattern/action keys is correctly converted."""
        config = [
            {
                "name": "deny-rm",
                "tool": "bash",
                "field": "command",
                "pattern": "rm -rf *",
                "action": "deny",
                "reason": "Dangerous command.",
            },
            {
                "tool": "web_search",
                "action": "allow",
            },
        ]
        rules = ToolPermissionRules.from_config(config)
        assert len(rules.rules) == 2

        r0, r1 = rules.rules
        assert r0.name == "deny-rm"
        assert r0.tool_name == "bash"
        assert r0.input_field == "command"
        assert r0.glob_pattern == "rm -rf *"
        assert r0.action == PermissionAction.DENY
        assert r0.reason == "Dangerous command."

        assert r1.tool_name == "web_search"
        assert r1.action == PermissionAction.ALLOW
        assert r1.input_field is None
        assert r1.glob_pattern is None

    def test_permission_rules_from_config_auto_name(self) -> None:
        """Rules without explicit names receive auto-generated names."""
        config = [{"tool": "bash", "action": "allow"}]
        rules = ToolPermissionRules.from_config(config)
        assert rules.rules[0].name == "rule-0"

    def test_permission_rules_from_config_invalid_action_defaults_ask(self) -> None:
        """An unrecognised action string defaults to ASK."""
        config = [{"tool": "bash", "action": "unknown_action"}]
        rules = ToolPermissionRules.from_config(config)
        assert rules.rules[0].action == PermissionAction.ASK

    def test_permission_rules_from_config_empty_list(self) -> None:
        """An empty config list produces an empty rule set."""
        rules = ToolPermissionRules.from_config([])
        assert len(rules.rules) == 0


# ---------------------------------------------------------------------------
# ToolPermissionRules — add_rule / remove_rule
# ---------------------------------------------------------------------------


class TestToolPermissionRulesMutation:
    def test_add_rule_appends(self) -> None:
        rules = ToolPermissionRules()
        rule = _deny_rule()
        rules.add_rule(rule)
        assert len(rules.rules) == 1
        assert rules.rules[0] is rule

    def test_remove_rule_by_name_returns_true(self) -> None:
        rule = _deny_rule(name="my-rule")
        rules = ToolPermissionRules([rule])
        removed = rules.remove_rule("my-rule")
        assert removed is True
        assert len(rules.rules) == 0

    def test_remove_rule_missing_returns_false(self) -> None:
        rules = ToolPermissionRules()
        assert rules.remove_rule("nonexistent") is False


# ---------------------------------------------------------------------------
# DenialCounter
# ---------------------------------------------------------------------------


class TestDenialCounter:
    def test_denial_counter_record_and_count(self) -> None:
        """Recording a denial increments the count for the run."""
        counter = DenialCounter(escalation_threshold=5, window_size=10)
        decision = _make_decision()
        counter.record_denial("run-1", "bash", decision)
        assert counter.get_denial_count("run-1") == 1

    def test_denial_counter_multiple_denials_increment(self) -> None:
        """Each denial increments the consecutive count."""
        counter = DenialCounter()
        decision = _make_decision()
        for _ in range(3):
            counter.record_denial("run-1", "bash", decision)
        assert counter.get_denial_count("run-1") == 3

    def test_denial_counter_approval_resets(self) -> None:
        """Calling record_approval resets the consecutive denial count to zero."""
        counter = DenialCounter()
        decision = _make_decision()
        counter.record_denial("run-1", "bash", decision)
        counter.record_denial("run-1", "bash", decision)
        assert counter.get_denial_count("run-1") == 2

        counter.record_approval("run-1", "bash")
        assert counter.get_denial_count("run-1") == 0

    def test_denial_counter_should_escalate_at_threshold(self) -> None:
        """should_escalate returns True when consecutive denials == threshold."""
        counter = DenialCounter(escalation_threshold=3)
        decision = _make_decision()
        for _ in range(3):
            counter.record_denial("run-1", "bash", decision)
        assert counter.should_escalate("run-1") is True

    def test_denial_counter_below_threshold_no_escalate(self) -> None:
        """should_escalate returns False when below threshold."""
        counter = DenialCounter(escalation_threshold=5)
        decision = _make_decision()
        for _ in range(4):
            counter.record_denial("run-1", "bash", decision)
        assert counter.should_escalate("run-1") is False

    def test_denial_counter_zero_count_no_escalate(self) -> None:
        """A run with no denials should not escalate."""
        counter = DenialCounter(escalation_threshold=5)
        assert counter.should_escalate("run-new") is False

    def test_denial_counter_reset_clears_all(self) -> None:
        """reset() removes both history and consecutive count."""
        counter = DenialCounter()
        decision = _make_decision()
        counter.record_denial("run-1", "bash", decision)
        counter.reset("run-1")
        assert counter.get_denial_count("run-1") == 0
        assert counter.get_recent_denials("run-1") == []

    def test_denial_counter_per_run_isolation(self) -> None:
        """Denials for different run IDs are tracked independently."""
        counter = DenialCounter()
        decision = _make_decision()
        counter.record_denial("run-1", "bash", decision)
        counter.record_denial("run-1", "bash", decision)
        counter.record_denial("run-2", "bash", decision)
        assert counter.get_denial_count("run-1") == 2
        assert counter.get_denial_count("run-2") == 1

    def test_denial_counter_get_recent_denials(self) -> None:
        """get_recent_denials returns at most n records, most recent last."""
        counter = DenialCounter(window_size=10)
        decision = _make_decision()
        for _ in range(7):
            counter.record_denial("run-1", "bash", decision)
        recent = counter.get_recent_denials("run-1", n=3)
        assert len(recent) == 3
        assert all(isinstance(r, DenialRecord) for r in recent)

    def test_denial_counter_window_size_limits_history(self) -> None:
        """History is capped at window_size entries."""
        counter = DenialCounter(window_size=3)
        decision = _make_decision()
        for _ in range(10):
            counter.record_denial("run-1", "bash", decision)
        recent = counter.get_recent_denials("run-1", n=100)
        assert len(recent) <= 3


# ---------------------------------------------------------------------------
# PermissionGate
# ---------------------------------------------------------------------------


class TestPermissionGate:
    def _make_gate(
        self,
        rules: ToolPermissionRules | None = None,
        threshold: int = 3,
    ) -> PermissionGate:
        if rules is None:
            rules = ToolPermissionRules([_deny_rule()])
        counter = DenialCounter(escalation_threshold=threshold)
        return PermissionGate(rules=rules, denial_counter=counter)

    def test_permission_gate_deny_records_and_escalates(self) -> None:
        """DENY decisions accumulate; at threshold the gate escalates."""
        gate = self._make_gate(threshold=2)
        tool_input = {"command": "rm -rf /var"}

        # First denial — not yet escalated
        result1 = gate.check("run-1", "bash", tool_input)
        assert result1.permission_decision.action == PermissionAction.DENY
        assert result1.escalated is False
        assert result1.denial_count == 1

        # Second denial — threshold reached
        result2 = gate.check("run-1", "bash", tool_input)
        assert result2.escalated is True
        assert result2.denial_count == 2
        assert result2.escalation_reason is not None
        assert "Gate D" in result2.escalation_reason

    def test_permission_gate_allow_resets_counter(self) -> None:
        """An ALLOW decision resets the consecutive denial counter."""
        allow_rules = ToolPermissionRules(
            [
                _deny_rule(
                    name="deny-rm", tool_name="bash", input_field="command", glob_pattern="rm -rf *"
                ),
                _allow_rule(name="allow-ls", tool_name="bash", input_field=None, glob_pattern=None),
            ]
        )
        counter = DenialCounter(escalation_threshold=5)
        gate = PermissionGate(rules=allow_rules, denial_counter=counter)

        # Record some denials
        gate.check("run-1", "bash", {"command": "rm -rf /tmp"})
        gate.check("run-1", "bash", {"command": "rm -rf /tmp"})
        assert counter.get_denial_count("run-1") == 2

        # Now allow — resets count
        gate.check("run-1", "bash", {"command": "ls -la"})
        assert counter.get_denial_count("run-1") == 0

    def test_permission_gate_ask_resets_counter(self) -> None:
        """An ASK decision (no matching deny rule) resets the consecutive counter."""
        rules = ToolPermissionRules([_deny_rule(tool_name="bash")])
        counter = DenialCounter(escalation_threshold=5)
        gate = PermissionGate(rules=rules, denial_counter=counter)

        gate.check("run-1", "bash", {"command": "rm -rf /tmp"})
        gate.check("run-1", "bash", {"command": "rm -rf /tmp"})
        # ASK (unmatched tool)
        gate.check("run-1", "web_search", {"query": "hello"})
        assert counter.get_denial_count("run-1") == 0

    def test_permission_gate_returns_gate_decision_type(self) -> None:
        """check() always returns a PermissionGateDecision instance."""
        gate = self._make_gate()
        result = gate.check("run-1", "bash", {"command": "rm -rf /"})
        assert isinstance(result, PermissionGateDecision)

    def test_permission_gate_no_escalation_below_threshold(self) -> None:
        """Gate does not escalate when denial count is below threshold."""
        gate = self._make_gate(threshold=5)
        tool_input = {"command": "rm -rf /tmp"}
        for _ in range(4):
            result = gate.check("run-1", "bash", tool_input)
        assert result.escalated is False

    def test_permission_gate_per_run_isolation(self) -> None:
        """Escalation state for one run does not affect another run."""
        gate = self._make_gate(threshold=2)
        tool_input = {"command": "rm -rf /tmp"}

        gate.check("run-A", "bash", tool_input)
        gate.check("run-A", "bash", tool_input)
        # run-A should be escalated
        result_a = gate.check("run-A", "bash", tool_input)
        assert result_a.escalated is True

        # run-B starts clean
        result_b = gate.check("run-B", "bash", tool_input)
        assert result_b.escalated is False


# ---------------------------------------------------------------------------
# Default safe rules
# ---------------------------------------------------------------------------


class TestDefaultSafeRules:
    def test_default_safe_rules_deny_rm_rf(self) -> None:
        """Default rules block 'rm -rf <path>' in bash commands."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("bash", {"command": "rm -rf /home/user"})
        assert decision.action == PermissionAction.DENY

    def test_default_safe_rules_deny_rm_rf_root(self) -> None:
        """Default rules block 'rm -rf /' patterns."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("bash", {"command": "rm -rf /"})
        assert decision.action == PermissionAction.DENY

    def test_default_safe_rules_deny_etc_write(self) -> None:
        """Default rules block writes to /etc/."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("file_write", {"path": "/etc/hosts"})
        assert decision.action == PermissionAction.DENY

    def test_default_safe_rules_deny_boot_write(self) -> None:
        """Default rules block writes to /boot/."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("file_write", {"path": "/boot/grub/grub.cfg"})
        assert decision.action == PermissionAction.DENY

    def test_default_safe_rules_deny_ssh_write(self) -> None:
        """Default rules block writes to .ssh/ directories."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("file_write", {"path": "/home/user/.ssh/authorized_keys"})
        assert decision.action == PermissionAction.DENY

    def test_default_safe_rules_allow_safe_bash(self) -> None:
        """Safe bash commands (e.g. 'echo hi') are not denied by default rules."""
        rules = ToolPermissionRules.default_safe_rules()
        decision = rules.evaluate("bash", {"command": "echo hi"})
        # Safe commands are not explicitly allowed by default rules → ASK
        assert decision.action != PermissionAction.DENY

    def test_default_safe_rules_contains_rules(self) -> None:
        """Default safe rules are non-empty."""
        rules = ToolPermissionRules.default_safe_rules()
        assert len(rules.rules) > 0
