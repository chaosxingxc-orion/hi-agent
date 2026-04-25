"""Tests for RunSession integration with RunExecutor.

Validates that:
- RunExecutor with session=None works as before (backward compat)
- RunExecutor with session tracks L0 records
- RunExecutor with session marks compact boundaries after compression
- RunExecutor with session emits cost summary
- RunExecutor with session saves checkpoint at stage boundaries
- Session checkpoint contains correct state after run
"""

from __future__ import annotations

import json
import os
import tempfile

from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.session.run_session import RunSession

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_contract(
    task_id: str = "test-session-001",
    goal: str = "session integration test",
    **kwargs: object,
) -> TaskContract:
    """Helper to create task contracts for tests."""
    return TaskContract(task_id=task_id, goal=goal, **kwargs)


# ---------------------------------------------------------------------------
# Test: session=None works as before (backward compat)
# ---------------------------------------------------------------------------


class TestRunExecutorSessionNone:
    """RunExecutor still works fine when session is not explicitly provided."""

    def test_execute_completes_without_explicit_session(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(
            contract,
            kernel,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        result = executor.execute()
        assert result == "completed"

    def test_default_session_created_internally(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(
            contract,
            kernel,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        # A default session should be created internally
        assert executor.session is not None

    def test_explicit_none_session(self) -> None:
        """Passing session=None explicitly should still create default."""
        contract = _make_contract()
        kernel = MockKernel()
        executor = RunExecutor(
            contract,
            kernel,
            session=None,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        # Default session created internally
        assert executor.session is not None


# ---------------------------------------------------------------------------
# Test: session tracks L0 records
# ---------------------------------------------------------------------------


class TestRunExecutorSessionL0Records:
    """RunExecutor delegates event recording to session."""

    def test_session_receives_l0_records(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-l0", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        result = executor.execute()
        assert result == "completed"

        # Session should have accumulated L0 records
        assert len(session.l0_records) > 0

    def test_session_l0_contains_run_started(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-l0-events", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        event_types = [r["event_type"] for r in session.l0_records]
        assert "RunStarted" in event_types

    def test_session_l0_contains_stage_events(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-stages", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        event_types = [r["event_type"] for r in session.l0_records]
        assert "StageStateChanged" in event_types

    def test_session_events_also_tracked(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-events", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        # Session events list should also be populated
        assert len(session.events) > 0


# ---------------------------------------------------------------------------
# Test: session marks compact boundaries after compression
# ---------------------------------------------------------------------------


class TestRunExecutorSessionCompactBoundary:
    """RunExecutor marks compact boundaries in session after stage compression."""

    def test_compact_boundaries_set_after_stages(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-compact", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        result = executor.execute()
        assert result == "completed"

        # At least one compact boundary should exist (one per completed stage)
        assert session.last_compact_boundary is not None

    def test_l1_summaries_populated(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-l1", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        # L1 summaries should be set for completed stages
        assert len(session.l1_summaries) > 0

    def test_compact_boundary_has_stage_id(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-cb-stage", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        boundary = session.last_compact_boundary
        assert boundary is not None
        assert boundary.stage_id != ""
        assert boundary.summary_ref != ""


# ---------------------------------------------------------------------------
# Test: session emits cost summary
# ---------------------------------------------------------------------------


class TestRunExecutorSessionCostSummary:
    """RunExecutor emits cost summary via observability at run end."""

    def test_cost_summary_emitted_on_success(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-cost", task_contract=contract)
        observed: list[tuple[str, dict]] = []

        def hook(name: str, payload: dict[str, object]) -> None:
            observed.append((name, payload))

        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            observability_hook=hook,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        executor.execute()

        cost_events = [e for e in observed if e[0] == "run_cost_summary"]
        assert len(cost_events) == 1
        summary = cost_events[0][1]
        assert "total_cost_usd" in summary
        assert "total_llm_calls" in summary

    def test_cost_summary_tracks_routing_calls(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-llm", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        cost = session.get_cost_summary()
        # At least routing LLM calls should be recorded (one per stage)
        assert cost["total_llm_calls"] > 0

    def test_cost_summary_emitted_on_failure(self) -> None:
        contract = _make_contract(constraints=["fail_action:gather_info"])
        kernel = MockKernel()
        session = RunSession(run_id="test-run-cost-fail", task_contract=contract)
        observed: list[tuple[str, dict]] = []

        def hook(name: str, payload: dict[str, object]) -> None:
            observed.append((name, payload))

        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            observability_hook=hook,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        executor.execute()

        cost_events = [e for e in observed if e[0] == "run_cost_summary"]
        assert len(cost_events) == 1


# ---------------------------------------------------------------------------
# Test: session saves checkpoint at stage boundaries
# ---------------------------------------------------------------------------


class TestRunExecutorSessionCheckpoint:
    """RunExecutor saves session checkpoint at stage boundaries."""

    def test_checkpoint_saved_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract = _make_contract()
            kernel = MockKernel()
            session = RunSession(
                run_id="test-run-ckpt",
                task_contract=contract,
                storage_dir=tmpdir,
            )
            executor = RunExecutor(
                contract,
                kernel,
                session=session,
                raw_memory=RawMemoryStore(),
                event_emitter=EventEmitter(),
                compressor=MemoryCompressor(),
                acceptance_policy=AcceptancePolicy(),
                cts_budget=CTSExplorationBudget(),
                policy_versions=PolicyVersionSet(),
            )

            executor.execute()

            # Checkpoint file should exist
            checkpoint_files = [f for f in os.listdir(tmpdir) if f.startswith("checkpoint_")]
            assert len(checkpoint_files) > 0

    def test_checkpoint_contains_stage_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract = _make_contract()
            kernel = MockKernel()
            session = RunSession(
                run_id="test-run-ckpt-state",
                task_contract=contract,
                storage_dir=tmpdir,
            )
            executor = RunExecutor(
                contract,
                kernel,
                session=session,
                raw_memory=RawMemoryStore(),
                event_emitter=EventEmitter(),
                compressor=MemoryCompressor(),
                acceptance_policy=AcceptancePolicy(),
                cts_budget=CTSExplorationBudget(),
                policy_versions=PolicyVersionSet(),
            )

            executor.execute()

            checkpoint_files = [f for f in os.listdir(tmpdir) if f.startswith("checkpoint_")]
            assert len(checkpoint_files) > 0

            # Load and verify checkpoint contents
            ckpt_path = os.path.join(tmpdir, checkpoint_files[0])
            with open(ckpt_path, encoding="utf-8") as f:
                ckpt = json.load(f)

            assert "current_stage" in ckpt
            assert ckpt["current_stage"] != ""
            assert "action_seq" in ckpt
            assert "stage_states" in ckpt

    def test_checkpoint_run_id_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract = _make_contract()
            kernel = MockKernel()
            session = RunSession(
                run_id="test-run-ckpt-id",
                task_contract=contract,
                storage_dir=tmpdir,
            )
            executor = RunExecutor(
                contract,
                kernel,
                session=session,
                raw_memory=RawMemoryStore(),
                event_emitter=EventEmitter(),
                compressor=MemoryCompressor(),
                acceptance_policy=AcceptancePolicy(),
                cts_budget=CTSExplorationBudget(),
                policy_versions=PolicyVersionSet(),
            )

            executor.execute()

            checkpoint_files = [f for f in os.listdir(tmpdir) if f.startswith("checkpoint_")]
            ckpt_path = os.path.join(tmpdir, checkpoint_files[0])
            with open(ckpt_path, encoding="utf-8") as f:
                ckpt = json.load(f)

            # run_id in checkpoint should match the kernel-assigned run_id
            assert ckpt["run_id"] == executor.run_id


# ---------------------------------------------------------------------------
# Test: session checkpoint contains correct state after run
# ---------------------------------------------------------------------------


class TestRunExecutorSessionCheckpointState:
    """Session checkpoint has accurate state reflecting the run."""

    def test_checkpoint_has_l0_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract = _make_contract()
            kernel = MockKernel()
            session = RunSession(
                run_id="test-run-ckpt-l0",
                task_contract=contract,
                storage_dir=tmpdir,
            )
            executor = RunExecutor(
                contract,
                kernel,
                session=session,
                raw_memory=RawMemoryStore(),
                event_emitter=EventEmitter(),
                compressor=MemoryCompressor(),
                acceptance_policy=AcceptancePolicy(),
                cts_budget=CTSExplorationBudget(),
                policy_versions=PolicyVersionSet(),
            )

            executor.execute()

            ckpt = session.to_checkpoint()
            assert len(ckpt["l0_records"]) > 0

    def test_checkpoint_has_l1_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract = _make_contract()
            kernel = MockKernel()
            session = RunSession(
                run_id="test-run-ckpt-l1",
                task_contract=contract,
                storage_dir=tmpdir,
            )
            executor = RunExecutor(
                contract,
                kernel,
                session=session,
                raw_memory=RawMemoryStore(),
                event_emitter=EventEmitter(),
                compressor=MemoryCompressor(),
                acceptance_policy=AcceptancePolicy(),
                cts_budget=CTSExplorationBudget(),
                policy_versions=PolicyVersionSet(),
            )

            executor.execute()

            ckpt = session.to_checkpoint()
            assert len(ckpt["l1_summaries"]) > 0

    def test_checkpoint_has_llm_calls(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-ckpt-llm", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        ckpt = session.to_checkpoint()
        assert len(ckpt["llm_calls"]) > 0

    def test_checkpoint_has_compact_boundaries(self) -> None:
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-ckpt-cb", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        ckpt = session.to_checkpoint()
        assert len(ckpt["compact_boundaries"]) > 0

    def test_checkpoint_round_trip(self) -> None:
        """Checkpoint can be serialized and restored."""
        contract = _make_contract()
        kernel = MockKernel()
        session = RunSession(run_id="test-run-roundtrip", task_contract=contract)
        executor = RunExecutor(
            contract,
            kernel,
            session=session,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        ckpt_data = session.to_checkpoint()
        restored = RunSession.from_checkpoint(ckpt_data, task_contract=contract)

        assert restored.run_id == session.run_id
        assert len(restored.l0_records) == len(session.l0_records)
        assert len(restored.llm_calls) == len(session.llm_calls)
        assert restored.current_stage == session.current_stage
