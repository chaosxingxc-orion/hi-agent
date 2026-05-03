"""W32-A: FastAPI lifespan adapter for :class:`RealKernelBackend`.

Provides the async context manager FastAPI uses for startup/shutdown
hooks. On startup it triggers the AgentServer's run rehydration so
lease-expired runs from a prior process are picked up. On shutdown it
drains the RunManager and closes the durable stores.

R-AS-1: this module is a member of the second permitted seam
(``agent_server/runtime/**``); every ``from hi_agent.`` line carries
``# r-as-1-seam: <reason>``.

W33-C.1: the lifespan now also starts the W32-C lease-expiry loop and
current_stage watchdog tasks that previously only ran under
``hi_agent.server.app.lifespan``. Without this, the production
agent_server FastAPI process never honoured those reforms — stale
leases would not be reclaimed mid-flight, and the Rule 8 step-5
watchdog would never fire.

W33-C.2: the lifespan also installs a SIGTERM handler that calls
``run_manager.drain(timeout_s=...)`` BEFORE ``shutdown(timeout=2.0)``,
so PM2/systemd/docker stop signals do not force-fail in-flight runs
after 2 s. The drain budget is overridable via
``HI_AGENT_DRAIN_TIMEOUT_S`` (default 30 s).

Why a dedicated lifespan helper: FastAPI's ``Router.lifespan_context``
expects an ``AbstractAsyncContextManager``. Wrapping the backend in a
lifespan function isolates the lifespan dance (startup/shutdown
ordering, exception handling) from the backend implementation, so the
backend itself stays a pure adapter and the lifespan can evolve
without touching the seam-annotated import lines.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# r-as-1-seam: silent_degradation is the loud-fallback contract emitter (Rule 7)
from hi_agent.observability.silent_degradation import (
    record_silent_degradation,
)

# r-as-1-seam: rehydration is a runtime-only operation, owned by AgentServer
from hi_agent.server.app import (
    _rehydrate_runs,
)

if TYPE_CHECKING:
    from agent_server.runtime.kernel_adapter import RealKernelBackend

_log = logging.getLogger("agent_server.runtime.lifespan")

_TERMINAL_STATES = frozenset(
    {
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "done",
        "error",
        "timed_out",
    }
)


async def _lease_expiry_loop(agent_server, interval_s: float) -> None:
    """Periodically scan for stale leases and re-enqueue them.

    Mirror of ``hi_agent.server.app._lease_expiry_loop``. Offloads the
    synchronous SQLite work to the default executor so the event loop
    is not blocked. Emits a Rule 7 silent-degradation signal on failure.
    """
    loop = asyncio.get_running_loop()
    while True:
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise
        try:
            await loop.run_in_executor(
                None, lambda: _rehydrate_runs(agent_server)
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record_silent_degradation(
                component="lease_expiry_loop",
                reason="lease_expiry_scan_failed",
                exc=exc,
            )


async def _current_stage_watchdog(agent_server) -> None:
    """Detect non-terminal runs whose ``current_stage`` is None for >60 s.

    Mirror of ``hi_agent.server.app._current_stage_watchdog``. Required
    for Rule 8 step 5: every run must report a non-None ``current_stage``
    within 30 s of starting; sustained ``None`` for >60 s is a violation.
    """
    warned: dict[str, float] = {}
    while True:
        try:
            await asyncio.sleep(30.0)
        except asyncio.CancelledError:
            raise
        try:
            runs = agent_server.run_manager.list_runs()
        except Exception as exc:
            record_silent_degradation(
                component="current_stage_watchdog",
                reason="list_runs_failed",
                exc=exc,
            )
            continue
        now_loop = asyncio.get_running_loop().time()
        now_iso = datetime.now(UTC).isoformat()
        for run in runs:
            run_id = getattr(run, "run_id", None)
            state = getattr(run, "state", None)
            cur_stage = getattr(run, "current_stage", None)
            created_at = getattr(run, "created_at", None) or ""
            if state in _TERMINAL_STATES or run_id is None:
                warned.pop(run_id or "", None)
                continue
            if cur_stage is not None:
                warned.pop(run_id, None)
                continue
            age_s = 0.0
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(
                        created_at.rstrip("Z")
                    )
                    now_dt = datetime.fromisoformat(now_iso.rstrip("Z"))
                    # If created_at carries no tzinfo, fall back to a naive
                    # subtraction so we still measure age.
                    if created_dt.tzinfo is None:
                        age_s = (
                            now_dt.replace(tzinfo=None) - created_dt
                        ).total_seconds()
                    else:
                        age_s = (now_dt - created_dt).total_seconds()
                except (ValueError, TypeError):
                    age_s = 0.0
            if age_s > 60.0 and run_id not in warned:
                warned[run_id] = now_loop
                _log.warning(
                    "current_stage watchdog: run %s has current_stage=None "
                    "for %.1fs (state=%s) — Rule 8 step-5 violation",
                    run_id,
                    age_s,
                    state,
                )
                record_silent_degradation(
                    component="current_stage_watchdog",
                    reason="current_stage_none_over_60s",
                    run_id=run_id,
                    extra={"age_seconds": age_s, "state": state or ""},
                )


def _install_sigterm_handler(agent_server) -> None:
    """Install a SIGTERM handler that drains in-flight runs gracefully.

    W33-C.2: SIGTERM must call ``drain(timeout_s)`` before ``shutdown``
    so PM2/systemd/docker stop does not force-fail live runs after 2 s.
    The drain budget defaults to 30 s; override via
    ``HI_AGENT_DRAIN_TIMEOUT_S``.
    """
    drain_timeout_s = float(
        os.environ.get("HI_AGENT_DRAIN_TIMEOUT_S", "30")
    )

    def _handler(signum: int, frame: object) -> None:
        _log.warning(
            "SIGTERM received — draining (timeout=%.1fs) before shutdown",
            drain_timeout_s,
        )
        try:
            agent_server.run_manager.drain(timeout_s=drain_timeout_s)
        except Exception as exc:
            _log.warning("SIGTERM drain raised: %s", exc)
        try:
            agent_server.run_manager.shutdown(timeout=2.0)
        except Exception as exc:
            _log.warning("SIGTERM shutdown raised: %s", exc)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (OSError, ValueError):
        # signal.signal raises ValueError when called from a non-main
        # thread (e.g. some test harnesses) and OSError on platforms
        # where SIGTERM is unsupported.
        _log.debug(
            "SIGTERM handler not installed (non-main thread or unsupported)"
        )


def build_real_kernel_lifespan(backend: RealKernelBackend):
    """Return an async context manager wrapping ``backend``'s lifecycle.

    Startup
    -------
    * Trigger ``_rehydrate_runs`` against the backend's AgentServer so
      lease-expired runs from a previous process are claimed and
      re-enqueued (Rule 8 step 1: long-lived process expectation).
    * Start the W32-C background lease-expiry loop and current_stage
      watchdog so they actually run on the production agent_server
      deployment shape (W33-C.1).
    * Install a SIGTERM handler that drains live runs before shutdown
      (W33-C.2).

    Shutdown
    --------
    * Cancel the background tasks.
    * Call ``backend.aclose`` to drain the RunManager and release
      worker threads. The AgentServer's own shutdown chain closes the
      SQLite connections.

    The returned context manager does NOT raise on rehydration failure
    — a startup-time rehydration error is logged and the app continues,
    matching the AgentServer's own lifespan behaviour (see
    ``hi_agent.server.app:lifespan``).
    """

    @contextlib.asynccontextmanager
    async def _lifespan(_app) -> AsyncIterator[None]:
        agent_server = backend.agent_server

        # Startup: rehydrate runs from previous process (best-effort).
        try:
            _rehydrate_runs(agent_server)
        except Exception as exc:  # rule7-exempt: startup rehydration is best-effort
            _log.warning(
                "build_real_kernel_lifespan: _rehydrate_runs raised: %s", exc
            )

        # W33-C.1: start lease-expiry + current_stage watchdog tasks.
        lease_interval_s = float(
            os.environ.get("HI_AGENT_LEASE_EXPIRY_INTERVAL_S", "30")
        )
        lease_task = asyncio.create_task(
            _lease_expiry_loop(agent_server, lease_interval_s)
        )
        watchdog_task = asyncio.create_task(
            _current_stage_watchdog(agent_server)
        )
        # Stash on the backend so test/introspection code can assert
        # they were started without reaching into agent_server private
        # attributes.
        backend._lease_expiry_task = lease_task  # type: ignore[attr-defined]
        backend._current_stage_watchdog_task = watchdog_task  # type: ignore[attr-defined]
        # Also stash on agent_server for parity with hi_agent.server.app.lifespan
        agent_server._lease_expiry_task = lease_task
        agent_server._current_stage_watchdog_task = watchdog_task
        _log.info(
            "lifespan: lease-expiry loop (interval=%.1fs) + current_stage "
            "watchdog started",
            lease_interval_s,
        )

        # W33-C.2: SIGTERM graceful drain handler.
        _install_sigterm_handler(agent_server)

        try:
            yield
        finally:
            # Cancel background tasks first so they do not race teardown.
            for bg_task in (lease_task, watchdog_task):
                bg_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await bg_task
            try:
                backend.aclose()
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "build_real_kernel_lifespan: backend.aclose raised: %s",
                    exc,
                )

    return _lifespan


__all__ = ["build_real_kernel_lifespan"]
