"""E2E skeletons for trajectory and replay subsystems — Layer 3.

These tests require operator-shape: a long-lived process with a real LLM
in HI_AGENT_LLM_MODE=real. They are skipped in default-offline CI runs.

Profile validated: default-offline (skipped), prod_e2e (target)
expiry_wave: Wave 30
"""

from __future__ import annotations

import pytest

_SKIP_REASON = "Requires operator-shape (PM2 + real LLM). prod_e2e profile. expiry_wave: Wave 30"


@pytest.mark.skip(reason=_SKIP_REASON)  # expiry_wave: Wave 30
def test_e2e_trajectory_graph_drives_stages() -> None:
    """Trajectory graph built from a TaskContract drives stage execution end-to-end.

    Asserts:
    - TrajectoryGraph.as_chain constructs correctly from real TRACE stages.
    - RunExecutor drives each graph node to NodeState.COMPLETED in order.
    - Final result.status is 'completed'.
    - No fallback events in result.fallback_events.
    """
    # Placeholder body — operator-shape required.
    raise NotImplementedError("Requires prod_e2e operator shape")


@pytest.mark.skip(reason=_SKIP_REASON)  # expiry_wave: Wave 30
def test_e2e_trajectory_backtrack_recovery() -> None:
    """A TrajectoryGraph with a backtrack edge recovers and reaches COMPLETED.

    Asserts:
    - Stage S3 backtracks to S2 on first failure.
    - After retry, run reaches completed state.
    - fallback_events contains the backtrack trigger record.
    """
    raise NotImplementedError("Requires prod_e2e operator shape")


@pytest.mark.skip(reason=_SKIP_REASON)  # expiry_wave: Wave 30
def test_e2e_replay_restores_completed_run() -> None:
    """ReplayEngine reconstructs a successful run from its event stream.

    Asserts:
    - ReplayReport.success is True after full run.
    - All 5 TRACE stages appear as 'completed' in stage_states.
    - task_view_count matches the number of TaskViewRecorded events.
    """
    raise NotImplementedError("Requires prod_e2e operator shape")


@pytest.mark.skip(reason=_SKIP_REASON)  # expiry_wave: Wave 30
def test_e2e_replay_from_jsonl_roundtrip() -> None:
    """Events persisted to JSONL by ReplayRecorder reproduce the same ReplayReport.

    Asserts:
    - load_event_envelopes_jsonl produces same count as in-memory events.
    - ReplayEngine.replay(loaded) yields same stage_states as original replay.
    """
    raise NotImplementedError("Requires prod_e2e operator shape")
