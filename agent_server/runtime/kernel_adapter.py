"""W32-A: real-kernel backend that binds facades to AgentServer.

This is the second R-AS-1 seam (after bootstrap.py). Every
``from hi_agent.`` import in this module carries an
``# r-as-1-seam: <reason>`` annotation and is enforced by
``scripts/check_facade_seams.py`` (extended in W32-A to scan
``agent_server/runtime/**``).

Responsibilities:

  * Construct exactly one :class:`hi_agent.server.app.AgentServer`
    instance. Per Rule 6 there is a single builder for this resource;
    facades receive callables, not the instance.
  * Translate the facade-shaped callable contract into RunManager calls
    bound to a :class:`hi_agent.server.tenant_context.TenantContext`.
  * Validate ``tenant_id`` on every method so cross-tenant leak attempts
    raise :class:`agent_server.contracts.errors.NotFoundError` (404),
    not a quiet ``None`` return.
  * Read run lifecycle events from the durable
    :class:`hi_agent.server.event_store.SQLiteEventStore` so the SSE
    stream surfaces real ``run_queued`` / ``run_started`` /
    ``run_completed`` events (Rule 8 step 5).

Rule 5 lifetime discipline: the AgentServer's RunManager runs on
worker threads (sync executor model) — there is no async client whose
loop ownership we have to track here. The async resources owned by the
AgentServer (LLM gateway httpx.AsyncClient, etc.) are managed by the
AgentServer's own lifespan, which we delegate to via
:func:`build_real_kernel_lifespan`.

Rule 12 spine: every method takes ``tenant_id`` as a kwarg and converts
it into a :class:`TenantContext` so the RunManager's workspace-scoping
contract is honoured. No ``"default"`` coercion under any posture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Hi-agent imports — every one carries an R-AS-1 seam annotation.
# r-as-1-seam: posture is platform config the adapter reads to fail-close
from hi_agent.config.posture import (
    Posture,
)

# r-as-1-seam: AgentServer is the durable RunManager + stores umbrella class
from hi_agent.server.app import (
    AgentServer,
)

# r-as-1-seam: RunManager workspace contract uses kernel TenantContext
from hi_agent.server.tenant_context import (
    TenantContext as KernelTenantContext,
)

from agent_server.contracts.errors import ContractError, NotFoundError

_log = logging.getLogger("agent_server.runtime.kernel_adapter")


class RealKernelBackend:
    """Real-kernel backend: binds the v1 facades to a live AgentServer.

    Construction is single-builder (Rule 6): the bootstrap calls this
    constructor exactly once per process; consumers receive the seven
    callable methods and never see the underlying ``AgentServer``.
    """

    def __init__(self, *, state_dir: Path, posture: Posture) -> None:
        """Build a real AgentServer rooted at ``state_dir``.

        Parameters
        ----------
        state_dir:
            Directory where the AgentServer's durable SQLite stores
            (run_store, event_store, idempotency, run_queue) live. This
            module sets ``HI_AGENT_DATA_DIR`` BEFORE constructing the
            AgentServer so the durable backends pick the right root.
        posture:
            Platform posture (dev / research / prod). Stored on the
            instance for callers that need to fail-close on missing
            scope; the AgentServer reads its own posture from the
            environment, so we don't pass it through.
        """
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._posture = posture

        # The bootstrap-owned IdempotencyStore (driving the middleware)
        # uses ``state_dir/idempotency.db``. The AgentServer's own
        # ``build_durable_backends`` ALSO defaults to
        # ``HI_AGENT_DATA_DIR/idempotency.db``. If both stores point at
        # the same file the middleware-owned reservation (hash =
        # full-body) will conflict with the kernel-owned reservation
        # (hash = body sans idempotency_key) the moment a duplicate
        # request reaches the kernel before the middleware has cached
        # the first response. Side-stepping that requires giving the
        # kernel a distinct data dir so its idempotency / runs / events
        # SQLite files do not collide with the bootstrap-owned ones.
        kernel_data_dir = self._state_dir / "kernel"
        kernel_data_dir.mkdir(parents=True, exist_ok=True)
        self._kernel_data_dir = kernel_data_dir

        import os

        prior_data_dir = os.environ.get("HI_AGENT_DATA_DIR")
        os.environ["HI_AGENT_DATA_DIR"] = str(kernel_data_dir)
        try:
            self._agent_server = AgentServer()
        finally:
            # Restore prior value so we don't leak our scoping into the
            # rest of the process. The AgentServer's stores have already
            # been opened against the directory we set above.
            if prior_data_dir is None:
                os.environ.pop("HI_AGENT_DATA_DIR", None)
            else:
                os.environ["HI_AGENT_DATA_DIR"] = prior_data_dir

        self._closed = False

    # ------------------------------------------------------------------
    # Lifespan hooks — invoked by build_real_kernel_lifespan.
    # ------------------------------------------------------------------

    @property
    def agent_server(self) -> AgentServer:
        """Return the underlying AgentServer (lifespan use only)."""
        return self._agent_server

    def aclose(self) -> None:
        """Drain in-flight runs and shut down the RunManager.

        Idempotent: calling twice is a no-op after the first invocation.
        """
        if self._closed:
            return
        try:
            self._agent_server.run_manager.shutdown(timeout=2.0)
        except Exception as exc:  # pragma: no cover - defensive shutdown
            _log.warning("RealKernelBackend.aclose: run_manager.shutdown raised: %s", exc)
        self._closed = True

    # ------------------------------------------------------------------
    # Run callables — match _InProcessRunBackend signature.
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
        """Create a run, dispatch it to a worker thread, return record."""
        if not tenant_id:
            err = ContractError(
                "tenant_id is required",
                detail="missing tenant_id",
                http_status=400,
            )
            raise err
        workspace = KernelTenantContext(
            tenant_id=tenant_id,
            user_id=metadata.get("user_id", "") or "",
            session_id=metadata.get("session_id", "") or "",
        )
        task_contract: dict[str, Any] = {
            "goal": goal,
            "profile_id": profile_id,
            "project_id": project_id,
            "tenant_id": tenant_id,
            "metadata": dict(metadata),
        }
        # ``run_id`` is the caller-provided identifier; when empty the
        # RunManager mints a UUID4. ``idempotency_key`` is forwarded as a
        # task_contract field (RunManager honours it via its
        # IdempotencyStore wiring).
        if run_id:
            task_contract["run_id"] = run_id
        if idempotency_key:
            task_contract["idempotency_key"] = idempotency_key

        managed_run = self._agent_server.run_manager.create_run(
            task_contract,
            workspace=workspace,
        )
        # Resolve the executor via the AgentServer's existing factory and
        # dispatch through start_run. The factory constructs a runnable
        # closure; the RunManager wraps it in a worker thread.
        executor_factory = self._agent_server.executor_factory
        if executor_factory is None:
            # Track A F4: revert the just-created ManagedRun before raising
            # so the run dict / queue does not retain an orphan record.
            self._cancel_orphan_run(managed_run.run_id, tenant_id)
            err = ContractError(
                "executor factory is not configured on the kernel",
                tenant_id=tenant_id,
                detail="executor_factory_missing",
                http_status=503,
            )
            raise err
        run_data = dict(task_contract, run_id=managed_run.run_id)
        # Track A F4: wrap executor_factory() AND start_run() in a single
        # try-block so any failure between create_run() and start_run()
        # cancels the orphan run before re-raising.
        try:
            try:
                task_runner = executor_factory(run_data)
            except RuntimeError as exc:
                # AgentServer raises RuntimeError("platform_not_ready: ...")
                # when prod-mode subsystem checks fail. Surface as a 503.
                err = ContractError(
                    str(exc),
                    tenant_id=tenant_id,
                    detail="platform_not_ready",
                    http_status=503,
                )
                raise err from exc

            def _executor_fn(_managed_run: Any) -> Any:
                return task_runner()

            self._agent_server.run_manager.start_run(managed_run.run_id, _executor_fn)
        except Exception:
            # Any failure above leaves a ManagedRun in the manager dict and
            # potentially in the durable run_queue. Revert by cancelling so
            # /runs/{id} returns 404 (per Rule 8 step-6 cancel semantics)
            # rather than an orphaned 'created' record that never advances.
            self._cancel_orphan_run(managed_run.run_id, tenant_id)
            raise
        return self._record_to_dict(managed_run.run_id, tenant_id)

    def _cancel_orphan_run(self, run_id: str, tenant_id: str) -> None:
        """Track A F4: revert a partially-created run on start_run failure.

        Called when ``executor_factory(...)`` or ``run_manager.start_run(...)``
        raises before the run is actually executing. We mark the run cancelled
        so it cannot leak into ``list_runs`` or be claimed by a worker, then
        emit a structured silent-degradation log if the cancel itself fails.
        Errors here MUST NOT shadow the original failure — the caller swallows
        any exception we raise so the original error reaches the HTTP layer.
        """
        try:
            self._agent_server.run_manager.cancel_run(
                run_id,
                workspace=KernelTenantContext(tenant_id=tenant_id),
            )
        except Exception as exc:  # pragma: no cover — defensive cleanup
            # Loud signal: orphan cleanup failed. Use the silent-degradation
            # spine so this is observable in metrics/logs, but never re-raise
            # because we are already unwinding from a primary failure.
            try:
                # r-as-1-seam: silent_degradation is the loud-fallback contract emitter
                from hi_agent.observability.silent_degradation import (
                    record_silent_degradation,
                )

                record_silent_degradation(
                    component="agent_server.runtime.kernel_adapter._cancel_orphan_run",
                    reason="orphan_cancel_failed",
                    exc=exc,
                )
            except Exception:  # pragma: no cover
                _log.warning(
                    "RealKernelBackend: orphan cancel for run_id=%s failed: %s",
                    run_id,
                    exc,
                )

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        """Return the dict-shaped record for ``run_id`` under ``tenant_id``.

        Raises :class:`NotFoundError` (404) if the run is not visible to
        this tenant — either because it does not exist or because it is
        owned by a different tenant.
        """
        return self._record_to_dict(run_id, tenant_id)

    def signal_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        signal: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a signal to a live run.

        ``cancel`` maps to RunManager.cancel_run. Unknown signals are a
        no-op for now — the v1 contract only specifies cancel; future
        signals (pause, resume) will land in a follow-up wave.
        """
        # Verify ownership BEFORE acting so unknown ids surface as 404.
        self._record_to_dict(run_id, tenant_id)
        if signal == "cancel":
            self._agent_server.run_manager.cancel_run(
                run_id,
                workspace=KernelTenantContext(tenant_id=tenant_id),
            )
        return self._record_to_dict(run_id, tenant_id)

    def cancel_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        """Cancel a live run; raise NotFoundError if the run is unknown."""
        # _record_to_dict raises NotFoundError for unknown runs, which is
        # the Rule 8 step-6 requirement (404 on cancel of unknown id).
        self._record_to_dict(run_id, tenant_id)
        cancelled = self._agent_server.run_manager.cancel_run(
            run_id,
            workspace=KernelTenantContext(tenant_id=tenant_id),
        )
        if not cancelled:
            # Run existed but was already terminal — return current state
            # so the facade can serialise it without inferring "cancelling".
            return self._record_to_dict(run_id, tenant_id)
        return self._record_to_dict(run_id, tenant_id)

    def iter_events(self, *, tenant_id: str, run_id: str) -> Iterable[dict[str, Any]]:
        """Yield event-store rows for ``run_id`` filtered by ``tenant_id``.

        Each row is shaped as ``{event_id, run_id, sequence, event_type,
        payload, payload_json, created_at}``. The event facade renders
        these as SSE frames.
        """
        # Ownership guard — unknown run_id raises 404.
        self._record_to_dict(run_id, tenant_id)
        event_store = self._agent_server._event_store
        if event_store is None:
            return []
        try:
            # NB: list_since uses ``WHERE sequence > ?``, so passing 0
            # would exclude the sequence-0 ``run_queued`` event the
            # RunManager emits at create_run. Pass -1 so the SSE stream
            # includes the very first lifecycle event.
            stored = event_store.list_since(
                run_id,
                since_sequence=-1,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # pragma: no cover - storage error
            _log.warning(
                "iter_events: event_store.list_since failed for run_id=%s: %s",
                run_id,
                exc,
            )
            return []
        out: list[dict[str, Any]] = []
        for ev in stored:
            try:
                payload = json.loads(ev.payload_json) if ev.payload_json else {}
            except json.JSONDecodeError:
                payload = {"_raw": ev.payload_json}
            out.append(
                {
                    "event_id": ev.event_id,
                    "run_id": ev.run_id,
                    "sequence": ev.sequence,
                    "event_type": ev.event_type,
                    "payload": payload,
                    "payload_json": ev.payload_json,
                    "created_at": ev.created_at,
                    "tenant_id": ev.tenant_id,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Artifact callables — minimal pass-through over the AgentServer.
    # ------------------------------------------------------------------

    def list_artifacts(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        """List artifacts for ``run_id`` filtered by ``tenant_id``."""
        if not tenant_id:
            return []
        registry = getattr(self._agent_server, "artifact_registry", None)
        if registry is None:
            return []
        try:
            records = registry.list_for_run(run_id=run_id, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover - registry error
            _log.warning("list_artifacts: artifact_registry.list_for_run failed: %s", exc)
            return []
        return [dict(rec) for rec in records]

    def get_artifact(self, *, tenant_id: str, artifact_id: str) -> dict[str, Any]:
        """Return artifact metadata; raise NotFoundError if not visible."""
        if not tenant_id:
            raise NotFoundError("artifact not found", tenant_id=tenant_id, detail=artifact_id)
        registry = getattr(self._agent_server, "artifact_registry", None)
        if registry is None:
            raise NotFoundError(
                "artifact registry not configured",
                tenant_id=tenant_id,
                detail=artifact_id,
            )
        try:
            record = registry.get(artifact_id=artifact_id, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover - registry error
            _log.warning("get_artifact: artifact_registry.get failed: %s", exc)
            raise NotFoundError(
                "artifact not found", tenant_id=tenant_id, detail=artifact_id
            ) from exc
        if record is None:
            raise NotFoundError("artifact not found", tenant_id=tenant_id, detail=artifact_id)
        return dict(record)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_to_dict(self, run_id: str, tenant_id: str) -> dict[str, Any]:
        """Fetch a run and translate to the dict the facades expect.

        Raises :class:`NotFoundError` (404) when the run is not visible
        to ``tenant_id``. RunManager.get_run returns None both for
        missing ids AND for cross-tenant access — the facade's contract
        is the same in either case (404, not 403, to avoid leaking
        existence).
        """
        workspace = KernelTenantContext(tenant_id=tenant_id)
        run = self._agent_server.run_manager.get_run(run_id, workspace=workspace)
        if run is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        full = self._agent_server.run_manager.to_dict(run)
        # Surface a contract-shaped envelope. The facades read these
        # specific keys; full RunRecord fields land under ``metadata``
        # so callers can introspect without a separate route.
        return {
            "tenant_id": run.tenant_id,
            "run_id": run.run_id,
            "state": run.state,
            "current_stage": run.current_stage,
            "started_at": run.started_at or full.get("started_at"),
            "finished_at": run.finished_at or full.get("finished_at"),
            "metadata": dict(run.task_contract.get("metadata", {}) or {}),
            "llm_fallback_count": int(full.get("llm_fallback_count", 0) or 0),
            "profile_id": run.task_contract.get("profile_id", ""),
            "project_id": run.project_id,
            "goal": run.task_contract.get("goal", ""),
            "idempotency_key": run.idempotency_key or "",
        }


__all__ = ["RealKernelBackend"]
