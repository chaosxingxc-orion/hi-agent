"""LLM gateway proxy contract types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMRequest:
    """Request routed through the posture-aware LLM gateway."""

    tenant_id: str
    run_id: str
    messages: tuple[dict[str, Any], ...]  # [{role, content}, ...]
    model_hint: str = ""  # advisory; gateway may override
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass(frozen=True)
class LLMResponse:
    """Response from the LLM gateway."""

    tenant_id: str
    run_id: str
    content: str
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    fallback_used: bool = False
    cost_usd: float = 0.0
