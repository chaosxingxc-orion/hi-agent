"""Unit tests: RunExecutor raises ValueError for each missing required injection.

Guards Rule 6 (H2-Track3) — all 5 inline fallback constructions removed:
  event_emitter, compressor, acceptance_policy, cts_budget, policy_versions.
Each must fail fast with a clear ValueError when not explicitly injected.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor


def _make_contract() -> TaskContract:
    return TaskContract(task_id="rule6-h2-t1", goal="Rule 6 guard test")


def _make_kernel() -> MagicMock:
    """Minimal mock kernel sufficient for RunExecutor construction checks."""
    kernel = MagicMock()
    kernel.start_run.return_value = "run-rule6-001"
    kernel.stages = {}
    return kernel


def _base_kwargs() -> dict:
    """Return all required args so individual tests can omit one at a time."""
    return {
        "contract": _make_contract(),
        "kernel": _make_kernel(),
        "raw_memory": RawMemoryStore(),
        "event_emitter": EventEmitter(),
        "compressor": MemoryCompressor(),
        "acceptance_policy": AcceptancePolicy(),
        "cts_budget": CTSExplorationBudget(),
        "policy_versions": PolicyVersionSet(),
    }


# ---------------------------------------------------------------------------
# event_emitter — first of the five guarded args
# ---------------------------------------------------------------------------


def test_runner_raises_on_missing_event_emitter() -> None:
    """RunExecutor must raise ValueError when event_emitter=None.

    Rule 6: unscoped EventEmitter inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["event_emitter"] = None
    with pytest.raises(ValueError, match="event_emitter"):
        RunExecutor(**kwargs)


def test_runner_event_emitter_error_mentions_rule6() -> None:
    """ValueError for missing event_emitter must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["event_emitter"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(**kwargs)


# ---------------------------------------------------------------------------
# compressor
# ---------------------------------------------------------------------------


def test_runner_raises_on_missing_compressor() -> None:
    """RunExecutor must raise ValueError when compressor=None.

    Rule 6: unscoped MemoryCompressor inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["compressor"] = None
    with pytest.raises(ValueError, match="compressor"):
        RunExecutor(**kwargs)


def test_runner_compressor_error_mentions_rule6() -> None:
    """ValueError for missing compressor must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["compressor"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(**kwargs)


# ---------------------------------------------------------------------------
# acceptance_policy
# ---------------------------------------------------------------------------


def test_runner_raises_on_missing_acceptance_policy() -> None:
    """RunExecutor must raise ValueError when acceptance_policy=None.

    Rule 6: unscoped AcceptancePolicy inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["acceptance_policy"] = None
    with pytest.raises(ValueError, match="acceptance_policy"):
        RunExecutor(**kwargs)


def test_runner_acceptance_policy_error_mentions_rule6() -> None:
    """ValueError for missing acceptance_policy must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["acceptance_policy"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(**kwargs)


# ---------------------------------------------------------------------------
# cts_budget
# ---------------------------------------------------------------------------


def test_runner_raises_on_missing_cts_budget() -> None:
    """RunExecutor must raise ValueError when cts_budget=None.

    Rule 6: unscoped CTSExplorationBudget inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["cts_budget"] = None
    with pytest.raises(ValueError, match="cts_budget"):
        RunExecutor(**kwargs)


def test_runner_cts_budget_error_mentions_rule6() -> None:
    """ValueError for missing cts_budget must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["cts_budget"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(**kwargs)


# ---------------------------------------------------------------------------
# policy_versions
# ---------------------------------------------------------------------------


def test_runner_raises_on_missing_policy_versions() -> None:
    """RunExecutor must raise ValueError when policy_versions=None.

    Rule 6: unscoped PolicyVersionSet inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["policy_versions"] = None
    with pytest.raises(ValueError, match="policy_versions"):
        RunExecutor(**kwargs)


def test_runner_policy_versions_error_mentions_rule6() -> None:
    """ValueError for missing policy_versions must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["policy_versions"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(**kwargs)


# ---------------------------------------------------------------------------
# Positive: all args provided → construction succeeds
# ---------------------------------------------------------------------------


def test_runner_constructs_successfully_with_all_required_args(tmp_path) -> None:
    """RunExecutor must construct without error when all 5 args are injected."""
    rm = RawMemoryStore(run_id="run-rule6-ok", base_dir=str(tmp_path))
    executor = RunExecutor(
        contract=_make_contract(),
        kernel=_make_kernel(),
        raw_memory=rm,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    assert executor.event_emitter is not None
    assert executor.compressor is not None
    assert executor.acceptance_policy is not None
    assert executor.cts_budget is not None
    assert executor.policy_versions is not None
