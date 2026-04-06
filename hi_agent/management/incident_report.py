"""Incident report composition helpers."""

from __future__ import annotations

from typing import Any


def build_incident_report(
    signals: dict[str, Any],
    alerts: list[dict[str, Any]],
    slo_snapshot: dict[str, Any],
    *,
    now_ts: float,
    service: str = "hi-agent",
) -> dict[str, Any]:
    """Build a deterministic incident report payload.

    Severity mapping:
      - `high`: temporal risk exists, critical alert exists, or both SLO targets fail.
      - `medium`: any warning pressure or one SLO target fails.
      - `low`: no pressure and SLO targets pass.
    """
    if not isinstance(service, str) or not service.strip():
        raise ValueError("service must be a non-empty string")

    has_temporal_risk = bool(signals.get("has_temporal_risk", False))
    has_reconcile_pressure = bool(signals.get("has_reconcile_pressure", False))
    has_gate_pressure = bool(signals.get("has_gate_pressure", False))

    normalized_alerts = list(alerts)
    alert_count = len(normalized_alerts)
    critical_count = 0
    for alert in normalized_alerts:
        if str(alert.get("severity", "")).strip().lower() == "critical":
            critical_count += 1

    success_target_met = bool(slo_snapshot.get("success_target_met", True))
    latency_target_met = bool(slo_snapshot.get("latency_target_met", True))

    if (
        has_temporal_risk
        or critical_count > 0
        or (not success_target_met and not latency_target_met)
    ):
        severity = "high"
    elif (
        has_reconcile_pressure
        or has_gate_pressure
        or (not success_target_met or not latency_target_met)
    ):
        severity = "medium"
    else:
        severity = "low"

    summary_title = f"{service.strip()} incident report ({severity})"
    key_facts = [
        f"alerts={alert_count}",
        f"critical_alerts={critical_count}",
        f"temporal_risk={has_temporal_risk}",
        f"reconcile_pressure={has_reconcile_pressure}",
        f"gate_pressure={has_gate_pressure}",
        f"slo_success_target_met={success_target_met}",
        f"slo_latency_target_met={latency_target_met}",
    ]

    recommendations: list[str] = []
    if has_temporal_risk:
        recommendations.append("Check runtime substrate connectivity and failover readiness.")
    if has_reconcile_pressure:
        recommendations.append("Drain reconcile backlog and inspect recent reconcile failures.")
    if has_gate_pressure:
        recommendations.append("Resolve stale pending gates and reduce approval wait time.")
    if not success_target_met:
        recommendations.append("Investigate run failures and prioritize error-budget burn causes.")
    if not latency_target_met:
        recommendations.append("Profile slow stages and reduce p95 latency regressions.")
    if not recommendations:
        recommendations.append("No immediate action required; continue routine monitoring.")

    return {
        "service": service.strip(),
        "generated_at": float(now_ts),
        "severity": severity,
        "summary_title": summary_title,
        "key_facts": key_facts,
        "recommendations": recommendations,
    }
