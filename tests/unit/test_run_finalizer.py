"""Unit tests for RunFinalizer (HI-W7-004)."""
import pytest
from unittest.mock import MagicMock
from hi_agent.execution.run_finalizer import RunFinalizerContext, RunFinalizer
from hi_agent.contracts.requests import RunResult


def make_ctx(**overrides):
    defaults = dict(
        run_id="test-run", contract=MagicMock(task_id="t1", acceptance_criteria=[], goal="test"),
        raw_memory=None, mid_term_store=None, long_term_consolidator=None,
        lifecycle=MagicMock(), stage_summaries={}, failure_collector=None,
        feedback_store=None, restart_policy=None, run_start_monotonic=None,
        last_exception_msg=None, last_exception_type=None, skill_ids_used=[],
        pending_subrun_futures={}, completed_subrun_results={},
        capability_provenance_store={}, emit_observability_fn=None,
        persist_snapshot_fn=None, finalize_skill_outcomes_fn=None,
        sync_to_context_fn=None, env="dev", readiness_snapshot={},
        mcp_status={}, kernel=MagicMock(mode="local-fsm"),
        stages=[], dag=None, action_seq=None, policy_versions=None, current_stage=None,
    )
    defaults.update(overrides)
    return RunFinalizerContext(**defaults)


def test_completed_returns_run_result():
    assert isinstance(RunFinalizer(make_ctx()).finalize("completed"), RunResult)

def test_completed_status():
    assert RunFinalizer(make_ctx()).finalize("completed").status == "completed"

def test_failed_status():
    assert RunFinalizer(make_ctx()).finalize("failed").status == "failed"

def test_run_id_preserved():
    assert RunFinalizer(make_ctx(run_id="run-42")).finalize("completed").run_id == "run-42"

def test_raw_memory_closed():
    raw = MagicMock()
    raw._base_dir = raw._base_dir_path = None
    RunFinalizer(make_ctx(raw_memory=raw)).finalize("completed")
    raw.close.assert_called_once()

def test_lifecycle_called():
    lc = MagicMock()
    RunFinalizer(make_ctx(lifecycle=lc)).finalize("completed")
    lc.finalize_run.assert_called_once()

def test_raw_close_before_lifecycle():
    order = []
    raw = MagicMock()
    raw._base_dir = raw._base_dir_path = None
    raw.close.side_effect = lambda: order.append("close")
    lc = MagicMock()
    lc.finalize_run.side_effect = lambda *a, **kw: order.append("lifecycle")
    RunFinalizer(make_ctx(raw_memory=raw, lifecycle=lc)).finalize("completed")
    assert order.index("close") < order.index("lifecycle")

def test_error_msg_in_failed_result():
    result = RunFinalizer(make_ctx(last_exception_msg="boom")).finalize("failed")
    assert result.error and "boom" in result.error
