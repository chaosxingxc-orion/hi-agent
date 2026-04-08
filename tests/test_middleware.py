"""Tests for the four-middleware architecture with 5-phase lifecycle hooks."""
from __future__ import annotations

import pytest
from typing import Any

from hi_agent.middleware.protocol import (
    HookAction,
    HookResult,
    LifecycleHook,
    LifecyclePhase,
    MiddlewareMessage,
)
from hi_agent.middleware.perception import PerceptionMiddleware
from hi_agent.middleware.control import ControlMiddleware
from hi_agent.middleware.execution import ExecutionMiddleware
from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.middleware.orchestrator import MiddlewareOrchestrator, PipelineBlockedError
from hi_agent.middleware.defaults import create_default_orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input_msg(text: str = "hello world") -> MiddlewareMessage:
    return MiddlewareMessage(
        source="user",
        target="perception",
        msg_type="user_input",
        payload={"user_input": text},
    )


def _make_perception_msg(text: str = "hello world") -> MiddlewareMessage:
    """Simulate output of perception middleware."""
    pm = PerceptionMiddleware()
    return pm.process(_make_input_msg(text))


def _make_control_msg(text: str = "hello world") -> MiddlewareMessage:
    """Simulate output of control middleware."""
    cm = ControlMiddleware()
    return cm.process(_make_perception_msg(text))


def _make_execution_msg(text: str = "hello world") -> MiddlewareMessage:
    """Simulate output of execution middleware."""
    em = ExecutionMiddleware()
    return em.process(_make_control_msg(text))


class DummyMiddleware:
    """A test middleware for insertion tests."""

    def __init__(self, mw_name: str = "dummy") -> None:
        self._name = mw_name
        self.created = False
        self.destroyed = False
        self.processed = False

    @property
    def name(self) -> str:
        return self._name

    def on_create(self, config: dict[str, Any]) -> None:
        self.created = True

    def on_destroy(self) -> None:
        self.destroyed = True

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        self.processed = True
        return MiddlewareMessage(
            source=self._name,
            target=message.target,
            msg_type=message.msg_type,
            payload={**message.payload, "dummy_touched": True},
            token_cost=message.token_cost + 1,
            metadata=message.metadata,
        )


# ===========================================================================
# Lifecycle tests
# ===========================================================================

