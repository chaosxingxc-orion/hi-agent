"""Tests for the P-2 Reasoning Trace side-channel.

Verifies that a business-layer stage handler can append structured reasoning
steps during stage execution, and that those steps are persisted to L1 STM
keyed by ``(run_id, stage_id)`` and retrievable after the stage finalizes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hi_agent.contracts.reasoning import ReasoningStep, ReasoningTrace
from hi_agent.memory.short_term import ShortTermMemoryStore
from hi_agent.runner_stage import StageExecutor


def _make_stage_executor(store: ShortTermMemoryStore) -> StageExecutor:
    """Build a StageExecutor wired with only the fields this test needs."""
    return StageExecutor(
        kernel=MagicMock(),
        route_engine=MagicMock(),
        context_manager=None,
        budget_guard=None,
        optional_stages=set(),
        acceptance_policy=MagicMock(),
        policy_versions=MagicMock(),
        knowledge_query_fn=None,
        knowledge_query_text_builder=None,
        retrieval_engine=None,
        auto_compress=None,
        cost_calculator=None,
        short_term_store=store,
    )


def test_stage_handler_can_append_step(tmp_path: Path) -> None:
    """A handler appends 3 steps; after persist, they are retrievable from L1."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path / "stm"))
    stage_exec = _make_stage_executor(store)

    run_id, stage_id = "run-1", "plan"

    # --- simulate a business-layer stage handler ---
    trace = stage_exec.get_reasoning_trace(run_id, stage_id)
    trace.append(ReasoningStep(description="assess inputs"))
    stage_exec.append_reasoning_step(
        run_id,
        stage_id,
        ReasoningStep(description="enumerate options", confidence=0.7),
    )
    stage_exec.append_reasoning_step(
        run_id,
        stage_id,
        ReasoningStep(description="select best", evidence_refs=["ev-1", "ev-2"]),
    )

    # --- platform finalizes the stage ---
    stage_exec.persist_reasoning_trace(run_id, stage_id)

    # --- retrieve from L1 ---
    loaded = store.load_reasoning_trace(run_id, stage_id)
    assert loaded is not None
    assert loaded.run_id == run_id
    assert loaded.stage_id == stage_id
    assert len(loaded.steps) == 3
    assert [s.description for s in loaded.steps] == [
        "assess inputs",
        "enumerate options",
        "select best",
    ]
    # step_index auto-assigned
    assert [s.step_index for s in loaded.steps] == [0, 1, 2]
    assert loaded.steps[1].confidence == 0.7
    assert loaded.steps[2].evidence_refs == ["ev-1", "ev-2"]


def test_reasoning_trace_persists_across_retrieve(tmp_path: Path) -> None:
    """A trace written by one store instance is readable from another."""
    storage_dir = tmp_path / "stm"
    writer = ShortTermMemoryStore(storage_dir=str(storage_dir))
    trace = ReasoningTrace(run_id="run-2", stage_id="act")
    trace.append(ReasoningStep(description="step A"))
    trace.append(ReasoningStep(description="step B"))
    writer.save_reasoning_trace("run-2", "act", trace)

    reader = ShortTermMemoryStore(storage_dir=str(storage_dir))
    loaded = reader.load_reasoning_trace("run-2", "act")
    assert loaded is not None
    assert len(loaded.steps) == 2
    assert loaded.steps[0].description == "step A"
    assert loaded.steps[1].description == "step B"


def test_empty_trace_serializes_as_empty(tmp_path: Path) -> None:
    """A stage that finalizes without steps produces an empty trace, not an error."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path / "stm"))
    stage_exec = _make_stage_executor(store)

    # Handler never appended — still access to create the empty trace.
    stage_exec.get_reasoning_trace("run-3", "evaluate")
    stage_exec.persist_reasoning_trace("run-3", "evaluate")

    loaded = store.load_reasoning_trace("run-3", "evaluate")
    assert loaded is not None
    assert loaded.run_id == "run-3"
    assert loaded.stage_id == "evaluate"
    assert loaded.steps == []


def test_load_missing_returns_none(tmp_path: Path) -> None:
    """Loading a never-written trace returns None rather than raising."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path / "stm"))
    assert store.load_reasoning_trace("nope", "nope") is None


def test_persist_without_trace_is_noop(tmp_path: Path) -> None:
    """Calling persist for a stage where no handler appended is a safe no-op."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path / "stm"))
    stage_exec = _make_stage_executor(store)
    # Should not raise.
    stage_exec.persist_reasoning_trace("ghost", "ghost")
    assert store.load_reasoning_trace("ghost", "ghost") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
