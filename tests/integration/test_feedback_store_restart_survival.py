"""Integration: FeedbackStore persists run feedback across restarts.

Verifies that feedback submitted to one FeedbackStore instance is readable from
a fresh instance pointing at the same JSON file (Rule 2 RO track: durable-store
changes require restart-survival test).
"""

from __future__ import annotations

import pytest
from hi_agent.evolve.feedback_store import FeedbackStore, RunFeedback


@pytest.mark.serial
def test_feedback_survives_restart(tmp_path):
    """Feedback submitted in store1 is readable from store2 (restart simulation)."""
    storage = tmp_path / "feedback.json"

    store1 = FeedbackStore(storage_path=storage)
    store1.submit(
        RunFeedback(
            run_id="run-001",
            rating=0.9,
            tenant_id="t-test",
            user_id="u-1",
            project_id="proj-001",
            notes="great run",
        )
    )
    # Simulate process death — FeedbackStore flushes synchronously so no
    # explicit close step is required.

    store2 = FeedbackStore(storage_path=storage)
    result = store2.get("run-001")
    assert result is not None, "Feedback not found after restart"
    assert result.tenant_id == "t-test"
    assert result.rating == 0.9
    assert result.notes == "great run"


@pytest.mark.serial
def test_multiple_feedback_entries_survive_restart(tmp_path):
    """Multiple feedback records all persist across restarts."""
    storage = tmp_path / "feedback_multi.json"

    store1 = FeedbackStore(storage_path=storage)
    store1.submit(RunFeedback(run_id="run-A", rating=0.8, tenant_id="t-test"))
    store1.submit(RunFeedback(run_id="run-B", rating=0.5, tenant_id="t-test"))
    store1.submit(RunFeedback(run_id="run-C", rating=1.0, tenant_id="t-test"))

    store2 = FeedbackStore(storage_path=storage)
    assert store2.get("run-A") is not None
    assert store2.get("run-B") is not None
    assert store2.get("run-C") is not None
    assert store2.get("run-D") is None


@pytest.mark.serial
def test_feedback_overwrite_survives_restart(tmp_path):
    """Overwritten feedback (same run_id) is reflected correctly after restart."""
    storage = tmp_path / "feedback_overwrite.json"

    store1 = FeedbackStore(storage_path=storage)
    store1.submit(RunFeedback(run_id="run-X", rating=0.3, tenant_id="t-test", notes="initial"))
    store1.submit(RunFeedback(run_id="run-X", rating=0.9, tenant_id="t-test", notes="revised"))

    store2 = FeedbackStore(storage_path=storage)
    result = store2.get("run-X")
    assert result is not None
    assert result.rating == 0.9
    assert result.notes == "revised"
