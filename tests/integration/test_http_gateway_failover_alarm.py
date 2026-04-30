"""Integration tests for Rule 7 alarm wiring in http_gateway.py — failover paths.

Wave 10.3 W3-B: Confirms that when FailoverChain.complete raises, record_fallback
is called with kind="llm" and reason="failover_chain_failed", and the
hi_agent_llm_fallback_total counter is incremented.

Both the sync (HttpLLMGateway) and async (HTTPGateway) paths are covered.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from hi_agent.llm.http_gateway import HTTPGateway, HttpLLMGateway
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(run_id: str = "run-gateway-alarm-001") -> LLMRequest:
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


def _make_failing_failover_chain() -> MagicMock:
    """Return a sync-style mock FailoverChain whose complete raises RuntimeError."""
    chain = MagicMock()
    chain.complete = AsyncMock(side_effect=RuntimeError("failover chain exploded"))
    return chain


# ---------------------------------------------------------------------------
# Sync path (HttpLLMGateway)
# ---------------------------------------------------------------------------


class TestSyncFailoverAlarm:
    """Verify Rule 7 alarm on the sync (urllib) gateway's failover path."""

    def test_failover_chain_failure_calls_record_fallback(self) -> None:
        """When FailoverChain.complete raises, record_fallback must be called.

        The sync gateway routes the async failover through SyncBridge
        (W23-C); we make ``call_sync`` raise to simulate FailoverChain
        failure.
        """
        run_id = "run-sync-failover-alarm"
        request = _make_request(run_id)
        direct_response = _make_response()

        failing_chain = _make_failing_failover_chain()
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=failing_chain,
        )

        # W23-C: SyncBridge.call_sync replaces AsyncBridgeService.submit.
        mock_bridge = MagicMock()
        mock_bridge.call_sync.side_effect = RuntimeError("failover chain exploded")

        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch(
                "hi_agent.llm.http_gateway.HttpLLMGateway._direct_complete",
                return_value=direct_response,
            ),
            patch("hi_agent.observability.fallback.record_fallback") as mock_rf,
        ):
            result = gateway.complete(request)

        # The call must succeed (falls through to direct path).
        assert result is direct_response

        # record_fallback must have been called with the right args.
        mock_rf.assert_called_once()
        _args, kwargs = mock_rf.call_args
        assert _args == ("llm",)
        assert kwargs["reason"] == "failover_chain_failed"
        assert kwargs["run_id"] == run_id
        assert "exc" in kwargs["extra"]

    def test_failover_chain_failure_does_not_crash_gateway(self) -> None:
        """Gateway must fall through to direct path even when failover chain fails."""
        run_id = "run-sync-failover-safe"
        request = _make_request(run_id)
        direct_response = _make_response()

        failing_chain = _make_failing_failover_chain()
        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=failing_chain,
        )

        mock_bridge = MagicMock()
        mock_bridge.call_sync.side_effect = RuntimeError("failover chain exploded")

        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch(
                "hi_agent.llm.http_gateway.HttpLLMGateway._direct_complete",
                return_value=direct_response,
            ),
            patch("hi_agent.observability.fallback.record_fallback"),
        ):
            result = gateway.complete(request)

        assert result is direct_response

    def test_no_fallback_alarm_when_failover_succeeds(self) -> None:
        """record_fallback must NOT be called when FailoverChain.complete succeeds.

        W23-C: SyncBridge.call_sync replaces AsyncBridgeService. Patching
        ``get_bridge`` to return a stub whose ``call_sync`` yields the
        success response directly is enough — the failover branch never
        sees an exception, so ``record_fallback`` is not invoked.
        """
        run_id = "run-sync-failover-ok"
        request = _make_request(run_id)
        success_response = _make_response()

        good_chain = MagicMock()
        good_chain.complete = AsyncMock(return_value=success_response)

        gateway = HttpLLMGateway(
            base_url="https://api.example.com/v1",
            api_key_env="NONEXISTENT_KEY",
            failover_chain=good_chain,
        )

        mock_bridge = MagicMock()
        mock_bridge.call_sync.return_value = success_response

        with (
            patch(
                "hi_agent.llm.http_gateway.get_bridge", return_value=mock_bridge
            ),
            patch("hi_agent.observability.fallback.record_fallback") as mock_rf,
        ):
            result = gateway.complete(request)

        assert result is success_response
        # record_fallback must NOT have been called with reason="failover_chain_failed".
        failover_calls = [
            c
            for c in mock_rf.call_args_list
            if c.kwargs.get("reason") == "failover_chain_failed"
        ]
        assert failover_calls == []


