"""W31-N (Wave 31, Track A1, N.1): single bootstrap seam.

This is the ONE module under ``agent_server/`` permitted to import from
``hi_agent.*`` per R-AS-1. It assembles the production northbound app
that the agent-server CLI (``serve.py``) hands to uvicorn, and that
RIA team consumes.

What it wires:

* :class:`hi_agent.server.idempotency.IdempotencyStore` — persistent
  SQLite-backed dedup, scoped under ``state_dir``.
* :class:`agent_server.facade.idempotency_facade.IdempotencyFacade` —
  the contract-shaped wrapper used by the middleware.
* :class:`agent_server.facade.run_facade.RunFacade`,
  :class:`~agent_server.facade.event_facade.EventFacade`,
  :class:`~agent_server.facade.artifact_facade.ArtifactFacade`,
  :class:`~agent_server.facade.manifest_facade.ManifestFacade` — all
  initialised against in-process stub callables. The real kernel
  binding lands in a follow-up wave; W31-N1/N2 only require the seam
  to exist and the middleware pipeline to be live.
* :class:`hi_agent.config.posture.Posture` — used to flip strict
  behaviour on research/prod.
* :func:`agent_server.api.build_app` — assembles the FastAPI app.
* :func:`register_idempotency_middleware` — registers the middleware
  in the order that puts ``TenantContextMiddleware`` outermost (runs
  first) and ``IdempotencyMiddleware`` inner (consumes the validated
  tenant id).

The in-process stub backends are intentionally minimal: they keep the
default-offline test profile (Rule 16) self-contained. They do NOT
attempt to run real LLM calls. Replacing them with the live kernel is
strictly a follow-up: the bootstrap is the only seam that needs to
change, by spec.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

# These hi_agent imports are SCOPED to this module per R-AS-1. The
# linter/governance gates accept this file as the single seam.
from hi_agent.config.posture import Posture
from hi_agent.observability.spine_events import emit_tenant_context
from hi_agent.server.idempotency import IdempotencyStore

from agent_server.api import build_app
from agent_server.config.settings import AgentServerSettings, load_settings
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.artifact_facade import ArtifactFacade
from agent_server.facade.event_facade import EventFacade
from agent_server.facade.idempotency_facade import IdempotencyFacade
from agent_server.facade.manifest_facade import ManifestFacade
from agent_server.facade.run_facade import RunFacade

__all__ = ["build_production_app"]


def _default_state_dir() -> Path:
    """Resolve the default state directory.

    Order of precedence:
      1. ``AGENT_SERVER_STATE_DIR`` env var
      2. ``HI_AGENT_HOME`` env var (existing platform convention)
      3. ``./.agent_server`` under the current working directory
    """
    import os

    explicit = os.environ.get("AGENT_SERVER_STATE_DIR")
    if explicit:
        return Path(explicit)
    home = os.environ.get("HI_AGENT_HOME")
    if home:
        return Path(home) / ".agent_server"
    return Path.cwd() / ".agent_server"


class _InProcessRunBackend:
    """Minimal in-process stub for the run/event/artifact callables.

    Each method returns a contract-shaped dict identical to the kernel's.
    The stub exists so the bootstrap can assemble a serve-able app under
    the default-offline profile without instantiating ``hi_agent`` HTTP
    server. Replacing it with a real kernel callable set is a follow-up
    track and only the bootstrap module changes.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], dict[str, Any]] = {}
        self._artifacts_by_run: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._artifacts_by_id: dict[tuple[str, str], dict[str, Any]] = {}
        self._events_by_run: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._counter = 0

    # ------------------------------------------------------------------
    # Run callables
    # ------------------------------------------------------------------

    def start_run(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        goal: str,
        project_id: str,
        run_id: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self._counter += 1
        rid = run_id or f"run_{self._counter:08d}"
        record = {
            "tenant_id": tenant_id,
            "run_id": rid,
            "state": "queued",
            "current_stage": None,
            "started_at": "1970-01-01T00:00:00Z",
            "finished_at": None,
            "metadata": dict(metadata),
            "llm_fallback_count": 0,
            "profile_id": profile_id,
            "project_id": project_id,
            "goal": goal,
            "idempotency_key": idempotency_key,
        }
        self._runs[(tenant_id, rid)] = record
        self._events_by_run.setdefault((tenant_id, rid), [])
        return record

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self._runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        return record

    def signal_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        signal: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        if signal == "cancel":
            record["state"] = "cancelling"
        return record

    def cancel_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self._runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        record["state"] = "cancelling"
        return record

    def iter_events(
        self, *, tenant_id: str, run_id: str
    ) -> Iterable[dict[str, Any]]:
        events = self._events_by_run.get((tenant_id, run_id))
        if events is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        return list(events)

    # ------------------------------------------------------------------
    # Artifact callables
    # ------------------------------------------------------------------

    def list_artifacts(
        self, *, tenant_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        return list(self._artifacts_by_run.get((tenant_id, run_id), []))

    def get_artifact(
        self, *, tenant_id: str, artifact_id: str
    ) -> dict[str, Any]:
        record = self._artifacts_by_id.get((tenant_id, artifact_id))
        if record is None:
            raise NotFoundError(
                "artifact not found", tenant_id=tenant_id, detail=artifact_id
            )
        return record


def build_production_app(
    *,
    settings: AgentServerSettings | None = None,
    state_dir: Path | str | None = None,
) -> FastAPI:
    """Construct the production agent-server FastAPI app.

    Parameters
    ----------
    settings:
        Optional pre-loaded :class:`AgentServerSettings`. When ``None``
        (the default), settings are loaded from environment variables
        via :func:`agent_server.config.settings.load_settings`.
    state_dir:
        Directory where persistent state (idempotency SQLite, future
        artifact registry, etc.) lives. When ``None``, resolves to the
        first of ``AGENT_SERVER_STATE_DIR``, ``HI_AGENT_HOME/.agent_server``,
        or ``./.agent_server``.

    Returns
    -------
    FastAPI
        An ASGI app with all routes and middleware wired. Caller is
        responsible for handing it to uvicorn / gunicorn.
    """
    if settings is None:
        settings = load_settings()
    resolved_state_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    resolved_state_dir.mkdir(parents=True, exist_ok=True)

    posture = Posture.from_env()

    # Idempotency: persistent store + facade + middleware-ready.
    # W31-N N.4: pass the posture-derived is_strict flag so route handlers
    # can read it without importing hi_agent.config.posture themselves.
    idem_store = IdempotencyStore(db_path=resolved_state_dir / "idempotency.db")
    idem_facade = IdempotencyFacade(
        store=idem_store, is_strict=posture.is_strict
    )

    # W31-N N.4: bind the real spine emitter for tenant context. The
    # bootstrap is the only seam allowed to hand this to the middleware
    # so route-level tests stay decoupled from hi_agent internals.
    def _tenant_event_emitter(tenant_id: str) -> None:
        emit_tenant_context(tenant_id=tenant_id)

    # Run/event/artifact backends — in-process stubs for W31-N1/N2.
    backend = _InProcessRunBackend()
    run_facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    event_facade = EventFacade(
        cancel_run=backend.cancel_run,
        get_run=backend.get_run,
        iter_events=backend.iter_events,
    )
    artifact_facade = ArtifactFacade(
        list_artifacts=backend.list_artifacts,
        get_artifact=backend.get_artifact,
    )
    manifest_facade = ManifestFacade()

    app = build_app(
        run_facade=run_facade,
        event_facade=event_facade,
        artifact_facade=artifact_facade,
        manifest_facade=manifest_facade,
        idempotency_facade=idem_facade,
        idempotency_strict=posture.is_strict,
        tenant_event_emitter=_tenant_event_emitter,
        # W31-N N.9: opt-in to L1 stub routers because production has the
        # idempotency facade (and per-tenant scoping) wired. Default-off
        # builds (route-level unit tests) keep them silent.
        include_mcp_tools=True,
        include_skills_memory=True,
    )

    # Stash references so the uvicorn worker / shutdown hook can reach
    # them for cleanup and so tests can introspect production wiring.
    app.state.agent_server_settings = settings
    app.state.agent_server_state_dir = resolved_state_dir
    app.state.idempotency_store = idem_store
    app.state.idempotency_facade = idem_facade
    app.state.run_facade = run_facade
    app.state.event_facade = event_facade
    app.state.artifact_facade = artifact_facade
    app.state.manifest_facade = manifest_facade
    app.state.posture = posture
    return app
