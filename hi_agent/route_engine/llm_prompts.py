"""Prompt templates for LLM-based routing decisions."""

from __future__ import annotations

import json
from typing import Any


def build_route_prompt(
    *,
    stage_id: str,
    run_id: str,
    seq: int,
    allowed_next_stages: list[str] | None = None,
) -> str:
    """Build structured prompt expected by :class:`LLMRouteEngine`.

    The response contract intentionally asks for strict JSON fields:
    `next_stage`, `confidence`, `rationale`, and optional `action_kind`.
    """
    if not stage_id.strip():
        raise ValueError("stage_id must be a non-empty string")
    if not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if seq < 0:
        raise ValueError("seq must be >= 0")

    allowed = ", ".join(allowed_next_stages or [])
    return (
        "You are a route decision engine.\n"
        f"run_id={run_id.strip()}\n"
        f"current_stage={stage_id.strip()}\n"
        f"sequence={seq}\n"
        f"allowed_next_stages={allowed}\n"
        "Return JSON object with keys: next_stage, confidence, rationale, action_kind.\n"
        "confidence must be a float in [0,1]."
    )


def build_route_decision_prompt(
    *,
    stage_id: str,
    run_id: str,
    seq: int,
    context: dict[str, Any] | None = None,
) -> str:
    """Backward-compatible strict JSON prompt used by ``LLMRouteEngine``."""
    return build_route_prompt(
        stage_id=stage_id,
        run_id=run_id,
        seq=seq,
        allowed_next_stages=None,
    ) + f"\ncontext={json.dumps(context or {}, ensure_ascii=False, sort_keys=True)}"
