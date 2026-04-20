"""Integration test: builder.py must not mutate RunExecutor sub-components after construction (HI-W10-002).

Verifies that the 3 previously-mutated sub-component attributes
(_middleware_orchestrator, skill_evolver, _skill_evolve_interval, tracer)
are wired at construction time via constructor params instead of
post-construction setattr on private attributes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_contract(goal: str = "test") -> MagicMock:
    import uuid

    from hi_agent.contracts import TaskContract
    return TaskContract(task_id=uuid.uuid4().hex, goal=goal)


class TestNoPostConstructionMutation:
    """Verify sub-components receive deps at construction, not via setattr afterward."""

    def test_stage_executor_gets_middleware_orchestrator_at_construction(self):
        """StageExecutor._middleware_orchestrator is set via constructor, not post-mutation."""
        sentinel_mw = MagicMock(name="MiddlewareOrchestrator")

        # Patch _build_middleware_orchestrator to return our sentinel
        from hi_agent.config.builder import SystemBuilder
        builder = SystemBuilder()

        with patch.object(
            builder._get_runtime_builder().__class__,
            "build_middleware_orchestrator",
            return_value=sentinel_mw,
        ):
            # Force the runtime builder's cached value
            builder._get_runtime_builder()._middleware_orchestrator = sentinel_mw

            contract = _make_contract()
            executor = builder.build_executor(contract)

            # The StageExecutor should have the middleware orchestrator set
            stage_exec = executor._stage_executor
            assert stage_exec._middleware_orchestrator is sentinel_mw, (
                "Expected middleware_orchestrator to be set via constructor, "
                "not post-construction mutation"
            )

    def test_run_lifecycle_gets_skill_evolver_at_construction(self):
        """RunLifecycle.skill_evolver is set via constructor, not post-mutation."""
        sentinel_evolver = MagicMock(name="SkillEvolver")

        from hi_agent.config.builder import SystemBuilder
        builder = SystemBuilder()

        with patch.object(builder, "build_skill_evolver", return_value=sentinel_evolver):
            contract = _make_contract()
            executor = builder.build_executor(contract)

            lifecycle = executor._lifecycle
            assert lifecycle.skill_evolver is sentinel_evolver, (
                "Expected skill_evolver to be set via constructor, "
                "not post-construction mutation"
            )

    def test_run_lifecycle_skill_evolve_interval_at_construction(self):
        """RunLifecycle._skill_evolve_interval is set via constructor."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig
        cfg = TraceConfig()
        cfg.skill_evolve_interval = 7  # custom interval

        builder = SystemBuilder(config=cfg)
        contract = _make_contract()
        executor = builder.build_executor(contract)

        lifecycle = executor._lifecycle
        assert lifecycle._skill_evolve_interval == 7, (
            "Expected skill_evolve_interval to be set via constructor, "
            "not post-construction mutation"
        )

    def test_run_telemetry_gets_tracer_at_construction(self, tmp_path):
        """RunTelemetry.tracer is set via constructor when trace_export_dir is configured."""
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        export_dir = str(tmp_path / "traces")
        cfg = TraceConfig()
        cfg.trace_export_dir = export_dir

        builder = SystemBuilder(config=cfg)
        contract = _make_contract()
        executor = builder.build_executor(contract)

        telemetry = executor._telemetry
        assert telemetry.tracer is not None, (
            "Expected tracer to be set via constructor when trace_export_dir is configured, "
            "not post-construction mutation"
        )

    def test_executor_has_no_direct_private_mutation_in_builder(self):
        """Build executor and confirm the 3 private setattr lines are gone from builder.py.

        This test reads builder source to verify no post-construction private-attribute
        mutations remain for the 3 known injection targets.
        """
        import pathlib
        builder_path = pathlib.Path(__file__).parent.parent.parent / "hi_agent" / "config" / "builder.py"
        source = builder_path.read_text(encoding="utf-8")

        # None of the 3 post-construction mutation patterns should appear
        assert "executor._stage_executor._middleware_orchestrator" not in source, (
            "Post-construction mutation of _stage_executor._middleware_orchestrator "
            "still present in builder.py"
        )
        assert "executor._lifecycle.skill_evolver" not in source, (
            "Post-construction mutation of _lifecycle.skill_evolver "
            "still present in builder.py"
        )
        assert "executor._telemetry.tracer" not in source, (
            "Post-construction mutation of _telemetry.tracer "
            "still present in builder.py"
        )

    def test_cognition_builder_provides_llm_gateway(self):
        """CognitionBuilder.build_llm_gateway() returns a gateway or None.

        Returns a TierAwareLLMGateway when llm_config.json has a configured
        default_provider with an api_key; returns None only when neither the
        config file nor environment variables supply credentials.
        """
        import threading

        from hi_agent.config.cognition_builder import CognitionBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.llm.tier_router import TierAwareLLMGateway

        cfg = TraceConfig()
        lock = threading.RLock()
        cb = CognitionBuilder(cfg, lock)
        gw = cb.build_llm_gateway()
        # Gateway is either a TierAwareLLMGateway (config/llm_config.json present
        # with valid api_key) or None (no credentials available in this env).
        assert gw is None or isinstance(gw, TierAwareLLMGateway)

    def test_runtime_builder_provides_kernel(self):
        """RuntimeBuilder.build_kernel() returns a RuntimeAdapter."""
        import threading

        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.runtime_builder import RuntimeBuilder
        from hi_agent.config.trace_config import TraceConfig

        cfg = TraceConfig()
        lock = threading.RLock()
        parent = SystemBuilder(config=cfg)
        rb = RuntimeBuilder(cfg, lock, parent=parent)
        kernel = rb.build_kernel()
        assert kernel is not None

    def test_runtime_builder_provides_metrics_collector(self):
        """RuntimeBuilder.build_metrics_collector() returns a MetricsCollector."""
        import threading

        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.runtime_builder import RuntimeBuilder
        from hi_agent.config.trace_config import TraceConfig

        cfg = TraceConfig()
        lock = threading.RLock()
        parent = SystemBuilder(config=cfg)
        rb = RuntimeBuilder(cfg, lock, parent=parent)
        mc = rb.build_metrics_collector()
        assert mc is not None
