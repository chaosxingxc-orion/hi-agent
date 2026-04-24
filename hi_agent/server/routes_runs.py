"""Run-related HTTP route handlers.

Extracted from app.py (Arch-7 decomposition). All route paths, HTTP methods,
and response schemas are identical to the originals — this is a pure move.

Handlers:
    handle_list_runs        GET  /runs
    handle_runs_active      GET  /runs/active
    handle_create_run       POST /runs
    handle_get_run          GET  /runs/{run_id}
    handle_signal_run       POST /runs/{run_id}/signal
    handle_cancel_run       POST /runs/{run_id}/cancel
    handle_submit_feedback  POST /runs/{run_id}/feedback
    handle_get_feedback     GET  /runs/{run_id}/feedback
    handle_resume_run       POST /runs/{run_id}/resume
    handle_run_artifacts    GET  /runs/{run_id}/artifacts
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.server.tenant_context import require_tenant_context
from hi_agent.server.workspace_path import WorkspaceKey


class GateDecisionRequest(BaseModel):
    """Request body for POST /runs/{run_id}/gate_decision."""

    decision: Literal["approve", "backtrack", "remediate", "escalate"]
    target_phase: str = ""
    remediation: dict = {}
    approver_id: str
    note: str = ""


logger = logging.getLogger(__name__)

def _get_feedback_store(server: Any) -> Any:
    """Return the server's FeedbackStore. Must be attached to server at startup."""
    store = getattr(server, "_feedback_store", None)
    if store is None:
        raise RuntimeError(
            "_feedback_store not initialized on server — check lifespan setup in app.py"
        )
    return store


async def handle_list_runs(request: Request) -> JSONResponse:
    """List all managed runs scoped to the caller's workspace."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    runs = manager.list_runs(workspace=ctx)
    return JSONResponse({"runs": [manager.to_dict(r) for r in runs]})


async def handle_runs_active(request: Request) -> JSONResponse:
    """Return active run contexts scoped to the caller's workspace."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: Any = request.app.state.agent_server
    rcm = getattr(server, "run_context_manager", None)
    if rcm is None:
        return JSONResponse({"run_ids": [], "count": 0, "status": "not_configured"})
    try:
        # Get owned run IDs from the workspace-aware manager, then post-filter
        # the rcm result (RunContextManager has no workspace API of its own).
        manager = server.run_manager
        owned_ids = {r.run_id for r in manager.list_runs(workspace=ctx)}
        all_active = rcm.list_runs()
        run_ids = [rid for rid in all_active if rid in owned_ids]
        return JSONResponse(
            {
                "run_ids": run_ids,
                "count": len(run_ids),
                "status": "ok",
            }
        )
    except Exception as exc:
        logger.warning("handle_runs_active: error fetching active runs: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_create_run(request: Request) -> JSONResponse:
    """Create a new run from the POST body, bound to the caller's workspace."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    if "goal" not in body:
        return JSONResponse({"error": "missing_goal"}, status_code=400)

    _idem_header = request.headers.get("Idempotency-Key")
    _idempotency_key_missing = _idem_header is None and "idempotency_key" not in body
    if _idem_header:
        body = dict(body, idempotency_key=_idem_header)

    server: Any = request.app.state.agent_server
    manager = server.run_manager
    try:
        run_id = manager.create_run(body, workspace=ctx)
    except ValueError as exc:
        if "idempotency_conflict" in str(exc):
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse({"error": str(exc)}, status_code=409)

    # Wave 8 / P1.2: extract project_id and emit warning header if missing.
    _project_missing = not bool(body.get("project_id", ""))

    # DF-27 / Rule 14: the builder now requires a non-empty profile_id.
    # Rather than silent-defaulting (which masks missing caller metadata) or
    # returning 400 (which is a breaking API change we defer until the
    # downstream roadmap P-3 lands), assign 'default' loudly here: one WARNING
    # log + one recorded fallback event so the fact is countable via /metrics
    # and inspectable on GET /runs/{id}.
    if not body.get("profile_id"):
        from hi_agent.observability.fallback import record_fallback

        logger.warning(
            "POST /runs received without profile_id; defaulting to 'default'. "
            "Downstream should supply profile_id per downstream roadmap (P-3)."
        )
        record_fallback(
            "route",
            reason="missing_profile_id",
            run_id=run_id,
            extra={"default_assigned": "default"},
        )
        body["profile_id"] = "default"

    # Register run in RunContextManager so /runs/active reflects live runs.
    rcm = getattr(server, "run_context_manager", None)
    if rcm is not None:
        with contextlib.suppress(Exception):
            rcm.get_or_create(run_id)

    # If the server has an executor factory, start the run immediately.
    if server.executor_factory is not None:
        run_data = dict(body, run_id=run_id)
        # Inject workspace_key so the executor factory can scope memory stores.
        if ctx.tenant_id and ctx.user_id and ctx.session_id:
            run_data["_workspace_key"] = WorkspaceKey(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                team_id=ctx.team_id,
            )
        try:
            task_runner = server.executor_factory(run_data)
        except RuntimeError as exc:
            # Platform subsystem not ready (e.g. LLM gateway requires API key in
            # prod mode). Return 503 so integrators can act on it, not a raw 500.
            logger.warning("handle_create_run: executor_factory failed — %s", exc)
            # Clean up the run we registered above
            with contextlib.suppress(Exception):
                manager.get_run(run_id)  # no-op, just guard
            return JSONResponse(
                {
                    "error": "platform_not_ready",
                    "detail": str(exc),
                    "run_id": run_id,
                    "hint": (
                        "Set HI_AGENT_ENV=dev for heuristic fallback, or provide "
                        "OPENAI_API_KEY / ANTHROPIC_API_KEY for production mode."
                    ),
                },
                status_code=503,
            )
        except Exception as exc:
            logger.exception("handle_create_run: executor_factory unexpected error — %s", exc)
            return JSONResponse(
                {
                    "error": "executor_build_failed",
                    "detail": str(exc),
                    "run_id": run_id,
                    "error_type": type(exc).__name__,
                },
                status_code=500,
            )

        def _executor_fn(_managed_run: Any) -> Any:
            try:
                return task_runner()
            finally:
                # Remove from active registry on completion or failure.
                if rcm is not None:
                    with contextlib.suppress(Exception):
                        rcm.remove(run_id)

        manager.start_run(run_id, _executor_fn)

    run = manager.get_run(run_id, workspace=ctx)
    extra_headers: dict[str, str] = {}
    if _idempotency_key_missing:
        extra_headers["X-Idempotency-Warning"] = "missing"
    if _project_missing:
        extra_headers["X-Project-Warning"] = "unscoped"
    return JSONResponse(
        manager.to_dict(run), status_code=201, headers=extra_headers  # type: ignore[arg-type]
    )


async def handle_get_run(request: Request) -> JSONResponse:
    """Return a single run by id, scoped to the caller's workspace."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse(
            {"error": "run_not_found", "run_id": run_id},
            status_code=404,
        )
    return JSONResponse(manager.to_dict(run))


