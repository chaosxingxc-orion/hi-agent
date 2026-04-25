"""Unit tests: RunExecutor must fail-fast when raw_memory is not injected.

Guards Rule 6 — inline fallback construction of unscoped RawMemoryStore is
forbidden since the S3 store registry (a35eb22) landed.  SA-A7 residual.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.route_engine.acceptance import AcceptancePolicy


def _make_contract() -> TaskContract:
    return TaskContract(task_id="test-injection-t1", goal="injection guard test")


def _make_kernel() -> MagicMock:
    """Minimal mock kernel sufficient for RunExecutor construction checks."""
    kernel = MagicMock()
    kernel.start_run.return_value = "run-injection-001"
    kernel.stages = {}
    return kernel


def test_runner_raises_on_missing_raw_memory() -> None:
    """RunExecutor must raise ValueError when raw_memory is not injected.

    The log-and-degrade fallback that constructed an unscoped RawMemoryStore
    was removed in track E1.  Any call without an injected store is a wiring
    bug and must fail immediately.
    """
    from hi_agent.runner import RunExecutor

    contract = _make_contract()
    kernel = _make_kernel()

    with pytest.raises(ValueError, match="must be injected by the builder"):
        RunExecutor(
            contract=contract,
            kernel=kernel,
            raw_memory=None,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )


def test_runner_raises_mentions_rule6() -> None:
    """The ValueError message must reference Rule 6 for traceability."""
    from hi_agent.runner import RunExecutor

    contract = _make_contract()
    kernel = _make_kernel()

    with pytest.raises(ValueError, match="Rule 6"):
        RunExecutor(
            contract=contract,
            kernel=kernel,
            raw_memory=None,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )


def test_runner_raises_mentions_builder_wiring() -> None:
    """The ValueError message must name the builder so the caller knows the fix."""
    from hi_agent.runner import RunExecutor

    contract = _make_contract()
    kernel = _make_kernel()

    with pytest.raises(ValueError, match="SystemBuilder"):
        RunExecutor(
            contract=contract,
            kernel=kernel,
            raw_memory=None,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )


def test_runner_does_not_raise_when_raw_memory_provided(tmp_path) -> None:
    """RunExecutor must construct successfully when raw_memory is injected."""
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.runner import RunExecutor

    contract = _make_contract()
    kernel = _make_kernel()
    raw_memory = RawMemoryStore(run_id="run-injection-ok", base_dir=str(tmp_path))

    executor = RunExecutor(
        contract=contract,
        kernel=kernel,
        raw_memory=raw_memory,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )

    assert executor.raw_memory is raw_memory
