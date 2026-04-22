"""Extensible middleware orchestrator with 5-phase per-middleware lifecycle.

Each middleware in the pipeline is executed through 5 internal lifecycle
phases (PRE_CREATE, PRE_EXECUTE, EXECUTE, POST_EXECUTE, PRE_DESTROY) every
time the pipeline runs.  The runner auto-invokes the full pipeline twice per
stage: once before LLM execution (pre_execute) and once after (post_execute).
Additional explicit calls to ``run()`` can be made for other trigger points.

The orchestrator IS a TrajectoryGraph. Users can:
  - add/replace/remove middlewares
  - insert custom middlewares at any position
  - register hooks at any lifecycle phase of any middleware
  - modify the flow graph (add routes, conditions)
  - visualize the flow as Mermaid

Default flow: perception -> control -> execution -> evaluation
  with escalation (eval->control) and reflection (eval->execution) loops.
"""

from __future__ import annotations

import logging as _logging
import threading
from collections.abc import Callable
from typing import Any

_logger = _logging.getLogger(__name__)

from hi_agent.middleware.protocol import (
    HookAction,
    HookResult,
    LifecycleHook,
    LifecyclePhase,
    MiddlewareMessage,
)
from hi_agent.trajectory.graph import (
    EdgeType,
    TrajectoryGraph,
    TrajEdge,
    TrajNode,
)


class PipelineBlockedError(Exception):
    """Raised when a hook BLOCKs the pipeline."""


