"""Integration test: HTTPStreamingGateway must not carry a cross-loop AsyncClient.

Reproduces the DF-18 class bug where a lazy self._client stored on the
gateway instance would be bound to the first event loop and fail on a
second asyncio.run() call with "Event loop is closed".

The fix (per-call AsyncClient via async with inside stream()) is verified by:
1. Checking the gateway has no self._client field after construction.
2. Calling stream() twice via two separate asyncio.run() invocations and
   asserting neither raises "Event loop is closed".
"""
from __future__ import annotations

import asyncio

from hi_agent.llm.streaming import HTTPStreamingGateway


class TestHTTPStreamingGatewayPerCallClient:
    """Verify the DF-18 class fix: no cross-loop AsyncClient stored on self."""

    def test_no_self_client_field_after_construction(self):
        """Gateway must not initialise a self._client field (DF-18 class fix).

        The pre-fix implementation stored self._client = None at construction
        time and lazily assigned an AsyncClient on first use, binding it to
        whichever loop was running then.  Post-fix, no such field should exist.
        """
        gw = HTTPStreamingGateway(
            base_url="https://api.anthropic.com",
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
        )
        assert not hasattr(gw, "_client"), (
            "HTTPStreamingGateway must not have a self._client field after the "
            "DF-18 class fix — AsyncClient must be constructed per-call inside "
            "stream() so it is always bound to the running loop."
        )

    def test_sequential_asyncio_run_calls_no_cross_loop_error(self):
        """Two sequential asyncio.run() calls must not raise 'Event loop is closed'.

        This is the exact failure mode from DF-18: the first asyncio.run()
        creates a loop, constructs (or uses) the AsyncClient on that loop,
        then closes the loop.  The second asyncio.run() opens a new loop but
        the old AsyncClient is bound to the closed loop — any operation on it
        raises RuntimeError('Event loop is closed').

        We use a mock HTTP server response to keep the test offline.  The
        key assertion is on the *exception type*, not the response content.
        """
        import httpx
        import respx

        gw = HTTPStreamingGateway(
            base_url="https://api.test.invalid",
            api_key="test-key",
            model="claude-test",
        )

        sse_usage = '{"input_tokens":1,"output_tokens":0}'
        sse_body = (
            "event: message_start\n"
            f'data: {{"type":"message_start","message":{{"usage":{sse_usage}}}}}\n'
            "\n"
            "event: message_stop\n"
            "data: {}\n"
            "\n"
        )

        from hi_agent.llm.protocol import LLMRequest

        request = LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )

        errors: list[str] = []

        async def _collect(run_index: int) -> None:
            with respx.mock(base_url="https://api.test.invalid") as mock:
                mock.post("/v1/messages").mock(
                    return_value=httpx.Response(200, text=sse_body)
                )
                try:
                    async for _ in gw.stream(request):
                        pass
                except Exception as exc:
                    errors.append(f"run {run_index}: {exc}")

        # Two separate asyncio.run() calls — each creates and closes its own loop.
        asyncio.run(_collect(1))
        asyncio.run(_collect(2))

        cross_loop_errors = [e for e in errors if "Event loop is closed" in e]
        assert not cross_loop_errors, (
            f"Cross-loop bug (DF-18 class) detected on sequential asyncio.run() calls: "
            f"{cross_loop_errors}"
        )


class TestHTTPStreamingGatewayAclose:
    """Verify aclose() is a safe no-op (post-fix: no persistent client to close)."""

    def test_aclose_is_idempotent_noop(self):
        """aclose() must not raise even when called multiple times."""
        gw = HTTPStreamingGateway(api_key="k")

        async def _close_twice():
            await gw.aclose()
            await gw.aclose()

        asyncio.run(_close_twice())  # must not raise
