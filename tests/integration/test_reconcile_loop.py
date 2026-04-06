"""Integration tests for automatic reconciliation loop behavior."""

from __future__ import annotations

from hi_agent.runtime_adapter import (
    ConsistencyIssue,
    InMemoryConsistencyJournal,
    ReconcileLoop,
)


class _FlakyBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._failures_left: dict[str, int] = {}

    def fail_open_stage(self, stage_id: str, failures: int) -> None:
        self._failures_left[stage_id] = failures

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(stage_id)
        remaining = self._failures_left.get(stage_id, 0)
        if remaining > 0:
            self._failures_left[stage_id] = remaining - 1
            raise RuntimeError(f"planned failure for {stage_id}")


def _seed_open_stage_issue(journal: InMemoryConsistencyJournal, stage_id: str) -> None:
    journal.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": stage_id},
            error="RuntimeError: open failed",
        )
    )


def test_run_once_reports_single_round_outcome() -> None:
    """A one-shot run should expose the first-round reconciler result."""
    journal = InMemoryConsistencyJournal()
    _seed_open_stage_issue(journal, "S1_understand")
    backend = _FlakyBackend()
    loop = ReconcileLoop(backend=backend, journal=journal)

    report = loop.run_once()

    assert report.rounds == 1
    assert report.applied == 1
    assert report.failed == 0
    assert report.skipped == 0
    assert report.dead_letter_count == 0
    assert backend.calls == ["S1_understand"]


def test_run_until_clean_retries_failed_rounds_with_backoff() -> None:
    """Retryable failures should be retried with deterministic backoff delays."""
    journal = InMemoryConsistencyJournal()
    _seed_open_stage_issue(journal, "S2_plan")
    backend = _FlakyBackend()
    backend.fail_open_stage("S2_plan", failures=1)

    sleeps: list[float] = []

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    loop = ReconcileLoop(
        backend=backend,
        journal=journal,
        max_issue_retries=3,
        backoff_base_seconds=0.5,
        backoff_multiplier=2.0,
        sleep_fn=_sleep,
    )

    report = loop.run_until_clean(max_rounds=5)

    assert report.rounds == 2
    assert report.applied == 1
    assert report.failed == 0
    assert report.skipped == 0
    assert report.dead_letter_count == 0
    assert sleeps == [0.5]
    assert backend.calls == ["S2_plan", "S2_plan"]


def test_run_until_clean_moves_repeated_failures_to_dead_letter() -> None:
    """Issues past retry limit should be counted as dead-letter and skipped."""
    journal = InMemoryConsistencyJournal()
    _seed_open_stage_issue(journal, "S3_execute")
    backend = _FlakyBackend()
    backend.fail_open_stage("S3_execute", failures=99)

    sleeps: list[float] = []

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    loop = ReconcileLoop(
        backend=backend,
        journal=journal,
        max_issue_retries=2,
        backoff_base_seconds=0.25,
        backoff_multiplier=2.0,
        sleep_fn=_sleep,
    )

    report = loop.run_until_clean(max_rounds=6)

    assert report.rounds == 2
    assert report.applied == 0
    assert report.failed == 0
    assert report.skipped == 1
    assert report.dead_letter_count == 1
    assert sleeps == [0.25]
    assert backend.calls == ["S3_execute", "S3_execute"]
