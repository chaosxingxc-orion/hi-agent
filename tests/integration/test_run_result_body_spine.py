"""Integration tests: RunResult.to_dict() spine field inclusion.

Layer 2 — Integration tests verifying that RunResult.to_dict() correctly
includes optional spine fields when non-empty (Wave 10.4 W4-E body enrichment).

These tests wire the real RunResult dataclass without mocking it, and
assert observable outputs on the dict representation per Rule 4.
"""

from __future__ import annotations

from hi_agent.contracts.requests import RunResult


class TestRunResultToDictSpine:
    def test_spine_fields_included_when_non_empty(self):
        """Non-empty tenant/user/session/project_id appear in to_dict() output."""
        result = RunResult(
            run_id="run-001",
            status="completed",
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            project_id="p1",
        )
        d = result.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["user_id"] == "u1"
        assert d["session_id"] == "s1"
        assert d["project_id"] == "p1"

    def test_spine_fields_omitted_when_empty(self):
        """Empty spine fields are NOT included in to_dict() (backwards-compatible)."""
        result = RunResult(
            run_id="run-002",
            status="completed",
        )
        d = result.to_dict()
        assert "tenant_id" not in d
        assert "user_id" not in d
        assert "session_id" not in d
        assert "project_id" not in d

    def test_existing_non_spine_fields_always_present(self):
        """Core fields like run_id, status, stages are always included."""
        result = RunResult(
            run_id="run-003",
            status="failed",
            error="something went wrong",
        )
        d = result.to_dict()
        assert "run_id" in d
        assert "status" in d
        assert "stages" in d
        assert "artifacts" in d
        assert "error" in d
        assert "duration_ms" in d
        assert "fallback_events" in d
        assert "llm_fallback_count" in d
        assert "finished_at" in d

    def test_partial_spine_fields_included_selectively(self):
        """Only non-empty spine fields are added; empty ones are omitted."""
        result = RunResult(
            run_id="run-004",
            status="completed",
            tenant_id="t2",
            user_id="",     # empty — should be omitted
            session_id="s2",
            project_id="",  # empty — should be omitted
        )
        d = result.to_dict()
        assert d["tenant_id"] == "t2"
        assert "user_id" not in d
        assert d["session_id"] == "s2"
        assert "project_id" not in d

    def test_backward_compat_no_spine_fields_set(self):
        """RunResult constructed without spine fields behaves exactly as before."""
        result = RunResult(run_id="run-005", status="completed")
        d = result.to_dict()
        # Verify the exact set of always-present keys
        expected_keys = {
            "run_id", "status", "stages", "artifacts", "error",
            "duration_ms", "failure_code", "failed_stage_id", "is_retryable",
            "execution_provenance", "fallback_events", "llm_fallback_count",
            "finished_at",
        }
        assert expected_keys.issubset(d.keys())
        # No spine keys
        for key in ("tenant_id", "user_id", "session_id", "project_id"):
            assert key not in d, f"Unexpected key {key!r} in backwards-compat dict"

    def test_str_comparison_backward_compat(self):
        """RunResult with spine fields still compares equal to status string."""
        result = RunResult(
            run_id="run-006",
            status="completed",
            tenant_id="t3",
        )
        assert result == "completed"
        assert str(result) == "completed"
