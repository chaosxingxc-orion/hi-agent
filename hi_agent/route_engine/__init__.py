"""Route engine package."""

from hi_agent.route_engine.acceptance import AcceptancePolicy, AcceptanceResult
from hi_agent.route_engine.base import BranchProposal, RouteEngine
from hi_agent.route_engine.capability_filter import (
    NON_CAPABILITY_ACTIONS,
    filter_proposal,
)
from hi_agent.route_engine.conditional_router import (
    ConditionalRoute,
    ConditionalRouter,
    RouteContext,
    RouteExplanation,
)
from hi_agent.route_engine.confidence_policy import should_escalate_route_decision
from hi_agent.route_engine.decision_audit import is_low_confidence, record_route_decision_audit
from hi_agent.route_engine.decision_audit_store import InMemoryDecisionAuditStore
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine, HybridRouteOutcome
from hi_agent.route_engine.llm_engine import LLMRouteDecision, LLMRouteEngine, LLMRouteParseError
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.route_engine.skill_aware_engine import SkillAwareRouteEngine

__all__ = [
    "AcceptancePolicy",
    "AcceptanceResult",
    "BranchProposal",
    "ConditionalRoute",
    "ConditionalRouter",
    "HybridRouteEngine",
    "HybridRouteOutcome",
    "InMemoryDecisionAuditStore",
    "LLMRouteDecision",
    "LLMRouteEngine",
    "LLMRouteParseError",
    "NON_CAPABILITY_ACTIONS",
    "RouteContext",
    "RouteEngine",
    "RouteExplanation",
    "RuleRouteEngine",
    "SkillAwareRouteEngine",
    "filter_proposal",
    "is_low_confidence",
    "record_route_decision_audit",
    "should_escalate_route_decision",
]
