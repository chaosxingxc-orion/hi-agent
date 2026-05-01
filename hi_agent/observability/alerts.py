"""Ledger-backed alert rule definitions for C11 operationally_observable closure.

Each AlertRule corresponds to a recurrence-ledger entry elevated to
closure_level: operationally_observable.  The runbook field points to the
ops runbook path; alert wiring surfaces to operators via /metrics.

Rule 15 requirement: operationally_observable = verified_at_release_head +
metric on /metrics + named alert rule + runbook path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerAlertRule:
    """Operator-visible alert rule wired to a recurrence-ledger entry.

    Attributes:
        name: Unique alert rule name, used as the alert identifier.
        metric: Prometheus metric name; must start with ``hi_agent_``.
        condition: Human-readable threshold condition, e.g. ``"rate > 0.1"``.
        severity: One of ``"warning"`` or ``"critical"``.
        runbook: Path to the ops runbook, e.g. ``"docs/runbooks/foo.md"``.
        issue_id: Recurrence-ledger issue_id this rule is wired to.
    """

    name: str
    metric: str
    condition: str
    severity: str
    runbook: str
    issue_id: str


# ---------------------------------------------------------------------------
# C11: 10 alert rules — one per recurrence-ledger entry at closure_level
# operationally_observable.
# ---------------------------------------------------------------------------

ALERT_RULES: list[LedgerAlertRule] = [
    # P0-1: release identity inconsistency
    LedgerAlertRule(
        name="hi_agent_manifest_freshness_violations_alert",
        metric="hi_agent_manifest_freshness_violations_total",
        condition="counter > 0 for 5m",
        severity="critical",
        runbook="docs/runbooks/manifest-stale.md",
        issue_id="P0-1",
    ),
    # P0-2: clean-env not tied to final HEAD
    LedgerAlertRule(
        name="hi_agent_clean_env_freshness_failures_alert",
        metric="hi_agent_clean_env_freshness_failures_total",
        condition="counter > 0 for 5m",
        severity="critical",
        runbook="docs/runbooks/clean-env-not-final-head.md",
        issue_id="P0-2",
    ),
    # P0-3: observability spine structural (non-real provenance layers)
    LedgerAlertRule(
        name="hi_agent_observability_spine_structural_alert",
        metric="hi_agent_observability_spine_structural_total",
        condition="counter > 0 for 5m",
        severity="warning",
        runbook="docs/runbooks/observability-spine-structural.md",
        issue_id="P0-3",
    ),
    # P0-4: soak evidence stale beyond 168h (1 week)
    LedgerAlertRule(
        name="hi_agent_soak_evidence_stale_alert",
        metric="hi_agent_soak_evidence_age_hours",
        condition="gauge > 168",
        severity="warning",
        runbook="docs/runbooks/soak-evidence-stale.md",
        issue_id="P0-4",
    ),
    # P0-5: chaos scenarios not runtime-coupled
    LedgerAlertRule(
        name="hi_agent_chaos_not_runtime_coupled_alert",
        metric="hi_agent_chaos_not_runtime_coupled_total",
        condition="counter > 0 for 5m",
        severity="critical",
        runbook="docs/runbooks/chaos-no-runtime-coupling.md",
        issue_id="P0-5",
    ),
    # P0-6: score cap overstates readiness
    LedgerAlertRule(
        name="hi_agent_score_cap_overstatement_alert",
        metric="hi_agent_score_cap_overstatement_total",
        condition="counter > 0 for 5m",
        severity="critical",
        runbook="docs/runbooks/score-cap-overstates-readiness.md",
        issue_id="P0-6",
    ),
    # S4-10: ownership accountability weak (missing owner tag)
    LedgerAlertRule(
        name="hi_agent_missing_owner_tag_alert",
        metric="hi_agent_missing_owner_tag_total",
        condition="counter > 0 for 1m",
        severity="warning",
        runbook="docs/runbooks/ownership-accountability-weak.md",
        issue_id="S4-10",
    ),
    # W17-A: release gate continue-on-error weakening
    LedgerAlertRule(
        name="hi_agent_release_gate_weakening_alert",
        metric="hi_agent_release_gate_continue_on_error_total",
        condition="counter > 0 for 1m",
        severity="critical",
        runbook="docs/runbooks/release-gate-weakening.md",
        issue_id="W17-A",
    ),
    # W17-B: cross-tenant primitive footgun (allowlist expiry)
    LedgerAlertRule(
        name="hi_agent_cross_tenant_footgun_alert",
        metric="hi_agent_cross_tenant_allowlist_expiry_total",
        condition="counter > 0 for 5m",
        severity="critical",
        runbook="docs/runbooks/cross-tenant-primitive-footgun.md",
        issue_id="W17-B",
    ),
    # W17-C: test theatre detected (heuristic fallback scope violation)
    LedgerAlertRule(
        name="hi_agent_test_theatre_alert",
        metric="hi_agent_test_theatre_detected_total",
        condition="counter > 0 for 5m",
        severity="warning",
        runbook="docs/runbooks/test-theatre-passing-via-fallback.md",
        issue_id="W17-C",
    ),
]
