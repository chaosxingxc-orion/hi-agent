"""W32-A: FastAPI lifespan adapter for :class:`RealKernelBackend`.

Provides the async context manager FastAPI uses for startup/shutdown
hooks. On startup it triggers the AgentServer's run rehydration so
lease-expired runs from a prior process are picked up. On shutdown it
drains the RunManager and closes the durable stores.

R-AS-1: this module is a member of the second permitted seam
(``agent_server/runtime/**``); every ``from hi_agent.`` line carries
``# r-as-1-seam: <reason>``.

Why a dedicated lifespan helper: FastAPI's ``Router.lifespan_context``
expects an ``AbstractAsyncContextManager``. Wrapping the backend in a
lifespan function isolates the lifespan dance (startup/shutdown
ordering, exception handling) from the backend implementation, so the
backend itself stays a pure adapter and the lifespan can evolve
without touching the seam-annotated import lines.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from hi_agent.server.app import _rehydrate_runs  # r-as-1-seam: rehydration is a runtime-only operation, owned by AgentServer

if TYPE_CHECKING:
    from agent_server.runtime.kernel_adapter import RealKernelBackend

_log = logging.getLogger("agent_server.runtime.lifespan")


def build_real_kernel_lifespan(backend: "RealKernelBackend"):
    """Return an async context manager wrapping ``backend``'s lifecycle.

    Startup
    -------
    * Trigger ``_rehydrate_runs`` against the backend's AgentServer so
      lease-expired runs from a previous process are claimed and
      re-enqueued (Rule 8 step 1: long-lived process expectation).

    Shutdown
    --------
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
        try:
            _rehydrate_runs(backend.agent_server)
        except Exception as exc:  # rule7-exempt: startup rehydration is best-effort
            _log.warning(
                "build_real_kernel_lifespan: _rehydrate_runs raised: %s", exc
            )
        try:
            yield
        finally:
            try:
                backend.aclose()
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "build_real_kernel_lifespan: backend.aclose raised: %s",
                    exc,
                )

    return _lifespan


__all__ = ["build_real_kernel_lifespan"]
