"""Generic LLM-backed capability handler factory.

Public API:
    make_llm_capability_handler — build a capability handler backed by an LLM
        gateway, with graceful heuristic fallback in non-prod environments.

Deprecated:
    register_default_capabilities — TRACE-specific wiring; moved to
        hi_agent.samples.trace_pipeline.register_trace_capabilities.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from hi_agent.capability.registry import CapabilityRegistry

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway

logger = logging.getLogger(__name__)


def _allow_heuristic_fallback() -> bool:
    """Whether heuristic capability fallback is allowed in current env."""
    override = os.environ.get("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("HI_AGENT_ENV", "prod").lower() != "prod"


def make_llm_capability_handler(
    capability_name: str,
    system_prompt: str,
    gateway: LLMGateway | None,
) -> Callable[[dict], dict]:
    """Build a generic LLM-backed capability handler.

    Business agents use this factory to create handlers for any capability
    name and system prompt — not just the TRACE S1-S5 set::

        from hi_agent.capability.defaults import make_llm_capability_handler
        from hi_agent.capability.registry import CapabilitySpec

        handler = make_llm_capability_handler(
            "classify_intent",
            "You are an intent classifier. Return JSON: {intent: str, confidence: float}",
            llm_gateway,
        )
        registry.register(CapabilitySpec(name="classify_intent", handler=handler))

    Args:
        capability_name: Name used in logs and error payloads.
        system_prompt: System-level instruction for the LLM.
        gateway: LLM gateway instance. When None, falls back to heuristic in
            non-prod mode and returns a failure response in prod mode.

    Returns:
        A callable ``handler(payload: dict) -> dict`` compatible with
        :class:`~hi_agent.capability.registry.CapabilitySpec`.
    """

    def handler(payload: dict) -> dict:
        # Honour explicit forced-failure flag injected by the runner for testing.
        if payload.get("should_fail"):
            return {"success": False, "score": 0.0, "reason": "forced_failure"}

        goal = payload.get("goal", payload.get("description", ""))
        stage_id = payload.get("stage_id", capability_name)
        context = payload.get("context", "")
        allow_fallback = _allow_heuristic_fallback()

        if gateway is not None:
            try:
                from hi_agent.llm.protocol import LLMRequest

                user_msg = (
                    f"Stage: {stage_id}\nGoal: {goal}\nContext: {context}\n\n"
                    'Respond in JSON: {"output": "...", "evidence": ["..."], '
                    '"score": 0.0-1.0, "done": true|false}'
                )
                request = LLMRequest(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )
                response = gateway.complete(request)
                try:
                    result = json.loads(response.content)
                    return {
                        "success": True,
                        "score": float(result.get("score", 0.7)),
                        "output": result.get("output", ""),
                        "evidence": result.get("evidence", []),
                        "stage_id": stage_id,
                    }
                except (json.JSONDecodeError, ValueError, KeyError):
                    return {
                        "success": True,
                        "score": 0.6,
                        "output": response.content,
                        "evidence": [f"{capability_name}:llm_output"],
                        "stage_id": stage_id,
                    }
            except Exception as exc:
                if not allow_fallback:
                    return {
                        "success": False,
                        "score": 0.0,
                        "output": "",
                        "evidence": [f"{capability_name}:llm_error:{stage_id}"],
                        "stage_id": stage_id,
                        "error": f"LLM call failed: {exc}",
                    }
                logger.warning(
                    "Capability %r: LLM call failed (%s), falling back to heuristic",
                    capability_name,
                    exc,
                )
        elif not allow_fallback:
            return {
                "success": False,
                "score": 0.0,
                "output": "",
                "evidence": [f"{capability_name}:missing_llm_gateway:{stage_id}"],
                "stage_id": stage_id,
                "error": "LLM gateway is required in prod mode",
            }

        # Non-prod fallback path only.
        label = goal or payload.get("action_kind", capability_name) or capability_name

        # Rule 14 (DF-10): record the heuristic degradation as a fallback
        # signal so the operator-shape gate (Rule 15) sees it.  We use
        # kind="capability" and attribute to the current run_id if the
        # caller provided one in the payload.
        try:
            from hi_agent.observability.fallback import record_fallback

            record_fallback(
                "capability",
                reason="heuristic_branch" if gateway is None else "llm_error_recovered",
                run_id=payload.get("run_id") or str(uuid.uuid4()),
                extra={
                    "capability": capability_name,
                    "stage_id": stage_id,
                },
            )
        except Exception:  # pragma: no cover — observability must never crash caller
            pass

        return {
            "success": True,
            "score": 0.5,
            "output": f"[{capability_name}] processed: {label[:200]}",
            "evidence": [f"{capability_name}:heuristic:{stage_id}"],
            "stage_id": stage_id,
            "_heuristic": True,  # marks as non-real execution
            "_provenance": {
                "mode": "sample",
                "capability_name": capability_name,
                "duration_ms": 0,
            },
        }

    handler.__name__ = f"{capability_name}_handler"
    return handler


# Backward-compat alias used internally by samples/trace_pipeline.py and tests.
_make_llm_handler = make_llm_capability_handler


def register_default_capabilities(
    registry: CapabilityRegistry,
    *,
    llm_gateway: LLMGateway | None = None,
) -> None:
    """Register TRACE stage capability handlers.

    .. deprecated::
        This is a *sample* wiring for the S1-S5 TRACE pipeline.  The
        implementation now lives in
        ``hi_agent.samples.trace_pipeline.register_trace_capabilities``.
        Business agents with different stage topologies should register their
        own handlers.  This function is kept for backward compatibility only.
    """
    from hi_agent.samples.trace_pipeline import register_trace_capabilities

    register_trace_capabilities(registry, llm_gateway=llm_gateway)