class MiddlewareOrchestrator:
    """Extensible middleware orchestrator with 5-phase per-middleware lifecycle hooks.

    The runner auto-invokes ``run()`` twice per stage (pre_execute, post_execute).
    Additional phases can be triggered by calling ``run()`` explicitly.
    """

    # Cost-per-million-token estimates by tier for savings calculations.
    _TIER_COST_PER_MTOK: dict[str, float] = {
        "strong": 15.0,
        "medium": 3.0,
        "light": 0.25,
    }

    def __init__(self) -> None:
        """Initialize MiddlewareOrchestrator."""
        self._middlewares: dict[str, Any] = {}  # name -> middleware instance
        self._hooks: dict[str, list[LifecycleHook]] = {}  # middleware_name -> hooks
        self._global_hooks: dict[LifecyclePhase, list[LifecycleHook]] = {
            phase: [] for phase in LifecyclePhase
        }
        self._flow_graph: TrajectoryGraph = TrajectoryGraph("middleware_flow")
        self._flow_order: list[str] = []  # ordered middleware names for traversal
        self._message_log: list[MiddlewareMessage] = []
        self._middleware_metrics: dict[str, dict[str, Any]] = {}
        self._middleware_configs: dict[str, dict[str, Any]] = {}
        self._tier_usage: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._setup_default_flow()

    # --- Default flow ---

    def _setup_default_flow(self) -> None:
        """Perception -> control -> execution -> evaluation + feedback loops."""
        default_names = ["perception", "control", "execution", "evaluation"]
        for name in default_names:
            node = TrajNode(node_id=name, node_type="middleware")
            self._flow_graph.add_node(node)
            self._hooks[name] = []
            self._middleware_metrics[name] = {
                "calls": 0,
                "tokens": 0,
                "errors": 0,
            }

        # Linear flow
        self._flow_graph.add_sequence("perception", "control")
        self._flow_graph.add_sequence("control", "execution")
        self._flow_graph.add_sequence("execution", "evaluation")

        # Feedback loops as backtrack edges
        self._flow_graph.add_backtrack(
            "evaluation",
            "execution",
            desc="reflection",
        )
        self._flow_graph.add_backtrack(
            "evaluation",
            "control",
            desc="escalation",
        )

        self._flow_order = list(default_names)

    # --- Middleware management ---

    def register_middleware(self, name: str, mw: Any) -> None:
        """Register a middleware. Does not change flow graph (assumes node exists)."""
        tier = getattr(mw, "_model_tier", "medium")
        with self._lock:
            self._middlewares[name] = mw
            if name not in self._hooks:
                self._hooks[name] = []
            if name not in self._middleware_metrics:
                self._middleware_metrics[name] = {
                    "calls": 0,
                    "tokens": 0,
                    "errors": 0,
                }
            # Track per-middleware tier usage for cost analysis
            self._tier_usage[name] = {
                "tier": tier,
                "input_tokens": 0,
                "output_tokens": 0,
            }

    def replace_middleware(self, name: str, mw: Any) -> None:
        """Replace an existing middleware instance."""
        with self._lock:
            if name not in self._middlewares:
                raise KeyError(f"Middleware '{name}' not registered")
            self._middlewares[name] = mw

    def add_middleware(
        self,
        name: str,
        mw: Any,
        after: str | None = None,
        before: str | None = None,
    ) -> None:
        """Insert middleware into flow. Reconnects edges automatically."""
        with self._lock:
            self._add_middleware_locked(name, mw, after=after, before=before)

    def _add_middleware_locked(
        self,
        name: str,
        mw: Any,
        after: str | None = None,
        before: str | None = None,
    ) -> None:
        """Internal: add middleware while caller holds self._lock."""
        # Add the node
        node = TrajNode(node_id=name, node_type="middleware")
        self._flow_graph.add_node(node)
        self._middlewares[name] = mw
        self._hooks[name] = []
        self._middleware_metrics[name] = {
            "calls": 0,
            "tokens": 0,
            "errors": 0,
        }

        if after is not None:
            # Insert after 'after': find outgoing SEQUENCE edge from 'after'
            outgoing = [
                e for e in self._flow_graph.get_outgoing(after) if e.edge_type == EdgeType.SEQUENCE
            ]
            if outgoing:
                next_node = outgoing[0].target
                # Remove old edge
                self._flow_graph.remove_edge(after, next_node)
                # Insert: after -> name -> next_node
                self._flow_graph.add_sequence(after, name)
                self._flow_graph.add_sequence(name, next_node)
            else:
                # Just add at end
                self._flow_graph.add_sequence(after, name)

            # Update flow order
            idx = (
                self._flow_order.index(after)
                if after in self._flow_order
                else len(self._flow_order)
            )
            self._flow_order.insert(idx + 1, name)

        elif before is not None:
            # Insert before 'before': find incoming SEQUENCE edge to 'before'
            incoming = [
                e for e in self._flow_graph.get_incoming(before) if e.edge_type == EdgeType.SEQUENCE
            ]
            if incoming:
                prev_node = incoming[0].source
                # Remove old edge
                self._flow_graph.remove_edge(prev_node, before)
                # Insert: prev_node -> name -> before
                self._flow_graph.add_sequence(prev_node, name)
                self._flow_graph.add_sequence(name, before)
            else:
                # Just add at beginning
                self._flow_graph.add_sequence(name, before)

            # Update flow order
            idx = self._flow_order.index(before) if before in self._flow_order else 0
            self._flow_order.insert(idx, name)
        else:
            # Append to end
            if self._flow_order:
                last = self._flow_order[-1]
                self._flow_graph.add_sequence(last, name)
            self._flow_order.append(name)

    def remove_middleware(self, name: str) -> None:
        """Remove and reconnect neighbors."""
        with self._lock:
            if name not in self._middlewares and self._flow_graph.get_node(name) is None:
                raise KeyError(f"Middleware '{name}' not found")

            # Find incoming and outgoing SEQUENCE edges to reconnect
            incoming_seq = [
                e for e in self._flow_graph.get_incoming(name) if e.edge_type == EdgeType.SEQUENCE
            ]
            outgoing_seq = [
                e for e in self._flow_graph.get_outgoing(name) if e.edge_type == EdgeType.SEQUENCE
            ]

            # Remove the node (removes all edges)
            self._flow_graph.remove_node(name)

            # Reconnect: each predecessor to each successor
            for inc in incoming_seq:
                for out in outgoing_seq:
                    if self._flow_graph.get_node(inc.source) and self._flow_graph.get_node(
                        out.target
                    ):
                        self._flow_graph.add_sequence(inc.source, out.target)

            self._middlewares.pop(name, None)
            self._hooks.pop(name, None)
            self._middleware_metrics.pop(name, None)
            if name in self._flow_order:
                self._flow_order.remove(name)

    # --- Lifecycle hooks ---

    def add_hook(
        self,
        middleware_name: str,
        phase: LifecyclePhase,
        callback: Callable[[MiddlewareMessage, dict[str, Any]], HookResult],
        priority: int = 0,
        name: str = "",
        once: bool = False,
    ) -> None:
        """Register a hook for a specific middleware's lifecycle phase."""
        hook = LifecycleHook(
            phase=phase,
            callback=callback,
            priority=priority,
            name=name,
            once=once,
        )
        with self._lock:
            self._hooks.setdefault(middleware_name, []).append(hook)

    def add_global_hook(
        self,
        phase: LifecyclePhase,
        callback: Callable[[MiddlewareMessage, dict[str, Any]], HookResult],
        priority: int = 0,
        name: str = "",
    ) -> None:
        """Register a hook that fires for ALL middlewares at given phase."""
        hook = LifecycleHook(
            phase=phase,
            callback=callback,
            priority=priority,
            name=name,
        )
        with self._lock:
            self._global_hooks[phase].append(hook)

    def remove_hook(self, middleware_name: str, hook_name: str) -> None:
        """Remove a named hook from a middleware."""
        with self._lock:
            hooks = self._hooks.get(middleware_name, [])
            self._hooks[middleware_name] = [h for h in hooks if h.name != hook_name]

    # --- Flow customization ---

    def add_route(
        self,
        source: str,
        target: str,
        condition: Callable[[dict[str, Any]], bool] | None = None,
        edge_type: str = "sequence",
    ) -> None:
        """Add a custom route edge between middlewares."""
        edge_types = [e.value for e in EdgeType]
        etype = EdgeType(edge_type) if edge_type in edge_types else EdgeType.SEQUENCE
        edge = TrajEdge(
            source=source,
            target=target,
            edge_type=etype,
            condition=condition,
        )
        self._flow_graph.add_edge(edge)

    def remove_route(self, source: str, target: str) -> None:
        """Remove a route between middlewares."""
        self._flow_graph.remove_edge(source, target)

    def get_flow_mermaid(self) -> str:
        """Render the flow graph as Mermaid."""
        return self._flow_graph.to_mermaid(title="Middleware Flow")

    # --- Execution ---

    def run(
        self,
        user_input: str,
        metadata: dict[str, Any] | None = None,
    ) -> MiddlewareMessage:
        """Execute full pipeline with lifecycle hooks at each middleware."""
        meta = metadata or {}
        _logger.debug("orchestrator.run_start")

        # Create initial message
        message = MiddlewareMessage(
            source="user",
            target="perception",
            msg_type="user_input",
            payload={"user_input": user_input},
            metadata=meta,
        )
        with self._lock:
            self._message_log.append(message)

        # Snapshot structural state under lock so concurrent add/remove_middleware
        # calls cannot corrupt this run's view mid-execution.
        with self._lock:
            _mw = dict(self._middlewares)

        current = "perception"
        max_iterations = 50  # safety limit
        iterations = 0

        while current is not None and iterations < max_iterations:
            iterations += 1

            if current not in _mw:
                break

            try:
                message = self._execute_middleware_with_lifecycle(
                    current,
                    message,
                    _mw_snapshot=_mw,
                )
            except PipelineBlockedError:
                _logger.info("orchestrator.pipeline_blocked name=%s", current)
                break

            with self._lock:
                self._message_log.append(message)

            # Route to next middleware
            current = self._route_next(current, message)

        _logger.debug("orchestrator.run_complete")
        return message

    def _execute_middleware_with_lifecycle(
        self,
        name: str,
        message: MiddlewareMessage,
        _mw_snapshot: dict[str, Any] | None = None,
    ) -> MiddlewareMessage:
        """Execute one middleware through all 5 lifecycle phases.

        1. pre_create hooks -> middleware.on_create()
        2. pre_execute hooks -> check for SKIP/BLOCK/MODIFY
        3. execute -> middleware.process(message) (with RETRY support)
        4. post_execute hooks -> check for MODIFY/BLOCK
        5. pre_destroy hooks -> middleware.on_destroy()

        Hook execution order: global hooks first, then middleware-specific,
        sorted by priority DESC.

        Args:
            _mw_snapshot: Snapshot of ``self._middlewares`` taken under lock by
                ``run()``.  When provided, used instead of reading the live dict
                so that concurrent structural mutations don't affect this run.
        """
        mw = (_mw_snapshot or self._middlewares)[name]
        metrics = self._middleware_metrics.get(name, {"calls": 0, "tokens": 0, "errors": 0})

        # Phase 1: PRE_CREATE
        hook_result = self._run_hooks(name, LifecyclePhase.PRE_CREATE, message)
        if hook_result.action == HookAction.BLOCK:
            _logger.info(
                "orchestrator.pipeline_blocked name=%s reason=%s",
                name,
                getattr(hook_result, "reason", ""),
            )
            raise PipelineBlockedError(hook_result.reason)
        config = self._middleware_configs.get(name, {})
        if hasattr(mw, "on_create"):
            mw.on_create(config)

        # Phase 2: PRE_EXECUTE
        hook_result = self._run_hooks(name, LifecyclePhase.PRE_EXECUTE, message)
        if hook_result.action == HookAction.BLOCK:
            _logger.info(
                "orchestrator.pipeline_blocked name=%s reason=%s",
                name,
                getattr(hook_result, "reason", ""),
            )
            raise PipelineBlockedError(hook_result.reason)
        if hook_result.action == HookAction.SKIP:
            # Skip this middleware, pass message through
            metrics["calls"] += 1
            with self._lock:
                self._middleware_metrics[name] = metrics
            # Phase 5: PRE_DESTROY even on skip
            self._run_hooks(name, LifecyclePhase.PRE_DESTROY, message)
            if hasattr(mw, "on_destroy"):
                mw.on_destroy()
            return message
        if hook_result.action == HookAction.MODIFY and hook_result.modified_message is not None:
            message = hook_result.modified_message

        # Phase 3: EXECUTE (with RETRY support)
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                result = mw.process(message)
                metrics["calls"] += 1
                metrics["tokens"] += result.token_cost
                break
            except Exception as exc:
                metrics["errors"] += 1
                _logger.warning("orchestrator.middleware_error name=%s error=%s", name, exc)
                if attempt == max_retries:
                    result = MiddlewareMessage(
                        source=name,
                        target="error",
                        msg_type="error",
                        payload={"error": str(exc)},
                        metadata=message.metadata,
                    )
                    break

        # Run execute hooks to check for RETRY
        exec_hook_result = self._run_hooks(name, LifecyclePhase.EXECUTE, result)
        if exec_hook_result.action == HookAction.RETRY:
            retry_limit = exec_hook_result.metadata.get("max_retries", 3)
            for _retry in range(retry_limit):
                try:
                    result = mw.process(message)
                    metrics["calls"] += 1
                    metrics["tokens"] += result.token_cost
                    break
                except Exception:
                    metrics["errors"] += 1

        # Phase 4: POST_EXECUTE
        hook_result = self._run_hooks(name, LifecyclePhase.POST_EXECUTE, result)
        if hook_result.action == HookAction.BLOCK:
            _logger.info(
                "orchestrator.pipeline_blocked name=%s reason=%s",
                name,
                getattr(hook_result, "reason", ""),
            )
            raise PipelineBlockedError(hook_result.reason)
        if hook_result.action == HookAction.MODIFY and hook_result.modified_message is not None:
            result = hook_result.modified_message

        # Phase 5: PRE_DESTROY
        self._run_hooks(name, LifecyclePhase.PRE_DESTROY, result)
        if hasattr(mw, "on_destroy"):
            mw.on_destroy()

        with self._lock:
            self._middleware_metrics[name] = metrics
            # Accumulate token usage for tier cost tracking
            if name in self._tier_usage:
                self._tier_usage[name]["input_tokens"] += result.token_cost
                self._tier_usage[name]["output_tokens"] += max(1, result.token_cost // 2)
        return result

    def _run_hooks(
        self,
        middleware_name: str,
        phase: LifecyclePhase,
        message: MiddlewareMessage,
    ) -> HookResult:
        """Run all hooks for a phase. Merge results (first BLOCK/SKIP wins)."""
        # Collect all applicable hooks
        hooks: list[LifecycleHook] = []

        # Global hooks first
        for h in self._global_hooks.get(phase, []):
            hooks.append(h)

        # Middleware-specific hooks
        for h in self._hooks.get(middleware_name, []):
            if h.phase == phase:
                hooks.append(h)

        # Sort by priority DESC (higher priority first)
        hooks.sort(key=lambda h: h.priority, reverse=True)

        combined = HookResult()
        hooks_to_remove: list[LifecycleHook] = []

        ctx: dict[str, Any] = {
            "middleware_name": middleware_name,
            "phase": phase.value,
        }

        for hook in hooks:
            if hook.once and hook._executed:
                continue

            result = hook.callback(message, ctx)
            hook._executed = True

            if hook.once:
                hooks_to_remove.append(hook)

            # First BLOCK wins
            if result.action == HookAction.BLOCK:
                return result

            # First SKIP wins
            if result.action == HookAction.SKIP:
                return result

            # RETRY is returned directly; propagate hook.max_retries into metadata
            # so the caller can use the hook's configured retry limit.
            if result.action == HookAction.RETRY:
                if "max_retries" not in result.metadata:
                    result.metadata["max_retries"] = hook.max_retries
                return result

            # MODIFY: apply, continue checking other hooks
            if result.action == HookAction.MODIFY:
                combined = result

        # Remove once-hooks
        for hook in hooks_to_remove:
            if hook in self._global_hooks.get(phase, []):
                self._global_hooks[phase].remove(hook)
            mw_hooks = self._hooks.get(middleware_name, [])
            if hook in mw_hooks:
                mw_hooks.remove(hook)

        return combined

    def _route_next(
        self,
        current: str,
        result: MiddlewareMessage,
    ) -> str | None:
        """Determine next middleware based on message target and flow graph.

        Priority:
        1. Special targets (end, error, user) -> stop
        2. If the message target matches a backtrack edge from current -> follow it
           (this handles escalation and reflection feedback loops)
        3. Otherwise, follow the flow graph SEQUENCE edges from current node
           (this handles normal flow and custom middleware insertion)
        """
        target = result.target

        # Special targets
        if target in ("end", "error", "user"):
            return None

        # Check if target is reachable via backtrack edge (feedback loop)
        backtrack_targets = {
            e.target
            for e in self._flow_graph.get_outgoing(current)
            if e.edge_type == EdgeType.BACKTRACK
        }
        if target in backtrack_targets and target in self._middlewares:
            return target

        # Follow the flow graph sequence
        outgoing_seq = [
            e for e in self._flow_graph.get_outgoing(current) if e.edge_type == EdgeType.SEQUENCE
        ]
        if outgoing_seq:
            seq_next = outgoing_seq[0].target
            if seq_next in self._middlewares:
                return seq_next

        # Fallback: if target is a known middleware, go there
        if target in self._middlewares:
            return target

        return None

    # --- Observability ---

    def get_message_log(self) -> list[MiddlewareMessage]:
        """Return all messages exchanged during execution."""
        with self._lock:
            return list(self._message_log)

    def get_cost_summary(self) -> dict[str, Any]:
        """Return per-middleware cost summary."""
        with self._lock:
            metrics_snapshot = {k: dict(v) for k, v in self._middleware_metrics.items()}
        total_tokens = 0
        per_middleware: dict[str, int] = {}
        for name, metrics in metrics_snapshot.items():
            tokens = metrics.get("tokens", 0)
            per_middleware[name] = tokens
            total_tokens += tokens
        return {
            "total_tokens": total_tokens,
            "per_middleware": per_middleware,
        }

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """Return all middleware metrics."""
        with self._lock:
            return {k: dict(v) for k, v in self._middleware_metrics.items()}

    def get_cost_breakdown(self) -> dict[str, dict[str, Any]]:
        """Return per-middleware cost estimate based on tier and token usage.

        Returns a dict keyed by middleware name, each containing:
        - tier: the model tier used
        - input_tokens: total input tokens consumed
        - output_tokens: estimated output tokens consumed
        - estimated_cost_usd: estimated cost in USD
        """
        with self._lock:
            tier_snapshot = {k: dict(v) for k, v in self._tier_usage.items()}
        breakdown: dict[str, dict[str, Any]] = {}
        for name, usage in tier_snapshot.items():
            tier = usage["tier"]
            input_tok = usage["input_tokens"]
            output_tok = usage["output_tokens"]
            cost_per_mtok = self._TIER_COST_PER_MTOK.get(tier, 3.0)
            estimated_cost = ((input_tok + output_tok) / 1_000_000) * cost_per_mtok
            breakdown[name] = {
                "tier": tier,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "estimated_cost_usd": estimated_cost,
            }
        return breakdown

    def get_cost_savings_estimate(self) -> dict[str, Any]:
        """Compare actual tiered cost vs hypothetical all-strong baseline.

        Returns:
            - actual_cost_usd: estimated cost using per-middleware tiers
            - baseline_cost_usd: estimated cost if all middlewares used "strong"
            - savings_usd: baseline - actual
            - savings_pct: percentage saved (0-100)
        """
        with self._lock:
            tier_snapshot = {k: dict(v) for k, v in self._tier_usage.items()}
        strong_cost_per_mtok = self._TIER_COST_PER_MTOK["strong"]
        actual_total = 0.0
        baseline_total = 0.0
        for usage in tier_snapshot.values():
            tier = usage["tier"]
            total_tok = usage["input_tokens"] + usage["output_tokens"]
            cost_per_mtok = self._TIER_COST_PER_MTOK.get(tier, 3.0)
            actual_total += (total_tok / 1_000_000) * cost_per_mtok
            baseline_total += (total_tok / 1_000_000) * strong_cost_per_mtok
        savings = baseline_total - actual_total
        savings_pct = (savings / baseline_total * 100.0) if baseline_total > 0 else 0.0
        return {
            "actual_cost_usd": actual_total,
            "baseline_cost_usd": baseline_total,
            "savings_usd": savings,
            "savings_pct": savings_pct,
        }
