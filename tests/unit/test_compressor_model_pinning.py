"""DF-34: memory compression must send the pinned model in LLMRequest.

Rule 15 E2E hit ``UnsupportedModel`` on volces because compression asked
the gateway for the ``light`` tier, which the coding-plan endpoint did not
serve.  Pinning the compressor to a concrete, known-good model (builder
default: ``glm-5.1``) avoids tier-routing surprises.
"""

from __future__ import annotations

from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord

_EMPTY_SUMMARY_JSON = (
    '{"findings":[],"decisions":[],"outcome":"active","contradiction_refs":[],"key_entities":[]}'
)


class _CaptureGateway:
    """Minimal LLMGateway stub that records the request it was given."""

    def __init__(self, payload: str = _EMPTY_SUMMARY_JSON) -> None:
        self.payload = payload
        self.captured: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.captured = request
        return LLMResponse(
            content=self.payload,
            model=request.model,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _records(n: int) -> list[RawEventRecord]:
    return [
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "s", "to_state": "running"},
        )
        for _ in range(n)
    ]


def test_memory_compressor_pinned_model_flows_into_llm_request():
    """When compression_model is set, LLMRequest.model uses that concrete ID."""
    gw = _CaptureGateway()
    mc = MemoryCompressor(
        gateway=gw,
        compress_threshold=1,
        compression_model="glm-5.1",
    )

    mc.compress_stage("stage-42", _records(2))

    assert gw.captured is not None, "gateway.complete was not invoked"
    assert gw.captured.model == "glm-5.1"


def test_memory_compressor_no_pin_falls_back_to_light_tier():
    """Without compression_model, legacy 'light' tier label is sent (backward compatible)."""
    gw = _CaptureGateway()
    mc = MemoryCompressor(gateway=gw, compress_threshold=1)

    mc.compress_stage("stage-42", _records(2))

    assert gw.captured is not None
    assert gw.captured.model == "light"


def test_build_compressor_pins_to_strong_tier_by_default():
    """SystemBuilder._build_compressor pins compression to glm-5.1."""
    from hi_agent.config.builder import SystemBuilder

    builder = SystemBuilder()
    compressor = builder._build_compressor()

    # Rule 15 unblock requires a concrete pin — not None (gateway default) and
    # not the symbolic "light" tier which the coding-plan endpoint may reject.
    assert compressor._compression_model == "glm-5.1"
