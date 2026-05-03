"""W31-N (Wave 31, Track A1, N.1): single bootstrap seam.

W32-A extends the single seam into a SECOND permitted seam under
``agent_server/runtime/**`` (kernel adapter module) so the heavy
``AgentServer`` wiring can live next to its facade-binding logic
instead of growing this module past its LOC budget. The two-seam list
under R-AS-1 is now:

  * ``agent_server/bootstrap.py`` (this file) — assembles the FastAPI
    app, picks dev-stub vs real-kernel backend, hands the lifespan to
    FastAPI.
  * ``agent_server/runtime/**`` — the runtime adapter that owns the
    AgentServer instance and exposes facade callables. Enforced by
    ``scripts/check_facade_seams.py``.

What this module wires:

* :class:`hi_agent.server.idempotency.IdempotencyStore` — persistent
  SQLite-backed dedup, scoped under ``state_dir``.
* :class:`agent_server.facade.idempotency_facade.IdempotencyFacade` —
  the contract-shaped wrapper used by the middleware.
* :class:`agent_server.facade.run_facade.RunFacade`,
  :class:`~agent_server.facade.event_facade.EventFacade`,
  :class:`~agent_server.facade.artifact_facade.ArtifactFacade`,
  :class:`~agent_server.facade.manifest_facade.ManifestFacade` — bound
  to either :class:`agent_server.runtime.RealKernelBackend` (default
  under all postures) or the legacy in-process stub
  (``AGENT_SERVER_BACKEND=stub`` only, dev posture only). The stub
  remains for the default-offline test profile (Rule 16); it is
  forbidden under research/prod posture and the resolution helper
  raises if requested there.
* :class:`hi_agent.config.posture.Posture` — used to flip strict
  behaviour on research/prod.
* :func:`agent_server.api.build_app` — assembles the FastAPI app.
* :func:`register_idempotency_middleware` — registers the middleware
  in the order that puts ``TenantContextMiddleware`` outermost (runs
  first) and ``IdempotencyMiddleware`` inner (consumes the validated
  tenant id).
* :func:`agent_server.runtime.build_real_kernel_lifespan` — wires the
  AgentServer's startup rehydration and shutdown drain into the
  FastAPI lifespan when the real backend is selected.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

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
from agent_server.runtime import RealKernelBackend, build_real_kernel_lifespan

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


def _resolve_backend_kind(posture: Posture) -> Literal["real", "stub"]:
    """Decide whether the bootstrap binds the real kernel or the in-process stub.

    Reads ``AGENT_SERVER_BACKEND`` (default ``"real"``). Values:

      * ``"real"`` — bind facades to :class:`RealKernelBackend`.
      * ``"stub"`` — keep the legacy :class:`_InProcessRunBackend`. This
        is the default-offline test profile (Rule 16) path and is ONLY
        valid under dev posture.

    Under research/prod posture the stub is fail-closed: callers that
    explicitly set ``AGENT_SERVER_BACKEND=stub`` get a ``ValueError``
    so the misconfiguration surfaces at startup rather than turning a
    production instance into a no-op responder.
    """
    import os

    raw = os.environ.get("AGENT_SERVER_BACKEND", "real").strip().lower()
    if raw not in ("real", "stub"):
        raise ValueError(
            f"AGENT_SERVER_BACKEND={raw!r} is not valid; expected 'real' or 'stub'."
        )
    if posture.is_strict and raw == "stub":
        raise ValueError(
            "AGENT_SERVER_BACKEND=stub is forbidden under research/prod posture; "
            "set AGENT_SERVER_BACKEND=real (the default) or unset it."
        )
    return raw  # type: ignore[return-value]  # narrowed above


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

    # W32-A: pick real-kernel vs stub backend. Real is default; stub is
    # dev-only and exists for the default-offline test profile.
    backend_kind = _resolve_backend_kind(posture)
    real_backend: RealKernelBackend | None = None
    stub_backend: _InProcessRunBackend | None = None
    if backend_kind == "real":
        real_backend = RealKernelBackend(
            state_dir=resolved_state_dir, posture=posture
        )
        run_facade = RunFacade(
            start_run=real_backend.start_run,
            get_run=real_backend.get_run,
            signal_run=real_backend.signal_run,
        )
        event_facade = EventFacade(
            cancel_run=real_backend.cancel_run,
            get_run=real_backend.get_run,
            iter_events=real_backend.iter_events,
        )
        artifact_facade = ArtifactFacade(
            list_artifacts=real_backend.list_artifacts,
            get_artifact=real_backend.get_artifact,
        )
    else:
        stub_backend = _InProcessRunBackend()
        run_facade = RunFacade(
            start_run=stub_backend.start_run,
            get_run=stub_backend.get_run,
            signal_run=stub_backend.signal_run,
        )
        event_facade = EventFacade(
            cancel_run=stub_backend.cancel_run,
            get_run=stub_backend.get_run,
            iter_events=stub_backend.iter_events,
        )
        artifact_facade = ArtifactFacade(
            list_artifacts=stub_backend.list_artifacts,
            get_artifact=stub_backend.get_artifact,
        )
    manifest_facade = ManifestFacade()

    # When real-kernel is selected, hand a lifespan into build_app so
    # the AgentServer's rehydration + drain hooks fire on FastAPI
    # startup/shutdown. Under stub the lifespan stays None — the stub
    # has no resources that outlive a request.
    lifespan = (
        build_real_kernel_lifespan(real_backend)
        if real_backend is not None
        else None
    )

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
        lifespan=lifespan,
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
    app.state.backend_kind = backend_kind
    # W32-A: stash the active backend so tests/introspection can drive
    # it directly (e.g. inject a stub skill that records invocation).
    app.state.run_backend = real_backend if real_backend is not None else stub_backend
    return app
