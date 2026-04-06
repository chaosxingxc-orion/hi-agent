"""Command helpers for incident lifecycle management."""

from __future__ import annotations

from hi_agent.contracts import deterministic_id


def cmd_incident_create(
    report: dict[str, object],
    *,
    actor: str,
    channel: str = "ops",
) -> dict[str, object]:
    """Create an incident ticket payload from a report."""
    if not isinstance(report, dict) or not report:
        raise ValueError("report must be a non-empty dict")

    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("actor must be a non-empty string")

    normalized_channel = channel.strip()
    if not normalized_channel:
        raise ValueError("channel must be a non-empty string")

    run_id = report.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        incident_id = deterministic_id(run_id.strip(), "incident", normalized_channel)
    else:
        incident_id = deterministic_id(normalized_actor, normalized_channel, "incident")

    return {
        "command": "incident_create",
        "incident_id": incident_id,
        "status": "open",
        "channel": normalized_channel,
        "created_by": normalized_actor,
        "report": dict(report),
    }


def cmd_incident_close(
    incident_id: str,
    *,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Build a close command payload for one incident."""
    normalized_incident_id = incident_id.strip()
    if not normalized_incident_id:
        raise ValueError("incident_id must be a non-empty string")

    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("actor must be a non-empty string")

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("reason must be a non-empty string")

    return {
        "command": "incident_close",
        "incident_id": normalized_incident_id,
        "status": "closed",
        "closed_by": normalized_actor,
        "reason": normalized_reason,
    }
