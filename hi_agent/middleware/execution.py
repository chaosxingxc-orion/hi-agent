"""Execution middleware: load resources, execute with minimal context, idempotent.

Receives ExecutionPlan from Control, walks each node in topological order,
loads per-node resources (skill, memory, knowledge, tools), executes with
a minimal context window, records evidence, and emits ExecutionResult per node.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from hi_agent.middleware.protocol import (
    ExecutionResult,
    MiddlewareMessage,
)


class ExecutionMiddleware:
    """Node-by-node execution middleware."""

    def __init__(
        self,
        capability_invoker: Any | None = None,
        harness_executor: Any | None = None,
        retrieval_engine: Any | None = None,
        skill_loader: Any | None = None,
        strict: bool = False,
        model_tier: str = "medium",
    ) -> None:
        """Initialize ExecutionMiddleware."""
        if strict and capability_invoker is None:
            raise RuntimeError(
                "ExecutionMiddleware requires capability_invoker in strict mode"
            )
        self._capability_invoker = capability_invoker
        self._harness_executor = harness_executor
        self._retrieval_engine = retrieval_engine
        self._skill_loader = skill_loader
        self._strict = strict
        self._model_tier = model_tier
        self._idempotency_cache: dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Return name."""
        return "execution"

    def on_create(self, config: dict[str, Any]) -> None:
        """Configure from external config dict."""
        if "strict" in config:
            self._strict = bool(config["strict"])
        if "model_tier" in config:
            self._model_tier = str(config["model_tier"])

    def on_destroy(self) -> None:
        """Cleanup per-run resources.

        Only clears per-invocation state (idempotency cache).  Injected platform
        dependencies (_capability_invoker, _harness_executor, _retrieval_engine,
        _skill_loader) are intentionally preserved so they remain available across
        multiple stage executions within the same run.
        """
        self._idempotency_cache.clear()

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        """Execute all nodes in the plan graph."""
        payload = message.payload
        graph_json = payload.get("graph_json", {})
        node_resources = payload.get("node_resources", {})
        perception_text = payload.get("perception_text", "")

        nodes = graph_json.get("nodes", [])
        results: list[dict[str, Any]] = []
        total_tokens = 0
        all_success = True

        for node in nodes:
            node_id = node.get("node_id", "unknown")
            node_payload = node.get("payload", {})
            resources = node_resources.get(node_id, {})

            # Load resources for this node
            loaded = self._load_resources(resources)

            # Build per-node execution context
            exec_context = {
                **node_payload,
                "resources": loaded,
                "perception_text": perception_text,
            }

            # Idempotency check
            idem_key = self._make_idempotency_key(node_id, exec_context)
            if self._ensure_idempotency(idem_key):
                cached = self._idempotency_cache[idem_key]
                results.append(cached)
                total_tokens += cached.get("tokens_used", 0)
                continue

            result = self._execute_node(exec_context, loaded)
            result_dict = {
                "node_id": node_id,
                "output": result.output,
                "evidence": result.evidence,
                "tokens_used": result.tokens_used,
                "success": result.success,
                "error": result.error,
                "idempotency_key": idem_key,
            }

            # Cache for idempotency
            self._idempotency_cache[idem_key] = result_dict
            results.append(result_dict)
            total_tokens += result.tokens_used
            if not result.success:
                all_success = False

        return MiddlewareMessage(
            source="execution",
            target="evaluation",
            msg_type="execution_result",
            payload={
                "results": results,
                "total_tokens": total_tokens,
                "all_success": all_success,
                "perception_text": perception_text,
            },
            token_cost=total_tokens,
            metadata=message.metadata,
        )

    def _load_resources(self, node_resources: dict[str, Any]) -> dict[str, Any]:
        """Load resources specified for this node."""
        loaded: dict[str, Any] = {}

        skill_id = node_resources.get("skill_id")
        if skill_id and self._skill_loader is not None:
            try:
                if hasattr(self._skill_loader, "load"):
                    loaded["skill"] = self._skill_loader.load(skill_id)
            except Exception as exc:
                logger.warning("Failed to load skill %r: %s", skill_id, exc)

        memory_query = node_resources.get("memory_query", "")
        if memory_query and self._retrieval_engine is not None:
            try:
                if hasattr(self._retrieval_engine, "retrieve"):
                    loaded["memory"] = self._retrieval_engine.retrieve(memory_query)
            except Exception as exc:
                logger.warning("Failed to retrieve memory for query %r: %s", memory_query, exc)

        loaded["tools"] = node_resources.get("tools", [])
        return loaded

    def _execute_node(
        self, node_payload: dict[str, Any], resources: dict[str, Any],
    ) -> ExecutionResult:
        """Execute a single node with minimal context."""
        node_id = node_payload.get("node_id", "node")
        description = node_payload.get("description", "")

        evidence: list[str] = []
        if description:
            evidence.append(f"Task: {description}")

        # If capability invoker available, delegate
        if self._capability_invoker is not None:
            try:
                if hasattr(self._capability_invoker, "invoke"):
                    result = self._capability_invoker.invoke(
                        node_payload, resources
                    )
                    # Extract real token count from the invoke result when available;
                    # fall back to a conservative estimate only when unavailable.
                    tokens = (
                        getattr(result, "tokens_used", None)
                        or getattr(result, "usage", {}).get("total_tokens") if hasattr(result, "__getitem__") or hasattr(result, "get") else None
                        or 50
                    )
                    return ExecutionResult(
                        node_id=node_id,
                        output=result,
                        evidence=evidence,
                        tokens_used=int(tokens) if tokens is not None else 50,
                        success=True,
                    )
            except Exception as exc:
                return ExecutionResult(
                    node_id=node_id,
                    output=None,
                    evidence=evidence,
                    tokens_used=10,
                    success=False,
                    error=str(exc),
                )

        if self._strict:
            error_msg = (
                "ExecutionMiddleware misconfigured: capability_invoker is required "
                "for real execution (strict mode)"
            )
            logger.error("%s; node_id=%s", error_msg, node_id)
            return ExecutionResult(
                node_id=node_id,
                output=None,
                evidence=evidence,
                tokens_used=0,
                success=False,
                error=error_msg,
            )
        # Non-strict: no invoker configured — return a degraded-but-passing result
        # so the pipeline can continue. The _degraded flag lets downstream layers
        # distinguish this from a real result.
        logger.warning(
            "ExecutionMiddleware: no capability_invoker configured, "
            "returning degraded result for node_id=%s",
            node_id,
        )
        return ExecutionResult(
            node_id=node_id,
            output={
                "_degraded": True,
                "description": description,
                "output": f"[degraded] {description}",
                "score": 0.5,
            },
            evidence=evidence,
            tokens_used=0,
            success=False,
            error="degraded_execution_no_invoker",
        )

    def _make_idempotency_key(
        self, node_id: str, context: dict[str, Any],
    ) -> str:
        """Generate a deterministic key for idempotency."""
        # Use a stable serialization for hashing
        key_data = json.dumps(
            {"node_id": node_id, "description": context.get("description", "")},
            sort_keys=True,
        )
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _ensure_idempotency(self, key: str) -> bool:
        """Check if this key was already executed. Returns True if cached."""
        return key in self._idempotency_cache

    def handle_reflection(self, msg: MiddlewareMessage) -> MiddlewareMessage:
        """Handle reflection feedback from evaluation: re-execute specific node."""
        payload = msg.payload
        node_id = payload.get("node_id", "unknown")
        retry_instruction = payload.get("retry_instruction", "")

        # Build a single-node execution
        node_payload = {
            "description": retry_instruction or f"Retry node {node_id}",
            "input_text": payload.get("perception_text", ""),
            "perception_text": payload.get("perception_text", ""),
        }
        resources = payload.get("resources", {})
        loaded = self._load_resources(resources)

        result = self._execute_node(node_payload, loaded)
        result_dict = {
            "node_id": node_id,
            "output": result.output,
            "evidence": result.evidence,
            "tokens_used": result.tokens_used,
            "success": result.success,
            "error": result.error,
            "idempotency_key": "",
        }

        return MiddlewareMessage(
            source="execution",
            target="evaluation",
            msg_type="execution_result",
            payload={
                "results": [result_dict],
                "total_tokens": result.tokens_used,
                "all_success": result.success,
                "perception_text": payload.get("perception_text", ""),
            },
            token_cost=result.tokens_used,
            metadata=msg.metadata,
        )
