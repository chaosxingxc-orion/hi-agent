"""W32-A: real-kernel runtime adapter (the second R-AS-1 seam after bootstrap.py).

Per R-AS-1 the only modules under ``agent_server/`` permitted to import
from ``hi_agent.*`` are:

  1. ``agent_server/bootstrap.py`` — assembles the production FastAPI
     app (W31-N1, W31-N2).
  2. ``agent_server/runtime/**``   — this sub-package, which binds the
     RIA-facing facades to the durable
     :class:`hi_agent.server.app.AgentServer` (W32-A).

Every ``from hi_agent.`` line in this sub-package MUST carry the
``# r-as-1-seam: <reason>`` end-of-line comment so reviewers can audit
each cross-boundary import as an intentional seam.

Why this is a separate sub-package and not part of bootstrap.py:

  * bootstrap.py is the FastAPI assembly layer (settings, middleware
    wiring, app.state stashing). Putting kernel adapter logic there
    pushes it well past the LOC budget and mixes "wire the app" with
    "drive the kernel".
  * The kernel adapter holds long-lived state (``AgentServer``,
    ``RunManager``, SQLite stores) whose lifetime spans the FastAPI
    lifespan, not just the build_production_app call. That naturally
    lives in its own module.

Public surface:

  * :class:`RealKernelBackend` — wraps an :class:`hi_agent.server.app.
    AgentServer` and exposes the start_run / get_run / signal_run /
    cancel_run / iter_events / list_artifacts / get_artifact callables
    that match what ``_InProcessRunBackend`` exposed in W31, so the
    facades can switch from stub to real without changing their
    signatures.
  * :func:`build_real_kernel_lifespan` — async context manager that
    handles startup (rehydrate runs) and shutdown (drain + close stores)
    integration with FastAPI's lifespan protocol.
"""
from __future__ import annotations

from agent_server.runtime.kernel_adapter import RealKernelBackend
from agent_server.runtime.lifespan import build_real_kernel_lifespan

__all__ = ["RealKernelBackend", "build_real_kernel_lifespan"]
