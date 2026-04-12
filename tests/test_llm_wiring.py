"""Tests for LLM Gateway wiring into RouteEngine and MemoryCompressor."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.helpers.llm_gateway_fixture import MockLLMGateway
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.route_engine.llm_engine import LLMRouteEngine, LLMRouteParseError
from hi_agent.route_engine.rule_engine import RuleRouteEngine


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_route_response(
    next_stage: str = "S3_build",
    confidence: float = 0.85,
    rationale: str = "LLM decided to build.",
    action_kind: str = "build_draft",
) -> str:
    return json.dumps(
        {
            "next_stage": next_stage,
            "confidence": confidence,
            "rationale": rationale,
            "action_kind": action_kind,
        }
    )


def _make_compress_response() -> str:
    return json.dumps(
        {
            "findings": ["finding-from-gateway"],
            "decisions": ["decision-from-gateway"],
            "outcome": "success",
            "contradiction_refs": [],
            "key_entities": ["entity-gw"],
        }
    )


def _make_records(n: int, stage_id: str = "S1") -> list[RawEventRecord]:
    """Generate *n* dummy raw event records."""
    records: list[RawEventRecord] = []
    for i in range(n):
        if i % 3 == 0:
            records.append(
                RawEventRecord(
                    event_type="StageStateChanged",
                    payload={
                        "stage_id": stage_id,
                        "from_state": "running",
                        "to_state": "completed" if i == n - 1 else "running",
                    },
                )
            )
        elif i % 3 == 1:
            records.append(
                RawEventRecord(
                    event_type="TaskViewRecorded",
                    payload={"task_view_id": f"tv-{i}"},
                )
            )
        else:
            records.append(
                RawEventRecord(
                    event_type="ActionExecuted",
                    payload={"action": f"action-{i}", "stage_id": stage_id},
                )
            )
    return records


# =========================================================================== #
# 1. LLM Route Engine �?gateway mode
# =========================================================================== #


class TestLLMRouteEngineGateway:
    """LLMRouteEngine uses LLMGateway when provided."""

    def test_decide_uses_gateway(self) -> None:
        gw = MockLLMGateway(default_response=_make_route_response())
        engine = LLMRouteEngine(gateway=gw)

        decision = engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)

        assert decision.next_stage == "S3_build"
        assert decision.confidence == pytest.approx(0.85)
        assert decision.rationale == "LLM decided to build."
        assert decision.action_kind == "build_draft"
        assert gw.call_count == 1

    def test_propose_uses_gateway(self) -> None:
        gw = MockLLMGateway(default_response=_make_route_response())
        engine = LLMRouteEngine(gateway=gw)

        proposals = engine.propose("S2_gather", "run-1", 1)

        assert len(proposals) == 1
        assert proposals[0].action_kind == "build_draft"
        assert "llm(conf=0.85)" in proposals[0].rationale
        assert gw.call_count == 1

    def test_gateway_request_has_system_and_user_messages(self) -> None:
        gw = MockLLMGateway(default_response=_make_route_response())
        engine = LLMRouteEngine(gateway=gw)

        engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)

        req = gw.last_request
        assert req is not None
        roles = [m["role"] for m in req.messages]
        assert "system" in roles
        assert "user" in roles
        assert req.metadata["purpose"] == "route_decision"
        assert req.metadata["run_id"] == "run-1"

    def test_gateway_takes_precedence_over_client(self) -> None:
        """When both gateway and client are provided, gateway wins."""
        gw = MockLLMGateway(
            default_response=_make_route_response(rationale="from gateway")
        )

        def client(_: str) -> str:
            return _make_route_response(rationale="from client")

        engine = LLMRouteEngine(client, gateway=gw)
        decision = engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)

        assert decision.rationale == "from gateway"
        assert gw.call_count == 1


# =========================================================================== #
# 2. LLM Route Engine �?fallback when no gateway
# =========================================================================== #


class TestLLMRouteEngineFallback:
    """LLMRouteEngine falls back correctly when gateway is None."""

    def test_propose_returns_empty_when_no_gateway_no_client(self) -> None:
        engine = LLMRouteEngine()
        proposals = engine.propose("S2_gather", "run-1", 1)
        assert proposals == []

    def test_decide_raises_when_no_gateway_no_client(self) -> None:
        engine = LLMRouteEngine()
        with pytest.raises(LLMRouteParseError, match="no gateway and no client"):
            engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)

    def test_legacy_client_still_works(self) -> None:
        def client(_: str) -> str:
            return _make_route_response(next_stage="S4_synthesize")

        engine = LLMRouteEngine(client)
        decision = engine.decide(stage_id="S2_gather", run_id="run-1", seq=1)
        assert decision.next_stage == "S4_synthesize"


# =========================================================================== #
# 3. HybridRouteEngine �?gateway passthrough
# =========================================================================== #


class TestHybridRouteEngineGateway:
    """HybridRouteEngine correctly passes gateway to LLMRouteEngine."""

    def test_hybrid_with_gateway_falls_back_to_llm_for_unknown_stage(self) -> None:
        gw = MockLLMGateway(
            default_response=_make_route_response(
                next_stage="evaluate_acceptance",
                confidence=0.76,
                rationale="No deterministic mapping.",
                action_kind="evaluate_acceptance",
            )
        )
        hybrid = HybridRouteEngine(gateway=gw, confidence_threshold=0.7)

        result = hybrid.propose_with_provenance(
            stage_id="SX_unknown", run_id="run-2", seq=3
        )
        assert result.source == "llm"
        assert result.confidence == pytest.approx(0.76)
        assert gw.call_count == 1

    def test_hybrid_with_gateway_uses_rules_for_known_stage(self) -> None:
        gw = MockLLMGateway(default_response=_make_route_response())
        hybrid = HybridRouteEngine(gateway=gw, confidence_threshold=0.7)

        result = hybrid.propose_with_provenance(
            stage_id="S2_gather", run_id="run-1", seq=1
        )
        assert result.source == "rule"
        assert gw.call_count == 0  # gateway never called

    def test_hybrid_backward_compat_with_llm_engine(self) -> None:
        """Passing llm_engine directly still works."""

        def client(_: str) -> str:
            return _make_route_response()

        hybrid = HybridRouteEngine(
            llm_engine=LLMRouteEngine(client),
            confidence_threshold=0.7,
        )
        result = hybrid.propose_with_provenance(
            stage_id="SX_unknown", run_id="run-1", seq=1
        )
        assert result.source == "llm"


# =========================================================================== #
# 4. MemoryCompressor �?gateway mode
# =========================================================================== #


class TestMemoryCompressorGateway:
    """MemoryCompressor uses LLMGateway for compression."""

    @pytest.mark.asyncio
    async def test_async_compression_with_gateway(self) -> None:
        gw = MockLLMGateway(default_response=_make_compress_response())
        compressor = MemoryCompressor(
            compress_threshold=5,
            gateway=gw,
        )

        records = _make_records(10)
        result = await compressor.acompress_stage("S2", records)

        assert result.compression_method == "llm"
        assert result.findings == ["finding-from-gateway"]
        assert result.decisions == ["decision-from-gateway"]
        assert result.outcome == "success"
        assert result.key_entities == ["entity-gw"]
        assert result.source_evidence_count == 10
        assert compressor.metrics.compressed_count == 1
        assert gw.call_count == 1

    @pytest.mark.asyncio
    async def test_gateway_request_has_correct_metadata(self) -> None:
        gw = MockLLMGateway(default_response=_make_compress_response())
        compressor = MemoryCompressor(
            compress_threshold=5,
            gateway=gw,
        )

        records = _make_records(10)
        await compressor.acompress_stage("S2", records)

        req = gw.last_request
        assert req is not None
        assert req.metadata["purpose"] == "memory_compression"
        assert req.metadata["stage_id"] == "S2"
        roles = [m["role"] for m in req.messages]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_gateway_takes_precedence_over_llm_fn(self) -> None:
        """When both gateway and llm_fn are provided, gateway wins."""
        gw = MockLLMGateway(default_response=_make_compress_response())

        async def mock_llm(prompt: str) -> str:
            return json.dumps({"findings": ["from-llm-fn"], "decisions": [], "outcome": "partial"})

        compressor = MemoryCompressor(
            llm_fn=mock_llm,
            compress_threshold=5,
            gateway=gw,
        )

        records = _make_records(10)
        result = await compressor.acompress_stage("S2", records)

        assert result.findings == ["finding-from-gateway"]  # from gateway, not llm_fn
        assert gw.call_count == 1

    def test_sync_compression_with_gateway(self) -> None:
        gw = MockLLMGateway(default_response=_make_compress_response())
        compressor = MemoryCompressor(
            compress_threshold=5,
            gateway=gw,
        )

        records = _make_records(10)
        result = compressor.compress_stage("S2", records)

        assert result.compression_method == "llm"
        assert result.findings == ["finding-from-gateway"]
        assert compressor.metrics.compressed_count == 1


# =========================================================================== #
# 5. MemoryCompressor �?fallback without gateway
# =========================================================================== #


class TestMemoryCompressorFallback:
    """MemoryCompressor fallback works correctly without gateway."""

    @pytest.mark.asyncio
    async def test_no_gateway_no_llm_fn_uses_fallback(self) -> None:
        compressor = MemoryCompressor(compress_threshold=5)

        records = _make_records(10)
        result = await compressor.acompress_stage("S1", records)

        assert result.compression_method == "fallback"
        assert compressor.metrics.fallback_count == 1

    @pytest.mark.asyncio
    async def test_below_threshold_uses_direct(self) -> None:
        gw = MockLLMGateway(default_response=_make_compress_response())
        compressor = MemoryCompressor(
            compress_threshold=25,
            gateway=gw,
        )

        records = _make_records(10)
        result = await compressor.acompress_stage("S1", records)

        assert result.compression_method == "direct"
        assert gw.call_count == 0  # gateway not called for below-threshold

    def test_sync_no_gateway_uses_fallback(self) -> None:
        compressor = MemoryCompressor(compress_threshold=5)

        records = _make_records(10)
        result = compressor.compress_stage("S1", records)

        assert result.compression_method == "fallback"
        assert compressor.metrics.fallback_count == 1

    @pytest.mark.asyncio
    async def test_legacy_llm_fn_still_works(self) -> None:
        """Legacy llm_fn path still works when no gateway."""
        llm_response = json.dumps(
            {
                "findings": ["from-legacy-fn"],
                "decisions": [],
                "outcome": "success",
                "contradiction_refs": [],
                "key_entities": [],
            }
        )

        async def mock_llm(prompt: str) -> str:
            return llm_response

        compressor = MemoryCompressor(
            llm_fn=mock_llm,
            compress_threshold=5,
        )

        records = _make_records(10)
        result = await compressor.acompress_stage("S2", records)

        assert result.compression_method == "llm"
        assert result.findings == ["from-legacy-fn"]
        assert compressor.metrics.compressed_count == 1
