"""Re-lease attempt_id bump regression test (W35-T9, C-3 closure promotion).

W35-T9 added the W34-F.2 fulfillment in ``hi_agent/server/app.py`` —
``_rehydrate_runs`` mints a fresh ``attempt_id`` (UUID4) on lease
re-release, links the new attempt back to the original ``run_id`` via
``parent_run_id``, and increments ``attempt_count``. The original
W35 delivery notice claimed ``verified_at_release_head`` but cited a
non-existent test file. RIA W35 corrective C-3 lands the regression
test so the closure level can promote from ``code-fix-only`` to
``verified_at_release_head``.

Layer 2 (integration) — real file-backed SQLite ``SQLiteRunStore``;
zero mocks on the subsystem under test. The bump logic itself was
extracted into ``_bump_attempt_id_on_release`` (a refactor-for-
testability with no semantic change) so the lineage invariants are
reachable without spinning up the full FastAPI startup harness.
"""

from __future__ import annotations

import logging
import time
import uuid

import pytest
from hi_agent.server.app import _bump_attempt_id_on_release
from hi_agent.server.run_store import RunRecord, SQLiteRunStore

pytestmark = pytest.mark.integration


def _make_record(
    *,
    run_id: str,
    tenant_id: str = "tenant-X",
    attempt_id: str = "initial-A",
    parent_run_id: str = "",
    attempt_count: int = 0,
) -> RunRecord:
    """Build a minimal RunRecord with W33-F spine fields populated."""
    now = time.time()
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        user_id="u1",
        session_id="s1",
        task_contract_json='{"task":"probe"}',
        status="queued",
        priority=5,
        attempt_count=attempt_count,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
        parent_run_id=parent_run_id,
        attempt_id=attempt_id,
    )


def _logger() -> logging.Logger:
    return logging.getLogger("test_run_manager_release_attempt_id_bump")


def test_release_bumps_attempt_id_to_fresh_uuid(tmp_path) -> None:
    """After release, attempt_id is replaced with a fresh UUID4 string."""
    store = SQLiteRunStore(db_path=str(tmp_path / "runs.db"))
    run_id = "run-X"
    store.upsert(_make_record(run_id=run_id, attempt_id="initial-A"))

    new_attempt_id = _bump_attempt_id_on_release(store, run_id, _logger())

    bumped = store.get(run_id)
    assert bumped is not None, "Record disappeared after bump"
    assert bumped.attempt_id != "initial-A", (
        "attempt_id was not rotated on re-lease; W34-F.2 lineage chain "
        "would be unwalkable for postmortem reconstruction."
    )
    # Helper return value matches what is persisted.
    assert new_attempt_id == bumped.attempt_id
    # Validate the new value is a real UUID4 string (not an empty/sentinel value).
    parsed = uuid.UUID(bumped.attempt_id)
    assert parsed.version == 4, (
        f"attempt_id={bumped.attempt_id!r} is not a UUID4; "
        f"got version={parsed.version}"
    )


def test_release_sets_parent_run_id_to_original(tmp_path) -> None:
    """After release, parent_run_id points at the original run_id."""
    store = SQLiteRunStore(db_path=str(tmp_path / "runs.db"))
    run_id = "run-X"
    store.upsert(
        _make_record(run_id=run_id, attempt_id="initial-A", parent_run_id="")
    )

    _bump_attempt_id_on_release(store, run_id, _logger())

    bumped = store.get(run_id)
    assert bumped is not None
    assert bumped.parent_run_id == run_id, (
        "parent_run_id must be set to the original run_id so the "
        "per-attempt lineage chain is walkable from the latest attempt "
        "back to the root run (W34-F.2 design)."
    )


def test_release_increments_attempt_count(tmp_path) -> None:
    """attempt_count is incremented; None/zero baselines both bump to >=1."""
    store = SQLiteRunStore(db_path=str(tmp_path / "runs.db"))

    # Case 1: attempt_count=2 → 3.
    run_a = "run-A"
    store.upsert(_make_record(run_id=run_a, attempt_count=2))
    _bump_attempt_id_on_release(store, run_a, _logger())
    bumped_a = store.get(run_a)
    assert bumped_a is not None
    assert bumped_a.attempt_count == 3, (
        f"attempt_count should increment 2 -> 3, got {bumped_a.attempt_count}"
    )

    # Case 2: attempt_count baseline of 0 → 1. RunRecord types attempt_count
    # as int (not Optional), so the production helper's
    # ``attempt_count or 0`` defensively coalesces None / 0 to the same
    # baseline; the durable column default is also 0. This case exercises
    # the zero-baseline path that ``_bump_attempt_id_on_release`` takes
    # for a freshly-recovered run that has never been retried.
    run_b = "run-B"
    store.upsert(_make_record(run_id=run_b, attempt_count=0))
    _bump_attempt_id_on_release(store, run_b, _logger())
    bumped_b = store.get(run_b)
    assert bumped_b is not None
    assert bumped_b.attempt_count == 1, (
        f"attempt_count should bump 0 -> 1, got {bumped_b.attempt_count}"
    )
