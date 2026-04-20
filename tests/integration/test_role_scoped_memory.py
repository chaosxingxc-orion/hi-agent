"""Integration tests for G-5 role-scoped memory namespace.

Covers L1 ShortTermMemoryStore, L2 MidTermMemoryStore, L3 LongTermMemoryGraph,
and DelegationRequest.role_id.

Note: ShortTermMemoryStore stores ShortTermMemory objects (not raw key/value);
tests use that API.  Role isolation is achieved by scoping the storage
directory via role_id — different role_ids produce different subdirectories.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stm(session_id: str, run_id: str, goal: str = "test"):
    from hi_agent.memory.short_term import ShortTermMemory

    return ShortTermMemory(
        session_id=session_id,
        run_id=run_id,
        task_goal=goal,
    )


# ---------------------------------------------------------------------------
# L1 ShortTermMemoryStore role isolation
# ---------------------------------------------------------------------------


class TestShortTermRoleScoping:
    """L1 ShortTermMemoryStore role isolation tests."""

    def test_save_and_load_with_role_id(self, tmp_path):
        """Basic: store scoped to role_id saves and loads correctly."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        mem = _make_stm("session-1", "run-001", goal="author's draft v1")
        store.save(mem)
        result = store.load("session-1")
        assert result is not None
        assert "author's draft v1" in result.task_goal

    def test_same_role_id_shares_across_instances(self, tmp_path):
        """Two store instances with same role_id share the same namespace."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store1 = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        store2 = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        # Both stores point to the same effective path.
        assert store1._effective_path == store2._effective_path

        # Data written by store1 is readable by store2 (same physical files).
        mem = _make_stm("run-001_session", "run-001", goal="our main argument")
        store1.save(mem)
        result = store2.load("run-001_session")
        assert result is not None
        assert "our main argument" in result.task_goal

    def test_different_role_id_isolated(self, tmp_path):
        """Different role_ids produce different subdirectories — isolation guaranteed."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store_a = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_a")
        store_b = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_b")

        # Different paths means different physical storage.
        assert store_a._effective_path != store_b._effective_path

        mem = _make_stm("session-1", "run-001", goal="reviewer_a secret")
        store_a.save(mem)

        # store_b has a different directory — it cannot see store_a's file.
        result = store_b.load("session-1")
        assert result is None, "Reviewer B must not read Reviewer A's memory"

    def test_no_role_id_backward_compatible(self, tmp_path):
        """Calls without role_id still work (backward compat)."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store = ShortTermMemoryStore(storage_dir=str(tmp_path))
        mem = _make_stm("session-1", "run-001")
        store.save(mem)
        result = store.load("session-1")
        assert result is not None

    def test_empty_role_id_same_as_default(self, tmp_path):
        """role_id='' is the same namespace as role_id not provided."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store_no_role = ShortTermMemoryStore(storage_dir=str(tmp_path))
        store_empty = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="")
        assert store_no_role._effective_path == store_empty._effective_path

    def test_role_id_scoped_dir_does_not_leak(self, tmp_path):
        """Files from role_a namespace are not present in role_b directory."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store_a = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_a")
        mem = _make_stm("session-1", "run-001", goal="secret data")
        store_a.save(mem)

        reviewer_b_dir = tmp_path / "_roles" / "reviewer_b"
        if reviewer_b_dir.exists():
            files = list(reviewer_b_dir.glob("*.json"))
            contents = [f.read_text() for f in files]
            assert not any("secret data" in c for c in contents)

    def test_role_id_storage_path_contains_role_name(self, tmp_path):
        """The effective path for a role store contains the role name."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        store = ShortTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        assert "author" in str(store._effective_path)
        assert "_roles" in str(store._effective_path)


# ---------------------------------------------------------------------------
# L2 MidTermMemoryStore role isolation
# ---------------------------------------------------------------------------