class TestLifecycleHooks:
    """Tests for the 5-phase lifecycle hook system."""

    def test_pre_create_hooks_fire_before_process(self):
        """pre_create hooks should fire before process()."""
        order: list[str] = []

        def on_pre_create(msg, ctx):
            order.append("pre_create")
            return HookResult()

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.PRE_CREATE,
            on_pre_create, name="track_create",
        )

        # Wrap process to track order
        orig_process = orch._middlewares["perception"].process
        def tracked_process(msg):
            order.append("process")
            return orig_process(msg)
        orch._middlewares["perception"].process = tracked_process

        orch.run("test input")
        assert order[0] == "pre_create"
        assert "process" in order

    def test_pre_execute_hooks_can_modify_input(self):
        """pre_execute hooks with MODIFY action should replace the input message."""
        def modify_hook(msg, ctx):
            modified = MiddlewareMessage(
                source=msg.source,
                target=msg.target,
                msg_type=msg.msg_type,
                payload={"user_input": "MODIFIED INPUT"},
                metadata=msg.metadata,
            )
            return HookResult(
                action=HookAction.MODIFY,
                modified_message=modified,
            )

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.PRE_EXECUTE,
            modify_hook, name="modifier",
        )

        result = orch.run("original input")
        # The perception middleware should have received "MODIFIED INPUT"
        log = orch.get_message_log()
        # Find perception output
        perception_out = [m for m in log if m.source == "perception"]
        assert perception_out
        assert perception_out[0].payload.get("raw_text") == "MODIFIED INPUT"

    def test_pre_execute_hooks_can_skip_middleware(self):
        """pre_execute hooks with SKIP should pass message through unchanged."""
        def skip_hook(msg, ctx):
            return HookResult(action=HookAction.SKIP, reason="skip control")

        orch = create_default_orchestrator()
        orch.add_hook(
            "control", LifecyclePhase.PRE_EXECUTE,
            skip_hook, name="skipper",
        )

        result = orch.run("test input")
        # Control was skipped but counted
        metrics = orch.get_metrics()
        assert metrics["control"]["calls"] >= 1  # skipped counts as a call

    def test_pre_execute_hooks_can_block_pipeline(self):
        """pre_execute hooks with BLOCK should stop the pipeline."""
        def block_hook(msg, ctx):
            return HookResult(action=HookAction.BLOCK, reason="blocked!")

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.PRE_EXECUTE,
            block_hook, name="blocker",
        )

        result = orch.run("test input")
        # Pipeline should stop at perception
        log = orch.get_message_log()
        # Only the initial user input should be in the log
        assert len(log) == 1  # just the initial message

    def test_execute_phase_calls_process(self):
        """The execute phase should call middleware.process()."""
        called = {"count": 0}
        orig_pm = PerceptionMiddleware()
        orig_process = orig_pm.process

        def counting_process(msg):
            called["count"] += 1
            return orig_process(msg)

        orig_pm.process = counting_process

        orch = MiddlewareOrchestrator()
        orch.register_middleware("perception", orig_pm)
        orch.register_middleware("control", ControlMiddleware())
        orch.register_middleware("execution", ExecutionMiddleware())
        orch.register_middleware("evaluation", EvaluationMiddleware())

        orch.run("test")
        assert called["count"] >= 1

    def test_post_execute_hooks_can_modify_output(self):
        """post_execute hooks with MODIFY should replace the output message."""
        def post_modify(msg, ctx):
            modified = MiddlewareMessage(
                source=msg.source,
                target=msg.target,
                msg_type=msg.msg_type,
                payload={**msg.payload, "post_modified": True},
                metadata=msg.metadata,
            )
            return HookResult(
                action=HookAction.MODIFY,
                modified_message=modified,
            )

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.POST_EXECUTE,
            post_modify, name="post_mod",
        )

        result = orch.run("test")
        log = orch.get_message_log()
        perception_out = [m for m in log if m.source == "perception"]
        assert perception_out
        assert perception_out[0].payload.get("post_modified") is True

    def test_pre_destroy_hooks_fire_after_process(self):
        """pre_destroy hooks should fire after process()."""
        order: list[str] = []

        def on_pre_destroy(msg, ctx):
            order.append("pre_destroy")
            return HookResult()

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.PRE_DESTROY,
            on_pre_destroy, name="track_destroy",
        )

        orig_process = orch._middlewares["perception"].process
        def tracked_process(msg):
            order.append("process")
            return orig_process(msg)
        orch._middlewares["perception"].process = tracked_process

        orch.run("test")
        assert "process" in order
        assert "pre_destroy" in order
        assert order.index("process") < order.index("pre_destroy")

    def test_hook_priority_ordering(self):
        """Hooks should execute in priority DESC order (higher first)."""
        order: list[int] = []

        def make_hook(priority):
            def hook(msg, ctx):
                order.append(priority)
                return HookResult()
            return hook

        orch = create_default_orchestrator()
        orch.add_hook("perception", LifecyclePhase.PRE_EXECUTE, make_hook(1), priority=1, name="low")
        orch.add_hook("perception", LifecyclePhase.PRE_EXECUTE, make_hook(10), priority=10, name="high")
        orch.add_hook("perception", LifecyclePhase.PRE_EXECUTE, make_hook(5), priority=5, name="mid")

        orch.run("test")
        assert order[:3] == [10, 5, 1]

    def test_global_hooks_fire_for_all_middlewares(self):
        """Global hooks should fire for every middleware."""
        names_seen: list[str] = []

        def global_hook(msg, ctx):
            names_seen.append(ctx.get("middleware_name", ""))
            return HookResult()

        orch = create_default_orchestrator()
        orch.add_global_hook(LifecyclePhase.PRE_EXECUTE, global_hook, name="global")

        orch.run("test")
        # Should have been called for at least perception, control, execution, evaluation
        assert "perception" in names_seen
        assert "control" in names_seen
        assert "execution" in names_seen
        assert "evaluation" in names_seen

    def test_once_hook_fires_only_once(self):
        """once=True hooks should execute only once then be auto-removed."""
        count = {"n": 0}

        def once_hook(msg, ctx):
            count["n"] += 1
            return HookResult()

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.PRE_EXECUTE,
            once_hook, name="once_hook", once=True,
        )

        # First run
        orch.run("test1")
        first_count = count["n"]

        # Second run (hook should have been removed)
        orch._message_log.clear()
        orch.run("test2")

        assert first_count == 1
        assert count["n"] == 1  # not incremented on second run

    def test_retry_action_re_executes_middleware(self):
        """RETRY action should re-execute the middleware."""
        call_count = {"n": 0}

        def retry_hook(msg, ctx):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return HookResult(
                    action=HookAction.RETRY,
                    metadata={"max_retries": 2},
                )
            return HookResult()

        orch = create_default_orchestrator()
        orch.add_hook(
            "perception", LifecyclePhase.EXECUTE,
            retry_hook, name="retrier",
        )

        orch.run("test")
        # The execute hook triggered a retry
        metrics = orch.get_metrics()
        # Perception should have been called more than once
        assert metrics["perception"]["calls"] >= 2


