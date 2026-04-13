"""Sample TRACE pipeline: S1→S2→S3→S4→S5 stage graph and capability handlers.

This module is an *example configuration* showing how to assemble a hi-agent
runtime that follows the five-stage TRACE methodology
(Understand → Gather → Build → Synthesize → Review).

Business agents with different stage topologies should define their own
stage graphs, stage_actions mappings, and capability bundles rather than
depending on this module directly.

Extension contract:
    - StageGraph topology   → caller-defined (pass to RunExecutor as stage_graph=)
    - stage_actions mapping → caller-defined (pass to RuleRouteEngine as stage_actions=)
    - Capability prompts    → caller-defined (or extend this mapping)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec
from hi_agent.trajectory.stage_graph import StageGraph

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage graph
# ---------------------------------------------------------------------------

#: Canonical stage ordering for the TRACE sample pipeline.
TRACE_STAGES: tuple[str, ...] = (
    "S1_understand",
    "S2_gather",
    "S3_build",
    "S4_synthesize",
    "S5_review",
)

#: Default stage → action_kind mapping for RuleRouteEngine.
TRACE_STAGE_ACTIONS: dict[str, str] = {
    "S1_understand": "analyze_goal",
    "S2_gather": "search_evidence",
    "S3_build": "build_draft",
    "S4_synthesize": "synthesize",
    "S5_review": "evaluate_acceptance",
}


def build_trace_stage_graph() -> StageGraph:
    """Return the canonical S1→S2→S3→S4→S5 stage graph.

    This is the default TRACE sample pipeline.  Pass the returned graph as
    ``stage_graph=`` when constructing :class:`~hi_agent.runner.RunExecutor`::

        from hi_agent.samples.trace_pipeline import build_trace_stage_graph
        executor = RunExecutor(contract, kernel, stage_graph=build_trace_stage_graph())
    """
    graph = StageGraph()
    graph.add_edge("S1_understand", "S2_gather")
    graph.add_edge("S2_gather", "S3_build")
    graph.add_edge("S3_build", "S4_synthesize")
    graph.add_edge("S4_synthesize", "S5_review")
    return graph


# ---------------------------------------------------------------------------
# Capability handlers
# ---------------------------------------------------------------------------

_TRACE_CAPABILITY_PROMPTS: dict[str, str] = {
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


def register_trace_capabilities(
    registry: CapabilityRegistry,
    *,
    llm_gateway: "LLMGateway | None" = None,
) -> None:
    """Register the five TRACE stage capability handlers into *registry*.

    This is the *sample* wiring for the S1-S5 TRACE pipeline.  Business agents
    with different stage topologies should register their own handlers instead.

    Args:
        registry: Capability registry to register into.
        llm_gateway: Optional LLM gateway.  Required in prod mode.
    """
    from hi_agent.capability.defaults import _make_llm_handler, _allow_heuristic_fallback

    if llm_gateway is None and not _allow_heuristic_fallback():
        raise RuntimeError(
            "register_trace_capabilities requires llm_gateway in prod mode. "
            "Set real LLM credentials or set HI_AGENT_ALLOW_HEURISTIC_FALLBACK=1."
        )
    if llm_gateway is None:
        logger.warning(
            "register_trace_capabilities: no llm_gateway provided; "
            "all TRACE capabilities will use heuristic-only execution in non-prod mode."
        )
    for name, system_prompt in _TRACE_CAPABILITY_PROMPTS.items():
        handler = _make_llm_handler(name, system_prompt, llm_gateway)
        registry.register(CapabilitySpec(name=name, handler=handler))
