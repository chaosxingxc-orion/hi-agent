"""Integration tests for RunExecutorFacade and check_readiness().

All tests use real components — no internal mocks (CLAUDE.md P3).
Tests that drive a full kernel run are marked ``@pytest.mark.integration``
and may be skipped in CI environments where agent-kernel is absent.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Smoke tests — no kernel required
# ---------------------------------------------------------------------------


class TestRunFacadeResult:
    """Unit-level: verify RunFacadeResult dataclass contract."""

    def test_success_fields(self) -> None:
        """RunFacadeResult with success=True has no error."""
        from hi_agent import RunFacadeResult

        r = RunFacadeResult(success=True, output="completed", run_id="r-001")
        assert r.success is True
        assert r.output == "completed"
        assert r.run_id == "r-001"
        assert r.error is None

    def test_failure_fields(self) -> None:
        """RunFacadeResult with success=False carries the error string."""
        from hi_agent import RunFacadeResult

        r = RunFacadeResult(
            success=False,
            output="failed",
            run_id="r-002",
            error="model_refusal",
        )
        assert r.success is False
        assert r.error == "model_refusal"


class TestReadinessReport:
    """Unit-level: verify ReadinessReport dataclass contract."""

    def test_fields_present(self) -> None:
        """ReadinessReport exposes ready, health, and subsystems fields."""
        from hi_agent import ReadinessReport

        rpt = ReadinessReport(
            ready=True,
            health="ok",
            subsystems={"kernel": {"status": "ok"}},
        )
        assert isinstance(rpt.ready, bool)
        assert isinstance(rpt.health, str)
        assert isinstance(rpt.subsystems, dict)

    def test_default_subsystems_is_empty_dict(self) -> None:
        """ReadinessReport.subsystems defaults to an empty dict."""
        from hi_agent import ReadinessReport

        rpt = ReadinessReport(ready=False, health="degraded")
        assert rpt.subsystems == {}


class TestRunExecutorFacadeInstantiation:
    """Verify facade can be imported and instantiated without a running kernel."""

    def test_import_from_package(self) -> None:
        """RunExecutorFacade is importable from the top-level package."""
        from hi_agent import RunExecutorFacade

        facade = RunExecutorFacade()
        assert facade is not None

    def test_run_before_start_raises(self) -> None:
        """Calling run() before start() raises RuntimeError."""
        from hi_agent import RunExecutorFacade

        facade = RunExecutorFacade()
        with pytest.raises(RuntimeError, match="start\\(\\)"):
            facade.run("hello")

    def test_stop_before_start_is_safe(self) -> None:
        """stop() is a no-op when start() was never called."""
        from hi_agent import RunExecutorFacade

        facade = RunExecutorFacade()
        # Must not raise even though start() was never called.
        facade.stop()


class TestCheckReadiness:
    """Verify check_readiness() returns a well-formed ReadinessReport."""

    def test_returns_readiness_report(self) -> None:
        """check_readiness() returns a ReadinessReport instance."""
        from hi_agent import ReadinessReport, check_readiness

        report = check_readiness()
        assert isinstance(report, ReadinessReport)

    def test_ready_is_bool(self) -> None:
        """ReadinessReport.ready is a boolean."""
        from hi_agent import check_readiness

        report = check_readiness()
        assert isinstance(report.ready, bool)

    def test_health_is_string(self) -> None:
        """ReadinessReport.health is a string."""
        from hi_agent import check_readiness

        report = check_readiness()
        assert isinstance(report.health, str)

    def test_subsystems_is_dict(self) -> None:
        """ReadinessReport.subsystems is a dict."""
        from hi_agent import check_readiness

        report = check_readiness()
        assert isinstance(report.subsystems, dict)

    def test_health_values_are_known(self) -> None:
        """ReadinessReport.health is one of the two known values."""
        from hi_agent import check_readiness

        report = check_readiness()
        assert report.health in ("ok", "degraded"), f"Unexpected health value: {report.health!r}"


# ---------------------------------------------------------------------------
# Full-runtime integration tests — require agent-kernel to be reachable
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunExecutorFacadeFullRun:
    """End-to-end tests that drive executor.execute() through the facade.

    These tests require a reachable agent-kernel instance (local or remote).
    They are skipped automatically when no kernel URL is configured.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_kernel(self):
        import os
        if not os.environ.get("HI_AGENT_KERNEL_BASE_URL"):
            pytest.skip(  # expiry_wave: permanent (W31-D D-2': condition-bounded skip)
                reason="requires agent-kernel URL (HI_AGENT_KERNEL_BASE_URL); "
                "facade.stop() calls sync_bridge which blocks without a running kernel"
            )

    def test_start_and_stop(self, tmp_path) -> None:
        """start() must build an executor; stop() must not raise."""
        from hi_agent import RunExecutorFacade

        facade = RunExecutorFacade()
        facade.start(
            run_id="facade-test-start",
            profile_id="default",
            model_tier="light",
            skill_dir=str(tmp_path),
        )
        assert facade._executor is not None
        facade.stop()
        assert facade._executor is None

    def test_run_returns_facade_result(self, tmp_path) -> None:
        """run() must return a RunFacadeResult with populated run_id."""
        from hi_agent import RunExecutorFacade, RunFacadeResult

        facade = RunExecutorFacade()
        facade.start(
            run_id="facade-test-run",
            profile_id="default",
            model_tier="light",
            skill_dir=str(tmp_path),
        )
        result = facade.run("Echo: integration test")
        facade.stop()

        assert isinstance(result, RunFacadeResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.output, str)
        assert result.run_id != ""
