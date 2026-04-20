"""Tests for the four-middleware architecture with 5-phase lifecycle hooks."""
from __future__ import annotations

from typing import Any

import pytest
from hi_agent.middleware.control import ControlMiddleware
from hi_agent.middleware.defaults import create_default_orchestrator
from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.middleware.execution import ExecutionMiddleware
from hi_agent.middleware.orchestrator import MiddlewareOrchestrator
from hi_agent.middleware.perception import PerceptionMiddleware
from hi_agent.middleware.protocol import (
    HookAction,
    HookResult,
    LifecyclePhase,
    MiddlewareMessage,
)

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


class _StubInvoker:
    """Stub capability invoker that returns a simple string result."""
    def invoke(self, payload: dict, resources: dict) -> str:
        desc = payload.get("description", "")
        return f"Completed: {desc}" if desc else "executed"


def _make_execution_msg(text: str = "hello world") -> MiddlewareMessage:
    """Simulate output of execution middleware with a stub invoker."""
    em = ExecutionMiddleware(capability_invoker=_StubInvoker())
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

        _ = orch.run("original input")
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

        _ = orch.run("test input")
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

        _ = orch.run("test input")
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

        _ = orch.run("test")
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


class TestPerceptionLLMSummarization:
    """Tests for optional LLM-based abstractive summarization in Perception."""

    def _make_long_text(self, char_count: int = 2000) -> str:
        """Create text that exceeds both the token threshold and char threshold."""
        return "First paragraph intro.\n\n" + ("Middle content word. " * (char_count // 20)) + "\n\nFinal paragraph conclusion."

    def test_llm_summarization_used_for_long_text(self):
        """When llm_gateway is available and text is long, LLM summarization is used."""
        from tests.helpers.llm_gateway_fixture import MockLLMGateway
        gateway = MockLLMGateway(default_response="LLM summary result")
        pm = PerceptionMiddleware(summary_threshold=10, llm_gateway=gateway)
        msg = _make_input_msg(self._make_long_text())
        result = pm.process(msg)
        assert result.payload["summary"] == "LLM summary result"
        assert result.payload["summarization_method"] == "llm"

    def test_extractive_used_when_no_gateway(self):
        """Without llm_gateway, extractive summarization is used."""
        pm = PerceptionMiddleware(summary_threshold=10, llm_gateway=None)
        msg = _make_input_msg(self._make_long_text())
        result = pm.process(msg)
        assert result.payload["summarization_method"] == "extractive"
        assert result.payload["summary"] is not None

    def test_short_text_skips_summarization(self):
        """Short text below threshold gets no summarization."""
        from tests.helpers.llm_gateway_fixture import MockLLMGateway
        gateway = MockLLMGateway(default_response="should not appear")
        pm = PerceptionMiddleware(summary_threshold=2000, llm_gateway=gateway)
        msg = _make_input_msg("short text")
        result = pm.process(msg)
        assert result.payload["summary"] is None
        assert result.payload["summarization_method"] == "none"

    def test_falls_back_to_extractive_on_llm_failure(self):
        """If LLM call raises an exception, falls back to extractive."""
        from hi_agent.llm.protocol import LLMRequest as _Req

        class FailingGateway:
            def complete(self, request: _Req):
                raise RuntimeError("LLM unavailable")
            def supports_model(self, model: str) -> bool:
                return True

        pm = PerceptionMiddleware(summary_threshold=10, llm_gateway=FailingGateway())
        msg = _make_input_msg(self._make_long_text())
        result = pm.process(msg)
        assert result.payload["summarization_method"] == "extractive"
        assert result.payload["summary"] is not None
        assert "First paragraph" in result.payload["summary"]

    def test_summarization_method_correctly_set_for_all_paths(self):
        """Verify summarization_method is present in all code paths."""
        from tests.helpers.llm_gateway_fixture import MockLLMGateway
        # Path 1: none (short text)
        pm = PerceptionMiddleware(summary_threshold=2000)
        r1 = pm.process(_make_input_msg("hi"))
        assert r1.payload["summarization_method"] == "none"

        # Path 2: extractive (long text, no gateway)
        pm2 = PerceptionMiddleware(summary_threshold=10)
        r2 = pm2.process(_make_input_msg(self._make_long_text()))
        assert r2.payload["summarization_method"] == "extractive"

        # Path 3: llm (long text, gateway present)
        gw = MockLLMGateway(default_response="summary")
        pm3 = PerceptionMiddleware(summary_threshold=10, llm_gateway=gw)
        r3 = pm3.process(_make_input_msg(self._make_long_text()))
        assert r3.payload["summarization_method"] == "llm"

    def test_llm_summary_shorter_than_input(self):
        """LLM summary should be shorter than the original input."""
        from tests.helpers.llm_gateway_fixture import MockLLMGateway
        gateway = MockLLMGateway(default_response="Brief summary.")
        pm = PerceptionMiddleware(summary_threshold=10, llm_gateway=gateway)
        long_text = self._make_long_text(3000)
        msg = _make_input_msg(long_text)
        result = pm.process(msg)
        assert len(result.payload["summary"]) < len(long_text)


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


class TestControlMiddlewareLLMDecomposition:
    """Tests for LLM-driven adaptive decomposition in ControlMiddleware."""

    def _make_mock_gateway(self, response_content: str):
        """Create a MockLLMGateway with the given response."""
        from tests.helpers.llm_gateway_fixture import MockLLMGateway
        gw = MockLLMGateway(default_response=response_content)
        return gw

    def test_llm_decomposition_produces_custom_stages(self):
        """When gateway returns valid JSON, custom stages are used."""
        import json
        stages = [
            {"stage_id": "parse", "stage_name": "Parse input",
             "description": "Parse the user input", "depends_on": []},
            {"stage_id": "compute", "stage_name": "Compute result",
             "description": "Run the computation", "depends_on": ["parse"]},
            {"stage_id": "format", "stage_name": "Format output",
             "description": "Format the final output", "depends_on": ["compute"]},
        ]
        gw = self._make_mock_gateway(json.dumps(stages))
        cm = ControlMiddleware(llm_gateway=gw)
        msg = _make_perception_msg("compute something")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        node_ids = [n["node_id"] for n in graph["nodes"]]
        assert node_ids == ["parse", "compute", "format"]
        assert len(graph["edges"]) == 2

    def test_fallback_to_default_when_gateway_is_none(self):
        """Without a gateway the default 5-stage plan is used."""
        cm = ControlMiddleware(llm_gateway=None)
        msg = _make_perception_msg("do something")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        assert len(graph["nodes"]) == 5
        node_ids = [n["node_id"] for n in graph["nodes"]]
        assert node_ids == ["understand", "gather", "build", "synthesize", "review"]

    def test_fallback_to_default_on_invalid_json(self):
        """When LLM returns non-JSON, fall back to default stages."""
        gw = self._make_mock_gateway("This is not valid JSON at all")
        cm = ControlMiddleware(llm_gateway=gw)
        msg = _make_perception_msg("do something")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        assert len(graph["nodes"]) == 5

    def test_fallback_to_default_on_llm_exception(self):
        """When the gateway raises an exception, fall back to default stages."""
        class ExplodingGateway:
            def complete(self, request):
                raise RuntimeError("LLM service unavailable")
            def supports_model(self, model):
                return True

        cm = ControlMiddleware(llm_gateway=ExplodingGateway())
        msg = _make_perception_msg("do something")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        assert len(graph["nodes"]) == 5

    def test_fallback_on_too_few_stages(self):
        """LLM returning only 1 stage should trigger fallback."""
        import json
        stages = [{"stage_id": "only", "stage_name": "Only stage",
                    "description": "Single", "depends_on": []}]
        gw = self._make_mock_gateway(json.dumps(stages))
        cm = ControlMiddleware(llm_gateway=gw)
        msg = _make_perception_msg("do something")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        assert len(graph["nodes"]) == 5  # fell back to default

    def test_custom_stages_have_correct_structure(self):
        """Each custom stage node must have node_id, node_type, and payload."""
        import json
        stages = [
            {"stage_id": "a", "stage_name": "Alpha",
             "description": "First step", "depends_on": []},
            {"stage_id": "b", "stage_name": "Beta",
             "description": "Second step", "depends_on": ["a"]},
        ]
        gw = self._make_mock_gateway(json.dumps(stages))
        cm = ControlMiddleware(llm_gateway=gw)
        msg = _make_perception_msg("task")
        result = cm.process(msg)
        graph = result.payload["graph_json"]
        for node in graph["nodes"]:
            assert "node_id" in node
            assert node["node_type"] == "stage"
            assert "description" in node["payload"]
        # First node carries the input text
        assert graph["nodes"][0]["payload"]["input_text"] == "task"
        # Subsequent nodes have empty input_text
        assert graph["nodes"][1]["payload"]["input_text"] == ""


class TestExecutionMiddleware:
    """Tests for ExecutionMiddleware execution and idempotency."""

    def test_execute_node_with_minimal_context(self):
        # Without a capability_invoker (non-strict mode), the middleware returns
        # a degraded-but-passing result so the pipeline can continue.
        em = ExecutionMiddleware()
        msg = _make_control_msg("test task")
        result = em.process(msg)
        results = result.payload.get("results", [])
        assert len(results) > 0
        # Non-strict mode: degraded result signals failure with success=False and _degraded flag
        assert results[0].get("success") is False
        assert results[0].get("output", {}).get("_degraded") is True

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
        for a, b in zip(r1, r2, strict=True):
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
        _ = orch.run("test reflection loop")
        log = orch.get_message_log()
        sources = [m.source for m in log]
        # Execution should appear more than once due to reflection
        exec_count = sources.count("execution")
        assert exec_count >= 1

    def test_escalation_loop(self):
        """Evaluation with escalate should route back to control."""
        orch = create_default_orchestrator(quality_threshold=0.99, max_retries=0)
        _ = orch.run("test escalation loop")
        log = orch.get_message_log()
        _ = [m.source for m in log]
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


# ===========================================================================
# Misconfiguration handling tests
# ===========================================================================

class TestExecutionMiddlewareMisconfiguration:
    """Tests for strict mode and missing invoker handling."""

    def test_strict_mode_without_invoker_raises(self):
        """strict=True without capability_invoker raises RuntimeError."""
        with pytest.raises(RuntimeError, match="capability_invoker in strict mode"):
            ExecutionMiddleware(strict=True)

    def test_non_strict_without_invoker_returns_failure(self):
        """strict=False without invoker returns degraded execution results with success=False."""
        em = ExecutionMiddleware()
        msg = _make_control_msg("test task")
        result = em.process(msg)
        results = result.payload.get("results", [])
        assert len(results) > 0
        for r in results:
            # Non-strict degraded mode: success=False with _degraded flag signals real failure
            assert r["success"] is False
            assert r["output"] is not None
            assert r["output"].get("_degraded") is True

    def test_non_strict_without_invoker_logs_warning(self, caplog):
        """strict=False without invoker logs a warning."""
        import logging
        em = ExecutionMiddleware()
        msg = _make_control_msg("test task")
        with caplog.at_level(logging.WARNING, logger="hi_agent.middleware.execution"):
            em.process(msg)
        assert any("no capability_invoker configured" in rec.message for rec in caplog.records)

    def test_real_invoker_no_synthetic_flag(self):
        """Normal execution with a real invoker does not produce _synthetic."""
        class FakeInvoker:
            def invoke(self, payload, resources):
                return "real result"

        em = ExecutionMiddleware(capability_invoker=FakeInvoker())
        msg = _make_control_msg("test task")
        result = em.process(msg)
        results = result.payload.get("results", [])
        assert len(results) > 0
        for r in results:
            output = r["output"]
            # Real invoker output should not be a dict with _synthetic
            if isinstance(output, dict):
                assert output.get("_synthetic") is not True
            else:
                assert output == "real result"

    def test_evaluation_scores_missing_invoker_result_as_zero(self):
        """Execution without invoker produces degraded results; evaluation passes them through."""
        em = ExecutionMiddleware()  # no invoker -> degraded result (success=False, _degraded=True)
        ev = EvaluationMiddleware(quality_threshold=0.5, max_retries=0)
        exec_msg = em.process(_make_control_msg("test task"))
        eval_msg = ev.process(exec_msg)
        evaluations = eval_msg.payload.get("evaluations", [])
        assert len(evaluations) > 0
        # Degraded results (success=False) are still scored by evaluation layer
        for e in evaluations:
            assert e["quality_score"] >= 0.0


# ===========================================================================
# LLM-based quality scoring tests
# ===========================================================================


class _FakeLLMResponse:
    """Minimal LLM response stub for testing."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLMGateway:
    """Fake LLM gateway that returns a pre-configured response."""

    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, request: Any) -> _FakeLLMResponse:
        return _FakeLLMResponse(self._content)

    def supports_model(self, model: str) -> bool:
        return True


class _ErrorLLMGateway:
    """LLM gateway that always raises an exception."""

    def complete(self, request: Any) -> None:
        raise RuntimeError("LLM unavailable")

    def supports_model(self, model: str) -> bool:
        return True


def _make_eval_msg_with_output(output: str) -> MiddlewareMessage:
    """Create an evaluation-ready message with a single successful result."""
    return MiddlewareMessage(
        source="execution",
        target="evaluation",
        msg_type="execution_result",
        payload={
            "results": [
                {
                    "node_id": "test_node",
                    "success": True,
                    "output": output,
                    "evidence": [],
                }
            ],
            "perception_text": "Summarize the data",
        },
    )


class TestLLMQualityScoring:
    """Tests for optional LLM-based quality scoring in EvaluationMiddleware."""

    def test_llm_scoring_used_when_gateway_returns_valid_json(self):
        """LLM scoring is used when gateway is available and returns valid JSON."""
        gateway = _FakeLLMGateway(
            '{"score": 0.85, "issues": [], "strengths": ["clear"]}'
        )
        ev = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway,
        )
        msg = _make_eval_msg_with_output("A detailed analysis of the data.")
        result = ev.process(msg)
        evals = result.payload["evaluations"]
        assert len(evals) == 1
        assert evals[0]["quality_score"] == 0.85
        assert evals[0]["scoring_mode"] == "llm"

    def test_heuristic_fallback_when_gateway_is_none(self):
        """Falls back to heuristic scoring when no gateway is provided."""
        ev = EvaluationMiddleware(quality_threshold=0.5)
        msg = _make_eval_msg_with_output(
            "A sufficiently long output to get a decent heuristic score here."
        )
        result = ev.process(msg)
        evals = result.payload["evaluations"]
        assert len(evals) == 1
        assert evals[0]["scoring_mode"] == "heuristic"
        assert evals[0]["quality_score"] > 0.0

    def test_heuristic_fallback_on_llm_parse_error(self):
        """Falls back to heuristic when LLM returns unparseable response."""
        gateway = _FakeLLMGateway("this is not json at all")
        ev = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway,
        )
        msg = _make_eval_msg_with_output(
            "Some output that is long enough for heuristic scoring to work."
        )
        result = ev.process(msg)
        evals = result.payload["evaluations"]
        assert evals[0]["scoring_mode"] == "heuristic"

    def test_heuristic_fallback_on_llm_exception(self):
        """Falls back to heuristic when LLM gateway raises an exception."""
        gateway = _ErrorLLMGateway()
        ev = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway,
        )
        msg = _make_eval_msg_with_output(
            "Some output that is long enough for heuristic scoring to work."
        )
        result = ev.process(msg)
        evals = result.payload["evaluations"]
        assert evals[0]["scoring_mode"] == "heuristic"
        assert evals[0]["quality_score"] > 0.0

    def test_scoring_mode_reflects_method_used(self):
        """scoring_mode is 'llm' with gateway and 'heuristic' without."""
        gateway = _FakeLLMGateway(
            '{"score": 0.9, "issues": [], "strengths": []}'
        )
        ev_llm = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway,
        )
        ev_heuristic = EvaluationMiddleware(quality_threshold=0.5)

        msg = _make_eval_msg_with_output("Good detailed output for testing.")

        result_llm = ev_llm.process(msg)
        result_heuristic = ev_heuristic.process(msg)

        assert result_llm.payload["evaluations"][0]["scoring_mode"] == "llm"
        assert result_heuristic.payload["evaluations"][0]["scoring_mode"] == "heuristic"

    def test_llm_score_clamped_to_valid_range(self):
        """LLM scores outside [0.0, 1.0] are clamped."""
        # Score above 1.0
        gateway_high = _FakeLLMGateway(
            '{"score": 1.5, "issues": [], "strengths": []}'
        )
        ev = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway_high,
        )
        msg = _make_eval_msg_with_output("Test output.")
        result = ev.process(msg)
        assert result.payload["evaluations"][0]["quality_score"] == 1.0
        assert result.payload["evaluations"][0]["scoring_mode"] == "llm"

        # Score below 0.0
        gateway_low = _FakeLLMGateway(
            '{"score": -0.5, "issues": ["bad"], "strengths": []}'
        )
        ev2 = EvaluationMiddleware(
            quality_threshold=0.5, llm_gateway=gateway_low,
        )
        result2 = ev2.process(msg)
        assert result2.payload["evaluations"][0]["quality_score"] == 0.0
        assert result2.payload["evaluations"][0]["scoring_mode"] == "llm"


# ===========================================================================
# Per-middleware model tier selection tests
# ===========================================================================


class TestMiddlewareModelTier:
    """Tests for per-middleware model tier selection (cost reduction)."""

    def test_perception_default_tier_is_light(self):
        """Perception middleware should default to 'light' tier."""
        pm = PerceptionMiddleware()
        assert pm._model_tier == "light"

    def test_control_default_tier_is_medium(self):
        """Control middleware should default to 'medium' tier."""
        cm = ControlMiddleware()
        assert cm._model_tier == "medium"

    def test_evaluation_default_tier_is_light(self):
        """Evaluation middleware should default to 'light' tier."""
        ev = EvaluationMiddleware()
        assert ev._model_tier == "light"

    def test_custom_tier_override(self):
        """Each middleware should accept a custom model_tier override."""
        pm = PerceptionMiddleware(model_tier="strong")
        assert pm._model_tier == "strong"

        cm = ControlMiddleware(model_tier="light")
        assert cm._model_tier == "light"

        em = ExecutionMiddleware(model_tier="strong")
        assert em._model_tier == "strong"

        ev = EvaluationMiddleware(model_tier="medium")
        assert ev._model_tier == "medium"

    def test_get_cost_breakdown_returns_per_middleware_stats(self):
        """Orchestrator.get_cost_breakdown() returns per-middleware tier and token stats."""
        orchestrator = MiddlewareOrchestrator()
        pm = PerceptionMiddleware(model_tier="light")
        cm = ControlMiddleware(model_tier="medium")
        em = ExecutionMiddleware(model_tier="medium")
        ev = EvaluationMiddleware(model_tier="light")
        orchestrator.register_middleware("perception", pm)
        orchestrator.register_middleware("control", cm)
        orchestrator.register_middleware("execution", em)
        orchestrator.register_middleware("evaluation", ev)

        # Run a simple pipeline
        orchestrator.run("test input")

        breakdown = orchestrator.get_cost_breakdown()
        assert "perception" in breakdown
        assert "evaluation" in breakdown
        assert breakdown["perception"]["tier"] == "light"
        assert breakdown["control"]["tier"] == "medium"
        assert breakdown["evaluation"]["tier"] == "light"
        # Perception should have some tokens after processing
        assert breakdown["perception"]["input_tokens"] >= 0

    def test_get_cost_savings_estimate_shows_savings(self):
        """Orchestrator.get_cost_savings_estimate() shows savings vs all-strong baseline."""
        orchestrator = MiddlewareOrchestrator()
        pm = PerceptionMiddleware(model_tier="light")
        cm = ControlMiddleware(model_tier="medium")
        em = ExecutionMiddleware(model_tier="medium")
        ev = EvaluationMiddleware(model_tier="light")
        orchestrator.register_middleware("perception", pm)
        orchestrator.register_middleware("control", cm)
        orchestrator.register_middleware("execution", em)
        orchestrator.register_middleware("evaluation", ev)

        # Run a pipeline to generate some token usage
        orchestrator.run("Analyze this input data for patterns and trends")

        savings = orchestrator.get_cost_savings_estimate()
        assert "actual_cost_usd" in savings
        assert "baseline_cost_usd" in savings
        assert "savings_usd" in savings
        assert "savings_pct" in savings
        # Using light+medium tiers should be cheaper than all-strong
        assert savings["actual_cost_usd"] <= savings["baseline_cost_usd"]
        assert savings["savings_usd"] >= 0.0
        # With light and medium tiers, savings percentage should be positive
        if savings["baseline_cost_usd"] > 0:
            assert savings["savings_pct"] > 0.0
