"""LLM-backed route engine with strict structured parsing."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.llm_prompts import build_route_decision_prompt


class LLMRouteParseError(ValueError):
    """Raised when LLM route output violates the structured contract."""


@dataclass(frozen=True)
class LLMRouteDecision:
    """Structured route decision returned by the LLM."""

    next_stage: str
    confidence: float
    rationale: str
    action_kind: str


class LLMRouteEngine:
    """Generate route decisions via an injected LLM client."""

    def __init__(self, client: Callable[[str], dict[str, Any] | str]) -> None:
        """Initialize engine with a callable ``client(prompt) -> response``."""
        self._client = client
        self.last_decision: LLMRouteDecision | None = None

    def decide(
        self,
        *,
        stage_id: str,
        run_id: str,
        seq: int,
        context: dict[str, Any] | None = None,
    ) -> LLMRouteDecision:
        """Produce and validate a structured route decision."""
        prompt = build_route_decision_prompt(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
            context=context,
        )
        raw = self._client(prompt)
        payload = self._parse_payload(raw)
        decision = self._validate_payload(payload)
        self.last_decision = decision
        return decision

    def propose(
        self,
        stage_id: str,
        run_id: str,
        seq: int,
        *,
        context: dict[str, Any] | None = None,
    ) -> list[BranchProposal]:
        """Create a branch proposal from an LLM decision."""
        decision = self.decide(
            stage_id=stage_id,
            run_id=run_id,
            seq=seq,
            context=context,
        )
        branch_id = deterministic_id(run_id, stage_id, str(seq), "llm")
        rationale = f"llm(conf={decision.confidence:.2f}): {decision.rationale}"
        return [
            BranchProposal(
                branch_id=branch_id,
                rationale=rationale,
                action_kind=decision.action_kind,
            )
        ]

    def _parse_payload(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LLMRouteParseError("llm output is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise LLMRouteParseError("llm output must decode to a JSON object")
            return payload
        raise LLMRouteParseError("llm output must be dict or JSON string")

    def _validate_payload(self, payload: dict[str, Any]) -> LLMRouteDecision:
        next_stage = payload.get("next_stage")
        confidence = payload.get("confidence")
        rationale = payload.get("rationale")

        if not isinstance(next_stage, str) or next_stage.strip() == "":
            raise LLMRouteParseError("field `next_stage` must be a non-empty string")
        if not isinstance(confidence, int | float):
            raise LLMRouteParseError("field `confidence` must be numeric")
        confidence_f = float(confidence)
        if confidence_f < 0.0 or confidence_f > 1.0:
            raise LLMRouteParseError("field `confidence` must be in [0, 1]")
        if not isinstance(rationale, str) or rationale.strip() == "":
            raise LLMRouteParseError("field `rationale` must be a non-empty string")

        action_kind = payload.get("action_kind", next_stage)
        if not isinstance(action_kind, str) or action_kind.strip() == "":
            raise LLMRouteParseError("field `action_kind` must be a non-empty string")

        return LLMRouteDecision(
            next_stage=next_stage.strip(),
            confidence=confidence_f,
            rationale=rationale.strip(),
            action_kind=action_kind.strip(),
        )

