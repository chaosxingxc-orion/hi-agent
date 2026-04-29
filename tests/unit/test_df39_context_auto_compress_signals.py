"""DF-39 regression tests for context and auto-compress fallback signals."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("fallback_explicit")

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from hi_agent.context.manager import ContextBudget, ContextManager, ContextSection
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.runner_stage import StageExecutor
from hi_agent.task_view.auto_compress import AutoCompressTrigger


class _FakeSnapshot:
    def __init__(self) -> None:
        self.health = SimpleNamespace(value="green")
        self.utilization_pct = 0.1

    def to_sections_dict(self) -> dict[str, str]:
        return {"system": "hello"}


class _RecordingRouteEngine:
    def __init__(self) -> None:
        self.providers: list[object] = []

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[object]:
        return []

    def set_context_provider(self, provider: object) -> None:
        self.providers.append(provider)


def test_runner_context_manager_receives_run_id(tmp_path) -> None:
    contract = TaskContract(task_id="df39-runner-001", goal="ctx propagation")
    kernel = MagicMock()
    kernel.start_run.return_value = "run-df39-runner-001"

    route_engine = _RecordingRouteEngine()
    session = MagicMock()
    expected_run_id = "run-df39-runner-001"

    class FakeContextManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def prepare_context(self, **kwargs: object) -> _FakeSnapshot:
            self.calls.append(kwargs)
            return _FakeSnapshot()

    context_manager = FakeContextManager()
    raw_memory = RawMemoryStore(run_id="run-df39-runner-001", base_dir=str(tmp_path))

    executor = RunExecutor(
        contract=contract,
        kernel=kernel,
        route_engine=route_engine,
        session=session,
        context_manager=context_manager,
        raw_memory=raw_memory,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    executor.run_id = expected_run_id

    assert route_engine.providers, "runner did not register a context provider"
    snapshot = route_engine.providers[-1]()
    assert snapshot["system"] == "hello"
    assert context_manager.calls == [
        {
            "purpose": "routing",
            "system_prompt": "TRACE Agent: ctx propagation",
            "run_id": expected_run_id,
        }
    ]


def test_stage_executor_passes_run_id_to_auto_compress() -> None:
    captured: list[dict[str, object]] = []

    class FakeAutoCompress:
        def check_and_compress(
            self,
            records: list[dict[str, object]],
            stage_id: str,
            *,
            budget_tokens: int = 8192,
            run_id: str | None = None,
        ) -> tuple[list[dict[str, object]], dict[str, object] | None]:
            captured.append(
                {
                    "records": list(records),
                    "stage_id": stage_id,
                    "budget_tokens": budget_tokens,
                    "run_id": run_id,
                }
            )
            return records, None

    stage_executor = StageExecutor(
        kernel=MagicMock(),
        route_engine=MagicMock(propose=MagicMock(return_value=[])),
        context_manager=None,
        budget_guard=None,
        optional_stages=set(),
        acceptance_policy=MagicMock(),
        policy_versions=MagicMock(),
        knowledge_query_fn=None,
        knowledge_query_text_builder=None,
        retrieval_engine=None,
        auto_compress=FakeAutoCompress(),
        cost_calculator=None,
    )

    executor = SimpleNamespace(
        run_id="run-df39-stage-001",
        current_stage="",
        session=SimpleNamespace(
            get_records_after_boundary=MagicMock(return_value=[]),
            set_stage_summary=MagicMock(),
            mark_compact_boundary=MagicMock(),
        ),
        contract=SimpleNamespace(goal="stage auto compress"),
        action_seq=0,
        branch_seq=0,
        decision_seq=0,
        _budget_tier_decision=None,
        _record_event=MagicMock(),
        _emit_observability=MagicMock(),
        _persist_snapshot=MagicMock(),
        _watchdog_reset=MagicMock(),
        _check_budget_exceeded=MagicMock(return_value=None),
        _record_skill_usage_from_proposal=MagicMock(),
        _execute_action_with_retry=MagicMock(),
        _record_failure=MagicMock(),
        _check_human_gate_triggers=MagicMock(),
        _watchdog_record_and_check=MagicMock(),
        _observe_skill_execution=MagicMock(),
        _trigger_recovery=MagicMock(),
        _compress_stage_summary=MagicMock(
            return_value=SimpleNamespace(outcome="completed", artifact_ids=[])
        ),
        _sync_to_context=MagicMock(),
        _signal_run_safe=MagicMock(),
        dag={},
        stage_summaries={},
        optional_stages=set(),
        policy_version="acceptance_v1",
        optimizer=SimpleNamespace(backpropagate=MagicMock()),
    )

    stage_executor.execute_stage("S1_understand", executor=executor)

    assert captured == [
        {
            "records": [],
            "stage_id": "S1_understand",
            "budget_tokens": 8192,
            "run_id": "run-df39-stage-001",
        }
    ]


def test_context_manager_truncation_fallback_records_signal() -> None:
    run_id = "test-df39-ctxmgr-truncate-001"
    clear_fallback_events(run_id)

    class EmptyCompressor:
        pass

    manager = ContextManager(
        budget=ContextBudget(total_window=1000, output_reserve=100),
        compressor=EmptyCompressor(),
    )
    section = ContextSection(
        name="history",
        content="a" * 500,
        tokens=500,
        budget=200,
        source="session_history",
    )

    manager._compact_history(section, target_tokens=100, run_id=run_id)

    events = get_fallback_events(run_id)
    assert any(event["reason"] == "compressor_missing_api" for event in events), events
    match = next(event for event in events if event["reason"] == "compressor_missing_api")
    assert match["kind"] == "heuristic"
    assert match["extra"]["component"] == "context_manager"
    assert match["extra"]["compressor_type"] == "EmptyCompressor"


def test_context_manager_passes_run_id_to_memory_compressor() -> None:
    run_id = "test-df39-ctxmgr-compressor-001"

    class RecordingCompressor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def compress_stage(self, stage_id: str, records: list[Any], **kwargs: object) -> Any:
            self.calls.append({"stage_id": stage_id, "records": records, **kwargs})
            return SimpleNamespace(findings=["summary"])

    compressor = RecordingCompressor()
    manager = ContextManager(budget=ContextBudget(), compressor=compressor)
    section = ContextSection(
        name="history",
        content="history text",
        tokens=100,
        budget=200,
        source="session_history",
    )

    manager._compact_history(section, target_tokens=50, run_id=run_id)

    assert compressor.calls
    assert compressor.calls[0]["stage_id"] == "history"
    assert compressor.calls[0]["run_id"] == run_id


def test_auto_compress_run_compressor_exception_records_fallback() -> None:
    run_id = "test-df39-autocompress-001"
    clear_fallback_events(run_id)

    class BoomCompressor:
        def compress_stage(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("injected compressor boom")

    trigger = AutoCompressTrigger(
        compress_threshold=0,
        window_threshold=0,
        compressor=BoomCompressor(),
    )
    records = [{"event_type": "x", "payload": {"i": i}} for i in range(3)]

    summary = trigger._run_compressor(records, "stage-1", run_id=run_id)

    assert summary["compression_method"] == "auto_fallback"
    events = get_fallback_events(run_id)
    assert any(event["reason"] == "auto_compress_exception" for event in events), events
    match = next(event for event in events if event["reason"] == "auto_compress_exception")
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "auto_compress._run_compressor"
    assert match["extra"]["stage_id"] == "stage-1"


def test_auto_compress_passes_run_id_to_compressor() -> None:
    run_id = "test-df39-autocompress-forward-001"

    class RecordingCompressor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def compress_stage(self, stage_id: str, records: list[Any], **kwargs: object) -> Any:
            self.calls.append({"stage_id": stage_id, "records": records, **kwargs})
            return SimpleNamespace(
                stage_id=stage_id,
                findings=["summary"],
                decisions=[],
                outcome="compressed",
                compression_method="llm",
            )

    compressor = RecordingCompressor()
    trigger = AutoCompressTrigger(
        compress_threshold=0,
        window_threshold=0,
        compressor=compressor,
    )
    records = [{"event_type": "x", "payload": {"i": i}} for i in range(3)]

    trigger._run_compressor(records, "stage-1", run_id=run_id)

    assert compressor.calls
    assert compressor.calls[0]["stage_id"] == "stage-1"
    assert compressor.calls[0]["run_id"] == run_id
