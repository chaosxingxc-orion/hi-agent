"""Operational alert evaluation helpers.

Alert registry pattern: ``ALERT_REGISTRY`` contains all alert rules sourced
from the recurrence-ledger.  ``evaluate_operational_alerts`` evaluates the
legacy signal-dict interface AND applies all registry rules against the
provided signals dict so callers get a single unified alert list.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Alert registry
# ---------------------------------------------------------------------------
# Each entry carries:
#   name        -- machine-readable alert code
#   metric_name -- the Prometheus metric this rule watches
#   rule        -- PromQL-style rule string (informational; not evaluated here)
#   description -- human-readable description for runbooks and dashboards
#   severity    -- "critical" | "warning" | "info"
#   runbook     -- path to the runbook that explains resolution steps

ALERT_REGISTRY: list[dict[str, str]] = [
    # -----------------------------------------------------------------------
    # Recurrence-ledger TBD-resolved (7 governance gate metrics)
    # -----------------------------------------------------------------------
    {
        "name": "clean_env_freshness_failure",
        "metric_name": "hi_agent_clean_env_freshness_failures_total",
        "rule": "hi_agent_clean_env_freshness_failures_total > 0 for 5m",
        "description": "Clean-env verification is not tied to the current HEAD SHA.",
        "severity": "critical",
        "runbook": "docs/runbooks/clean-env-not-final-head.md",
    },
    {
        "name": "observability_spine_structural",
        "metric_name": "hi_agent_observability_spine_structural_total",
        "rule": "hi_agent_observability_spine_structural_total > 0 for 5m",
        "description": "One or more observability spine layers report non-real provenance.",
        "severity": "critical",
        "runbook": "docs/runbooks/observability-spine-structural.md",
    },
    {
        "name": "chaos_not_runtime_coupled",
        "metric_name": "hi_agent_chaos_not_runtime_coupled_total",
        "rule": "hi_agent_chaos_not_runtime_coupled_total > 0 for 5m",
        "description": "One or more chaos scenarios are not runtime-coupled.",
        "severity": "critical",
        "runbook": "docs/runbooks/chaos-no-runtime-coupling.md",
    },
    {
        "name": "score_cap_overstatement",
        "metric_name": "hi_agent_score_cap_overstatement_total",
        "rule": "hi_agent_score_cap_overstatement_total > 0 for 5m",
        "description": "Release manifest current_verified_readiness overstates supported evidence.",
        "severity": "critical",
        "runbook": "docs/runbooks/score-cap-overstates-readiness.md",
    },
    {
        "name": "missing_owner_tag",
        "metric_name": "hi_agent_missing_owner_tag_total",
        "rule": "hi_agent_missing_owner_tag_total > 0 for 1m",
        "description": "Commits without Owner track tag or subject prefix detected.",
        "severity": "warning",
        "runbook": "docs/runbooks/ownership-accountability-weak.md",
    },
    {
        "name": "cross_tenant_allowlist_expiry",
        "metric_name": "hi_agent_cross_tenant_allowlist_expiry_total",
        "rule": "hi_agent_cross_tenant_allowlist_expiry_total > 0 for 5m",
        "description": "Expiring cross-tenant allowlist entries without replacement tests.",
        "severity": "critical",
        "runbook": "docs/runbooks/cross-tenant-primitive-footgun.md",
    },
    {
        "name": "test_theatre_detected",
        "metric_name": "hi_agent_test_theatre_detected_total",
        "rule": "hi_agent_test_theatre_detected_total > 0 for 5m",
        "description": "Test-theatre patterns (SUT-internal mock, vacuous assert) detected by CI.",
        "severity": "critical",
        "runbook": "docs/runbooks/test-theatre-passing-via-fallback.md",
    },
    # -----------------------------------------------------------------------
    # Orphan-resolved (3 metrics referenced in ledger, now registered)
    # -----------------------------------------------------------------------
    {
        "name": "manifest_freshness_violation",
        "metric_name": "hi_agent_manifest_freshness_violations_total",
        "rule": "hi_agent_manifest_freshness_violations_total > 0 for 5m",
        "description": "Release manifest is stale relative to current HEAD.",
        "severity": "critical",
        "runbook": "docs/runbooks/manifest-stale.md",
    },
    {
        "name": "soak_evidence_stale",
        "metric_name": "hi_agent_soak_evidence_age_hours",
        "rule": "hi_agent_soak_evidence_age_hours > 168",
        "description": "Most recent soak evidence is older than 7 days.",
        "severity": "warning",
        "runbook": "docs/runbooks/soak-evidence-stale.md",
    },
    {
        "name": "release_gate_continue_on_error",
        "metric_name": "hi_agent_release_gate_continue_on_error_total",
        "rule": "hi_agent_release_gate_continue_on_error_total > 0 for 1m",
        "description": "Release gate steps that used continue-on-error (gate weakening signal).",
        "severity": "warning",
        "runbook": "docs/runbooks/release-gate-weakening.md",
    },
]


def evaluate_operational_alerts(signals: dict[str, Any]) -> list[dict[str, str]]:
    """Translate operational signals to normalized alert rows.

    Evaluates the three legacy signal-dict keys (has_temporal_risk,
    has_reconcile_pressure, has_gate_pressure) for backward compatibility,
    then scans ``ALERT_REGISTRY`` for any registry rule whose metric_name
    appears as a truthy key in *signals*.

    Returns a list of alert dicts with keys: severity, code, message.
    """
    alerts: list[dict[str, str]] = []

    # Legacy hardcoded signals (kept for backward compatibility).
    if bool(signals.get("has_temporal_risk", False)):
        alerts.append(
            {
                "severity": "critical",
                "code": "temporal_risk",
                "message": "Temporal connectivity risk detected.",
            }
        )
    if bool(signals.get("has_reconcile_pressure", False)):
        alerts.append(
            {
                "severity": "warning",
                "code": "reconcile_pressure",
                "message": "Reconcile backlog/failures exceed safe range.",
            }
        )
    if bool(signals.get("has_gate_pressure", False)):
        alerts.append(
            {
                "severity": "warning",
                "code": "gate_pressure",
                "message": "Pending or stale human gates detected.",
            }
        )

    # Registry-driven signals: metric_name present and truthy in signals dict.
    for rule in ALERT_REGISTRY:
        metric_name = rule["metric_name"]
        if bool(signals.get(metric_name, False)):
            alerts.append(
                {
                    "severity": rule["severity"],
                    "code": rule["name"],
                    "message": rule["description"],
                }
            )

    return alerts
