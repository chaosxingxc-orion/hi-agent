"""Rule 7 closure tests for the LLM hot path (W23-B).

These tests assert that the three Rule-7 violation sites in
``hi_agent/llm/http_gateway.py`` (event-bus publish swallow on the
LLM-call boundary; ``record_fallback`` failure swallow on the inner
failover branch; ``record_fallback`` failure swallow on the outer
guard branch) now satisfy Rule 7's four-prong contract:

* Countable — a Prometheus counter is incremented.
* Attributable — a WARNING log carries the run_id and the exception.
* Inspectable — for the event-bus site, a per-run ``fallback_events``
  entry is appended.
* Gate-asserted — covered by ``scripts/check_rule7_observability.py``.

Per Rule 4, the SUT (``HttpLLMGateway``) is the **real** class; only
external collaborators (event bus, ``record_fallback``) are stubbed
to exercise the failure branches.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage
from hi_agent.observability.collector import (
    MetricsCollector,
    set_metrics_collector,
)
from hi_agent.observability.fallback import (
    clear_fallback_events,
    get_fallback_events,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def collector() -> MetricsCollector:
    """Fresh MetricsCollector registered as the process singleton."""
    c = MetricsCollector()
    set_metrics_collector(c)
    try:
        yield c
    finally:
        set_metrics_collector(None)


def _make_request(run_id: str = "run-w23b-rule7-001") -> LLMRequest:
    return LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4o",
        metadata={"run_id": run_id},
    )


def _make_response() -> LLMResponse:
    return LLMResponse(
        content="direct response",
        model="gpt-4o",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


# ---------------------------------------------------------------------------
# Site 1 — Event-bus publish failure on the LLM-call boundary
# ---------------------------------------------------------------------------


class TestEventBusPublishFailureClosure:
    """W23-B Site 1: ``event_bus.publish`` raising must emit signals."""

    def test_event_bus_publish_failure_increments_counter(
        self,
        collector: MetricsCollector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Counter ``hi_agent_event_bus_publish_errors_total`` must increment."""
        run_id = "run-w23b-ebus-counter"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        # Real HttpLLMGateway (SUT). No FailoverChain — we want the call to
        # hit the direct path so the event-bus boundary code runs and the
        # only failure injected is the event_bus.publish raising.
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
        )

        # Stub the event_bus to raise on publish; stub _direct_complete to
        # avoid an outbound HTTP call in offline tests.
        failing_bus = MagicMock()
        failing_bus.publish = MagicMock(side_effect=RuntimeError("ebus down"))

        with (
            patch("hi_agent.server.event_bus.event_bus", failing_bus),
            patch.object(
                HttpLLMGateway, "_direct_complete", return_value=_make_response()
            ),
            caplog.at_level(logging.WARNING, logger="hi_agent.llm.http_gateway"),
        ):
            result = gateway.complete(request)

        assert result.content == "direct response"

        snapshot = collector.snapshot()
        # The counter is registered as ``hi_agent_event_bus_publish_errors_total``.
        assert snapshot.get("hi_agent_event_bus_publish_errors_total"), (
            "expected hi_agent_event_bus_publish_errors_total to be present "
            f"in snapshot, got keys: {list(snapshot.keys())}"
        )
        # Sum across all label permutations.
        bucket = snapshot["hi_agent_event_bus_publish_errors_total"]
        total = sum(bucket.values()) if isinstance(bucket, dict) else bucket
        assert total >= 1

        clear_fallback_events(run_id)

    def test_event_bus_publish_failure_emits_warning_log(
        self,
        collector: MetricsCollector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A WARNING log must surface ``run_id`` and the original exception."""
        run_id = "run-w23b-ebus-log"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
        )
        failing_bus = MagicMock()
        failing_bus.publish = MagicMock(side_effect=RuntimeError("ebus exploded"))

        with (
            patch("hi_agent.server.event_bus.event_bus", failing_bus),
            patch.object(
                HttpLLMGateway, "_direct_complete", return_value=_make_response()
            ),
            caplog.at_level(logging.WARNING, logger="hi_agent.llm.http_gateway"),
        ):
            gateway.complete(request)

        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "event_bus_publish_failed" in r.getMessage()
        ]
        assert warnings, (
            "expected a WARNING log mentioning 'event_bus_publish_failed', "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        # The log must carry the run_id so the operator can attribute the failure.
        assert any(run_id in r.getMessage() for r in warnings)

        clear_fallback_events(run_id)

    def test_event_bus_publish_failure_appends_fallback_event(
        self,
        collector: MetricsCollector,
    ) -> None:
        """The per-run fallback_events list must carry the failure entry."""
        run_id = "run-w23b-ebus-events"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
        )
        failing_bus = MagicMock()
        failing_bus.publish = MagicMock(side_effect=RuntimeError("ebus boom"))

        with (
            patch("hi_agent.server.event_bus.event_bus", failing_bus),
            patch.object(
                HttpLLMGateway, "_direct_complete", return_value=_make_response()
            ),
        ):
            gateway.complete(request)

        events = get_fallback_events(run_id)
        ebus_events = [e for e in events if e.get("reason") == "event_bus_publish_failed"]
        assert ebus_events, (
            f"expected an event_bus_publish_failed entry, got events={events}"
        )
        assert ebus_events[0]["kind"] == "llm"
        assert "exc" in ebus_events[0].get("extra", {})

        clear_fallback_events(run_id)

    def test_event_bus_publish_failure_does_not_propagate(
        self,
        collector: MetricsCollector,
    ) -> None:
        """Caller must not see the event-bus exception (the call must complete)."""
        run_id = "run-w23b-ebus-noprop"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
        )
        failing_bus = MagicMock()
        failing_bus.publish = MagicMock(side_effect=RuntimeError("ebus dies"))

        expected = _make_response()
        with (
            patch("hi_agent.server.event_bus.event_bus", failing_bus),
            patch.object(HttpLLMGateway, "_direct_complete", return_value=expected),
        ):
            result = gateway.complete(request)

        assert result is expected
        clear_fallback_events(run_id)


# ---------------------------------------------------------------------------
# Sites 2 & 3 — record_fallback failure on inner / outer guard branches
# ---------------------------------------------------------------------------


class TestRecordFallbackFailureClosure:
    """W23-B Sites 2 & 3: ``record_fallback`` raising must emit signals."""

    def test_record_fallback_failure_increments_counter(
        self,
        collector: MetricsCollector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``hi_agent_fallback_recording_errors_total`` must increment."""
        run_id = "run-w23b-rf-counter"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        # Real gateway with a failing FailoverChain so the failover branch
        # is taken and ``record_fallback`` is invoked.
        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("chain exploded"))
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=failing_chain,
        )

        # W23-C: SyncBridge.call_sync replaces AsyncBridgeService.submit. We
        # inject the chain failure through the bridge.
        mock_bridge = MagicMock()
        mock_bridge.call_sync.side_effect = RuntimeError("chain exploded")

        # Make record_fallback itself raise so the alarm-bell branch runs.
        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch.object(
                HttpLLMGateway, "_direct_complete", return_value=_make_response()
            ),
            patch(
                "hi_agent.observability.fallback.record_fallback",
                side_effect=RuntimeError("recorder broken"),
            ),
            caplog.at_level(logging.WARNING, logger="hi_agent.llm.http_gateway"),
        ):
            result = gateway.complete(request)

        # The call must still succeed via the direct fallback path.
        assert result.content == "direct response"

        snapshot = collector.snapshot()
        assert snapshot.get("hi_agent_fallback_recording_errors_total"), (
            "expected hi_agent_fallback_recording_errors_total to be present, "
            f"got keys: {list(snapshot.keys())}"
        )
        bucket = snapshot["hi_agent_fallback_recording_errors_total"]
        total = sum(bucket.values()) if isinstance(bucket, dict) else bucket
        assert total >= 1

        clear_fallback_events(run_id)

    def test_record_fallback_failure_emits_warning_log_with_original_reason(
        self,
        collector: MetricsCollector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The WARNING log must carry both the original reason and the recording exc."""
        run_id = "run-w23b-rf-log"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("orig chain fail"))
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=failing_chain,
        )

        mock_bridge = MagicMock()
        mock_bridge.call_sync.side_effect = RuntimeError("orig chain fail")

        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch.object(
                HttpLLMGateway, "_direct_complete", return_value=_make_response()
            ),
            patch(
                "hi_agent.observability.fallback.record_fallback",
                side_effect=RuntimeError("recorder kaput"),
            ),
            caplog.at_level(logging.WARNING, logger="hi_agent.llm.http_gateway"),
        ):
            gateway.complete(request)

        # The W23-B WARNING includes both original_reason and recording exc.
        recording_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "fallback_recording_failed" in r.getMessage()
            and "failover_chain_failed" in r.getMessage()
        ]
        assert recording_warnings, (
            "expected fallback_recording_failed WARNING preserving original_reason; "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        # The recording exception must surface in the log message.
        assert any("recorder kaput" in r.getMessage() for r in recording_warnings)

        clear_fallback_events(run_id)

    def test_record_fallback_failure_does_not_propagate(
        self,
        collector: MetricsCollector,
    ) -> None:
        """Caller must not see the recorder exception either."""
        run_id = "run-w23b-rf-noprop"
        request = _make_request(run_id)
        clear_fallback_events(run_id)

        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("chain bombs"))
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=failing_chain,
        )

        mock_bridge = MagicMock()
        mock_bridge.call_sync.side_effect = RuntimeError("chain bombs")

        expected = _make_response()
        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch.object(HttpLLMGateway, "_direct_complete", return_value=expected),
            patch(
                "hi_agent.observability.fallback.record_fallback",
                side_effect=RuntimeError("recorder bursts"),
            ),
        ):
            result = gateway.complete(request)

        assert result is expected
        clear_fallback_events(run_id)
