"""Track W2-E.1: RunPostmortem carries project_id from TaskContract.

Audit found that ``RunLifecycle.build_postmortem`` constructed
``RunPostmortem(...)`` without ``project_id``, so the dataclass default ``""``
was persisted into Evolve's run history.  Cross-run / cross-project analysis
then could not attribute postmortems to the originating project.

Layer 2 — Integration: real RunExecutor + real RunLifecycle.  No MagicMock on
the subsystem under test.
"""

from __future__ import annotations

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

pytestmark = pytest.mark.integration


def _make_executor(*, project_id: str) -> RunExecutor:
    contract = TaskContract(
        task_id="t-pm-spine",
        goal="postmortem spine test",
        task_family="quick_task",
        project_id=project_id,
    )
    return RunExecutor(
        contract,
        MockKernel(strict_mode=True),
        policy_versions=PolicyVersionSet(),
        raw_memory=RawMemoryStore(),
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
    )


def test_build_postmortem_carries_project_id_from_contract() -> None:
    """W2-E.1: contract.project_id flows into RunPostmortem.project_id."""
    executor = _make_executor(project_id="proj-X")
    pm = executor._build_postmortem("completed")
    assert pm.project_id == "proj-X", (
        "RunPostmortem.project_id must be sourced from TaskContract.project_id; "
        f"got {pm.project_id!r}"
    )


def test_build_postmortem_empty_project_id_when_contract_unscoped() -> None:
    """Back-compat: an unscoped TaskContract still produces a valid postmortem
    (with empty project_id), it just preserves the contract's empty value."""
    executor = _make_executor(project_id="")
    pm = executor._build_postmortem("completed")
    assert pm.project_id == ""


def test_build_postmortem_two_projects_dont_cross_attribute() -> None:
    """W2-E.1: postmortems for two contracts attribute to their own project."""
    pm_a = _make_executor(project_id="proj-A")._build_postmortem("completed")
    pm_b = _make_executor(project_id="proj-B")._build_postmortem("failed")
    assert pm_a.project_id == "proj-A"
    assert pm_b.project_id == "proj-B"
