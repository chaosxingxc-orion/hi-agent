"""Tests for async LLM integration: protocol, HTTPGateway, compressor, runner cost tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from hi_agent.llm.protocol import (
    AsyncLLMGateway,
    LLMGateway,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)
from hi_agent.memory.async_compressor import AsyncMemoryCompressor, CompressionResult


# ---------------------------------------------------------------------------
# Mock async gateway
# ---------------------------------------------------------------------------

class MockAsyncGateway:
    """Simple mock that satisfies AsyncLLMGateway protocol."""

    def __init__(self, response_content: str = "test response") -> None:
        self._response_content = response_content
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            content=self._response_content,
            model="mock-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def supports_model(self, model: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# 1. AsyncLLMGateway protocol shape
# ---------------------------------------------------------------------------

def test_async_llm_gateway_protocol():
    """AsyncLLMGateway protocol should define complete() and supports_model()."""
    # Verify protocol has the expected methods
    assert hasattr(AsyncLLMGateway, "complete")
    assert hasattr(AsyncLLMGateway, "supports_model")

    # Verify a mock gateway structurally matches the protocol
    gw = MockAsyncGateway()
    assert hasattr(gw, "complete")
    assert hasattr(gw, "supports_model")
    assert gw.supports_model("anything")


# ---------------------------------------------------------------------------
# 2. HTTPGateway.complete() with mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_gateway_complete(monkeypatch):
    """HTTPGateway.complete() should build payload and parse response."""
    from hi_agent.llm.http_gateway import HTTPGateway

    gateway = HTTPGateway(
        base_url="http://test.local",
        api_key="test-key",
        default_model="gpt-4o",
    )

    mock_raw = {
        "choices": [
            {
                "message": {"content": "Hello from mock"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
        "model": "gpt-4o",
    }

    class MockHTTPResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return mock_raw

    async def mock_post(url, json=None, **kwargs):
        return MockHTTPResponse()

    monkeypatch.setattr(gateway._client, "post", mock_post)

    request = LLMRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="default",
    )
    response = await gateway.complete(request)

    assert response.content == "Hello from mock"
    assert response.model == "gpt-4o"
    assert response.usage.prompt_tokens == 20
    assert response.usage.completion_tokens == 10

    await gateway.aclose()


# ---------------------------------------------------------------------------
# 3. HTTPGateway.supports_model()
# ---------------------------------------------------------------------------

def test_http_gateway_supports_model():
    """HTTPGateway.supports_model() should return True for any model."""
    from hi_agent.llm.http_gateway import HTTPGateway

    gateway = HTTPGateway(base_url="http://test.local", api_key="k")
    assert gateway.supports_model("gpt-4o") is True
    assert gateway.supports_model("claude-opus-4") is True
    assert gateway.supports_model("some-random-model") is True


# ---------------------------------------------------------------------------
# 4. AsyncMemoryCompressor with gateway
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_compressor_with_gateway():
    """Compressor should use StructuredCompressor when gateway supports async calls.

    The mock gateway returns plain text (not valid JSON), so StructuredCompressor's
    LLM parse step falls back to a minimal structured summary.  The resulting
    CompressionResult.summary should be a [CONTEXT COMPACTION ...] block.
    """
    gw = MockAsyncGateway(response_content="Compressed summary of events.")
    compressor = AsyncMemoryCompressor(gateway=gw, model="mock-model")

    records = [
        {"event_type": "action", "payload": "Searched database"},
        {"event_type": "observation", "payload": "Found 5 results"},
    ]
    result = await compressor.compress(records, context="stage-1")

    assert isinstance(result, CompressionResult)
    # Structured compression produces a formatted context block, not raw LLM text.
    assert "[CONTEXT COMPACTION" in result.summary
    assert "[END COMPACTION" in result.summary
    assert result.input_tokens > 0
    assert result.compression_ratio > 0
    # With only 3 messages (1 system + 2 user), all fit in the head section so
    # StructuredCompressor falls back to a minimal summary without calling the LLM.
    # The gateway may have 0 calls for small record sets.


# ---------------------------------------------------------------------------
# 5. AsyncMemoryCompressor without gateway (fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_compressor_without_gateway():
    """Compressor should fall back to string concat without a gateway."""
    compressor = AsyncMemoryCompressor(gateway=None)

    records = [
        {"event_type": "action", "payload": "Step A"},
        {"event_type": "result", "payload": "Step B"},
    ]
    result = await compressor.compress(records)

    assert "[action] Step A" in result.summary
    assert "[result] Step B" in result.summary
    assert ";" in result.summary  # joined by "; "
    assert result.compression_ratio > 0


# ---------------------------------------------------------------------------
# 6. AsyncMemoryCompressor with empty records
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_compressor_empty_records():
    """Empty records should return an empty summary with ratio 1.0."""
    compressor = AsyncMemoryCompressor()
    result = await compressor.compress([])

    assert result.summary == ""
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.compression_ratio == 1.0


# ---------------------------------------------------------------------------
# 7. Runner._track_llm_cost
# ---------------------------------------------------------------------------

def test_runner_track_llm_cost():
    """_track_llm_cost should record cost to session."""
    from hi_agent.contracts import TaskContract
    from hi_agent.runner import RunExecutor

    from hi_agent.runtime_adapter.mock_kernel import MockKernel

    contract = TaskContract(task_id="t-001", goal="test goal")
    kernel = MockKernel()
    executor = RunExecutor(contract=contract, kernel=kernel)

    # Manually wire up session and cost calculator
    mock_session = MagicMock()
    mock_session.task_contract = contract
    executor.session = mock_session

    from hi_agent.session.cost_tracker import CostCalculator

    executor._cost_calculator = CostCalculator()

    # Build a fake response with usage
    @dataclass
    class FakeUsage:
        prompt_tokens: int = 100
        completion_tokens: int = 50

    @dataclass
    class FakeResponse:
        model: str = "gpt-4o"
        usage: Any = None

    resp = FakeResponse(model="gpt-4o", usage=FakeUsage())
    executor._track_llm_cost(resp)

    assert mock_session.record_llm_call.called
    call_args = mock_session.record_llm_call.call_args
    record = call_args[0][0]
    assert record.model == "gpt-4o"
    assert record.input_tokens == 100
    assert record.output_tokens == 50
    assert record.cost_usd > 0


# ---------------------------------------------------------------------------
# 8. HybridRouteEngine with gateway (LLM fallback)
# ---------------------------------------------------------------------------

def test_hybrid_engine_with_gateway():
    """HybridRouteEngine should fall through to LLM when rules are weak."""
    import json

    from hi_agent.llm.mock_gateway import MockLLMGateway
    from hi_agent.route_engine.hybrid_engine import HybridRouteEngine

    # MockLLMGateway returns plain text by default; LLMRouteEngine expects JSON.
    mock_decision = json.dumps({
        "next_stage": "S2",
        "confidence": 0.85,
        "rationale": "Proceeding to analysis",
        "action_kind": "analyze",
    })
    gateway = MockLLMGateway(default_response=mock_decision)
    engine = HybridRouteEngine(gateway=gateway)

    proposals = engine.propose(
        stage_id="S1",
        run_id="run-001",
        seq=0,
    )

    # Rule engine should return "unknown" → confidence 0 → LLM fallback
    assert len(proposals) >= 1
    assert "llm" in proposals[0].rationale.lower()
