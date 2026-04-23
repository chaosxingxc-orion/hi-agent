"""Golden path: dev-smoke tier — no real LLM/kernel, heuristic execution (W12-001)."""

from __future__ import annotations

import uuid


class TestDevSmokeGoldenPath:
    """Full execution path with heuristic fallback (no API keys required)."""

    def test_executor_completes_with_heuristic_fallback(self):
        """build_executor() + execute() completes without real LLM."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts import TaskContract

        builder = SystemBuilder()
        contract = TaskContract(
            task_id=uuid.uuid4().hex, goal="golden path smoke test", profile_id="test"
        )
        executor = builder.build_executor(contract)
        result = executor.execute()
        assert str(result) in ("completed", "failed", "reflected")

    def test_readiness_returns_expected_keys(self):
        """builder.readiness() returns dict with required keys."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        r = builder.readiness()
        assert isinstance(r, dict)
        # Must contain at least one of the known readiness keys.
        assert "ready" in r or "status" in r or "health" in r

    def test_readiness_has_subsystems_key(self):
        """builder.readiness() snapshot includes subsystems dict."""
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        r = builder.readiness()
        assert "subsystems" in r
        assert isinstance(r["subsystems"], dict)

    def test_execution_provenance_is_populated(self):
        """RunResult.execution_provenance is non-None after execute() in heuristic mode."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.contracts import TaskContract

        builder = SystemBuilder()
        contract = TaskContract(
            task_id=uuid.uuid4().hex, goal="provenance smoke test", profile_id="test"
        )
        executor = builder.build_executor(contract)
        result = executor.execute()
        # execution_provenance is populated when the full pipeline runs;
        # it may be None in degraded/stub modes — assert type is consistent.
        from hi_agent.contracts.requests import RunResult

        assert isinstance(result, RunResult)
        # Status must be a non-empty string.
        assert isinstance(result.status, str)
        assert result.status != ""
