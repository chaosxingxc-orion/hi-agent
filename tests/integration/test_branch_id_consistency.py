"""Tests for D3 fix: branch_id consistency across all branch events.

All events emitted during a single branch execution must use the same
branch_id that comes from proposal.branch_id (the deterministic hash),
not a counter-based ID from _make_branch_id().
"""

from __future__ import annotations

import inspect
import os
from typing import Any

# Allow heuristic fallback so tests can run without real LLM credentials.
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.contracts import TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contract(
    task_id: str = "test-bid-001",
    goal: str = "branch id consistency test",
) -> TaskContract:
    return TaskContract(task_id=task_id, goal=goal)


def _get_envelopes_of_type(executor: RunExecutor, event_type: str) -> list[Any]:
    """Return event envelopes of a given type from the executor's emitter."""
    return [e for e in executor.event_emitter.events if e.event_type == event_type]


def _get_branch_envelopes(executor: RunExecutor) -> list[Any]:
    """Return all event envelopes that carry a branch_id in their payload."""
    return [e for e in executor.event_emitter.events if e.payload.get("branch_id")]


def _proposed_branch_ids(executor: RunExecutor) -> list[str]:
    """Return branch_ids from BranchProposed events."""
    return [e.payload["branch_id"] for e in _get_envelopes_of_type(executor, "BranchProposed")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBranchIdConsistency:
    """All branch-lifecycle events must share the same branch_id as the proposal."""

    def test_branch_proposed_events_emitted(self) -> None:
        """At least one BranchProposed event must be emitted during execute."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        proposed = _get_envelopes_of_type(executor, "BranchProposed")
        assert len(proposed) >= 1, "At least one BranchProposed event expected"

    def test_branch_proposed_uses_proposal_branch_id(self) -> None:
        """BranchProposed event must carry proposal.branch_id (not a counter).

        A counter-based ID from _make_branch_id() looks like
        ``run-0001:S1_understand:b000``.  The proposal.branch_id is a
        deterministic base64/hex string from ``deterministic_id()``
        and must not contain the ``:b0`` counter fragment.
        """
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        proposed = _get_envelopes_of_type(executor, "BranchProposed")
        assert proposed, "At least one BranchProposed event expected"

        for event in proposed:
            bid = event.payload["branch_id"]
            assert ":b0" not in bid, (
                f"branch_id {bid!r} looks like a counter-based ID from "
                "_make_branch_id — runner_stage.py should use "
                "proposal.branch_id instead"
            )

    def test_all_branch_events_share_proposal_branch_id(self) -> None:
        """ActionDispatched / ActionSucceeded / BranchSucceeded must all use
        the same branch_id as the corresponding BranchProposed event.
        """
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        proposed_ids = set(_proposed_branch_ids(executor))
        assert proposed_ids, "Expected at least one BranchProposed event"

        # Every branch-related event should reference one of the proposed IDs.
        for event in _get_branch_envelopes(executor):
            bid = event.payload["branch_id"]
            assert bid in proposed_ids, (
                f"Event {event.event_type!r} has branch_id {bid!r} "
                f"which is not in the set of proposed branch_ids {proposed_ids}"
            )

    def test_action_dispatched_matches_proposed(self) -> None:
        """branch_id in ActionDispatched must equal branch_id in BranchProposed."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        proposed_ids = set(_proposed_branch_ids(executor))
        dispatched = _get_envelopes_of_type(executor, "ActionDispatched")

        for event in dispatched:
            assert event.payload["branch_id"] in proposed_ids, (
                f"ActionDispatched branch_id {event.payload['branch_id']!r} "
                f"does not match any BranchProposed id: {proposed_ids}"
            )

    def test_make_branch_id_still_exists_but_deprecated(self) -> None:
        """_make_branch_id must still exist (not deleted) with a deprecation note."""
        kernel = MockKernel(strict_mode=True)
        contract = _make_contract()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        assert hasattr(executor, "_make_branch_id"), (
            "_make_branch_id should still exist (deprecated but not deleted)"
        )

        doc = inspect.getdoc(executor._make_branch_id) or ""
        assert "DEPRECATED" in doc or "deprecated" in doc.lower(), (
            "_make_branch_id docstring should mention deprecation"
        )
