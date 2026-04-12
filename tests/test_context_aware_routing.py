"""Tests for context-aware LLM routing and auto-compression triggers."""

from __future__ import annotations

import json

import pytest

from tests.helpers.llm_gateway_fixture import MockLLMGateway
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord
from hi_agent.route_engine.llm_engine import LLMRouteEngine
from hi_agent.route_engine.llm_prompts import (
    CONTEXT_AWARE_ROUTE_PROMPT,
    build_context_aware_route_prompt,
)
from hi_agent.task_view.auto_compress import AutoCompressTrigger


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_route_json(
    next_stage: str = "S3_build",
    confidence: float = 0.85,
    rationale: str = "Evidence supports building.",
    action_kind: str = "build_draft",
) -> str:
    return json.dumps({
        "next_stage": next_stage,
        "confidence": confidence,
        "rationale": rationale,
        "action_kind": action_kind,
    })


def _sample_context() -> dict:
    return {
        "stage_summaries": "S1 Understand: succeeded\nS2 Gather: succeeded",
        "fresh_evidence": "Found API docs. Verified schema.",
        "current_stage_state": "S3_build: in_progress",
        "allowed_next_stages": ["S4_synthesize", "S5_review"],
    }


def _make_records(n: int) -> list[dict]:
    """Generate *n* dummy evidence records."""
    return [
        {
            "event_type": "StageStateChanged",
            "payload": {"stage_id": f"S{i}", "to_state": "completed"},
            "tags": [],
        }
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# 1. LLMRouteEngine with context_provider sends context to LLM
# --------------------------------------------------------------------------- #


class TestLLMRouteEngineContextAware:
    """Verify that context_provider enriches the LLM prompt."""

    def test_context_provider_sends_context_to_llm(self):
        """When context_provider is set, the prompt includes stage summaries."""
        gw = MockLLMGateway(default_response=_make_route_json())
        ctx = _sample_context()

        engine = LLMRouteEngine(
            gateway=gw,
            context_provider=lambda: ctx,
        )

        decision = engine.decide(stage_id="S3_build", run_id="run-1", seq=2)

        assert decision.next_stage == "S3_build"
        # Inspect prompt sent to gateway.
        last_req = gw.last_request
        assert last_req is not None
        user_msg = last_req.messages[-1]["content"]
        assert "S1 Understand: succeeded" in user_msg
        assert "Found API docs" in user_msg
        assert "S3_build: in_progress" in user_msg

    def test_context_includes_stage_summaries_and_evidence(self):
        """Stage summaries and fresh evidence appear in the user prompt."""
        gw = MockLLMGateway(default_response=_make_route_json())

        engine = LLMRouteEngine(
            gateway=gw,
            context_provider=lambda: {
                "stage_summaries": "S1: done\nS2: done",
                "fresh_evidence": "New data found",
                "current_stage_state": "active",
            },
        )

        engine.decide(stage_id="S3_build", run_id="run-1", seq=3)
        user_msg = gw.last_request.messages[-1]["content"]

        assert "S1: done" in user_msg
        assert "New data found" in user_msg
        assert "Completed Stage Summaries" in user_msg
        assert "Fresh Evidence" in user_msg

    def test_no_context_provider_backward_compat(self):
        """Without context_provider, engine uses the basic prompt."""
        gw = MockLLMGateway(default_response=_make_route_json())

        engine = LLMRouteEngine(gateway=gw)

        decision = engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)
        assert decision.next_stage == "S3_build"

        user_msg = gw.last_request.messages[-1]["content"]
        # Basic prompt uses the old format.
        assert "current_stage=S2_gather" in user_msg
        assert "Completed Stage Summaries" not in user_msg

    def test_propose_with_context_provider(self):
        """propose() also benefits from context_provider."""
        gw = MockLLMGateway(default_response=_make_route_json())
        ctx = _sample_context()

        engine = LLMRouteEngine(
            gateway=gw,
            context_provider=lambda: ctx,
        )

        proposals = engine.propose("S3_build", "run-1", 2)
        assert len(proposals) == 1
        assert "0.85" in proposals[0].rationale

        user_msg = gw.last_request.messages[-1]["content"]
        assert "S1 Understand: succeeded" in user_msg

    def test_legacy_client_with_context_provider(self):
        """context_provider works with legacy callable client too."""
        captured_prompts: list[str] = []

        def mock_client(prompt: str) -> str:
            captured_prompts.append(prompt)
            return _make_route_json()

        engine = LLMRouteEngine(
            client=mock_client,
            context_provider=lambda: _sample_context(),
        )

        decision = engine.decide(stage_id="S3_build", run_id="run-1", seq=2)
        assert decision.next_stage == "S3_build"
        assert "S1 Understand: succeeded" in captured_prompts[0]


# --------------------------------------------------------------------------- #
# 2. AutoCompressTrigger tests
# --------------------------------------------------------------------------- #


