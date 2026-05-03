"""W33-C.1: agent_server lifespan must start the W32-C reform tasks.

The W32-C reforms (background lease-expiry loop and current_stage
watchdog) were originally only attached to ``hi_agent.server.app``'s
Starlette lifespan. The production agent_server FastAPI process,
which is what RIA actually deploys, did NOT exercise that lifespan —
its own ``build_real_kernel_lifespan`` only called ``_rehydrate_runs``
once at startup, leaving stale leases unreclaimed mid-flight and the
current_stage watchdog completely silent.

This test boots the production app, drives FastAPI's startup hook,
and asserts that BOTH background tasks are now alive on the backend.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest


@pytest.mark.asyncio
async def test_lifespan_starts_lease_expiry_and_current_stage_watchdog(
    tmp_path, monkeypatch
) -> None:
    """The real-kernel lifespan must start both W32-C background tasks.

    Acceptance: after FastAPI's startup hook runs, the backend exposes
    non-None task handles for both the lease-expiry loop and the
    current_stage watchdog, neither of which is already finished.
    """
    # Force dev posture so the AgentServer construction path stays the
    # default-offline shape (no real LLM, no auth required).
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path)
    backend = app.state.run_backend
    assert backend is not None

    # Drive the FastAPI lifespan manually so the startup task is
    # invoked. Using the bound lifespan from app.router is sufficient —
    # FastAPI exposes the same async context manager TestClient would
    # invoke.
    @asynccontextmanager
    async def _drive():
        async with app.router.lifespan_context(app):
            yield

    async with _drive():
        lease_task = getattr(backend, "_lease_expiry_task", None)
        watchdog_task = getattr(backend, "_current_stage_watchdog_task", None)
        assert lease_task is not None, (
            "lifespan must start the W32-C lease-expiry loop on the real backend"
        )
        assert watchdog_task is not None, (
            "lifespan must start the W32-C current_stage watchdog on the real backend"
        )
        assert not lease_task.done(), (
            "lease-expiry loop terminated immediately; expected long-running task"
        )
        assert not watchdog_task.done(), (
            "current_stage watchdog terminated immediately; expected long-running task"
        )

    # After teardown the tasks must be cancelled cleanly (no hung tasks).
    assert lease_task.done(), "lease-expiry task must finish on shutdown"
    assert watchdog_task.done(), "watchdog task must finish on shutdown"