class TestMidTermRoleScoping:
    """L2 MidTermMemoryStore role isolation tests."""

    def test_different_role_l2_isolated(self, tmp_path):
        """L2 stores with different role_ids point to different directories."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        store_a = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_a")
        store_b = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_b")
        assert store_a._effective_path != store_b._effective_path

    def test_same_role_l2_shared(self, tmp_path):
        """L2 with same role_id shares storage."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        store1 = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        store2 = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="author")
        assert store1._effective_path == store2._effective_path

    def test_no_role_id_backward_compatible(self, tmp_path):
        """MidTermMemoryStore without role_id still initialises at storage_dir root."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        store = MidTermMemoryStore(storage_dir=str(tmp_path))
        assert store._effective_path == Path(str(tmp_path))

    def test_role_id_storage_path_contains_role_name(self, tmp_path):
        """Effective path for a role store contains the role name."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        store = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="editor")
        assert "editor" in str(store._effective_path)
        assert "_roles" in str(store._effective_path)

    def test_l2_data_isolation(self, tmp_path):
        """Daily summary written by role_a is not visible to role_b store."""
        from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore

        store_a = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_a")
        store_b = MidTermMemoryStore(storage_dir=str(tmp_path), role_id="reviewer_b")

        summary = DailySummary(date="2026-04-20", key_learnings=["reviewer_a insight"])
        store_a.save(summary)

        result = store_b.load("2026-04-20")
        assert result is None, "reviewer_b must not see reviewer_a's daily summary"


# ---------------------------------------------------------------------------
# L3 LongTermMemoryGraph role isolation
# ---------------------------------------------------------------------------


class TestLongTermRoleScoping:
    """L3 LongTermMemoryGraph role isolation tests."""

    def test_different_role_l3_isolated(self, tmp_path):
        """Graphs with different role_ids point to different files."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        graph_a = LongTermMemoryGraph(base_dir=str(tmp_path), role_id="reviewer_a")
        graph_b = LongTermMemoryGraph(base_dir=str(tmp_path), role_id="reviewer_b")
        assert graph_a._effective_path != graph_b._effective_path

    def test_same_role_l3_shared(self, tmp_path):
        """Graphs with same role_id share the same file path."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        graph1 = LongTermMemoryGraph(base_dir=str(tmp_path), role_id="author")
        graph2 = LongTermMemoryGraph(base_dir=str(tmp_path), role_id="author")
        assert graph1._effective_path == graph2._effective_path

    def test_no_role_id_backward_compatible(self, tmp_path):
        """LongTermMemoryGraph without role_id resolves to root graph.json."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        graph = LongTermMemoryGraph(base_dir=str(tmp_path))
        assert graph._effective_path == Path(str(tmp_path)) / "graph.json"

    def test_role_id_path_contains_role_name(self, tmp_path):
        """Effective path for a role graph contains the role name."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        graph = LongTermMemoryGraph(base_dir=str(tmp_path), role_id="author")
        assert "author" in str(graph._effective_path)
        assert "_roles" in str(graph._effective_path)


# ---------------------------------------------------------------------------
# DelegationRequest.role_id
# ---------------------------------------------------------------------------


class TestDelegationRoleId:
    """DelegationRequest carries role_id."""

    def test_delegation_request_has_role_id(self):
        from hi_agent.task_mgmt.delegation import DelegationRequest

        req = DelegationRequest(
            goal="review the paper",
            task_id="task-001",
            role_id="reviewer_a",
        )
        assert req.role_id == "reviewer_a"

    def test_delegation_request_role_id_defaults_empty(self):
        from hi_agent.task_mgmt.delegation import DelegationRequest

        req = DelegationRequest(goal="test", task_id="task-002")
        assert req.role_id == ""

    def test_delegation_request_different_roles_independent(self):
        """Two requests with different role_ids are independent."""
        from hi_agent.task_mgmt.delegation import DelegationRequest

        req_a = DelegationRequest(goal="review A", task_id="t-a", role_id="reviewer_a")
        req_b = DelegationRequest(goal="review B", task_id="t-b", role_id="reviewer_b")
        assert req_a.role_id != req_b.role_id

    def test_delegation_request_same_role_matches(self):
        """Author v1 and Author v2 share the same role_id."""
        from hi_agent.task_mgmt.delegation import DelegationRequest

        req_v1 = DelegationRequest(goal="write draft", task_id="t-v1", role_id="author")
        req_v2 = DelegationRequest(goal="revise draft", task_id="t-v2", role_id="author")
        assert req_v1.role_id == req_v2.role_id