class TestAutoCompressTriggerShouldCompress:
    """Test should_compress returns correct level."""

    def test_none_for_small_records(self):
        trigger = AutoCompressTrigger(snip_threshold=50, window_threshold=6000)
        records = _make_records(5)
        assert trigger.should_compress(records) == "none"

    def test_snip_when_records_exceed_threshold(self):
        trigger = AutoCompressTrigger(snip_threshold=10)
        records = _make_records(20)
        assert trigger.should_compress(records) == "snip"

    def test_window_when_tokens_exceed_window_threshold(self):
        """Many records with high token count but below compress trigger."""
        trigger = AutoCompressTrigger(
            snip_threshold=500,
            window_threshold=100,
            compress_threshold=50,
        )
        # Each record is ~20 tokens, 10 records = ~200 tokens > 100.
        records = _make_records(10)
        # Without compressor, compress level is only if budget exceeded.
        level = trigger.should_compress(records, budget_tokens=100000)
        # With compressor=None but compress_threshold=50 < total,
        # should still be "compress" if compressor is set.
        # Without compressor, falls to "window".
        assert level in ("window", "compress")

    def test_compress_when_compressor_available_and_threshold_exceeded(self):
        """Compress level when compressor is set and threshold exceeded."""
        compressor = MemoryCompressor()  # Dummy, no LLM needed for detection.
        trigger = AutoCompressTrigger(
            snip_threshold=500,
            window_threshold=10,
            compress_threshold=10,
            compressor=compressor,
        )
        records = _make_records(10)
        level = trigger.should_compress(records, budget_tokens=100000)
        assert level == "compress"


class TestAutoCompressTriggerCheckAndCompress:
    """Test check_and_compress behavior."""

    def test_no_compression_needed(self):
        trigger = AutoCompressTrigger(snip_threshold=50, window_threshold=6000)
        records = _make_records(3)
        filtered, summary = trigger.check_and_compress(records, "S1")
        assert filtered == records
        assert summary is None

    def test_snips_old_records(self):
        trigger = AutoCompressTrigger(snip_threshold=5)
        records = _make_records(20)
        filtered, summary = trigger.check_and_compress(
            records, "S1", budget_tokens=100000
        )
        assert len(filtered) <= 5
        # Should keep most recent.
        assert filtered[-1] == records[-1]

    def test_triggers_llm_compression_when_threshold_exceeded(self):
        """When compressor is available and threshold exceeded, get summary."""
        compressor = MemoryCompressor()  # Uses direct path (no LLM).
        trigger = AutoCompressTrigger(
            snip_threshold=500,
            window_threshold=10,
            compress_threshold=10,
            compressor=compressor,
        )
        records = _make_records(15)
        filtered, summary = trigger.check_and_compress(
            records, "S2", budget_tokens=100000
        )
        # Summary should be produced.
        assert summary is not None
        assert "stage_id" in summary

    def test_window_truncates_to_budget(self):
        """Records get truncated to fit token budget."""
        trigger = AutoCompressTrigger(
            snip_threshold=500,
            window_threshold=10,
            compress_threshold=999999,
        )
        records = _make_records(50)
        filtered, summary = trigger.check_and_compress(
            records, "S1", budget_tokens=50
        )
        # Filtered should have fewer records than original.
        assert len(filtered) < len(records)


# --------------------------------------------------------------------------- #
# 3. CONTEXT_AWARE_ROUTE_PROMPT formatting
# --------------------------------------------------------------------------- #


class TestContextAwareRoutePrompt:
    """Test prompt template and builder."""

    def test_template_has_required_placeholders(self):
        assert "{run_id}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{stage_id}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{seq}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{stage_summaries}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{fresh_evidence}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{current_stage_state}" in CONTEXT_AWARE_ROUTE_PROMPT
        assert "{allowed_next_stages}" in CONTEXT_AWARE_ROUTE_PROMPT

    def test_build_context_aware_prompt_formatting(self):
        prompt = build_context_aware_route_prompt(
            stage_id="S3_build",
            run_id="run-42",
            seq=5,
            stage_summaries="S1: succeeded\nS2: succeeded",
            fresh_evidence="Found three API endpoints.",
            current_stage_state="building draft",
            allowed_next_stages=["S4_synthesize", "S5_review"],
        )

        assert "run_id: run-42" in prompt
        assert "current_stage: S3_build" in prompt
        assert "sequence: 5" in prompt
        assert "S1: succeeded" in prompt
        assert "Found three API endpoints." in prompt
        assert "building draft" in prompt
        assert "S4_synthesize, S5_review" in prompt
        assert "Return JSON" in prompt

    def test_build_context_aware_prompt_defaults(self):
        """Empty optional fields produce '(none)' placeholders."""
        prompt = build_context_aware_route_prompt(
            stage_id="S1",
            run_id="run-1",
            seq=0,
        )
        assert "(none)" in prompt

    def test_build_context_aware_prompt_validation(self):
        with pytest.raises(ValueError, match="stage_id"):
            build_context_aware_route_prompt(stage_id="  ", run_id="run-1", seq=0)
        with pytest.raises(ValueError, match="run_id"):
            build_context_aware_route_prompt(stage_id="S1", run_id="  ", seq=0)
        with pytest.raises(ValueError, match="seq"):
            build_context_aware_route_prompt(stage_id="S1", run_id="run-1", seq=-1)