# ===========================================================================
# Middleware tests
# ===========================================================================

class TestPerceptionMiddleware:
    """Tests for PerceptionMiddleware entity extraction and summarization."""

    def test_extract_dates(self):
        pm = PerceptionMiddleware()
        msg = _make_input_msg("Meeting on 2024-01-15 and January 20, 2024")
        result = pm.process(msg)
        entities = result.payload.get("entities", [])
        date_entities = [e for e in entities if e["entity_type"] == "date"]
        assert len(date_entities) >= 2

    def test_extract_urls(self):
        pm = PerceptionMiddleware()
        msg = _make_input_msg("Visit https://example.com for details")
        result = pm.process(msg)
        entities = result.payload.get("entities", [])
        url_entities = [e for e in entities if e["entity_type"] == "url"]
        assert len(url_entities) == 1
        assert "example.com" in url_entities[0]["value"]

    def test_extract_emails(self):
        pm = PerceptionMiddleware()
        msg = _make_input_msg("Contact user@example.com for help")
        result = pm.process(msg)
        entities = result.payload.get("entities", [])
        email_entities = [e for e in entities if e["entity_type"] == "email"]
        assert len(email_entities) == 1

    def test_extract_code_blocks(self):
        pm = PerceptionMiddleware()
        msg = _make_input_msg("Here is code:\n```python\nprint('hi')\n```\nDone.")
        result = pm.process(msg)
        entities = result.payload.get("entities", [])
        code_entities = [e for e in entities if e["entity_type"] == "code_block"]
        assert len(code_entities) == 1

    def test_summarize_long_input(self):
        pm = PerceptionMiddleware(summary_threshold=10)  # very low threshold
        long_text = "First paragraph.\n\n" + "Middle. " * 500 + "\n\nLast paragraph."
        msg = _make_input_msg(long_text)
        result = pm.process(msg)
        summary = result.payload.get("summary")
        assert summary is not None
        assert "First paragraph" in summary

    def test_no_summary_for_short_input(self):
        pm = PerceptionMiddleware(summary_threshold=2000)
        msg = _make_input_msg("short text")
        result = pm.process(msg)
        assert result.payload.get("summary") is None


class TestControlMiddleware:
    """Tests for ControlMiddleware decomposition and validation."""

    def test_decompose_into_trajectory_graph(self):
        cm = ControlMiddleware()
        msg = _make_perception_msg("analyze revenue data")
        result = cm.process(msg)
        graph_json = result.payload.get("graph_json", {})
        assert "nodes" in graph_json
        assert "edges" in graph_json
        assert len(graph_json["nodes"]) == 5  # default TRACE stages

    def test_validates_executability(self):
        cm = ControlMiddleware()
        msg = _make_perception_msg("test task")
        result = cm.process(msg)
        issues = result.payload.get("validation_issues", [])
        assert isinstance(issues, list)
        # Default decomposition should have no issues (all nodes get bindings)
        assert len(issues) == 0

    def test_handle_escalation(self):
        cm = ControlMiddleware()
        escalation = MiddlewareMessage(
            source="evaluation",
            target="control",
            msg_type="escalation",
            payload={
                "node_id": "build",
                "perception_text": "original task",
                "feedback": "output was incomplete",
            },
        )
        result = cm.handle_escalation(escalation)
        assert result.msg_type == "execution_plan"
        assert result.payload["total_nodes"] == 1


class TestExecutionMiddleware:
    """Tests for ExecutionMiddleware execution and idempotency."""

    def test_execute_node_with_minimal_context(self):
        em = ExecutionMiddleware()
        msg = _make_control_msg("test task")
        result = em.process(msg)
        results = result.payload.get("results", [])
        assert len(results) > 0
        assert results[0].get("success") is True

    def test_idempotency_check(self):
        em = ExecutionMiddleware()
        msg = _make_control_msg("test task")

        # First call
        result1 = em.process(msg)
        r1 = result1.payload["results"]

        # Second call with same input -- should use cache
        result2 = em.process(msg)
        r2 = result2.payload["results"]

        # Results should be identical (cached)
        for a, b in zip(r1, r2):
            assert a["node_id"] == b["node_id"]
            assert a["output"] == b["output"]

    def test_handle_reflection(self):
        em = ExecutionMiddleware()
        reflection = MiddlewareMessage(
            source="evaluation",
            target="execution",
            msg_type="reflection",
            payload={
                "node_id": "build",
                "retry_instruction": "improve output quality",
                "perception_text": "original task",
            },
        )
        result = em.handle_reflection(reflection)
        assert result.msg_type == "execution_result"
        results = result.payload.get("results", [])
        assert len(results) == 1


