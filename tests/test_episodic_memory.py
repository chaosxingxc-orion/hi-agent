"""Tests for episodic memory: store, builder, and retriever."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hi_agent.contracts.memory import StageSummary
from hi_agent.contracts.task import TaskContract
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodeRecord, EpisodicMemoryStore
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.retriever import MemoryRetriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> str:
    return str(tmp_path / "episodes")


@pytest.fixture()
def store(tmp_dir: str) -> EpisodicMemoryStore:
    return EpisodicMemoryStore(storage_dir=tmp_dir)


def _make_episode(
    run_id: str = "run-1",
    task_family: str = "analysis",
    outcome: str = "completed",
    failure_codes: list[str] | None = None,
    tags: list[str] | None = None,
    timestamp: str = "2026-04-07T10:00:00+00:00",
) -> EpisodeRecord:
    return EpisodeRecord(
        run_id=run_id,
        task_id=f"task-{run_id}",
        task_family=task_family,
        goal=f"Goal for {run_id}",
        outcome=outcome,
        stages_completed=["S1", "S2"],
        key_findings=["finding-a", "finding-b"],
        key_decisions=["decision-x"],
        failure_codes=failure_codes or [],
        duration_seconds=120.0,
        timestamp=timestamp,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# EpisodicMemoryStore CRUD
# ---------------------------------------------------------------------------

class TestEpisodicMemoryStoreCRUD:
    def test_store_and_get(self, store: EpisodicMemoryStore) -> None:
        ep = _make_episode()
        store.store(ep)
        retrieved = store.get("run-1")
        assert retrieved is not None
        assert retrieved.run_id == "run-1"
        assert retrieved.goal == "Goal for run-1"
        assert retrieved.key_findings == ["finding-a", "finding-b"]

    def test_get_nonexistent_returns_none(self, store: EpisodicMemoryStore) -> None:
        assert store.get("no-such-run") is None

    def test_count(self, store: EpisodicMemoryStore) -> None:
        assert store.count() == 0
        store.store(_make_episode("run-1"))
        store.store(_make_episode("run-2"))
        assert store.count() == 2

    def test_clear(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("run-1"))
        store.store(_make_episode("run-2"))
        assert store.count() == 2
        store.clear()
        assert store.count() == 0

    def test_store_auto_timestamps(self, store: EpisodicMemoryStore) -> None:
        ep = _make_episode(timestamp="")
        store.store(ep)
        retrieved = store.get("run-1")
        assert retrieved is not None
        assert retrieved.timestamp != ""


# ---------------------------------------------------------------------------
# Query with filters
# ---------------------------------------------------------------------------

class TestEpisodicMemoryStoreQuery:
    def test_query_by_task_family(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", task_family="analysis"))
        store.store(_make_episode("r2", task_family="coding"))
        store.store(_make_episode("r3", task_family="analysis"))
        results = store.query(task_family="analysis")
        assert len(results) == 2
        assert all(r.task_family == "analysis" for r in results)

    def test_query_by_outcome(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", outcome="completed"))
        store.store(_make_episode("r2", outcome="failed"))
        store.store(_make_episode("r3", outcome="completed"))
        results = store.query(outcome="failed")
        assert len(results) == 1
        assert results[0].run_id == "r2"

    def test_query_by_tags(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", tags=["urgent", "review"]))
        store.store(_make_episode("r2", tags=["review"]))
        store.store(_make_episode("r3", tags=["urgent"]))
        results = store.query(tags=["urgent", "review"])
        assert len(results) == 1
        assert results[0].run_id == "r1"

    def test_query_limit(self, store: EpisodicMemoryStore) -> None:
        for i in range(10):
            store.store(_make_episode(
                f"r{i}",
                timestamp=f"2026-04-07T{10 + i:02d}:00:00+00:00",
            ))
        results = store.query(limit=3)
        assert len(results) == 3

    def test_query_returns_most_recent_first(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r-old", timestamp="2026-01-01T00:00:00+00:00"))
        store.store(_make_episode("r-new", timestamp="2026-04-07T12:00:00+00:00"))
        results = store.query()
        assert results[0].run_id == "r-new"
        assert results[1].run_id == "r-old"

    def test_query_combined_filters(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", task_family="analysis", outcome="completed"))
        store.store(_make_episode("r2", task_family="analysis", outcome="failed"))
        store.store(_make_episode("r3", task_family="coding", outcome="completed"))
        results = store.query(task_family="analysis", outcome="completed")
        assert len(results) == 1
        assert results[0].run_id == "r1"


# ---------------------------------------------------------------------------
# Similar failures
# ---------------------------------------------------------------------------

class TestGetSimilarFailures:
    def test_finds_matching_failures(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", failure_codes=["missing_evidence", "budget_exhausted"]))
        store.store(_make_episode("r2", failure_codes=["model_refusal"]))
        store.store(_make_episode("r3", failure_codes=["missing_evidence", "no_progress"]))
        results = store.get_similar_failures(["missing_evidence"])
        assert len(results) == 2
        run_ids = {r.run_id for r in results}
        assert "r1" in run_ids
        assert "r3" in run_ids

    def test_ranks_by_overlap_count(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", failure_codes=["missing_evidence"]))
        store.store(_make_episode("r2", failure_codes=["missing_evidence", "no_progress"]))
        results = store.get_similar_failures(["missing_evidence", "no_progress"])
        assert results[0].run_id == "r2"  # 2 overlaps vs 1

    def test_empty_failure_codes_returns_empty(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", failure_codes=["missing_evidence"]))
        assert store.get_similar_failures([]) == []


# ---------------------------------------------------------------------------
# Successful patterns
# ---------------------------------------------------------------------------

class TestGetSuccessfulPatterns:
    def test_returns_only_successes_in_family(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", task_family="analysis", outcome="completed"))
        store.store(_make_episode("r2", task_family="analysis", outcome="failed"))
        store.store(_make_episode("r3", task_family="coding", outcome="completed"))
        results = store.get_successful_patterns("analysis")
        assert len(results) == 1
        assert results[0].run_id == "r1"
        assert results[0].outcome == "completed"


# ---------------------------------------------------------------------------
# EpisodeBuilder
# ---------------------------------------------------------------------------

class TestEpisodeBuilder:
    def test_build_from_run_data(self) -> None:
        builder = EpisodeBuilder()
        contract = TaskContract(
            task_id="task-1",
            goal="Analyze customer data",
            task_family="analysis",
        )
        summaries = {
            "S1": StageSummary(
                stage_id="S1",
                stage_name="Understand",
                findings=["data has 1000 rows"],
                decisions=["use pandas approach"],
                outcome="done",
            ),
            "S2": StageSummary(
                stage_id="S2",
                stage_name="Gather",
                findings=["schema validated"],
                decisions=["skip optional columns"],
                outcome="done",
            ),
        }
        episode = builder.build(
            run_id="run-42",
            task_contract=contract,
            stage_summaries=summaries,
            outcome="completed",
            duration_seconds=300.0,
        )
        assert episode.run_id == "run-42"
        assert episode.task_id == "task-1"
        assert episode.task_family == "analysis"
        assert episode.goal == "Analyze customer data"
        assert episode.outcome == "completed"
        assert set(episode.stages_completed) == {"S1", "S2"}
        assert "data has 1000 rows" in episode.key_findings
        assert "schema validated" in episode.key_findings
        assert "use pandas approach" in episode.key_decisions
        assert "skip optional columns" in episode.key_decisions
        assert episode.duration_seconds == 300.0
        assert episode.timestamp != ""

    def test_build_with_l1_memories(self) -> None:
        builder = EpisodeBuilder()
        contract = TaskContract(task_id="t2", goal="Build feature", task_family="coding")
        summaries = {
            "S1": StageSummary(
                stage_id="S1",
                stage_name="Understand",
                findings=["from-summary"],
                decisions=["decision-from-summary"],
            ),
        }
        l1 = [
            CompressedStageMemory(
                stage_id="S1",
                findings=["from-l1-finding"],
                decisions=["decision-from-l1"],
            ),
        ]
        episode = builder.build(
            run_id="run-99",
            task_contract=contract,
            stage_summaries=summaries,
            l1_memories=l1,
            outcome="failed",
            failure_codes=["missing_evidence"],
        )
        # L1 findings take priority over summary findings
        assert "from-l1-finding" in episode.key_findings
        # Decisions merge: summaries first, then L1 supplements
        assert "decision-from-summary" in episode.key_decisions
        assert "decision-from-l1" in episode.key_decisions
        assert episode.failure_codes == ["missing_evidence"]

    def test_build_with_no_failure_codes(self) -> None:
        builder = EpisodeBuilder()
        contract = TaskContract(task_id="t3", goal="Simple task", task_family="quick_task")
        episode = builder.build(
            run_id="run-simple",
            task_contract=contract,
            stage_summaries={},
        )
        assert episode.failure_codes == []


# ---------------------------------------------------------------------------
# MemoryRetriever
# ---------------------------------------------------------------------------

class TestMemoryRetriever:
    def test_retrieve_for_stage_with_episodic(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", task_family="analysis", outcome="completed"))
        store.store(_make_episode(
            "r2", task_family="analysis", outcome="failed",
            failure_codes=["missing_evidence"],
        ))
        retriever = MemoryRetriever(episodic_store=store)
        snippets = retriever.retrieve_for_stage(
            task_family="analysis",
            stage_id="S1",
            current_failures=["missing_evidence"],
        )
        assert len(snippets) > 0
        # Should contain both success and failure references
        text = "\n".join(snippets)
        assert "success" in text or "r1" in text
        assert "past-failure" in text or "r2" in text

    def test_retrieve_for_stage_no_episodic(self) -> None:
        retriever = MemoryRetriever(episodic_store=None)
        snippets = retriever.retrieve_for_stage(
            task_family="analysis", stage_id="S1"
        )
        assert snippets == []

    def test_retrieve_similar_episodes(self, store: EpisodicMemoryStore) -> None:
        store.store(_make_episode("r1", task_family="analysis", outcome="completed"))
        store.store(_make_episode(
            "r2", task_family="analysis", outcome="failed",
            failure_codes=["no_progress"],
        ))
        store.store(_make_episode("r3", task_family="coding", outcome="completed"))
        retriever = MemoryRetriever(episodic_store=store)
        episodes = retriever.retrieve_similar_episodes(
            task_family="analysis",
            failure_codes=["no_progress"],
            limit=5,
        )
        run_ids = {e.run_id for e in episodes}
        assert "r2" in run_ids  # failure match
        assert "r1" in run_ids  # family match
        assert "r3" not in run_ids  # different family, no failure overlap

    def test_retrieve_respects_token_budget(self, store: EpisodicMemoryStore) -> None:
        # Store many episodes
        for i in range(20):
            store.store(_make_episode(
                f"r{i}",
                task_family="analysis",
                outcome="completed",
                timestamp=f"2026-04-07T{10 + i % 10:02d}:00:00+00:00",
            ))
        retriever = MemoryRetriever(episodic_store=store)
        # Very tight budget should limit results
        snippets = retriever.retrieve_for_stage(
            task_family="analysis",
            stage_id="S1",
            budget_tokens=50,  # ~200 chars, very tight
        )
        # Should have at most a few snippets due to budget
        assert len(snippets) <= 3


# ---------------------------------------------------------------------------
# Persistence: store -> new instance -> get
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_survives_new_instance(self, tmp_dir: str) -> None:
        store1 = EpisodicMemoryStore(storage_dir=tmp_dir)
        store1.store(_make_episode("run-persist"))

        # Create a completely new store instance pointing to same dir
        store2 = EpisodicMemoryStore(storage_dir=tmp_dir)
        retrieved = store2.get("run-persist")
        assert retrieved is not None
        assert retrieved.run_id == "run-persist"
        assert retrieved.goal == "Goal for run-persist"
        assert retrieved.key_findings == ["finding-a", "finding-b"]

    def test_query_survives_new_instance(self, tmp_dir: str) -> None:
        store1 = EpisodicMemoryStore(storage_dir=tmp_dir)
        store1.store(_make_episode("r1", task_family="analysis", outcome="completed"))
        store1.store(_make_episode("r2", task_family="analysis", outcome="failed"))

        store2 = EpisodicMemoryStore(storage_dir=tmp_dir)
        results = store2.query(task_family="analysis", outcome="completed")
        assert len(results) == 1
        assert results[0].run_id == "r1"
