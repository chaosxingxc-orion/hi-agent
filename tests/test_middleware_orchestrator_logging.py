"""Unit tests for M-1: MiddlewareOrchestrator logging fix.

Verifies that error-relevant events produce log records, making them
visible in production.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest
from hi_agent.middleware.orchestrator import MiddlewareOrchestrator
from hi_agent.middleware.protocol import (
    HookAction,
    HookResult,
    LifecyclePhase,
    MiddlewareMessage,
)


class _RaisingMiddleware:
    """Middleware whose process() always raises."""

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        raise RuntimeError("middleware_process_error")


class _NormalMiddleware:
    """Middleware that passes the message through."""

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        return MiddlewareMessage(
            source="normal",
            target="end",
            msg_type=message.msg_type,
            payload=message.payload,
            metadata=message.metadata,
        )


class TestOrchestratorLogging:
    """Tests for log emission in MiddlewareOrchestrator."""

    def test_middleware_error_logged_on_process_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """process() raising should emit orchestrator.middleware_error log."""
        orch = MiddlewareOrchestrator()
        orch.register_middleware("perception", _RaisingMiddleware())

        with caplog.at_level(logging.WARNING, logger="hi_agent.middleware.orchestrator"):
            orch.run("test input")

        messages = [r.message for r in caplog.records]
        assert any("orchestrator.middleware_error" in m for m in messages), (
            f"Expected 'orchestrator.middleware_error' in log records, got: {messages}"
        )

    def test_pipeline_blocked_logged_on_block_hook(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A BLOCK hook should emit orchestrator.pipeline_blocked log."""
        orch = MiddlewareOrchestrator()
        orch.register_middleware("perception", _NormalMiddleware())

        def _blocking_hook(
            msg: MiddlewareMessage, ctx: dict[str, Any]
        ) -> HookResult:
            return HookResult(action=HookAction.BLOCK, reason="test_block")

        orch.add_hook(
            "perception",
            LifecyclePhase.PRE_EXECUTE,
            _blocking_hook,
            name="test_blocker",
        )

        with caplog.at_level(logging.INFO, logger="hi_agent.middleware.orchestrator"):
            orch.run("test input")

        messages = [r.message for r in caplog.records]
        assert any("orchestrator.pipeline_blocked" in m for m in messages), (
            f"Expected 'orchestrator.pipeline_blocked' in log records, got: {messages}"
        )

    def test_run_start_and_complete_logged_at_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """run() should emit run_start and run_complete debug logs."""
        orch = MiddlewareOrchestrator()
        orch.register_middleware("perception", _NormalMiddleware())

        with caplog.at_level(logging.DEBUG, logger="hi_agent.middleware.orchestrator"):
            orch.run("hello")

        messages = [r.message for r in caplog.records]
        assert any("orchestrator.run_start" in m for m in messages), (
            f"Expected 'orchestrator.run_start' in log records, got: {messages}"
        )
        assert any("orchestrator.run_complete" in m for m in messages), (
            f"Expected 'orchestrator.run_complete' in log records, got: {messages}"
        )
