"""
Acceptance tests 19-20 + hardening tests for Plan B Phase 5.
"""
import time

import pytest
from pathlib import Path


def _team_writer(proc_id: int, n_events: int, db_path: str) -> None:
    """Module-level worker for multi-process team write test (must be picklable on Windows)."""
    from hi_agent.server.team_event_store import TeamEventStore, TeamEvent
    store = TeamEventStore(db_path)
    store.initialize()
    for i in range(n_events):
        store.insert(TeamEvent(
            event_id=f"p{proc_id}-e{i}",
            tenant_id="t1",
            team_space_id="t1",
            event_type="test",
            payload_json="{}",
            source_run_id=f"r-{proc_id}-{i}",
            source_user_id=f"u{proc_id}",
            source_session_id="s1",
            publish_reason="test",
            schema_version=1,
            created_at=time.time(),
        ))


# Acceptance test 19: Legacy rows hidden from normal users
def test_19_legacy_rows_not_visible_in_normal_list(tmp_path):
    """Runs with user_id='__legacy__' must not appear in normal user's list."""
    from hi_agent.server.run_store import SQLiteRunStore, RunRecord
    import time

    store = SQLiteRunStore(str(tmp_path / "runs.db"))
    legacy = RunRecord(
        run_id="legacy-run",
        tenant_id="t1",
        task_contract_json="{}",
        status="completed",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
        user_id="__legacy__",
        session_id="__legacy__",
    )
    store.upsert(legacy)
    results = store.list_by_workspace("t1", "u1", session_id=None)
    assert not any(r.run_id == "legacy-run" for r in results)


# Acceptance test 20: Workspace IDs safely encoded for filesystem paths
def test_20_unsafe_ids_encoded_in_paths(tmp_path):
    from hi_agent.server.workspace_path import WorkspaceKey, WorkspacePathHelper

    evil_ids = [
        "../evil",
        "../../etc/passwd",
        "user\x00name",
        "user/admin",
        "tenant\\system",
    ]
    for evil in evil_ids:
        key = WorkspaceKey(tenant_id=evil, user_id="u1", session_id="s1")
        path = WorkspacePathHelper.private(tmp_path, key)
        parts = Path(path).relative_to(tmp_path).parts
        for part in parts:
            assert ".." not in part, f"Path traversal in {path} for id={evil!r}"
            assert "/" not in part
            assert "\\" not in part
            assert "\x00" not in part


# Fuzz test: path traversal across all ID positions
@pytest.mark.parametrize("field,evil", [
    ("tenant_id", "../hack"),
    ("user_id", "../../root"),
    ("session_id", "sess/../escape"),
    ("team_id", "team/../../admin"),
])
def test_fuzz_path_traversal(tmp_path, field, evil):
    from hi_agent.server.workspace_path import WorkspaceKey, WorkspacePathHelper
    kwargs = {"tenant_id": "t1", "user_id": "u1", "session_id": "s1", "team_id": ""}
    kwargs[field] = evil

    # Only test if the field value is non-empty and WorkspaceKey accepts it
    try:
        key = WorkspaceKey(**kwargs)
    except (ValueError, TypeError):
        pytest.skip(f"WorkspaceKey rejected {field}={evil!r} at construction")

    # Private path: only uses tenant_id, user_id, session_id
    if field != "team_id":
        path = WorkspacePathHelper.private(tmp_path, key)
        relative = Path(path).relative_to(tmp_path)
        assert ".." not in str(relative).replace("\\", "/")

    # Team path: uses team_id (or falls back to tenant_id when team_id is empty)
    team_path = WorkspacePathHelper.team(tmp_path, key)
    team_relative = Path(team_path).relative_to(tmp_path)
    assert ".." not in str(team_relative).replace("\\", "/")


# Multi-process concurrent team writes
def test_multiprocess_team_writes_no_corruption(tmp_path):
    """Multiple processes writing to the same TeamEventStore must not corrupt data."""
    import multiprocessing
    from hi_agent.server.team_event_store import TeamEventStore

    db_path = str(tmp_path / "team.db")
    init_store = TeamEventStore(db_path)
    init_store.initialize()

    procs = [
        multiprocessing.Process(target=_team_writer, args=(p, 10, db_path))
        for p in range(3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    final_store = TeamEventStore(db_path)
    final_store.initialize()
    events = final_store.list_since("t1", "t1", since_id=0)
    assert len(events) == 30
