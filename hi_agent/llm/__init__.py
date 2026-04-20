"""LLM Gateway module -- provider-decoupled LLM access for hi-agent."""

from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway
from hi_agent.llm.budget_tracker import LLMBudgetTracker
from hi_agent.llm.cache import (
    CacheAwareTokenUsage,
    PromptCacheConfig,
    PromptCacheInjector,
    PromptCacheStats,
    parse_cache_usage,
)
from hi_agent.llm.errors import (
    LLMBudgetExhaustedError,
    LLMError,
    LLMProviderError,
    LLMTimeoutError,
)
from hi_agent.llm.failover import (
    CredentialEntry,
    CredentialPool,
    FailoverChain,
    FailoverError,
    FailoverReason,
    RetryPolicy,
    classify_http_error,
    make_credential_pool_from_env,
)
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.model_selector import ModelSelector, SelectionResult
from hi_agent.llm.protocol import AsyncLLMGateway, LLMGateway, LLMRequest, LLMResponse, TokenUsage
from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel
from hi_agent.llm.router import ModelRouter
from hi_agent.llm.streaming import (
    AsyncStreamingLLMGateway,
    HTTPStreamingGateway,
    SseParser,
    StreamDelta,
    StreamDeltaType,
)
from hi_agent.llm.tier_presets import apply_research_defaults
from hi_agent.llm.tier_router import TierAwareLLMGateway, TierMapping, TierRouter

__all__ = [
    # Core protocols & types
    "AnthropicLLMGateway",
    "AsyncLLMGateway",
    # Streaming (Track A)
    "AsyncStreamingLLMGateway",
    # Prompt caching (Track C)
    "CacheAwareTokenUsage",
    # Failover (Track B)
    "CredentialEntry",
    "CredentialPool",
    "FailoverChain",
    "FailoverError",
    "FailoverReason",
    "HTTPStreamingGateway",
    "HttpLLMGateway",
    "LLMBudgetExhaustedError",
    "LLMBudgetTracker",
    "LLMError",
    "LLMGateway",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "ModelRegistry",
    "ModelRouter",
    "ModelSelector",
    "ModelTier",
    "PromptCacheConfig",
    "PromptCacheInjector",
    "PromptCacheStats",
    "RegisteredModel",
    "RetryPolicy",
    "SelectionResult",
    "SseParser",
    "StreamDelta",
    "StreamDeltaType",
    "TierAwareLLMGateway",
    "TierMapping",
    "TierRouter",
    "TokenUsage",
    "apply_research_defaults",
    "classify_http_error",
    "make_credential_pool_from_env",
    "parse_cache_usage",
]