async def handle_signal_run(request: Request) -> JSONResponse:
    """Send a signal to an existing run, enforcing workspace ownership."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse(
            {"error": "run_not_found", "run_id": run_id},
            status_code=404,
        )

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    signal = body.get("signal")
    if signal == "cancel":
        ok = manager.cancel_run(run_id, workspace=ctx)
        if ok:
            return JSONResponse({"run_id": run_id, "state": "cancelled"})
        return JSONResponse(
            {"error": "cannot_cancel", "run_id": run_id},
            status_code=409,
        )
    return JSONResponse(
        {"error": "unknown_signal", "signal": signal},
        status_code=400,
    )


async def handle_cancel_run(request: Request) -> JSONResponse:
    """Cancel an existing run, enforcing workspace ownership."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse(
            {"error": "run_not_found", "run_id": run_id},
            status_code=404,
        )

    ok = manager.cancel_run(run_id, workspace=ctx)
    if ok:
        return JSONResponse({"run_id": run_id, "state": "cancelled"})
    return JSONResponse(
        {"error": "cannot_cancel", "run_id": run_id},
        status_code=409,
    )


async def handle_submit_feedback(request: Request) -> JSONResponse:
    """POST /runs/{run_id}/feedback — record explicit feedback for a completed run."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    if manager.get_run(run_id, workspace=ctx) is None:
        return JSONResponse({"error": "run_not_found", "run_id": run_id}, status_code=404)
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    rating = body.get("rating")
    if rating is None or not isinstance(rating, (int, float)):
        return JSONResponse(
            {"error": "rating_required", "detail": "rating must be a number"}, status_code=400
        )
    notes = body.get("notes", "")
    from hi_agent.evolve.feedback_store import RunFeedback

    feedback = RunFeedback(run_id=run_id, rating=float(rating), notes=str(notes))
    store = _get_feedback_store(server)
    store.submit(feedback)
    return JSONResponse(
        {"run_id": run_id, "rating": feedback.rating, "submitted_at": feedback.submitted_at}
    )


async def handle_get_feedback(request: Request) -> JSONResponse:
    """GET /runs/{run_id}/feedback — return feedback for a run."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    if manager.get_run(run_id, workspace=ctx) is None:
        return JSONResponse({"error": "run_not_found", "run_id": run_id}, status_code=404)
    store = _get_feedback_store(server)
    record = store.get(run_id)
    if record is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    from dataclasses import asdict

    return JSONResponse(asdict(record))