# ---------------------------------------------------------------------------
# Async path (HTTPGateway)
# ---------------------------------------------------------------------------


class TestAsyncFailoverAlarm:
    """Verify Rule 7 alarm on the async (httpx) gateway's failover path."""

    def test_async_failover_chain_failure_calls_record_fallback(self) -> None:
        """When async FailoverChain.complete raises, record_fallback must be called."""
        run_id = "run-async-failover-alarm"
        request = _make_request(run_id)
        direct_response = _make_response()

        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("async failover boom"))

        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
            failover_chain=failing_chain,
        )

        async def run_test():
            with (
                patch(
                    "hi_agent.llm.http_gateway.HTTPGateway._direct_complete",
                    new_callable=AsyncMock,
                    return_value=direct_response,
                ),
                patch("hi_agent.observability.fallback.record_fallback") as mock_rf,
            ):
                result = await gateway.complete(request)
                return result, mock_rf

        result, mock_rf = asyncio.run(run_test())

        assert result is direct_response
        mock_rf.assert_called_once()
        _args, kwargs = mock_rf.call_args
        assert _args == ("llm",)
        assert kwargs["reason"] == "failover_chain_failed"
        assert kwargs["run_id"] == run_id
        assert "exc" in kwargs["extra"]

    def test_async_failover_chain_failure_does_not_crash_gateway(self) -> None:
        """Async gateway must fall through to direct path when failover chain fails."""
        run_id = "run-async-failover-safe"
        request = _make_request(run_id)
        direct_response = _make_response()

        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("async failover boom"))

        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
            failover_chain=failing_chain,
        )

        async def run_test():
            with (
                patch(
                    "hi_agent.llm.http_gateway.HTTPGateway._direct_complete",
                    new_callable=AsyncMock,
                    return_value=direct_response,
                ),
                patch("hi_agent.observability.fallback.record_fallback"),
            ):
                return await gateway.complete(request)

        result = asyncio.run(run_test())
        assert result is direct_response

    def test_async_no_fallback_alarm_when_failover_succeeds(self) -> None:
        """record_fallback must NOT be called (for failover reason) when chain succeeds."""
        run_id = "run-async-failover-ok"
        request = _make_request(run_id)
        success_response = _make_response()

        good_chain = MagicMock()
        good_chain.complete = AsyncMock(return_value=success_response)

        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
            failover_chain=good_chain,
        )

        async def run_test():
            with patch("hi_agent.observability.fallback.record_fallback") as mock_rf:
                result = await gateway.complete(request)
                return result, mock_rf

        result, mock_rf = asyncio.run(run_test())

        assert result is success_response
        failover_calls = [
            c
            for c in mock_rf.call_args_list
            if c.kwargs.get("reason") == "failover_chain_failed"
        ]
        assert failover_calls == []

    def test_async_fallback_counter_incremented_on_failover_failure(self) -> None:
        """The hi_agent_llm_fallback_total counter must be incremented on failover failure.

        This test exercises the real record_fallback (not mocked) and checks
        that the metrics collector sees the increment.
        """
        from hi_agent.observability.collector import get_metrics_collector
        from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events

        run_id = "run-async-counter-001"
        request = _make_request(run_id)
        direct_response = _make_response()

        # Clear any prior events for isolation.
        clear_fallback_events(run_id)

        failing_chain = MagicMock()
        failing_chain.complete = AsyncMock(side_effect=RuntimeError("counter test boom"))

        gateway = HTTPGateway(
            base_url="https://api.example.com/v1",
            api_key="fake-key",
            failover_chain=failing_chain,
        )

        async def run_test():
            with patch(
                "hi_agent.llm.http_gateway.HTTPGateway._direct_complete",
                new_callable=AsyncMock,
                return_value=direct_response,
            ):
                return await gateway.complete(request)

        result = asyncio.run(run_test())
        assert result is direct_response

        # Fallback event must be recorded for this run_id.
        events = get_fallback_events(run_id)
        assert len(events) >= 1
        assert any(e["reason"] == "failover_chain_failed" for e in events)
        assert all(e["kind"] == "llm" for e in events if e["reason"] == "failover_chain_failed")

        # Metrics collector must have the counter incremented.
        collector = get_metrics_collector()
        if collector is not None:
            snapshot = collector.snapshot()
            # The counter name used by record_fallback is hi_agent_llm_fallback_total
            assert snapshot.get("hi_agent_llm_fallback_total", 0) >= 1
