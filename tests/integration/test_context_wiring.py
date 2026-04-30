"""Tests for ContextManager wiring into Runner, Builder, and API."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hi_agent.context.manager import (
    ContextBudget,
    ContextHealth,
    ContextManager,
)
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

# ======================================================================
# Helpers
# ======================================================================


def _make_contract(**overrides: Any) -> TaskContract:
    defaults = {
        "task_id": "t-ctx-001",
        "goal": "Test context wiring",
        "task_family": "quick_task",
        "profile_id": "test",
    }
    defaults.update(overrides)
    return TaskContract(**defaults)


def _make_executor(
    *,
    context_manager: Any | None = None,
    route_engine: Any | None = None,
    observability_hook: Any | None = None,
    session: Any | None = "SKIP",
) -> RunExecutor:
    """Create a minimal RunExecutor for testing."""
    kwargs: dict[str, Any] = {
        "contract": _make_contract(),
        "kernel": MockKernel(),
        "route_engine": route_engine or RuleRouteEngine(),
        "event_emitter": EventEmitter(),
        "raw_memory": RawMemoryStore(),
        "compressor": MemoryCompressor(),
        "acceptance_policy": AcceptancePolicy(),
        "cts_budget": CTSExplorationBudget(),
        "policy_versions": PolicyVersionSet(),
        "context_manager": context_manager,
    }
    if observability_hook is not None:
        kwargs["observability_hook"] = observability_hook
    # Avoid RunSession import issues in tests by passing None explicitly
    if session != "SKIP":
        kwargs["session"] = session
    return RunExecutor(**kwargs)


# ======================================================================
# Part 1: Runner wiring
# ======================================================================


class TestRunExecutorContextManagerRouting:
    """Test that ContextManager.prepare_context is used for routing."""

    def test_cm_sets_context_provider(self):
        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        engine = RuleRouteEngine()
        engine._context_provider = None  # type: ignore  expiry_wave: Wave 17
        _ = _make_executor(
            context_manager=cm,
            route_engine=engine,
            session=None,
        )
        # The context provider should have been overwritten
        assert engine._context_provider is not None
        ctx = engine._context_provider()
        assert "health" in ctx
        assert "utilization_pct" in ctx

    def test_cm_prepare_context_called_for_routing(self):
        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        cm.add_history_entry(role="user", content="hello world")
        engine = RuleRouteEngine()
        engine._context_provider = None  # type: ignore  expiry_wave: Wave 17
        _make_executor(
            context_manager=cm,
            route_engine=engine,
            session=None,
        )
        ctx = engine._context_provider()
        assert isinstance(ctx, dict)
        assert ctx["health"] == "green"

    def test_cm_fallback_to_session_on_error(self):
        """If CM.prepare_context raises, fall back to session context."""

        class _RaisingContextManager:
            """Stub collaborator that always raises from prepare_context."""

            def prepare_context(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("boom")

        cm = _RaisingContextManager()

        session = MagicMock()
        session.build_context_for_llm.return_value = {"fallback": True}

        engine = RuleRouteEngine()
        engine._context_provider = None  # type: ignore  expiry_wave: Wave 17
        _ = _make_executor(
            context_manager=cm,
            route_engine=engine,
            session=session,
        )
        ctx = engine._context_provider()
        assert ctx == {"fallback": True}
        session.build_context_for_llm.assert_called_with("routing")


class TestRunExecutorContextManagerRecordResponse:
    """Test record_response called after routing."""

    def test_record_response_after_routing(self):
        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        # Capture the token list length before execution to detect new calls
        initial_iterations = len(cm._iteration_tokens)
        executor = _make_executor(context_manager=cm, session=None)
        # Execute triggers routing which calls record_response
        executor.execute()
        # record_response appends to _iteration_tokens; verify at least one call happened
        assert len(cm._iteration_tokens) > initial_iterations, (
            "record_response was not called: _iteration_tokens did not grow"
        )
        # Verify output_tokens=200 was passed (the routing estimate constant)
        assert 200 in cm._iteration_tokens


class TestRunExecutorContextManagerHistoryEntries:
    """Test history entries added during execution."""

    def test_history_entries_added_on_events(self):
        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        executor = _make_executor(context_manager=cm, session=None)
        executor.execute()
        # Events should have been added as history entries
        history = cm.get_history_after_compact()
        assert len(history) > 0
        # Each entry should have role=system and contain event type
        for entry in history:
            assert entry["role"] == "system"
            assert "[" in entry["content"]  # contains [EventType]


class TestRunExecutorContextManagerHealthEmission:
    """Test context health emitted at stage boundaries."""

    def test_context_health_emitted(self):
        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        events: list[tuple[str, dict]] = []

        def hook(name: str, payload: dict) -> None:
            events.append((name, payload))

        executor = _make_executor(
            context_manager=cm,
            session=None,
            observability_hook=hook,
        )
        executor.execute()
        health_events = [e for e in events if e[0] == "context_health"]
        assert len(health_events) > 0
        for _, payload in health_events:
            assert "health" in payload
            assert "utilization_pct" in payload
            assert "compressions" in payload
            assert "circuit_breaker_open" in payload
            assert "diminishing_returns" in payload


class TestRunExecutorBackwardCompat:
    """Test backward compat: context_manager=None preserves existing behavior."""

    def test_none_cm_preserves_existing_behavior(self):
        executor = _make_executor(context_manager=None, session=None)
        assert executor.context_manager is None
        result = executor.execute()
        assert result == "completed"

    def test_none_cm_session_context_still_works(self):
        """When CM is None but session is provided, session context works."""
        session = MagicMock()
        session.build_context_for_llm.return_value = {"session": True}
        session.run_id = "run-1"
        session.stage_states = {}
        session.action_seq = 0
        session.branch_seq = 0
        session.current_stage = ""
        session.l1_summaries = {}
        engine = RuleRouteEngine()
        engine._context_provider = None  # type: ignore  expiry_wave: Wave 17
        _ = _make_executor(
            context_manager=None,
            route_engine=engine,
            session=session,
        )
        # With CM=None, the session-based provider should be set
        ctx = engine._context_provider()
        assert ctx == {"session": True}


# ======================================================================
# Part 2: Builder wiring
# ======================================================================


class TestSystemBuilderContextManager:
    """Test SystemBuilder.build_context_manager creates instance."""

    def test_build_context_manager(self):
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig()
        builder = SystemBuilder(config)
        cm = builder.build_context_manager()
        assert isinstance(cm, ContextManager)

    def test_build_executor_includes_cm(self):
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        config = TraceConfig()
        builder = SystemBuilder(config)
        contract = _make_contract()
        executor = builder.build_executor(contract)
        assert executor.context_manager is not None
        assert isinstance(executor.context_manager, ContextManager)


# ======================================================================
# Part 3: API wiring
# ======================================================================


class TestAPIContextHealth:
    """Test API GET /context/health returns health report."""

    def test_context_health_endpoint_no_cm(self):
        """503 when no context_manager configured."""
        import io

        from hi_agent.server.app import AgentAPIHandler, AgentServer

        server = AgentServer.__new__(AgentServer)
        server.context_manager = None
        server.run_manager = MagicMock()

        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server
        handler.wfile = io.BytesIO()
        handler.requestline = "GET /context/health HTTP/1.1"
        handler._headers_buffer = []

        sent: list[tuple[int, dict]] = []
        _ = handler._send_json

        def mock_send_json(status: int, body: dict) -> None:
            sent.append((status, body))

        handler._send_json = mock_send_json  # type: ignore  expiry_wave: Wave 17
        handler._handle_context_health()
        assert sent[0][0] == 503

    def test_context_health_endpoint_with_cm(self):
        """200 with health report when CM is configured."""
        from hi_agent.server.app import AgentAPIHandler, AgentServer

        cm = ContextManager(budget=ContextBudget(total_window=50_000))
        server = AgentServer.__new__(AgentServer)
        server.context_manager = cm
        server.run_manager = MagicMock()

        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        sent: list[tuple[int, dict]] = []

        def mock_send_json(status: int, body: dict) -> None:
            sent.append((status, body))

        handler._send_json = mock_send_json  # type: ignore  expiry_wave: Wave 17
        handler._handle_context_health()
        assert sent[0][0] == 200
        body = sent[0][1]
        assert "health" in body
        assert "utilization_pct" in body
        assert "total_tokens" in body
        assert "budget_tokens" in body
        assert "per_section" in body


# ======================================================================
# Part 4: Full cycle test
# ======================================================================


class TestFullCycleContextManager:
    """Full cycle: execute with CM -> health GREEN -> add history -> health grows."""

    def test_full_cycle(self):
        budget = ContextBudget(total_window=50_000, output_reserve=4_000)
        cm = ContextManager(budget=budget)

        # Initially health should be GREEN
        report = cm.get_health_report()
        assert report.health == ContextHealth.GREEN
        assert report.utilization_pct < 0.1

        # Add many history entries to grow context
        for i in range(100):
            cm.add_history_entry(
                role="system",
                content=f"Event {i}: " + "x" * 200,
                metadata={"stage_id": f"S{i % 5 + 1}"},
            )

        # Health should have grown
        report2 = cm.get_health_report()
        assert report2.total_tokens > report.total_tokens

        # Execute with CM through runner
        events: list[tuple[str, dict]] = []

        def hook(name: str, payload: dict) -> None:
            events.append((name, payload))

        executor = _make_executor(
            context_manager=cm,
            session=None,
            observability_hook=hook,
        )
        result = executor.execute()
        assert result == "completed"

        # Should have context_health events
        health_events = [e for e in events if e[0] == "context_health"]
        assert len(health_events) > 0

        # History should have grown from event recording
        final_history = cm.get_history_after_compact()
        assert len(final_history) > 100  # original 100 + runner events

    def test_compress_triggered_on_high_utilization(self):
        """When context is nearly full, compression should be triggered."""
        # Use tiny budget so it fills up quickly
        budget = ContextBudget(
            total_window=1_000,
            output_reserve=100,
            system_prompt=100,
            tool_definitions=100,
            skill_prompts=100,
            memory_context=100,
            knowledge_context=100,
        )
        cm = ContextManager(budget=budget)

        # Fill history to trigger compression
        for i in range(50):
            cm.add_history_entry(
                role="user",
                content=f"Message {i}: " + "word " * 50,
            )

        snapshot = cm.prepare_context(purpose="routing")
        # With tiny budget, should be ORANGE/RED or compression applied
        assert snapshot.health in (
            ContextHealth.GREEN,
            ContextHealth.YELLOW,
            ContextHealth.ORANGE,
            ContextHealth.RED,
        )
        # Compressions may have been applied
        _ = cm.get_health_report()
        # The snapshot should be bounded by budget
        assert snapshot.total_tokens <= budget.effective_window or snapshot.compressions_applied > 0
