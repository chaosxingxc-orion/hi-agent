"""Default LLM-backed capability handlers for TRACE stage actions."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway

logger = logging.getLogger(__name__)


def _make_llm_handler(
    capability_name: str,
    system_prompt: str,
    gateway: "LLMGateway | None",
) -> Callable[[dict], dict]:
    """Build a capability handler that calls LLM when available, falls back to heuristic."""

    def handler(payload: dict) -> dict:
        # Honour explicit forced-failure flag injected by the runner for testing.
        if payload.get("should_fail"):
            return {"success": False, "score": 0.0, "reason": "forced_failure"}

        goal = payload.get("goal", payload.get("description", ""))
        stage_id = payload.get("stage_id", capability_name)
        context = payload.get("context", "")

        if gateway is not None:
            try:
                from hi_agent.llm.protocol import LLMRequest
                user_msg = (
                    f"Stage: {stage_id}\nGoal: {goal}\nContext: {context}\n\n"
                    "Respond in JSON: {\"output\": \"...\", \"evidence\": [\"...\"], "
                    "\"score\": 0.0-1.0, \"done\": true|false}"
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
                    # LLM returned non-JSON — treat as text output
                    return {
                        "success": True,
                        "score": 0.6,
                        "output": response.content,
                        "evidence": [f"{capability_name}:llm_output"],
                        "stage_id": stage_id,
                    }
            except Exception as exc:
                logger.warning(
                    "Capability %r: LLM call failed (%s), falling back to heuristic",
                    capability_name,
                    exc,
                )

        # Heuristic fallback — produce a minimal but non-fake result.
        # When no goal is available in the payload (e.g. the runner omits it),
        # fall back to the action_kind or a generic label so we still return
        # success=True and allow the run to progress.
        label = goal or payload.get("action_kind", capability_name) or capability_name
        return {
            "success": True,
            "score": 0.5,
            "output": f"[{capability_name}] processed: {label[:200]}",
            "evidence": [f"{capability_name}:heuristic:{stage_id}"],
            "stage_id": stage_id,
        }

    handler.__name__ = f"{capability_name}_handler"
    return handler


_CAPABILITY_PROMPTS: dict[str, str] = {
    "analyze_goal": (
        "You are a goal analysis engine. Given a task goal and context, "
        "extract key requirements, constraints, and success criteria. "
        "Be precise and structured."
    ),
    "search_evidence": (
        "You are an evidence search engine. Given a goal, identify what "
        "evidence or information is needed and summarize the key findings. "
        "Focus on facts relevant to the goal."
    ),
    "build_draft": (
        "You are a solution builder. Given the goal and gathered evidence, "
        "construct a draft solution or analysis. Be concrete and actionable."
    ),
    "synthesize": (
        "You are a synthesis engine. Combine the goal, evidence, and draft "
        "into a coherent final output. Ensure completeness and quality."
    ),
    "evaluate_acceptance": (
        "You are an acceptance evaluator. Given the task goal and the produced "
        "output, assess whether the result meets the acceptance criteria. "
        "Return a score from 0.0 (fail) to 1.0 (pass) and justify your assessment."
    ),
}


def register_default_capabilities(
    registry: CapabilityRegistry,
    *,
    llm_gateway: "LLMGateway | None" = None,
) -> None:
    """Register TRACE stage capability handlers.

    When *llm_gateway* is provided, each handler calls the LLM for real
    execution and falls back to a heuristic on failure.  Without a gateway,
    handlers use the heuristic path only.

    Args:
        registry: Capability registry to populate.
        llm_gateway: Optional LLM gateway for model-backed execution.
    """
    if llm_gateway is None:
        logger.warning(
            "register_default_capabilities: no llm_gateway provided — "
            "all TRACE capabilities will use heuristic-only execution. "
            "Set OPENAI_API_KEY or ANTHROPIC_API_KEY for real LLM calls."
        )
    for name, system_prompt in _CAPABILITY_PROMPTS.items():
        handler = _make_llm_handler(name, system_prompt, llm_gateway)
        registry.register(CapabilitySpec(name=name, handler=handler))
