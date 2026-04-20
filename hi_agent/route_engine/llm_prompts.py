"""Prompt templates for LLM-based routing decisions."""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Context-aware routing prompt template
# ---------------------------------------------------------------------------

CONTEXT_AWARE_ROUTE_PROMPT = """\
You are a route decision engine for the TRACE framework.

## Current Run State
run_id: {run_id}
current_stage: {stage_id}
sequence: {seq}

## Completed Stage Summaries
{stage_summaries}

## Current Stage State
{current_stage_state}

## Fresh Evidence (since last compression)
{fresh_evidence}

## Available Transitions
{allowed_next_stages}

Based on the evidence gathered so far and the current stage, propose the best next action.

Return JSON:
{{"next_stage": "...", "confidence": 0.0-1.0, "rationale": "...", "action_kind": "..."}}\
"""


# ---------------------------------------------------------------------------
# Basic routing prompts
# ---------------------------------------------------------------------------


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
    return (
        build_route_prompt(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
            allowed_next_stages=None,
        )
        + f"\ncontext={json.dumps(context or {}, ensure_ascii=False, sort_keys=True)}"
    )


def build_context_aware_route_prompt(
    *,
    stage_id: str,
    run_id: str,
    seq: int,
    stage_summaries: str = "",
    fresh_evidence: str = "",
    current_stage_state: str = "",
    allowed_next_stages: list[str] | None = None,
) -> str:
    """Build a context-aware routing prompt with stage summaries and evidence.

    Parameters
    ----------
    stage_id:
        Current stage identifier.
    run_id:
        Run identifier.
    seq:
        Decision sequence number.
    stage_summaries:
        Formatted summaries of completed stages (L1).
    fresh_evidence:
        Evidence gathered since last compact boundary.
    current_stage_state:
        Current stage status description.
    allowed_next_stages:
        List of valid next-stage identifiers.
    """
    if not stage_id.strip():
        raise ValueError("stage_id must be a non-empty string")
    if not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if seq < 0:
        raise ValueError("seq must be >= 0")

    allowed = ", ".join(allowed_next_stages or [])

    return CONTEXT_AWARE_ROUTE_PROMPT.format(
        run_id=run_id.strip(),
        stage_id=stage_id.strip(),
        seq=seq,
        stage_summaries=stage_summaries or "(none)",
        fresh_evidence=fresh_evidence or "(none)",
        current_stage_state=current_stage_state or "(none)",
        allowed_next_stages=allowed or "(none)",
    )