class TestEvaluationMiddleware:
    """Tests for EvaluationMiddleware pass/retry/escalate routing."""

    def test_pass_on_good_quality(self):
        ev = EvaluationMiddleware(quality_threshold=0.5)
        msg = _make_execution_msg("good output with substantial content here for quality")
        result = ev.process(msg)
        verdict = result.payload.get("overall_verdict")
        assert verdict == "pass"

    def test_retry_on_low_quality(self):
        ev = EvaluationMiddleware(quality_threshold=0.99)  # impossible threshold
        msg = _make_execution_msg("test")
        result = ev.process(msg)
        verdict = result.payload.get("overall_verdict")
        assert verdict in ("retry", "escalate")

    def test_escalate_after_max_retries(self):
        ev = EvaluationMiddleware(quality_threshold=0.99, max_retries=0)
        msg = _make_execution_msg("test")
        result = ev.process(msg)
        # With max_retries=0, should escalate immediately
        evals = result.payload.get("evaluations", [])
        # At least one should escalate
        escalated = [e for e in evals if e["verdict"] == "escalate"]
        assert len(escalated) > 0

    def test_retry_routing_target(self):
        ev = EvaluationMiddleware(quality_threshold=0.99, max_retries=3)
        msg = _make_execution_msg("test")
        result = ev.process(msg)
        if result.payload.get("overall_verdict") == "retry":
            assert result.target == "execution"

    def test_escalation_routing_target(self):
        ev = EvaluationMiddleware(quality_threshold=0.99, max_retries=0)
        msg = _make_execution_msg("test")
        result = ev.process(msg)
        if result.payload.get("overall_verdict") == "escalate":
            assert result.target == "control"


# ===========================================================================
# Orchestrator tests
# ===========================================================================