async def handle_resume_run(request: Request) -> JSONResponse:
    """Resume a run from its checkpoint file."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    import os
    import threading

    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    # Search for checkpoint file (run os.path.exists off the event loop)
    loop = asyncio.get_running_loop()
    checkpoint_path = body.get("checkpoint_path")
    if not checkpoint_path:
        candidates = [
            os.path.join(".checkpoint", f"checkpoint_{run_id}.json"),
            os.path.join(".hi_agent", f"checkpoint_{run_id}.json"),
        ]
        for candidate in candidates:
            if await loop.run_in_executor(None, os.path.exists, candidate):
                checkpoint_path = candidate
                break

    if not checkpoint_path or not await loop.run_in_executor(None, os.path.exists, checkpoint_path):
        return JSONResponse(
            {"error": "checkpoint_not_found", "run_id": run_id},
            status_code=404,
        )

    def _resume_in_background() -> None:
        try:
            from hi_agent.runner import RunExecutor

            kernel = server._builder.build_kernel()
            RunExecutor.resume_from_checkpoint(
                checkpoint_path,
                kernel,
                evolve_engine=server._builder.build_evolve_engine(),
                harness_executor=server._builder.build_harness(),
            )
        except Exception as exc:
            logger.error(
                "Background checkpoint resume failed for run %r: %s",
                run_id,
                exc,
                exc_info=True,
            )

    thread = threading.Thread(target=_resume_in_background, daemon=True)
    thread.start()

    return JSONResponse(
        {
            "status": "resuming",
            "run_id": run_id,
            "checkpoint_path": checkpoint_path,
        }
    )


async def handle_run_artifacts(request: Request) -> JSONResponse:
    """Return artifact IDs associated with a completed run, scoped to caller's workspace."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]
    server: Any = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    result = run.result
    artifact_ids: list[str] = []
    if result is not None:
        artifact_ids = list(getattr(result, "artifacts", []) or [])
    # Enrich with full artifact data if registry is available.
    registry = getattr(server, "artifact_registry", None)
    if registry is not None:
        artifacts = [registry.get(aid) for aid in artifact_ids]
        artifacts_payload = [a.to_dict() for a in artifacts if a is not None]
    else:
        artifacts_payload = [{"artifact_id": aid} for aid in artifact_ids]
    return JSONResponse(
        {"run_id": run_id, "artifacts": artifacts_payload, "count": len(artifacts_payload)}
    )


async def handle_gate_decision(request: Request) -> JSONResponse:
    """Apply a structured gate decision to a run.

    POST /runs/{run_id}/gate_decision

    Accepts a :class:`GateDecisionRequest` body with decision type
    (approve / backtrack / remediate / escalate), an approver identity,
    and optional phase / remediation fields.

    Returns:
        200 with ``{run_id, decision, event_id, status}`` on success.
        400 on validation error.
        401 when caller is not authenticated.
    """
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    run_id = request.path_params["run_id"]

    try:
        raw = await request.json()
        body = GateDecisionRequest(**raw)
    except Exception as exc:
        return JSONResponse({"error": "invalid_request", "detail": str(exc)}, status_code=400)

    server: Any = request.app.state.agent_server
    event_id = str(uuid.uuid4())

    # Attempt to apply via a live GateCoordinator if the system exposes one.
    coord = getattr(getattr(server, "_builder", None), "_gate_coordinator", None)
    if coord is None:
        coord = getattr(server, "gate_coordinator", None)
    if coord is not None and hasattr(coord, "apply_decision"):
        try:
            coord.apply_decision(
                run_id=run_id,
                decision=body.decision,
                target_phase=body.target_phase,
                remediation=body.remediation,
                approver_id=body.approver_id,
                note=body.note,
            )
        except Exception as exc:
            logger.warning("handle_gate_decision: apply_decision failed: %s", exc)

    return JSONResponse(
        {
            "run_id": run_id,
            "decision": body.decision,
            "event_id": event_id,
            "status": "accepted",
        }
    )
