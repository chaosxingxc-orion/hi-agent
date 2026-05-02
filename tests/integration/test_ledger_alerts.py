"""Integration tests for C11: ledger entries at operationally_observable level.

Validates that ALERT_RULES in hi_agent.observability.alerts covers all 10
recurrence-ledger entries and that each rule satisfies the operator-visibility
contract (metric prefix, severity enum, non-empty fields, runbook path).
"""

from __future__ import annotations

from hi_agent.observability.alerts import ALERT_RULES, LedgerAlertRule


def test_alert_rules_cover_all_ledger_entries() -> None:
    """ALERT_RULES must contain at least 10 entries (one per C11 ledger entry)."""
    assert len(ALERT_RULES) >= 10, (
        f"Expected >= 10 alert rules, got {len(ALERT_RULES)}. "
        "Each recurrence-ledger entry at operationally_observable requires a rule."
    )


def test_alert_rules_have_required_fields() -> None:
    """Every LedgerAlertRule instance must have all non-empty required fields."""
    for rule in ALERT_RULES:
        assert isinstance(rule, LedgerAlertRule), f"Expected LedgerAlertRule, got {type(rule)}"
        assert rule.name, f"Alert rule missing name: {rule!r}"
        assert rule.metric, f"Alert rule missing metric: {rule!r}"
        assert rule.condition, f"Alert rule missing condition: {rule!r}"
        assert rule.severity, f"Alert rule missing severity: {rule!r}"
        assert rule.runbook, f"Alert rule missing runbook: {rule!r}"
        assert rule.issue_id, f"Alert rule missing issue_id: {rule!r}"


def test_alert_rule_metric_names_prefixed() -> None:
    """All metric names in ALERT_RULES must start with ``hi_agent_``."""
    for rule in ALERT_RULES:
        assert rule.metric.startswith("hi_agent_"), (
            f"Metric {rule.metric!r} in rule {rule.name!r} does not start with 'hi_agent_'. "
            "All platform metrics must use the hi_agent_ namespace."
        )


def test_alert_rule_severities_valid() -> None:
    """All severity values must be exactly ``'warning'`` or ``'critical'``."""
    valid = {"warning", "critical"}
    for rule in ALERT_RULES:
        assert rule.severity in valid, (
            f"Rule {rule.name!r} has invalid severity {rule.severity!r}. "
            f"Must be one of {sorted(valid)}."
        )


def test_alert_rules_names_unique() -> None:
    """Alert rule names must be unique within ALERT_RULES."""
    names = [r.name for r in ALERT_RULES]
    assert len(names) == len(set(names)), (
        f"Duplicate alert rule names found: {[n for n in names if names.count(n) > 1]}"
    )


def test_alert_rules_issue_ids_unique() -> None:
    """Each ledger issue_id should map to at most one alert rule."""
    ids = [r.issue_id for r in ALERT_RULES]
    assert len(ids) == len(set(ids)), (
        f"Duplicate issue_ids in ALERT_RULES: {[i for i in ids if ids.count(i) > 1]}"
    )


def test_alert_rules_runbook_paths_are_strings() -> None:
    """Runbook paths must be non-empty strings (path references, not URLs)."""
    for rule in ALERT_RULES:
        assert isinstance(rule.runbook, str) and rule.runbook.strip(), (
            f"Rule {rule.name!r} has invalid runbook path: {rule.runbook!r}"
        )
