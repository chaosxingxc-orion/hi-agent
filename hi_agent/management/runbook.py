"""Incident runbook generation helpers."""

from __future__ import annotations

from typing import Any


def build_incident_runbook(report: dict[str, Any], *, max_steps: int = 6) -> dict[str, Any]:
    """Build prioritized runbook steps from an incident report.

    Args:
      report: Incident report payload.
      max_steps: Upper bound of returned action steps.

    Returns:
      A normalized runbook payload containing title/severity/steps/owner_hint.
    """
    if max_steps <= 0:
        raise ValueError("max_steps must be > 0")
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")

    severity = str(report.get("severity", "")).strip().lower()
    if severity not in {"low", "medium", "high"}:
        raise ValueError("report.severity must be one of: low, medium, high")

    service = str(report.get("service", "")).strip() or "hi-agent"
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise ValueError("report.recommendations must be a list")

    base_steps_by_severity = {
        "high": [
            "Stabilize production impact and declare incident owner.",
            "Mitigate immediate risk with safe fallback or traffic controls.",
            "Collect critical telemetry and failing run samples.",
        ],
        "medium": [
            "Assign owner and verify current user impact scope.",
            "Investigate top contributing signals and failing paths.",
        ],
        "low": [
            "Validate monitoring data and keep watch for regressions.",
        ],
    }

    steps: list[str] = list(base_steps_by_severity[severity])
    for rec in recommendations:
        text = str(rec).strip()
        if text:
            steps.append(text)

    # Deduplicate while preserving order, then cap length.
    deduped_steps: list[str] = []
    seen: set[str] = set()
    for step in steps:
        if step in seen:
            continue
        seen.add(step)
        deduped_steps.append(step)

    owner_hint = {
        "high": "incident-commander",
        "medium": "oncall-engineer",
        "low": "service-owner",
    }[severity]

    return {
        "title": f"{service} incident runbook",
        "severity": severity,
        "steps": deduped_steps[:max_steps],
        "owner_hint": owner_hint,
    }
