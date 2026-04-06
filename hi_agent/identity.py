"""Identity helpers for run/action/task-view deterministic IDs."""

from __future__ import annotations

from hi_agent.contracts import deterministic_id


def action_id(run_id: str, stage_id: str, branch_id: str, seq: int) -> str:
    """Create deterministic action ID."""
    return deterministic_id(run_id, stage_id, branch_id, str(seq))


def task_view_id(
    run_id: str,
    stage_id: str,
    branch_id: str,
    capture_seq: int,
    evidence_hash: str,
    policy_version: str,
) -> str:
    """Create deterministic task view ID."""
    return deterministic_id(
        run_id,
        stage_id,
        branch_id,
        str(capture_seq),
        evidence_hash,
        policy_version,
    )

