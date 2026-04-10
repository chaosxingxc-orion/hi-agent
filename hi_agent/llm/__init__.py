"""LLM Gateway module -- provider-decoupled LLM access for hi-agent."""

from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway
from hi_agent.llm.budget_tracker import LLMBudgetTracker
from hi_agent.llm.errors import (
    LLMBudgetExhaustedError,
    LLMError,
    LLMProviderError,
    LLMTimeoutError,
)
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.mock_gateway import MockLLMGateway
from hi_agent.llm.model_selector import ModelSelector, SelectionResult
from hi_agent.llm.protocol import AsyncLLMGateway, LLMGateway, LLMRequest, LLMResponse, TokenUsage
from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel
from hi_agent.llm.router import ModelRouter
from hi_agent.llm.tier_router import TierMapping, TierRouter

__all__ = [
    "AnthropicLLMGateway",
    "AsyncLLMGateway",
    "HttpLLMGateway",
    "LLMBudgetExhaustedError",
    "LLMBudgetTracker",
    "LLMError",
    "LLMGateway",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "MockLLMGateway",
    "ModelRegistry",
    "ModelRouter",
    "ModelSelector",
    "ModelTier",
    "RegisteredModel",
    "SelectionResult",
    "TierMapping",
    "TierRouter",
    "TokenUsage",
]