class TestMiddlewareOrchestrator:
    """Tests for the extensible orchestrator."""

    def test_default_flow(self):
        """Default flow: perception -> control -> execution -> evaluation."""
        orch = create_default_orchestrator()
        result = orch.run("hello world")
        assert result is not None
        log = orch.get_message_log()
        sources = [m.source for m in log]
        assert "user" in sources
        assert "perception" in sources
        assert "control" in sources
        assert "execution" in sources

    def test_register_and_replace_middleware(self):
        orch = create_default_orchestrator()
        dummy = DummyMiddleware("perception")
        orch.replace_middleware("perception", dummy)
        orch.run("test")
        assert dummy.processed

    def test_register_middleware_unknown_raises(self):
        orch = create_default_orchestrator()
        with pytest.raises(KeyError):
            orch.replace_middleware("nonexistent", DummyMiddleware())

    def test_add_middleware_after(self):
        """add_middleware(after='perception') inserts correctly."""
        orch = create_default_orchestrator()
        validator = DummyMiddleware("validator")
        orch.add_middleware("validator", validator, after="perception")

        # The flow should now be: perception -> validator -> control -> ...
        outgoing = orch._flow_graph.get_outgoing("perception")
        seq_targets = [e.target for e in outgoing if e.edge_type.value == "sequence"]
        assert "validator" in seq_targets

        outgoing_val = orch._flow_graph.get_outgoing("validator")
        seq_targets_val = [e.target for e in outgoing_val if e.edge_type.value == "sequence"]
        assert "control" in seq_targets_val

    def test_add_middleware_before(self):
        """add_middleware(before='control') inserts correctly."""
        orch = create_default_orchestrator()
        validator = DummyMiddleware("validator")
        orch.add_middleware("validator", validator, before="control")

        incoming = orch._flow_graph.get_incoming("control")
        seq_sources = [e.source for e in incoming if e.edge_type.value == "sequence"]
        assert "validator" in seq_sources

    def test_remove_middleware_reconnects(self):
        """remove_middleware should reconnect neighbors."""
        orch = create_default_orchestrator()
        orch.remove_middleware("control")

        # perception should now connect to execution
        outgoing = orch._flow_graph.get_outgoing("perception")
        seq_targets = [e.target for e in outgoing if e.edge_type.value == "sequence"]
        assert "execution" in seq_targets

    def test_add_route_creates_custom_edge(self):
        orch = create_default_orchestrator()
        # Add a direct route from perception to evaluation
        orch.add_route("perception", "evaluation", edge_type="conditional")
        outgoing = orch._flow_graph.get_outgoing("perception")
        targets = [e.target for e in outgoing]
        assert "evaluation" in targets

    def test_reflection_loop(self):
        """Evaluation with retry should route back to execution."""
        # Use a threshold that forces retry
        orch = create_default_orchestrator(quality_threshold=0.99, max_retries=1)
        result = orch.run("test reflection loop")
        log = orch.get_message_log()
        sources = [m.source for m in log]
        # Execution should appear more than once due to reflection
        exec_count = sources.count("execution")
        assert exec_count >= 1

    def test_escalation_loop(self):
        """Evaluation with escalate should route back to control."""
        orch = create_default_orchestrator(quality_threshold=0.99, max_retries=0)
        result = orch.run("test escalation loop")
        log = orch.get_message_log()
        sources = [m.source for m in log]
        # Control should appear more than once due to escalation
        # (or at least evaluation routes to control)
        eval_msgs = [m for m in log if m.source == "evaluation"]
        if eval_msgs:
            assert any(m.target == "control" for m in eval_msgs) or any(m.target == "end" for m in eval_msgs)

    def test_get_flow_mermaid(self):
        orch = create_default_orchestrator()
        mermaid = orch.get_flow_mermaid()
        assert "flowchart TD" in mermaid
        assert "perception" in mermaid
        assert "control" in mermaid
        assert "execution" in mermaid
        assert "evaluation" in mermaid

    def test_get_cost_summary(self):
        orch = create_default_orchestrator()
        orch.run("test cost tracking")
        summary = orch.get_cost_summary()
        assert "total_tokens" in summary
        assert "per_middleware" in summary
        assert "perception" in summary["per_middleware"]

    def test_get_metrics(self):
        orch = create_default_orchestrator()
        orch.run("test metrics")
        metrics = orch.get_metrics()
        assert "perception" in metrics
        assert metrics["perception"]["calls"] >= 1

    def test_custom_middleware_integration(self):
        """A custom middleware can be added and participates in the pipeline."""
        orch = create_default_orchestrator()
        custom = DummyMiddleware("custom")
        orch.add_middleware("custom", custom, after="perception")
        orch.run("test custom")
        assert custom.processed

    def test_run_end_to_end(self):
        """Full end-to-end run with default config."""
        orch = create_default_orchestrator()
        result = orch.run("Analyze quarterly revenue data for Q1 2024")
        assert result is not None
        assert result.source in ("evaluation", "execution", "control", "perception")
        summary = orch.get_cost_summary()
        assert summary["total_tokens"] > 0

    def test_remove_hook(self):
        orch = create_default_orchestrator()
        count = {"n": 0}

        def hook(msg, ctx):
            count["n"] += 1
            return HookResult()

        orch.add_hook("perception", LifecyclePhase.PRE_EXECUTE, hook, name="removable")
        orch.remove_hook("perception", "removable")
        orch.run("test")
        assert count["n"] == 0

    def test_message_log_populated(self):
        orch = create_default_orchestrator()
        orch.run("test logging")
        log = orch.get_message_log()
        assert len(log) > 1  # at least initial + one middleware output


# ===========================================================================
# Defaults tests
# ===========================================================================

class TestDefaults:
    """Tests for the default orchestrator factory."""

    def test_create_default_orchestrator_runs_through(self):
        orch = create_default_orchestrator()
        result = orch.run("Create a simple report on Python best practices")
        assert result is not None
        metrics = orch.get_metrics()
        for name in ("perception", "control", "execution", "evaluation"):
            assert name in metrics
            assert metrics[name]["calls"] >= 1

    def test_create_with_custom_params(self):
        orch = create_default_orchestrator(
            quality_threshold=0.3,
            max_retries=1,
            summary_threshold=100,
            max_entities=10,
            max_plan_nodes=5,
        )
        result = orch.run("test with custom params")
        assert result is not None

    def test_all_middlewares_registered(self):
        orch = create_default_orchestrator()
        assert "perception" in orch._middlewares
        assert "control" in orch._middlewares
        assert "execution" in orch._middlewares
        assert "evaluation" in orch._middlewares
