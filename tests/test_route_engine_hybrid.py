"""Tests for prompt/LLM/hybrid route engine behavior."""

from __future__ import annotations

import json

import pytest
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.route_engine.llm_engine import LLMRouteEngine, LLMRouteParseError
from hi_agent.route_engine.llm_prompts import build_route_decision_prompt
from hi_agent.route_engine.rule_engine import RuleRouteEngine


def test_build_route_decision_prompt_contains_required_fields() -> None:
    """Prompt should pin the strict JSON schema and input envelope."""
    prompt = build_route_decision_prompt(
        stage_id="S2_gather",
        run_id="run-1",
        seq=9,
        context={"k": "v"},
    )
    assert "next_stage" in prompt
    assert "confidence" in prompt
    assert "rationale" in prompt
    assert "S2_gather" in prompt
    assert "run-1" in prompt


def test_llm_route_engine_parses_json_string_response() -> None:
    """Engine should parse and validate a JSON-string payload."""

    def fake_client(_: str) -> str:
        return json.dumps(
            {
                "next_stage": "build_draft",
                "confidence": 0.82,
                "rationale": "Need to draft the main artifact.",
            }
        )

    engine = LLMRouteEngine(fake_client)
    decision = engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)

    assert decision.next_stage == "build_draft"
    assert decision.confidence == pytest.approx(0.82)
    assert decision.rationale == "Need to draft the main artifact."


def test_llm_route_engine_rejects_malformed_payload() -> None:
    """Engine should fail loudly when required fields are missing."""

    def fake_client(_: str) -> dict[str, object]:
        return {"confidence": 0.5, "rationale": "missing next stage"}

    engine = LLMRouteEngine(fake_client)

    with pytest.raises(LLMRouteParseError):
        engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)


def test_hybrid_route_prefers_rule_when_confident() -> None:
    """Known stage should stay on deterministic rule path."""

    def fake_client(_: str) -> dict[str, object]:
        raise AssertionError("LLM should not be called for confident rule route")

    hybrid = HybridRouteEngine(
        rule_engine=RuleRouteEngine(),
        llm_engine=LLMRouteEngine(fake_client),
        confidence_threshold=0.7,
    )

    result = hybrid.propose_with_provenance(stage_id="S2_gather", run_id="run-1", seq=2)
    assert result.source == "rule"
    assert result.confidence == pytest.approx(1.0)
    assert result.proposals[0].action_kind == "search_evidence"


def test_hybrid_route_falls_back_to_llm_when_rule_unknown() -> None:
    """Unknown stage should fallback to the LLM path."""

    def fake_client(_: str) -> dict[str, object]:
        return {
            "next_stage": "evaluate_acceptance",
            "confidence": 0.76,
            "rationale": "No deterministic mapping for this stage.",
        }

    hybrid = HybridRouteEngine(
        rule_engine=RuleRouteEngine(),
        llm_engine=LLMRouteEngine(fake_client),
        confidence_threshold=0.7,
    )

    result = hybrid.propose_with_provenance(stage_id="SX_unknown", run_id="run-2", seq=3)
    assert result.source == "llm"
    assert result.confidence == pytest.approx(0.76)
    assert result.proposals[0].action_kind == "evaluate_acceptance"
    assert result.proposals[0].rationale.startswith("llm(conf=0.76)")

