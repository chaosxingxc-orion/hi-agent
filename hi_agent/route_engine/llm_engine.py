"""LLM-backed route engine with strict structured parsing."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.llm.protocol import LLMGateway, LLMRequest
from hi_agent.route_engine.base import BranchProposal
from hi_agent.route_engine.llm_prompts import (
    build_context_aware_route_prompt,
    build_route_decision_prompt,
)


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
    """Generate route decisions via an injected LLM client.

    Supports two modes:

    1. **Gateway mode** — provide an :class:`LLMGateway` instance.  The engine
       builds a structured :class:`LLMRequest` with system/user messages and
       parses the JSON response.
    2. **Legacy callable mode** — provide a plain ``client(prompt) -> response``
       callable (backward-compatible with existing tests/code).

    If both *gateway* and *client* are ``None`` the engine is inert and
    :meth:`propose` will return an empty list (rule-based fallback expected
    from :class:`HybridRouteEngine`).
    """

    def __init__(
        self,
        client: Callable[[str], dict[str, Any] | str] | None = None,
        *,
        gateway: LLMGateway | None = None,
        context_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """Initialize engine with a callable or an LLMGateway (or both).

        Parameters
        ----------
        client:
            Legacy callable ``(prompt) -> dict | str``.
        gateway:
            Structured LLM gateway.  When provided, takes precedence over
            *client*.
        context_provider:
            Optional callable returning run context (stage summaries, fresh
            evidence, current stage state).  When set, routing decisions
            include this context in the LLM prompt.
        """
        self._client = client
        self._gateway = gateway
        self._context_provider = context_provider
        self.last_decision: LLMRouteDecision | None = None

    def set_context_provider(self, provider: Callable[[], dict] | None) -> None:
        """Update the context provider without accessing the private field directly."""
        self._context_provider = provider

    @property
    def context_provider(self) -> Callable[[], dict] | None:
        """Read the current context provider."""
        return self._context_provider

    # -- public API -----------------------------------------------------------

    def decide(
        self,
        *,
        stage_id: str,
        run_id: str,
        seq: int,
        context: dict[str, Any] | None = None,
    ) -> LLMRouteDecision:
        """Produce and validate a structured route decision.

        When a *context_provider* was supplied at init time, its output is
        merged into the prompt so the LLM sees stage summaries, fresh
        evidence, and current stage state.
        """
        # Enrich context from provider if available.
        rich_context: dict[str, Any] | None = None
        if self._context_provider is not None:
            rich_context = self._context_provider()

        if rich_context is not None:
            prompt = build_context_aware_route_prompt(
                stage_id=stage_id,
                run_id=run_id,
                seq=seq,
                stage_summaries=rich_context.get("stage_summaries", ""),
                fresh_evidence=rich_context.get("fresh_evidence", ""),
                current_stage_state=rich_context.get("current_stage_state", ""),
                allowed_next_stages=rich_context.get("allowed_next_stages"),
            )
        else:
            prompt = build_route_decision_prompt(
                stage_id=stage_id,
                run_id=run_id,
                seq=seq,
                context=context,
            )

        if self._gateway is not None:
            raw = self._call_gateway(prompt, stage_id=stage_id, run_id=run_id, seq=seq)
        elif self._client is not None:
            raw = self._client(prompt)
        else:
            raise LLMRouteParseError("LLMRouteEngine has no gateway and no client; cannot decide")

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
        """Create a branch proposal from an LLM decision.

        Returns an empty list when no gateway/client is configured so that
        callers (e.g. :class:`HybridRouteEngine`) can fall back to rules.
        """
        if self._gateway is None and self._client is None:
            return []

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

    # -- gateway helper -------------------------------------------------------

    def _call_gateway(
        self,
        prompt: str,
        *,
        stage_id: str,
        run_id: str,
        seq: int,
    ) -> str:
        """Build an :class:`LLMRequest` and call the gateway."""
        system_message = (
            "You are a route decision engine for the TRACE framework. "
            "Given the current stage, run context, and sequence number, "
            "decide what the next stage should be. "
            "Return a JSON object with keys: next_stage, confidence, rationale, action_kind. "
            "confidence must be a float in [0,1]."
        )
        request = LLMRequest(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            model="default",
            temperature=0.3,
            max_tokens=1024,
            metadata={
                "run_id": run_id,
                "stage_id": stage_id,
                "seq": seq,
                "purpose": "route_decision",
            },
        )
        response = self._gateway.complete(request)  # type: ignore[union-attr]  expiry_wave: permanent
        return response.content

    def _parse_payload(self, raw: Any) -> dict[str, Any]:
        """Run _parse_payload."""
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
        """Run _validate_payload."""
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
