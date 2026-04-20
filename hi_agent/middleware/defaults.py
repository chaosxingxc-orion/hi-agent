"""Factory for default middleware configuration."""

from __future__ import annotations

from typing import Any

from hi_agent.middleware.control import ControlMiddleware
from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.middleware.execution import ExecutionMiddleware
from hi_agent.middleware.orchestrator import MiddlewareOrchestrator
from hi_agent.middleware.perception import PerceptionMiddleware


def create_default_orchestrator(
    context_manager: Any | None = None,
    skill_loader: Any | None = None,
    knowledge_manager: Any | None = None,
    llm_gateway: Any | None = None,
    capability_invoker: Any | None = None,
    harness_executor: Any | None = None,
    retrieval_engine: Any | None = None,
    quality_threshold: float = 0.7,
    max_retries: int = 3,
    summary_threshold: int = 2000,
    max_entities: int = 50,
    max_plan_nodes: int = 20,
    llm_summarize_char_threshold: int = 500,
    summarize_temperature: float = 0.3,
    summarize_max_tokens: int = 200,
) -> MiddlewareOrchestrator:
    """Create orchestrator with all four default middlewares."""
    orchestrator = MiddlewareOrchestrator()

    orchestrator.register_middleware(
        "perception",
        PerceptionMiddleware(
            context_manager=context_manager,
            summary_threshold=summary_threshold,
            max_entities=max_entities,
            llm_gateway=llm_gateway,
            model_tier="light",
            llm_summarize_char_threshold=llm_summarize_char_threshold,
            summarize_temperature=summarize_temperature,
            summarize_max_tokens=summarize_max_tokens,
        ),
    )
    orchestrator.register_middleware(
        "control",
        ControlMiddleware(
            skill_loader=skill_loader,
            knowledge_manager=knowledge_manager,
            llm_gateway=llm_gateway,
            max_plan_nodes=max_plan_nodes,
            model_tier="medium",
        ),
    )
    orchestrator.register_middleware(
        "execution",
        ExecutionMiddleware(
            capability_invoker=capability_invoker,
            harness_executor=harness_executor,
            retrieval_engine=retrieval_engine,
            skill_loader=skill_loader,
            model_tier="medium",
        ),
    )
    orchestrator.register_middleware(
        "evaluation",
        EvaluationMiddleware(
            quality_threshold=quality_threshold,
            max_retries=max_retries,
            llm_gateway=llm_gateway,
            model_tier="light",
        ),
    )

    return orchestrator
