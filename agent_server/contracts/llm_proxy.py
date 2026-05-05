"""LLM gateway proxy contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.llm_proxy")


@dataclass(frozen=True)
class LLMRequest:
    """Request routed through the posture-aware LLM gateway."""

    tenant_id: str
    run_id: str
    messages: tuple[dict[str, Any], ...]  # [{role, content}, ...]
    model_hint: str = ""  # advisory; gateway may override
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness.

        ``messages`` is a tuple — empty tuple is falsy and counts as
        missing under research/prod posture.
        """
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not self.messages:
            missing.append("messages")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"LLMRequest constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "llm_request_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not self.content:
            missing.append("content")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"LLMResponse constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "llm_response_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
