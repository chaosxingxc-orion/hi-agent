"""Default LLM-backed capability handlers for TRACE stage actions."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway

logger = logging.getLogger(__name__)


def _allow_heuristic_fallback() -> bool:
    """Whether heuristic capability fallback is allowed in current env."""
    override = os.environ.get("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("HI_AGENT_ENV", "prod").lower() != "prod"


def _make_llm_handler(
    capability_name: str,
    system_prompt: str,
    gateway: "LLMGateway | None",
) -> Callable[[dict], dict]:
    """Build a capability handler that requires real LLM in prod mode."""

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
    """Register TRACE stage capability handlers."""
    if llm_gateway is None:
        if not _allow_heuristic_fallback():
            raise RuntimeError(
                "register_default_capabilities requires llm_gateway in prod mode. "
                "Set real LLM credentials or set HI_AGENT_ALLOW_HEURISTIC_FALLBACK=1."
            )
        logger.warning(
            "register_default_capabilities: no llm_gateway provided; "
            "all TRACE capabilities will use heuristic-only execution in non-prod mode."
        )
    for name, system_prompt in _CAPABILITY_PROMPTS.items():
        handler = _make_llm_handler(name, system_prompt, llm_gateway)
        registry.register(CapabilitySpec(name=name, handler=handler))
