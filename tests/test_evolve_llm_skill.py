"""Tests for LLM-based skill extraction and Evolve->SkillRegistry wiring."""

from __future__ import annotations

import json

from hi_agent.evolve.contracts import RunPostmortem
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.skill_extractor import SkillExtractor
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage
from hi_agent.skill.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_postmortem(**overrides) -> RunPostmortem:
    defaults = {
        "run_id": "run-001",
        "task_id": "task-001",
        "task_family": "code_review",
        "outcome": "completed",
        "stages_completed": ["understand", "gather", "build", "synthesize"],
        "stages_failed": [],
        "branches_explored": 3,
        "branches_pruned": 0,
        "total_actions": 12,
        "failure_codes": [],
        "duration_seconds": 45.0,
        "quality_score": 0.85,
        "efficiency_score": 0.9,
        "trajectory_summary": "Reviewed code and produced summary",
    }
    defaults.update(overrides)
    return RunPostmortem(**defaults)


class MockLLMGateway:
    """A mock LLM gateway that returns a pre-configured response."""

    def __init__(self, content: str = "[]") -> None:
        self._content = content
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            content=self._content,
            model="mock-model",
            usage=TokenUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
        )

    def supports_model(self, model: str) -> bool:
        return True


class ErrorLLMGateway:
    """A mock LLM gateway that always raises."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM service unavailable")

    def supports_model(self, model: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Tests: LLM skill extraction
# ---------------------------------------------------------------------------

def test_llm_extract_returns_candidates():
    """LLM gateway returns valid JSON -> skill candidates produced."""
    llm_response = json.dumps([
        {
            "name": "CodeReviewPipeline",
            "description": "End-to-end code review pattern",
            "applicability": "code_review",
            "preconditions": ["has_source_code"],
        },
        {
            "name": "SummaryGenerator",
            "description": "Generate summaries from analysis",
            "applicability": "code_review",
            "preconditions": ["analysis_complete"],
        },
    ])
    gateway = MockLLMGateway(content=llm_response)
    extractor = SkillExtractor(gateway=gateway)
    pm = _make_postmortem()

    candidates = extractor.extract(pm)

    assert len(candidates) == 2
    assert candidates[0].name == "CodeReviewPipeline"
    assert candidates[0].description == "End-to-end code review pattern"
    assert candidates[0].applicability_scope == "code_review"
    assert candidates[0].preconditions == ["has_source_code"]
    assert candidates[0].confidence == 0.7
    assert candidates[0].source_run_ids == ["run-001"]
    assert candidates[1].name == "SummaryGenerator"
    # Verify LLM was actually called
    assert len(gateway.calls) == 1


def test_llm_extract_fallback_on_gateway_error():
    """When LLM gateway raises, fall back to heuristic extraction."""
    gateway = ErrorLLMGateway()
    extractor = SkillExtractor(gateway=gateway)
    pm = _make_postmortem()

    candidates = extractor.extract(pm)

    # Heuristics should produce candidates for this postmortem
    assert len(candidates) >= 1
    # Verify these are heuristic-style names
    names = [c.name for c in candidates]
    assert any("Pipeline:" in n or "EfficientExplore:" in n for n in names)


def test_llm_extract_fallback_on_unparseable_response():
    """When LLM returns non-JSON, fall back to heuristic extraction."""
    gateway = MockLLMGateway(content="This is not valid JSON at all.")
    extractor = SkillExtractor(gateway=gateway)
    pm = _make_postmortem()

    candidates = extractor.extract(pm)

    # Should fall back to heuristics
    assert len(candidates) >= 1
    names = [c.name for c in candidates]
    assert any("Pipeline:" in n or "EfficientExplore:" in n for n in names)


def test_llm_extract_fallback_on_empty_list():
    """When LLM returns empty list, fall back to heuristics."""
    gateway = MockLLMGateway(content="[]")
    extractor = SkillExtractor(gateway=gateway)
    pm = _make_postmortem()

    candidates = extractor.extract(pm)

    # Empty LLM result -> heuristic fallback
    assert len(candidates) >= 1


def test_no_gateway_uses_heuristics():
    """Without gateway, heuristic extraction is used directly."""
    extractor = SkillExtractor()
    pm = _make_postmortem()

    candidates = extractor.extract(pm)

    assert len(candidates) >= 1
    names = [c.name for c in candidates]
    assert any("Pipeline:" in n or "EfficientExplore:" in n for n in names)


# ---------------------------------------------------------------------------
# Tests: EvolveEngine auto-registration
# ---------------------------------------------------------------------------

def test_engine_auto_registers_candidates_in_registry():
    """EvolveEngine registers extracted candidates in SkillRegistry."""
    registry = SkillRegistry()
    engine = EvolveEngine(skill_registry=registry)
    pm = _make_postmortem()

    result = engine.on_run_completed(pm)

    # Engine should have found skill candidates
    assert result.metrics.skill_candidates_found >= 1

    # All candidates should be registered
    registered = registry.list_by_stage("candidate")
    assert len(registered) >= 1
    assert all(s.lifecycle_stage == "candidate" for s in registered)


def test_engine_without_registry_backward_compat():
    """EvolveEngine works fine without a skill registry (default None)."""
    engine = EvolveEngine()
    pm = _make_postmortem()

    result = engine.on_run_completed(pm)

    # Should still produce results without error
    assert result.metrics.skill_candidates_found >= 1
    assert len(result.changes) >= 1


def test_full_flow_postmortem_llm_extract_register_verify():
    """Full flow: postmortem -> LLM extract -> register -> verify in registry."""
    llm_response = json.dumps([
        {
            "name": "FullReviewSkill",
            "description": "Complete code review skill",
            "applicability": "code_review",
            "preconditions": ["repo_cloned", "diff_available"],
        },
    ])
    gateway = MockLLMGateway(content=llm_response)
    registry = SkillRegistry()
    extractor = SkillExtractor(gateway=gateway)
    engine = EvolveEngine(
        skill_extractor=extractor,
        skill_registry=registry,
    )

    pm = _make_postmortem()
    result = engine.on_run_completed(pm)

    # Verify LLM was called
    assert len(gateway.calls) == 1

    # Verify skill candidate appeared in result
    assert result.metrics.skill_candidates_found == 1
    skill_changes = [c for c in result.changes if c.change_type == "skill_candidate"]
    assert len(skill_changes) == 1
    assert "Complete code review skill" in skill_changes[0].description

    # Verify registered in registry
    registered = registry.list_by_stage("candidate")
    assert len(registered) == 1
    assert registered[0].name == "FullReviewSkill"
    assert registered[0].description == "Complete code review skill"
    assert registered[0].preconditions == ["repo_cloned", "diff_available"]
    assert "run-001" in registered[0].source_run_ids
