"""Command-style wrappers for route decision audit store operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def cmd_decision_audit_append(store: object, audit: Mapping[str, Any]) -> dict[str, Any]:
    """Append one audit record via store and return normalized payload."""
    append = getattr(store, "append", None)
    if not callable(append):
        raise TypeError("store must provide callable append(audit)")
    if not isinstance(audit, Mapping):
        raise TypeError("audit must be a mapping")
    appended = append(dict(audit))
    return {"command": "decision_audit_append", "audit": dict(appended)}


def cmd_decision_audit_latest(store: object, run_id: str, stage_id: str) -> dict[str, Any]:
    """Fetch latest audit record for one (run_id, stage_id) pair."""
    latest_by_stage = getattr(store, "latest_by_stage", None)
    if not callable(latest_by_stage):
        raise TypeError("store must provide callable latest_by_stage(run_id, stage_id)")
    normalized_run_id = _non_empty(run_id, "run_id")
    normalized_stage_id = _non_empty(stage_id, "stage_id")
    audit = latest_by_stage(normalized_run_id, normalized_stage_id)
    return {
        "command": "decision_audit_latest",
        "run_id": normalized_run_id,
        "stage_id": normalized_stage_id,
        "audit": None if audit is None else dict(audit),
    }


def cmd_decision_audit_list_run(store: object, run_id: str) -> dict[str, Any]:
    """List all audits for one run via store."""
    list_by_run = getattr(store, "list_by_run", None)
    if not callable(list_by_run):
        raise TypeError("store must provide callable list_by_run(run_id)")
    normalized_run_id = _non_empty(run_id, "run_id")
    audits = [dict(item) for item in list_by_run(normalized_run_id)]
    return {
        "command": "decision_audit_list_run",
        "run_id": normalized_run_id,
        "count": len(audits),
        "audits": audits,
    }


def _non_empty(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be a non-empty string")
    return normalized

