"""DF-48 regression test: reasoning trace persistence.

Pins the persist_reasoning_trace → save_reasoning_trace → load-back path.
Code was already correct at HEAD; this test adds coverage to prevent
regressions.

Background (P-2): StageExecutor.persist_reasoning_trace() flushes the
in-memory ReasoningTrace to L1 ShortTermMemoryStore via
ShortTermMemoryStore.save_reasoning_trace().  The trace is then loadable
by ShortTermMemoryStore.load_reasoning_trace() and must parse as a valid
ReasoningTrace with all appended steps present.
"""

from __future__ import annotations

from typing import Any

import pytest
from hi_agent.contracts.reasoning import ReasoningStep, ReasoningTrace
from hi_agent.memory.short_term import ShortTermMemoryStore

# ---------------------------------------------------------------------------
# Test — DF-48: persist_reasoning_trace writes JSON that round-trips cleanly
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_reasoning_trace_persists_to_session(tmp_path: Any) -> None:
    """Regression DF-48: persist_reasoning_trace must write trace data that can
    be read back.

    Strategy: rather than constructing a full StageExecutor (which requires a
    complete RunExecutor harness), we drive the persistence layer directly:
      1. Build a ShortTermMemoryStore backed by tmp_path.
      2. Construct a ReasoningTrace with N steps.
      3. Call save_reasoning_trace(run_id, stage_id, trace).
      4. Call load_reasoning_trace(run_id, stage_id) and assert the file exists
         and the deserialized trace has exactly N steps with correct content.

    This pins the storage contract, which is the core of DF-48.  The
    StageExecutor path (append_reasoning_step + persist_reasoning_trace) is
    also exercised in the second sub-test below to confirm end-to-end wiring.
    """
    store = ShortTermMemoryStore(storage_dir=str(tmp_path), max_sessions=0)

    run_id = "run-df48-test"
    stage_id = "stage-analysis"
    n_steps = 3

    trace = ReasoningTrace(run_id=run_id, stage_id=stage_id)
    for i in range(n_steps):
        trace.append(
            ReasoningStep(
                description=f"Step {i}: analysed evidence chunk {i}",
                evidence_refs=[f"doc-{i}"],
                confidence=round(0.7 + i * 0.1, 1),
            )
        )

    # --- Act: persist and reload -------------------------------------------
    store.save_reasoning_trace(run_id, stage_id, trace)

    # The file must exist on disk under the _reasoning sub-directory.
    reasoning_dir = tmp_path / "_reasoning"
    assert reasoning_dir.exists(), (
        "_reasoning sub-directory not created by save_reasoning_trace."
    )
    trace_files = list(reasoning_dir.glob("*.json"))
    assert len(trace_files) == 1, (
        f"Expected exactly one trace JSON file, found: {trace_files}"
    )

    # Load back and verify.
    loaded = store.load_reasoning_trace(run_id, stage_id)

    assert loaded is not None, (
        "load_reasoning_trace returned None after a successful save.  "
        "This is the DF-48 regression."
    )
    assert loaded.run_id == run_id
    assert loaded.stage_id == stage_id
    assert len(loaded.steps) == n_steps, (
        f"Expected {n_steps} steps after round-trip, got {len(loaded.steps)}.  "
        "Steps were lost during serialization.  This is the DF-48 regression."
    )

    # Verify step content survives serialization.
    for i, step in enumerate(loaded.steps):
        assert f"Step {i}" in step.description, (
            f"Step {i} description mismatch after round-trip: {step.description!r}"
        )
        assert step.step_index == i, (
            f"step_index not assigned correctly: expected {i}, got {step.step_index}"
        )


@pytest.mark.integration
def test_stage_executor_persist_reasoning_trace_end_to_end(tmp_path: Any) -> None:
    """DF-48 end-to-end wiring: StageExecutor.append_reasoning_step then
    persist_reasoning_trace writes a trace that ShortTermMemoryStore can load.

    Exercises the full StageExecutor side-channel path:
      append_reasoning_step → _reasoning_traces dict → persist_reasoning_trace
      → save_reasoning_trace → disk → load_reasoning_trace.

    StageExecutor is constructed with minimal dependencies since only the
    reasoning-trace side-channel is under test.  All other constructor args
    are None/empty (they are not invoked by the reasoning-trace methods).
    """
    from hi_agent.runner_stage import StageExecutor

    store = ShortTermMemoryStore(storage_dir=str(tmp_path), max_sessions=0)

    # StageExecutor has many constructor kwargs; only short_term_store matters
    # for the reasoning-trace side-channel.  The rest are set to None/empty so
    # the executor can be constructed without a full RunExecutor harness.
    executor = StageExecutor(
        kernel=None,
        route_engine=None,
        context_manager=None,
        budget_guard=None,
        optional_stages=set(),
        acceptance_policy=None,
        policy_versions=None,
        knowledge_query_fn=None,
        knowledge_query_text_builder=None,
        retrieval_engine=None,
        auto_compress=None,
        cost_calculator=None,
        short_term_store=store,
    )

    run_id = "run-df48-e2e"
    stage_id = "stage-plan"

    executor.append_reasoning_step(
        run_id, stage_id, ReasoningStep(description="Identified goal ambiguity")
    )
    executor.append_reasoning_step(
        run_id, stage_id, ReasoningStep(description="Selected strategy A")
    )

    executor.persist_reasoning_trace(run_id, stage_id)

    loaded = store.load_reasoning_trace(run_id, stage_id)

    assert loaded is not None, (
        "load_reasoning_trace returned None after StageExecutor.persist_reasoning_trace. "
        "The side-channel → disk path is broken.  This is the DF-48 regression."
    )
    assert len(loaded.steps) == 2, (
        f"Expected 2 steps, got {len(loaded.steps)}.  "
        "Not all appended steps survived persist_reasoning_trace."
    )
    assert loaded.steps[0].description == "Identified goal ambiguity"
    assert loaded.steps[1].description == "Selected strategy A"

    # After persist, the in-memory trace must be cleared (popped from dict).
    in_memory = executor._reasoning_traces.get((run_id, stage_id))
    assert in_memory is None, (
        "In-memory trace was not cleared after persist_reasoning_trace; "
        "calling persist twice would write a second (empty) trace."
    )
