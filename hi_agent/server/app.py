"""HTTP API server for hi-agent using Starlette + uvicorn.

Endpoints:
    POST /runs          -- Submit a new task (body: TaskContract JSON)
    GET  /runs/{run_id} -- Query run status
    GET  /runs          -- List active runs
    GET  /runs/active   -- Active RunContext entries from RunContextManager
    POST /runs/{run_id}/signal    -- Send signal to run
    POST /runs/{run_id}/feedback  -- Submit explicit feedback for a run
    GET  /runs/{run_id}/feedback  -- Retrieve feedback for a run
    POST /runs/{run_id}/resume    -- Resume run from checkpoint
    GET  /runs/{run_id}/events -- SSE stream of run events
    GET  /health        -- Health check
    GET  /ready         -- Platform readiness contract (200=ready, 503=not ready)
    GET  /manifest      -- System capabilities manifest (dynamic)
    GET  /metrics       -- Prometheus metrics
    GET  /metrics/json  -- Metrics as JSON
    GET  /cost          -- LLM cost breakdown
    POST /knowledge/ingest           -- Ingest text knowledge
    POST /knowledge/ingest-structured -- Ingest structured facts
    GET  /knowledge/query            -- Query knowledge
    GET  /knowledge/status           -- Knowledge system stats
    POST /knowledge/lint             -- Run health check
    POST /knowledge/sync             -- Sync graph->wiki
    POST /memory/dream               -- Trigger dream consolidation
    POST /memory/consolidate         -- Trigger consolidation
    GET  /memory/status              -- Memory tier status
    GET  /skills/list                -- List skills
    GET  /skills/status              -- Skill system status
    POST /skills/evolve              -- Trigger evolution cycle
    GET  /skills/{skill_id}/metrics  -- Skill metrics
    GET  /skills/{skill_id}/versions -- Skill versions
    POST /skills/{skill_id}/optimize -- Optimize skill prompt
    POST /skills/{skill_id}/promote  -- Promote challenger
    GET  /context/health             -- Context health report
    POST /replay/{run_id}            -- Trigger replay of a recorded run
    GET  /replay/{run_id}/status     -- Check replay file availability
    GET  /management/capacity        -- Capacity tuning recommendations
    GET  /tools                      -- List registered capabilities
    POST /tools/call                 -- Invoke a registered capability by name
    POST /mcp/tools/list             -- MCP tools/list (enumerate tools with schemas)
    POST /mcp/tools/call             -- MCP tools/call (invoke a tool by name)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from hi_agent.auth.operation_policy import require_operation
from hi_agent.config.stack import ConfigStack
from hi_agent.config.watcher import ConfigFileWatcher
from hi_agent.server.auth_middleware import AuthMiddleware
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.event_bus import event_bus
from hi_agent.server.rate_limiter import RateLimiter
from hi_agent.server.run_manager import RunManager
from hi_agent.server.ops_routes import handle_doctor, handle_release_gate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Starlette route handlers
# ---------------------------------------------------------------------------

async def handle_health(request: Request) -> JSONResponse:
    """Return aggregated server health status across all subsystems."""
    server: AgentServer = request.app.state.agent_server
    subsystems: dict[str, dict[str, Any]] = {}
    overall = "ok"

    # --- run_manager (always present) ---
    try:
        status = server.run_manager.get_status()
        subsystems["run_manager"] = {
            "status": "ok",
            "active_runs": status["active_runs"],
            "queued_runs": status["queued_runs"],
            "capacity": status["total_capacity"],
        }
    except Exception:
        subsystems["run_manager"] = {"status": "error"}
        overall = "degraded"

    # --- memory ---
    try:
        mm = server.memory_manager
        if mm is None:
            subsystems["memory"] = {"status": "not_configured", "configured": False}
        else:
            info: dict[str, Any] = {"status": "ok", "configured": True}
            stm = getattr(mm, "short_term_store", None)
            mtm = getattr(mm, "mid_term_store", None)
            ltm = getattr(mm, "long_term_graph", None)
            if stm is not None:
                info["stm_count"] = len(stm) if hasattr(stm, "__len__") else 0
            if mtm is not None:
                info["mtm_count"] = len(mtm) if hasattr(mtm, "__len__") else 0
            if ltm is not None:
                info["ltm_count"] = len(ltm) if hasattr(ltm, "__len__") else 0
            subsystems["memory"] = info
    except Exception:
        subsystems["memory"] = {"status": "error"}
        overall = "degraded"

    # --- metrics ---
    try:
        mc = server.metrics_collector
        if mc is None:
            subsystems["metrics"] = {"status": "not_configured"}
        else:
            snap = mc.snapshot()
            total_events = 0
            for val in snap.values():
                if isinstance(val, dict):
                    for v in val.values():
                        if isinstance(v, (int, float)):
                            total_events += int(v)
                        elif isinstance(v, dict) and "count" in v:
                            total_events += int(v["count"])
            subsystems["metrics"] = {
                "status": "ok",
                "events_recorded": total_events,
            }
    except Exception:
        subsystems["metrics"] = {"status": "error"}
        overall = "degraded"

    # --- context ---
    try:
        cm = server.context_manager
        if cm is None:
            subsystems["context"] = {"status": "not_configured"}
        else:
            report = cm.get_health_report()
            health_str = report.health.value.upper()
            ctx_status = "ok"
            if health_str in ("ORANGE", "RED"):
                ctx_status = "degraded"
                overall = "degraded"
            subsystems["context"] = {
                "status": ctx_status,
                "health": health_str,
            }
    except Exception:
        subsystems["context"] = {"status": "error"}
        overall = "degraded"

    # --- event_bus ---
    try:
        stats = event_bus.get_stats()
        eb_status = "ok"
        if stats.get("total_dropped", 0) > 0:
            eb_status = "degraded"
            overall = "degraded"
        subsystems["event_bus"] = {
            "status": eb_status,
            "subscribers": stats.get("subscriber_count", 0),
            "dropped": stats.get("total_dropped", 0),
        }
    except Exception:
        subsystems["event_bus"] = {"status": "error"}
        overall = "degraded"

    # --- kernel adapter (ResilientKernelAdapter health: error rate, circuit state) ---
    try:
        kernel = getattr(getattr(server, "_builder", None), "_kernel", None)  # cached adapter; None if not yet built
        if kernel is not None and hasattr(kernel, "get_health"):
            kh = kernel.get_health()
            ka_status = kh.get("status", "ok")
            if ka_status == "unhealthy":
                overall = "degraded"
            subsystems["kernel_adapter"] = {
                "status": ka_status,
                "error_rate": kh.get("error_rate", 0.0),
                "total_calls": kh.get("total_calls", 0),
                "buffer_size": kernel.get_buffer_size() if hasattr(kernel, "get_buffer_size") else 0,
            }
        else:
            subsystems["kernel_adapter"] = {"status": "not_built"}
    except Exception:
        subsystems["kernel_adapter"] = {"status": "error"}

    return JSONResponse({
        "status": overall,
        "subsystems": subsystems,
        "timestamp": datetime.now(UTC).isoformat(),
    })


async def handle_ready(request: Request) -> JSONResponse:
    """Return platform readiness contract.

    200 means ready (kernel + capabilities functional).
    503 means not ready (one or more blocking subsystems failed).

    Reads from the live server builder so the response reflects the same
    registries and subsystems used by actual run execution — not a
    reconstructed default snapshot.
    """
    server: AgentServer = request.app.state.agent_server
    try:
        builder = getattr(server, "_builder", None)
        if builder is None:
            # Fallback: server not fully initialized yet
            from hi_agent.config.builder import SystemBuilder
            builder = SystemBuilder(config=getattr(server, "_config", None))
        snapshot = builder.readiness()
    except Exception as exc:
        snapshot = {
            "ready": False,
            "health": "error",
            "error": str(exc),
        }
    status_code = 200 if snapshot.get("ready") else 503
    return JSONResponse(snapshot, status_code=status_code)


async def handle_manifest(request: Request) -> JSONResponse:
    """Return dynamic system capabilities manifest."""
    server: AgentServer = request.app.state.agent_server
    capabilities: list[str] = []
    skills: list[dict] = []
    models: list[dict] = []
    profiles: list[dict] = []
    mcp_servers: list[dict] = []

    # --- Capabilities from live CapabilityInvoker/Registry ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            # Build or reuse the shared invoker — CapabilityInvoker.registry is public.
            invoker = builder.build_invoker()
            if invoker is not None:
                # CapabilityInvoker stores registry as public `registry` attribute.
                registry = getattr(invoker, "registry", None) or getattr(invoker, "_registry", None)
                if registry is not None and hasattr(registry, "list_names"):
                    capabilities = list(registry.list_names())
    except Exception as _cap_exc:
        logger.warning("manifest: capability enumeration failed: %s", _cap_exc)

    # --- Skills ---
    try:
        # Prefer the builder's shared skill_loader singleton; fall back to server attribute.
        builder = getattr(server, "_builder", None)
        skill_loader = None
        if builder is not None and hasattr(builder, "build_skill_loader"):
            skill_loader = builder.build_skill_loader()
        if skill_loader is None:
            skill_loader = getattr(server, "skill_loader", None)
        if skill_loader is not None:
            # discover() returns int (count), not a list — use list_skills() for objects.
            if hasattr(skill_loader, "discover"):
                skill_loader.discover()
            if hasattr(skill_loader, "list_skills"):
                skills = [
                    {"name": getattr(s, "name", str(s)), "source": getattr(s, "source", "unknown")}
                    for s in skill_loader.list_skills()
                ]
    except Exception as _skill_exc:
        logger.warning("manifest: skill enumeration failed: %s", _skill_exc)

    # --- Profiles from ProfileRegistry ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None and hasattr(builder, "build_profile_registry"):
            reg = builder.build_profile_registry()
            if reg is not None and hasattr(reg, "list_profiles"):
                for p in reg.list_profiles():
                    profiles.append({
                        "profile_id": p.profile_id,
                        "display_name": p.display_name,
                        "stage_count": len(p.stage_actions),
                        "has_evaluator": p.evaluator_factory is not None,
                    })
    except Exception as _prof_exc:
        logger.warning("manifest: profile enumeration failed: %s", _prof_exc)

    # --- MCP servers with availability status ---
    try:
        mcp_server_obj = getattr(server, "mcp_server", None)
        if mcp_server_obj is not None:
            mcp_registry = getattr(mcp_server_obj, "_registry", None)
            if mcp_registry is not None and hasattr(mcp_registry, "list_servers"):
                for srv in mcp_registry.list_servers():
                    # Determine tool availability: only available when transport wired.
                    binding = getattr(mcp_server_obj, "_binding", None)
                    unavailable = set(getattr(binding, "_unavailable", []))
                    tools = srv.get("tools", [])
                    server_id = srv["server_id"]
                    mcp_servers.append({
                        "server_id": server_id,
                        "status": srv.get("status", "unknown"),
                        "tools": [
                            {
                                "name": t,
                                "available": f"mcp.{server_id}.{t}" not in unavailable,
                            }
                            for t in tools
                        ],
                    })
    except Exception as _mcp_exc:
        logger.warning("manifest: MCP server enumeration failed: %s", _mcp_exc)

    # --- Active stage list from stage graph ---
    stages: list[str] = []
    try:
        stage_graph = getattr(server, "stage_graph", None)
        if stage_graph is not None:
            transitions = getattr(stage_graph, "transitions", {})
            stages = sorted(transitions.keys())
    except Exception as _stage_exc:
        logger.warning("manifest: stage graph enumeration failed: %s", _stage_exc)

    # --- Models from live tier router ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            tier_router = getattr(builder, "_tier_router", None)
            if tier_router is not None:
                registry = getattr(tier_router, "_registry", None)
                if registry is not None and hasattr(registry, "list_models"):
                    models = [
                        {"name": m if isinstance(m, str) else getattr(m, "name", str(m)), "status": "configured"}
                        for m in registry.list_models()
                    ]
    except Exception as _model_exc:
        logger.warning("manifest: model enumeration failed: %s", _model_exc)

    # --- Plugins from live plugin loader singleton (with discovery) ---
    plugins: list[dict] = []
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None and hasattr(builder, "build_skill_loader"):
            # Use builder to get/initialize the shared plugin loader singleton.
            plugin_loader = getattr(builder, "_plugin_loader", None)
            if plugin_loader is None:
                from hi_agent.plugin.loader import PluginLoader
                plugin_loader = PluginLoader()
                plugin_loader.load_all()  # trigger discovery before listing
                builder._plugin_loader = plugin_loader
            if hasattr(plugin_loader, "list_loaded"):
                plugins = plugin_loader.list_loaded()
    except Exception as _plugin_exc:
        logger.warning("manifest: plugin enumeration failed: %s", _plugin_exc)

    # --- Active profile from config ---
    active_profile: str | None = None
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            cfg = getattr(builder, "_config", None)
            if cfg is not None:
                active_profile = getattr(cfg, "active_profile", None) or getattr(cfg, "profile", None)
    except Exception as _active_prof_exc:
        logger.warning("manifest: active profile lookup failed: %s", _active_prof_exc)

    # --- Runtime mode, environment, and evolve policy ---
    # All three are derived from the same resolvers used by /ready so that
    # /manifest and /ready never drift on these fields.
    evolve_policy: dict = {}
    runtime_mode: str = "dev-smoke"
    manifest_env: str = "dev"
    manifest_llm_mode: str = "unknown"
    manifest_kernel_mode: str = "local-fsm"
    manifest_execution_mode: str = "local"
    provenance_contract_version: str = "unknown"
    try:
        import os as _os_ep
        from hi_agent.config.evolve_policy import resolve_evolve_effective as _rep
        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm
        from hi_agent.contracts.execution_provenance import CONTRACT_VERSION as _cv
        provenance_contract_version = _cv
        _builder = getattr(server, "_builder", None)
        _ev_mode = "auto"
        if _builder is not None:
            _cfg = getattr(_builder, "_config", None)
            if _cfg is not None:
                _ev_mode = getattr(_cfg, "evolve_mode", "auto")
        manifest_env = _os_ep.environ.get("HI_AGENT_ENV", "dev").lower()
        # Obtain a live readiness snapshot so runtime_mode uses the same
        # llm_mode/kernel_mode keys that resolve_runtime_mode expects.
        _readiness_snap: dict = {}
        if _builder is not None:
            try:
                _readiness_snap = _builder.readiness()
            except Exception:
                pass
        runtime_mode = _rrm(manifest_env, _readiness_snap)
        manifest_llm_mode = _readiness_snap.get("llm_mode", "unknown")
        manifest_kernel_mode = _readiness_snap.get("kernel_mode", "local-fsm")
        manifest_execution_mode = _readiness_snap.get("execution_mode", "local")
        _ev_enabled, _ev_source = _rep(_ev_mode, runtime_mode)
        evolve_policy = {"mode": _ev_mode, "effective": _ev_enabled, "source": _ev_source}
    except Exception as _ep_exc:
        logger.warning("manifest: runtime_mode/evolve_policy lookup failed: %s", _ep_exc)

    return JSONResponse({
        "name": "hi-agent",
        "version": "0.1.0",
        "framework": "TRACE",
        "stages": stages,
        "capabilities": capabilities,
        "profiles": profiles,
        "skills": skills,
        "models": models,
        "mcp_servers": mcp_servers,
        "plugins": plugins,
        "evolve_policy": evolve_policy,
        "endpoints": [
            # Core
            "GET /health",
            "GET /ready",
            "GET /manifest",
            # Runs
            "POST /runs",
            "GET /runs",
            "GET /runs/active",
            "GET /runs/{run_id}",
            "GET /runs/{run_id}/artifacts",
            "POST /runs/{run_id}/signal",
            "POST /runs/{run_id}/resume",
            "GET /runs/{run_id}/events",
            # Metrics
            "GET /metrics",
            "GET /metrics/json",
            # Cost
            "GET /cost",
            # Memory
            "POST /memory/dream",
            "POST /memory/consolidate",
            "GET /memory/status",
            # Knowledge
            "POST /knowledge/ingest",
            "POST /knowledge/ingest-structured",
            "GET /knowledge/query",
            "GET /knowledge/status",
            "POST /knowledge/lint",
            "POST /knowledge/sync",
            # Skills
            "GET /skills/list",
            "GET /skills/status",
            "POST /skills/evolve",
            "GET /skills/{skill_id}/metrics",
            "GET /skills/{skill_id}/versions",
            "POST /skills/{skill_id}/optimize",
            "POST /skills/{skill_id}/promote",
            # Context
            "GET /context/health",
            # MCP
            "GET /mcp/status",
            "GET /mcp/tools",
            "POST /mcp/tools/list",
            "POST /mcp/tools/call",
            # Plugins
            "GET /plugins/list",
            "GET /plugins/status",
            # Replay
            "POST /replay/{run_id}",
            "GET /replay/{run_id}/status",
            # Management
            "GET /management/capacity",
            # Tools
            "GET /tools",
            "POST /tools/call",
            # Artifacts
            "GET /artifacts",
            "GET /artifacts/{artifact_id}",
        ],
        "active_profile": active_profile,
        "runtime_mode": runtime_mode,
        "environment": manifest_env,
        "llm_mode": manifest_llm_mode,
        "kernel_mode": manifest_kernel_mode,
        "execution_mode": manifest_execution_mode,
        "provenance_contract_version": provenance_contract_version,
        # Contract field consumption levels — integrators must read this to understand
        # which TaskContract fields the default TRACE pipeline actually acts on.
        # ACTIVE: drives execution behavior or outcome
        # PASSTHROUGH: stored/returned but not consumed by default pipeline
        # QUEUE_ONLY: affects scheduling before execution, not stage behavior
        "contract_field_status": {
            "goal": "ACTIVE",
            "task_family": "ACTIVE",
            "risk_level": "ACTIVE",
            "constraints": "ACTIVE",
            "acceptance_criteria": "ACTIVE",
            "budget": "ACTIVE",
            "deadline": "ACTIVE",
            "profile_id": "ACTIVE",
            "decomposition_strategy": "ACTIVE",
            "priority": "QUEUE_ONLY",
            "environment_scope": "PASSTHROUGH",
            "input_refs": "PASSTHROUGH",
            "parent_task_id": "PASSTHROUGH",
        },
        # Explicit platform E2E contract — integrators must read this to understand
        # what "working" means and under what conditions.
        "e2e_contract": {
            "dev_smoke_path": {
                "status": "available",
                "description": (
                    "Default service mode runs in dev/fallback mode. "
                    "POST /runs → GET /runs/{id} → GET /runs/{id}/artifacts is functional. "
                    "This is a smoke path using heuristic fallback — not production E2E."
                ),
            },
            "production_e2e": {
                "status": "requires_prerequisites",
                "prerequisites": [
                    "OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable",
                    "kernel_base_url set to a real agent-kernel HTTP endpoint",
                    "HI_AGENT_ENV=prod",
                ],
                "description": (
                    "Formal production E2E is not available in default (dev) mode. "
                    "Set HI_AGENT_ENV=prod and provide real credentials + kernel endpoint."
                ),
            },
            "mcp_provider": {
                "status": "infrastructure_only",
                "description": (
                    "External MCP server transport (stdio/SSE/HTTP) is not yet implemented. "
                    "Platform tools are accessible as MCP-compatible endpoints, but "
                    "external server registration and invocation forwarding are deferred."
                ),
            },
        },
    })


async def handle_list_runs(request: Request) -> JSONResponse:
    """List all managed runs."""
    server: AgentServer = request.app.state.agent_server
    manager = server.run_manager
    runs = manager.list_runs()
    return JSONResponse({"runs": [manager.to_dict(r) for r in runs]})


async def handle_runs_active(request: Request) -> JSONResponse:
    """Return currently active run contexts from RunContextManager."""
    server: AgentServer = request.app.state.agent_server
    rcm = getattr(server, "run_context_manager", None)
    if rcm is None:
        return JSONResponse({"run_ids": [], "count": 0, "status": "not_configured"})
    try:
        run_ids = rcm.list_runs()
        return JSONResponse({
            "run_ids": run_ids,
            "count": len(run_ids),
            "status": "ok",
        })
    except Exception as exc:
        logger.warning("handle_runs_active: error fetching active runs: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_create_run(request: Request) -> JSONResponse:
    """Create a new run from the POST body."""
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    if "goal" not in body:
        return JSONResponse({"error": "missing_goal"}, status_code=400)

    server: AgentServer = request.app.state.agent_server
    manager = server.run_manager
    run_id = manager.create_run(body)

    # Register run in RunContextManager so /runs/active reflects live runs.
    rcm = getattr(server, "run_context_manager", None)
    if rcm is not None:
        try:
            rcm.get_or_create(run_id)
        except Exception:
            pass

    # If the server has an executor factory, start the run immediately.
    if server.executor_factory is not None:
        run_data = dict(body, run_id=run_id)
        try:
            task_runner = server.executor_factory(run_data)
        except RuntimeError as exc:
            # Platform subsystem not ready (e.g. LLM gateway requires API key in
            # prod mode). Return 503 so integrators can act on it, not a raw 500.
            logger.warning("handle_create_run: executor_factory failed — %s", exc)
            # Clean up the run we registered above
            try:
                manager.get_run(run_id)  # no-op, just guard
            except Exception:
                pass
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
                    try:
                        rcm.remove(run_id)
                    except Exception:
                        pass

        manager.start_run(run_id, _executor_fn)

    run = manager.get_run(run_id)
    return JSONResponse(manager.to_dict(run), status_code=201)  # type: ignore[arg-type]


async def handle_get_run(request: Request) -> JSONResponse:
    """Return a single run by id."""
    run_id = request.path_params["run_id"]
    server: AgentServer = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id)
    if run is None:
        return JSONResponse(
            {"error": "run_not_found", "run_id": run_id}, status_code=404,
        )
    return JSONResponse(manager.to_dict(run))


async def handle_signal_run(request: Request) -> JSONResponse:
    """Send a signal to an existing run."""
    run_id = request.path_params["run_id"]
    server: AgentServer = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id)
    if run is None:
        return JSONResponse(
            {"error": "run_not_found", "run_id": run_id}, status_code=404,
        )

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    signal = body.get("signal")
    if signal == "cancel":
        ok = manager.cancel_run(run_id)
        if ok:
            return JSONResponse({"run_id": run_id, "state": "cancelled"})
        return JSONResponse(
            {"error": "cannot_cancel", "run_id": run_id}, status_code=409,
        )
    return JSONResponse(
        {"error": "unknown_signal", "signal": signal}, status_code=400,
    )


_feedback_store_fallback: Any = None


def _get_feedback_store(server: "AgentServer") -> Any:
    """Return the server's FeedbackStore, creating a module-level fallback if needed."""
    global _feedback_store_fallback
    store = getattr(server, "_feedback_store", None)
    if store is not None:
        return store
    if _feedback_store_fallback is None:
        from hi_agent.evolve.feedback_store import FeedbackStore
        _feedback_store_fallback = FeedbackStore()
    return _feedback_store_fallback


async def handle_submit_feedback(request: Request) -> JSONResponse:
    """POST /runs/{run_id}/feedback — record explicit feedback for a completed run."""
    run_id = request.path_params["run_id"]
    server: AgentServer = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    rating = body.get("rating")
    if rating is None or not isinstance(rating, (int, float)):
        return JSONResponse({"error": "rating_required", "detail": "rating must be a number"}, status_code=400)
    notes = body.get("notes", "")
    from hi_agent.evolve.feedback_store import RunFeedback
    feedback = RunFeedback(run_id=run_id, rating=float(rating), notes=str(notes))
    store = _get_feedback_store(server)
    store.submit(feedback)
    return JSONResponse({"run_id": run_id, "rating": feedback.rating, "submitted_at": feedback.submitted_at})


async def handle_get_feedback(request: Request) -> JSONResponse:
    """GET /runs/{run_id}/feedback — return feedback for a run."""
    run_id = request.path_params["run_id"]
    server: AgentServer = request.app.state.agent_server
    store = _get_feedback_store(server)
    record = store.get(run_id)
    if record is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    from dataclasses import asdict
    return JSONResponse(asdict(record))


async def handle_resume_run(request: Request) -> JSONResponse:
    """Resume a run from its checkpoint file."""
    import os
    import threading

    run_id = request.path_params["run_id"]

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    # Search for checkpoint file (run os.path.exists off the event loop)
    loop = asyncio.get_event_loop()
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

    server: AgentServer = request.app.state.agent_server

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
                run_id, exc, exc_info=True,
            )

    thread = threading.Thread(target=_resume_in_background, daemon=True)
    thread.start()

    return JSONResponse({
        "status": "resuming",
        "run_id": run_id,
        "checkpoint_path": checkpoint_path,
    })


async def handle_run_events_sse(request: Request) -> StreamingResponse:
    """Stream all events for a run as Server-Sent Events."""
    run_id = request.path_params["run_id"]

    async def generate():  # type: ignore[return]
        q = event_bus.subscribe(run_id)
        try:
            while True:
                event = await q.get()
                data = json.dumps({
                    "run_id": event.run_id,
                    "event_type": event.event_type,
                    "commit_offset": event.commit_offset,
                    "payload": event.payload_json,
                })
                yield f"id: {event.commit_offset}\ndata: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(run_id, q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------
# Metrics endpoints
# ------------------------------------------------------------------

async def handle_metrics_prometheus(request: Request) -> Response:
    """Return metrics in Prometheus exposition format."""
    server: AgentServer = request.app.state.agent_server
    collector = getattr(server, "metrics_collector", None)
    if collector is None:
        return Response(
            "# No metrics collector configured\n",
            media_type="text/plain; charset=utf-8",
        )
    return Response(
        collector.to_prometheus_text(),
        media_type="text/plain; charset=utf-8",
    )


async def handle_metrics_json(request: Request) -> JSONResponse:
    """Return metrics snapshot as JSON."""
    server: AgentServer = request.app.state.agent_server
    collector = getattr(server, "metrics_collector", None)
    if collector is None:
        return JSONResponse({})
    return JSONResponse(collector.snapshot())


async def handle_cost(request: Request) -> JSONResponse:
    """Return LLM cost breakdown sourced from MetricsCollector.

    Response fields:
        total_usd: Cumulative USD spend across all runs.
        per_model_breakdown: Cost by model name (from counter labels).
        per_tier_breakdown: Cost by tier (from counter labels).
        run_count: Number of runs that reported cost.
        avg_cost_per_run: Average cost per run.
    """
    server: AgentServer = request.app.state.agent_server
    collector = getattr(server, "metrics_collector", None)
    if collector is None:
        return JSONResponse({
            "total_usd": 0.0,
            "per_model_breakdown": {},
            "per_tier_breakdown": {},
            "run_count": 0,
            "avg_cost_per_run": 0.0,
        })
    snap = collector.snapshot()

    # Extract total cost from the counter.
    cost_counter = snap.get("llm_cost_usd_total", {})
    total_usd = sum(cost_counter.values()) if cost_counter else 0.0

    # Extract per-run histogram data.
    cost_hist = snap.get("llm_cost_per_run", {})
    run_count = 0
    cost_sum = 0.0
    for entry in cost_hist.values():
        if isinstance(entry, dict):
            run_count += entry.get("count", 0)
            cost_sum += entry.get("sum", 0.0)
    avg_cost = cost_sum / run_count if run_count > 0 else 0.0

    # Per-model and per-tier breakdowns from counter labels.
    per_model: dict[str, float] = {}
    per_tier: dict[str, float] = {}
    for label_key, value in cost_counter.items():
        if isinstance(label_key, str) and "model=" in label_key:
            for part in label_key.split(","):
                part = part.strip()
                if part.startswith("model="):
                    model_name = part.split("=", 1)[1].strip('"')
                    per_model[model_name] = per_model.get(model_name, 0.0) + value
                elif part.startswith("tier="):
                    tier_name = part.split("=", 1)[1].strip('"')
                    per_tier[tier_name] = per_tier.get(tier_name, 0.0) + value

    return JSONResponse({
        "total_usd": total_usd,
        "per_model_breakdown": per_model,
        "per_tier_breakdown": per_tier,
        "run_count": run_count,
        "avg_cost_per_run": avg_cost,
    })


# ------------------------------------------------------------------
# Memory lifecycle handlers
# ------------------------------------------------------------------

async def handle_memory_dream(request: Request) -> JSONResponse:
    """Trigger dream consolidation (short-term -> mid-term)."""
    server: AgentServer = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder
            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.trigger_dream(body.get("date"))
    return JSONResponse(result)


@require_operation("memory.consolidate")
async def handle_memory_consolidate(request: Request) -> JSONResponse:
    """Trigger consolidation (mid-term -> long-term)."""
    server: AgentServer = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder
            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.trigger_consolidation(body.get("days", 7))
    return JSONResponse(result)


async def handle_memory_status(request: Request) -> JSONResponse:
    """Return memory tier status."""
    server: AgentServer = request.app.state.agent_server
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    profile_id = body.get("profile_id", "")
    if profile_id:
        # K-9: Build a per-request scoped manager for profile deployments.
        try:
            from hi_agent.config.builder import SystemBuilder
            _builder = SystemBuilder()
            manager = _builder.build_memory_lifecycle_manager(profile_id=profile_id)
        except Exception as _build_exc:
            return JSONResponse(
                {"error": f"profile_manager_build_failed: {_build_exc}"}, status_code=500
            )
    else:
        manager = server.memory_manager

    if manager is None:
        return JSONResponse({"error": "memory_not_configured"}, status_code=503)

    result = manager.get_status()
    return JSONResponse(result)


# ------------------------------------------------------------------
# Knowledge handlers
# ------------------------------------------------------------------

async def handle_knowledge_ingest(request: Request) -> JSONResponse:
    """Ingest text knowledge as a wiki page."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    title = body.get("title", "")
    content = body.get("content", "")
    if not title or not content:
        return JSONResponse(
            {"error": "missing_title_or_content"}, status_code=400,
        )
    tags = body.get("tags", [])
    page_id = km.ingest_text(title, content, tags)
    return JSONResponse({"page_id": page_id, "status": "created"}, status_code=201)


async def handle_knowledge_ingest_structured(request: Request) -> JSONResponse:
    """Ingest structured facts into the knowledge graph."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    facts = body.get("facts", [])
    count = km.ingest_structured(facts)
    return JSONResponse(
        {"nodes_created": count, "status": "created"}, status_code=201,
    )


async def handle_knowledge_query(request: Request) -> JSONResponse:
    """Query knowledge across all sources."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    q = request.query_params.get("q", "")
    limit = int(request.query_params.get("limit", "10"))
    budget = int(request.query_params.get("budget", "1500"))
    if not q:
        return JSONResponse(
            {"error": "missing_query_param_q"}, status_code=400,
        )
    context = km.query_for_context(q, budget_tokens=budget)
    result = km.query(q, limit=limit)
    return JSONResponse({
        "query": q,
        "total_results": result.total_results,
        "context": context,
    })


async def handle_knowledge_status(request: Request) -> JSONResponse:
    """Return knowledge system stats."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    stats = km.get_stats()
    return JSONResponse(stats)


async def handle_knowledge_lint(request: Request) -> JSONResponse:
    """Run knowledge health check."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    issues = km.lint()
    return JSONResponse({"issues": issues, "count": len(issues)})


async def handle_knowledge_sync(request: Request) -> JSONResponse:
    """Sync graph nodes to wiki pages."""
    server: AgentServer = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"}, status_code=503,
        )
    pages_synced = km.renderer.to_wiki_pages(km.wiki)
    km.wiki.rebuild_index()
    return JSONResponse({
        "pages_synced": pages_synced,
        "status": "completed",
    })


# ------------------------------------------------------------------
# Skill handlers
# ------------------------------------------------------------------

async def handle_skills_list(request: Request) -> JSONResponse:
    """List all discovered skills with eligibility status."""
    server: AgentServer = request.app.state.agent_server
    loader = server.skill_loader
    if loader is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        loader.discover()
        skills = loader.list_skills(eligible_only=False)
        items = []
        for s in skills:
            eligible, reason = s.check_eligibility()
            items.append({
                "skill_id": s.skill_id,
                "name": s.name,
                "version": s.version,
                "description": s.description,
                "lifecycle_stage": s.lifecycle_stage,
                "confidence": s.confidence,
                "eligible": eligible,
                "eligibility_reason": reason,
                "tags": s.tags,
            })
        return JSONResponse({"skills": items, "count": len(items)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skills_status(request: Request) -> JSONResponse:
    """Overall skill system status (counts, top performers)."""
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    loader = server.skill_loader
    if evolver is None or loader is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        loader.discover()
        all_skills = loader.list_skills(eligible_only=False)
        eligible = [s for s in all_skills if s.check_eligibility()[0]]
        all_metrics = evolver._observer.get_all_metrics()

        top = sorted(
            all_metrics.items(),
            key=lambda kv: kv[1].success_rate,
            reverse=True,
        )[:5]
        top_performers = [
            {
                "skill_id": sid,
                "success_rate": m.success_rate,
                "total_executions": m.total_executions,
            }
            for sid, m in top
        ]

        return JSONResponse({
            "total_skills": len(all_skills),
            "eligible_skills": len(eligible),
            "observed_skills": len(all_metrics),
            "top_performers": top_performers,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@require_operation("skill.evolve")
async def handle_skills_evolve(request: Request) -> JSONResponse:
    """Trigger evolution cycle, return EvolutionReport."""
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        from dataclasses import asdict
        report = evolver.evolve_cycle()
        return JSONResponse(asdict(report))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_metrics(request: Request) -> JSONResponse:
    """Get skill metrics from observer."""
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        from dataclasses import asdict
        metrics = evolver._observer.get_metrics(skill_id)
        return JSONResponse(asdict(metrics))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_versions(request: Request) -> JSONResponse:
    """List versions with champion/challenger status."""
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        versions = evolver._version_manager.list_versions(skill_id)
        items = []
        for v in versions:
            items.append({
                "version": v.version,
                "is_champion": v.is_champion,
                "is_challenger": v.is_challenger,
                "created_at": v.created_at,
            })
        return JSONResponse({
            "skill_id": skill_id,
            "versions": items,
            "count": len(items),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_optimize(request: Request) -> JSONResponse:
    """Trigger prompt optimization for one skill."""
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        new_prompt = evolver.optimize_prompt(skill_id)
        if new_prompt is None:
            return JSONResponse({
                "skill_id": skill_id,
                "optimized": False,
                "reason": "no_optimization_needed",
            })
        record = evolver.deploy_optimization(skill_id, new_prompt)
        return JSONResponse({
            "skill_id": skill_id,
            "optimized": True,
            "new_version": record.version,
            "is_challenger": record.is_challenger,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@require_operation("skill.promote")
async def handle_skill_promote(request: Request) -> JSONResponse:
    """Promote challenger to champion."""
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"}, status_code=503,
        )
    try:
        promoted = evolver._version_manager.promote_challenger(skill_id)
        return JSONResponse({
            "skill_id": skill_id,
            "promoted": promoted,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Context health handler
# ------------------------------------------------------------------

async def handle_context_health(request: Request) -> JSONResponse:
    """Return context health report."""
    server: AgentServer = request.app.state.agent_server
    cm = server.context_manager
    if cm is None:
        return JSONResponse(
            {"error": "context_manager_not_configured"}, status_code=503,
        )
    try:
        report = cm.get_health_report()
        return JSONResponse({
            "health": report.health.value,
            "utilization_pct": report.utilization_pct,
            "total_tokens": report.total_tokens,
            "budget_tokens": report.budget_tokens,
            "per_section": report.per_section,
            "compressions_total": report.compressions_total,
            "compression_failures": report.compression_failures,
            "circuit_breaker_open": report.circuit_breaker_open,
            "diminishing_returns": report.diminishing_returns,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Replay handlers
# ------------------------------------------------------------------


async def handle_replay_trigger(request: Request) -> JSONResponse:
    """Trigger replay of a recorded run from its event JSONL file."""
    run_id = request.path_params["run_id"]

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    event_file = body.get("event_file")
    if not event_file:
        import os

        _loop = asyncio.get_event_loop()
        candidates = [
            f"replay_{run_id}.jsonl",
            os.path.join(".hi_agent", f"replay_{run_id}.jsonl"),
        ]
        for candidate in candidates:
            if await _loop.run_in_executor(None, os.path.exists, candidate):
                event_file = candidate
                break

    if not event_file:
        return JSONResponse(
            {"error": "event_file_not_found", "run_id": run_id},
            status_code=404,
        )

    try:
        from hi_agent.replay import ReplayEngine, load_event_envelopes_jsonl

        _loop2 = asyncio.get_event_loop()
        events = await _loop2.run_in_executor(None, load_event_envelopes_jsonl, event_file)
        run_events = [e for e in events if e.run_id == run_id]
        if not run_events:
            return JSONResponse(
                {"error": "no_events_for_run", "run_id": run_id},
                status_code=404,
            )
        report = ReplayEngine().replay(run_events)
        return JSONResponse({
            "run_id": run_id,
            "status": "completed",
            "success": report.success,
            "stage_states": report.stage_states,
            "task_view_count": report.task_view_count,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_replay_status(request: Request) -> JSONResponse:
    """Check whether a replay event file exists for the given run."""
    import os

    run_id = request.path_params["run_id"]
    _loop = asyncio.get_event_loop()
    candidates = [
        f"replay_{run_id}.jsonl",
        os.path.join(".hi_agent", f"replay_{run_id}.jsonl"),
    ]
    for candidate in candidates:
        if await _loop.run_in_executor(None, os.path.exists, candidate):
            return JSONResponse({
                "run_id": run_id,
                "replay_available": True,
                "event_file": candidate,
            })
    return JSONResponse({
        "run_id": run_id,
        "replay_available": False,
    })


# ------------------------------------------------------------------
# Management: capacity advice
# ------------------------------------------------------------------

async def handle_capacity_advice(request: Request) -> JSONResponse:
    """Return capacity tuning recommendations based on current server health.

    The handler re-uses the /health subsystem data as the ``health_payload``
    and, when available, the metrics snapshot as ``metrics_snapshot``.
    This keeps the endpoint self-contained with no external dependencies
    beyond what the server already tracks.
    """
    from hi_agent.management.capacity_advisor import (
        recommend_server_capacity_tuning,
        recommendations_to_payload,
    )

    server: AgentServer = request.app.state.agent_server
    try:
        # Build a minimal health payload that mirrors /health's shape so the
        # advisor can inspect run_manager utilisation statistics.
        run_manager_info: dict[str, Any] = {}
        try:
            status = server.run_manager.get_status()
            active = int(status.get("active_runs", 0))
            queued = int(status.get("queued_runs", 0))
            capacity = int(status.get("total_capacity", 0))
            queue_util = (active + queued) / capacity if capacity > 0 else 0.0
            queue_full = int(status.get("queue_full_rejections", 0))
            queue_timeouts = int(status.get("queue_timeouts", 0))
            run_manager_info = {
                "active_runs": active,
                "queued_runs": queued,
                "capacity": capacity,
                "queue_utilization": queue_util,
                "queue_full_rejections": queue_full,
                "queue_timeouts": queue_timeouts,
            }
        except Exception:
            pass

        health_payload: dict[str, Any] = {
            "subsystems": {"run_manager": run_manager_info},
        }

        # Optional: supply metrics snapshot when a collector is configured.
        metrics_snapshot: dict[str, Any] | None = None
        try:
            collector = getattr(server, "metrics_collector", None)
            if collector is not None:
                metrics_snapshot = collector.snapshot()
        except Exception:
            pass

        recommendations = recommend_server_capacity_tuning(
            health_payload, metrics_snapshot
        )
        return JSONResponse({
            "recommendations": recommendations_to_payload(recommendations),
            "status": "ok",
        })
    except Exception as exc:
        logger.warning("handle_capacity_advice error: %s", exc)
        return JSONResponse({"error": str(exc), "status": "error"}, status_code=500)


# ------------------------------------------------------------------
# Tools (capability registry) endpoints
# ------------------------------------------------------------------

async def handle_tools_list(request: Request) -> JSONResponse:
    """Return all registered capabilities as a tool list.

    Response shape::

        {"tools": [{"name": "file_read", "description": "...", "parameters": {...}}, ...]}
    """
    server: AgentServer = request.app.state.agent_server
    try:
        invoker = server._builder.build_invoker()
        registry = invoker.registry
        tools = []
        for name in registry.list_names():
            spec = registry.get(name)
            tools.append({
                "name": name,
                "description": getattr(spec, "description", ""),
                "parameters": getattr(spec, "parameters", {}),
            })
        return JSONResponse({"tools": tools, "count": len(tools)})
    except Exception as exc:
        logger.warning("handle_tools_list error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_tools_call(request: Request) -> JSONResponse:
    """Invoke a registered capability by name.

    Request body::

        {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}

    Response shape::

        {"success": bool, "result": {...}}
    """
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    name = body.get("name")
    if not name:
        return JSONResponse({"error": "missing_name"}, status_code=400)
    arguments = body.get("arguments", {})

    server: AgentServer = request.app.state.agent_server
    try:
        invoker = server._builder.build_invoker()
        result = invoker.invoke(name, arguments)
        return JSONResponse({"success": True, "result": result})
    except KeyError:
        return JSONResponse(
            {"success": False, "error": f"unknown_tool: {name}"}, status_code=404,
        )
    except Exception as exc:
        logger.warning("handle_tools_call error for %r: %s", name, exc)
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Catch-all for 404
# ------------------------------------------------------------------

async def handle_not_found(request: Request) -> JSONResponse:
    """Return 404 for unmatched routes."""
    return JSONResponse({"error": "not_found"}, status_code=404)


# ------------------------------------------------------------------
# MCP endpoints
# ------------------------------------------------------------------

async def handle_mcp_status(request: Request) -> JSONResponse:
    """Return MCP server registry status.

    Note: MCP external-server transport is not yet wired.  The platform
    exposes its own capabilities via MCP-style endpoints (/mcp/tools/list,
    /mcp/tools/call), but real external MCP server registration, binding,
    and invocation forwarding require a transport layer that is deferred.
    """
    try:
        from hi_agent.mcp.health import MCPHealth
        server: AgentServer = request.app.state.agent_server
        mcp_reg = server.mcp_registry
        # Include tool count from _mcp_server so status and tools endpoints agree.
        tool_count = 0
        mcp_srv = getattr(server, "_mcp_server", None)
        if mcp_srv is not None:
            try:
                tool_count = len(mcp_srv.list_tools().get("tools", []))
            except Exception:
                pass
        # Derive transport status from a real health probe, not merely from
        # whether the transport object exists.  A server whose subprocess fails
        # to answer the JSON-RPC initialize handshake must NOT be reported as
        # "wired" or "external_provider".
        _builder = getattr(server, "_builder", None)
        _transport = getattr(_builder, "_mcp_transport", None) if _builder is not None else None
        health = MCPHealth(mcp_reg, transport=_transport)
        health_results = health.check_all()
        any_healthy = any(s == "healthy" for s in health_results.values())
        if any_healthy:
            transport_status = "wired"
            capability_mode = "external_provider"
            note = (
                "External MCP server transport is active; at least one server passed "
                "a live health check and its tools are bound into the capability registry."
            )
        elif _transport is not None:
            transport_status = "registered_but_unreachable"
            capability_mode = "infrastructure_only"
            note = (
                "Transport object exists but no external MCP server responded to the "
                "health check.  Tools are declared but NOT registered as callable "
                "capabilities.  Verify the server commands in your plugin manifests."
            )
        else:
            transport_status = "not_wired"
            capability_mode = "infrastructure_only"
            note = (
                "No external MCP server transport is active.  Platform tools are accessible "
                "via /mcp/tools/list and /mcp/tools/call as MCP-compatible endpoints.  "
                "Register stdio MCP servers via plugin manifests (mcp_servers field) to "
                "enable external providers."
            )
        return JSONResponse({
            "servers": mcp_reg.list_servers(),
            "health": health.snapshot(),
            "count": len(mcp_reg),
            "tool_count": tool_count,
            "transport_status": transport_status,
            "capability_mode": capability_mode,
            "note": note,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc), "servers": [], "count": 0}, status_code=500)


async def handle_mcp_tools(request: Request) -> JSONResponse:
    """Return all tools across registered MCP servers.

    Prefers _mcp_server (same data source as /mcp/tools/list) so all tool
    endpoints return a consistent view.
    """
    try:
        server: AgentServer = request.app.state.agent_server
        mcp_srv = getattr(server, "_mcp_server", None)
        if mcp_srv is not None:
            try:
                return JSONResponse(mcp_srv.list_tools())
            except Exception:
                pass
        # Fallback: registry-based listing
        mcp_reg = server.mcp_registry
        tools: list[dict] = []
        for srv in mcp_reg.list_servers():
            for tool_name in srv.get("tools", []):
                tools.append({
                    "server_id": srv["server_id"],
                    "tool": tool_name,
                    "capability_name": f"mcp.{srv['server_id']}.{tool_name}",
                })
        return JSONResponse({"tools": tools, "count": len(tools)})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "tools": [], "count": 0}, status_code=500)


async def handle_mcp_tools_list(request: Request) -> JSONResponse:
    """MCP tools/list — enumerate all registered tools with their input schemas.

    Returns an MCP-compatible response:
    {"tools": [{"name": str, "description": str, "inputSchema": {...}}]}
    """
    server: AgentServer = request.app.state.agent_server
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return JSONResponse({"error": "mcp_server_not_configured"}, status_code=503)
    try:
        return JSONResponse(mcp_server.list_tools())
    except Exception as exc:
        logger.exception("handle_mcp_tools_list failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_mcp_tools_call(request: Request) -> JSONResponse:
    """MCP tools/call — invoke a named tool with arguments.

    Request body (flat form):
        {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}

    Or JSON-RPC params envelope:
        {"params": {"name": "file_read", "arguments": {"path": "CLAUDE.md"}}}

    Returns an MCP-compatible content response:
        {"content": [{"type": "text", "text": str}], "isError": bool}
    """
    server: AgentServer = request.app.state.agent_server
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return JSONResponse({"error": "mcp_server_not_configured"}, status_code=503)
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    params = body.get("params", {})
    name = body.get("name") or params.get("name")
    arguments = body.get("arguments", params.get("arguments", {}))
    if not name:
        return JSONResponse({"error": "missing_tool_name"}, status_code=400)
    try:
        result = mcp_server.call_tool(name, arguments or {})
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("handle_mcp_tools_call failed for tool %r", name)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Plugin endpoints
# ------------------------------------------------------------------

async def handle_plugins_list(request: Request) -> JSONResponse:
    """Return list of loaded plugins."""
    try:
        server: AgentServer = request.app.state.agent_server
        plugin_loader = server.plugin_loader
        return JSONResponse({
            "plugins": plugin_loader.list_loaded(),
            "count": len(plugin_loader),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc), "plugins": [], "count": 0}, status_code=500)


async def handle_plugins_status(request: Request) -> JSONResponse:
    """Return plugin system status summary."""
    try:
        server: AgentServer = request.app.state.agent_server
        plugin_loader = server.plugin_loader
        plugins = plugin_loader.list_loaded()
        active = sum(1 for p in plugins if p.get("status") == "active")
        return JSONResponse({
            "total": len(plugins),
            "active": active,
            "inactive": len(plugins) - active,
            "plugins": [{"name": p["name"], "status": p.get("status", "loaded")} for p in plugins],
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Artifact endpoints
# ------------------------------------------------------------------


async def handle_list_artifacts(request: Request) -> JSONResponse:
    """Return all stored artifacts."""
    server: AgentServer = request.app.state.agent_server
    registry = getattr(server, "artifact_registry", None)
    if registry is None:
        return JSONResponse({"artifacts": []})
    artifact_type = request.query_params.get("type")
    producer = request.query_params.get("producer")
    artifacts = registry.query(artifact_type=artifact_type, producer_action_id=producer)
    return JSONResponse({"artifacts": [a.to_dict() for a in artifacts], "count": len(artifacts)})


async def handle_get_artifact(request: Request) -> JSONResponse:
    """Return a single artifact by ID."""
    artifact_id = request.path_params["artifact_id"]
    server: AgentServer = request.app.state.agent_server
    registry = getattr(server, "artifact_registry", None)
    if registry is None:
        return JSONResponse({"error": "artifact_registry_unavailable"}, status_code=503)
    artifact = registry.get(artifact_id)
    if artifact is None:
        return JSONResponse({"error": "not_found", "artifact_id": artifact_id}, status_code=404)
    return JSONResponse(artifact.to_dict())


async def handle_run_artifacts(request: Request) -> JSONResponse:
    """Return artifact IDs associated with a completed run."""
    run_id = request.path_params["run_id"]
    server: AgentServer = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id)
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
    return JSONResponse({"run_id": run_id, "artifacts": artifacts_payload, "count": len(artifacts_payload)})


# ------------------------------------------------------------------
# build_app: construct Starlette application
# ------------------------------------------------------------------

def build_app(agent_server: AgentServer) -> Starlette:
    """Build a Starlette application with all routes.

    Args:
        agent_server: AgentServer instance holding all state.

    Returns:
        Configured Starlette application.
    """
    routes = [
        # Core
        Route("/health", handle_health, methods=["GET"]),
        Route("/ready", handle_ready, methods=["GET"]),
        Route("/manifest", handle_manifest, methods=["GET"]),
        Route("/doctor", handle_doctor, methods=["GET"]),
        Route("/ops/release-gate", handle_release_gate, methods=["GET"]),

        # Runs
        Route("/runs", handle_list_runs, methods=["GET"]),
        Route("/runs", handle_create_run, methods=["POST"]),
        Route("/runs/active", handle_runs_active, methods=["GET"]),
        Route("/runs/{run_id}/artifacts", handle_run_artifacts, methods=["GET"]),
        Route("/runs/{run_id}", handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/signal", handle_signal_run, methods=["POST"]),
        Route("/runs/{run_id}/feedback", handle_submit_feedback, methods=["POST"]),
        Route("/runs/{run_id}/feedback", handle_get_feedback, methods=["GET"]),
        Route("/runs/{run_id}/resume", handle_resume_run, methods=["POST"]),
        Route("/runs/{run_id}/events", handle_run_events_sse, methods=["GET"]),

        # Metrics
        Route("/metrics", handle_metrics_prometheus, methods=["GET"]),
        Route("/metrics/json", handle_metrics_json, methods=["GET"]),

        # Cost
        Route("/cost", handle_cost, methods=["GET"]),

        # Memory
        Route("/memory/dream", handle_memory_dream, methods=["POST"]),
        Route("/memory/consolidate", handle_memory_consolidate, methods=["POST"]),
        Route("/memory/status", handle_memory_status, methods=["GET"]),

        # Knowledge
        Route("/knowledge/ingest", handle_knowledge_ingest, methods=["POST"]),
        Route(
            "/knowledge/ingest-structured",
            handle_knowledge_ingest_structured,
            methods=["POST"],
        ),
        Route("/knowledge/query", handle_knowledge_query, methods=["GET"]),
        Route("/knowledge/status", handle_knowledge_status, methods=["GET"]),
        Route("/knowledge/lint", handle_knowledge_lint, methods=["POST"]),
        Route("/knowledge/sync", handle_knowledge_sync, methods=["POST"]),

        # Skills
        Route("/skills/list", handle_skills_list, methods=["GET"]),
        Route("/skills/status", handle_skills_status, methods=["GET"]),
        Route("/skills/evolve", handle_skills_evolve, methods=["POST"]),
        Route("/skills/{skill_id}/metrics", handle_skill_metrics, methods=["GET"]),
        Route("/skills/{skill_id}/versions", handle_skill_versions, methods=["GET"]),
        Route("/skills/{skill_id}/optimize", handle_skill_optimize, methods=["POST"]),
        Route("/skills/{skill_id}/promote", handle_skill_promote, methods=["POST"]),

        # Context
        Route("/context/health", handle_context_health, methods=["GET"]),

        # MCP
        Route("/mcp/status", handle_mcp_status, methods=["GET"]),
        Route("/mcp/tools", handle_mcp_tools, methods=["GET"]),
        Route("/mcp/tools/list", handle_mcp_tools_list, methods=["POST"]),
        Route("/mcp/tools/call", handle_mcp_tools_call, methods=["POST"]),

        # Plugins
        Route("/plugins/list", handle_plugins_list, methods=["GET"]),
        Route("/plugins/status", handle_plugins_status, methods=["GET"]),

        # Replay
        Route("/replay/{run_id}", handle_replay_trigger, methods=["POST"]),
        Route("/replay/{run_id}/status", handle_replay_status, methods=["GET"]),

        # Management
        Route("/management/capacity", handle_capacity_advice, methods=["GET"]),

        # Tools (capability registry)
        Route("/tools", handle_tools_list, methods=["GET"]),
        Route("/tools/call", handle_tools_call, methods=["POST"]),

        # Artifacts
        Route("/artifacts", handle_list_artifacts, methods=["GET"]),
        Route("/artifacts/{artifact_id}", handle_get_artifact, methods=["GET"]),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):  # type: ignore[misc]
        """Start/stop background subsystems around the Starlette lifespan."""
        mm: MemoryLifecycleManager | None = agent_server.memory_manager
        if mm is not None:
            await mm.start()
        slo = agent_server.slo_monitor
        if slo is not None:
            await slo.start()
        if agent_server._config_stack._base_path:
            agent_server._watcher = ConfigFileWatcher(
                stack=agent_server._config_stack,
                on_reload=agent_server._on_config_reload,
                poll_interval_seconds=2.0,
            )
            asyncio.create_task(agent_server._watcher.start())
            logger.info(
                "ConfigFileWatcher started for %s",
                agent_server._config_stack._base_path,
            )
        try:
            yield
        finally:
            if mm is not None:
                await mm.stop()
            if slo is not None:
                await slo.stop()
            if agent_server._watcher is not None:
                agent_server._watcher.stop()
            mcp_transport = getattr(agent_server._builder, "_mcp_transport", None)
            if mcp_transport is not None and hasattr(mcp_transport, "close_all"):
                mcp_transport.close_all()
                logger.info("lifespan: MCP transport subprocesses closed.")
            evidence_store = getattr(agent_server._builder, "_evidence_store", None)
            if evidence_store is not None and hasattr(evidence_store, "close"):
                evidence_store.close()
                logger.info("lifespan: SqliteEvidenceStore connection closed.")

    app = Starlette(routes=routes, lifespan=lifespan)

    # Auth middleware (outermost — rejects unauthenticated requests before
    # they reach rate limiting or route handlers).
    # Enabled only when HI_AGENT_API_KEY env-var is set; no-op otherwise.
    app.add_middleware(AuthMiddleware)

    # Rate limiting middleware.
    app.add_middleware(
        RateLimiter,
        max_requests=agent_server._rate_limit_rps,
        window_seconds=60.0,
        burst=max(20, agent_server._rate_limit_rps // 5),
    )

    # Attach agent server reference so handlers can access it.
    app.state.agent_server = agent_server

    # Catch-all for HTTP exceptions. Starlette by default returns plain-text
    # bodies; we override to return JSON for all status codes, and pass dict
    # details through as-is (required for typed 403 payloads from auth guards).
    from starlette.exceptions import HTTPException

    async def http_exception_handler(
        request: Request, exc: HTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse({"error": "not_found"}, status_code=404)
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(detail, status_code=exc.status_code)

    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(404, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(405, http_exception_handler)  # type: ignore[arg-type]

    return app


# ------------------------------------------------------------------
# AgentServer: main server class (backward compatible)
# ------------------------------------------------------------------

class AgentServer:
    """Agent server that holds agent state and runs via uvicorn."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        config: Any | None = None,
        rate_limit_rps: int = 100,
        profile_registry: Any | None = None,
    ) -> None:
        """Initialize the agent server.

        Args:
            host: Bind address.
            port: Bind port.
            config: Optional TraceConfig instance. When provided, a
                :class:`SystemBuilder` is created and the default
                executor factory is wired automatically.
            rate_limit_rps: Maximum requests per 60-second window for
                the rate-limiting middleware (per client IP).
            profile_registry: Optional pre-populated ProfileRegistry.  When
                provided, it is injected into the internal SystemBuilder so that
                business-agent profiles registered before server construction are
                available for executor resolution without modifying platform
                internals.
        """
        self._host = host
        self._port = port
        self._rate_limit_rps = rate_limit_rps
        self.server_address = (host, port)
        self.memory_manager: MemoryLifecycleManager | None = None
        self.knowledge_manager: Any | None = None
        self.skill_evolver: Any | None = None
        self.skill_loader: Any | None = None
        self.context_manager: Any | None = None
        self.metrics_collector: Any | None = None
        self.run_context_manager: Any | None = None
        self.capacity_advisor: Any | None = None
        self.slo_monitor: Any | None = None

        # stage_graph — the active stage topology for this server instance.
        # Business agents that inject a custom stage graph should also set this
        # attribute so the /manifest endpoint reflects the real topology.
        # Defaults to the sample TRACE S1-S5 graph; can be replaced at startup.
        from hi_agent.trajectory.stage_graph import default_trace_stage_graph
        self.stage_graph = default_trace_stage_graph()

        import os

        # Lazy import to avoid circular dependency at module level.
        from hi_agent.config.trace_config import TraceConfig

        self._config = config if config is not None else TraceConfig()

        # Platform default: dev mode (heuristic fallback, in-process kernel).
        # Users opt into prod mode explicitly via HI_AGENT_ENV=prod or --prod.
        # This ensures the server works out of the box for both CLI and
        # programmatic users without external dependencies.
        os.environ.setdefault("HI_AGENT_ENV", "dev")

        # Config stack for hot-reload and per-run overrides.
        base_config_path = os.environ.get("HI_AGENT_CONFIG_FILE")
        self._config_stack = ConfigStack(
            base_config_path=base_config_path,
            profile=os.environ.get("HI_AGENT_PROFILE"),
            env=os.environ.get("HI_AGENT_ENV", "dev"),
        )
        if base_config_path:
            # Use stack-resolved config (incorporates file + profile + env).
            self._config = self._config_stack.resolve()
        self._watcher: ConfigFileWatcher | None = None

        # RunManager respects server_max_concurrent_runs from config.
        self.run_manager = RunManager(
            max_concurrent=self._config.server_max_concurrent_runs,
        )

        from hi_agent.config.builder import SystemBuilder

        self._builder = SystemBuilder(
            self._config,
            config_stack=self._config_stack,
            profile_registry=profile_registry,
        )
        # Generation counter incremented on each config reload.  In-flight runs
        # capture a reference to the executor at dispatch time and are unaffected
        # by subsequent reloads.  Only new runs get the new builder.
        self._builder_generation: int = 0
        self.executor_factory: Callable[..., Callable[..., Any]] | None = (
            self._default_executor_factory
        )

        # Build a shared CapabilityInvoker and wire MCPServer.
        try:
            from hi_agent.server.mcp import MCPServer
            _invoker = self._builder.build_invoker()
            self._mcp_server: Any | None = MCPServer(
                registry=_invoker.registry,
                invoker=_invoker,
            )
        except Exception as _exc:
            logger.warning("MCPServer initialization failed (%s: %s); /mcp/tools/* endpoints will be unavailable.", type(_exc).__name__, _exc)
            self._mcp_server = None

        # Build shared ArtifactRegistry so artifact endpoints can serve stored artifacts.
        self.artifact_registry = self._builder.build_artifact_registry()

        # Build shared MCPRegistry so all /mcp/* endpoints use the same instance.
        self.mcp_registry = self._builder.build_mcp_registry()

        # Build shared PluginLoader so /plugins/* endpoints use the builder's cached
        # instance instead of creating orphan loaders that bypass registered state.
        self.plugin_loader = self._builder.build_plugin_loader()

        # Wire server-level subsystems so /health, /memory/*, /skills/*,
        # /context/* endpoints operate on live instances rather than None.
        try:
            self.memory_manager = self._builder.build_memory_lifecycle_manager()
        except Exception as _exc:
            logger.warning("MemoryLifecycleManager initialization failed (%s: %s); /memory/* endpoints will be unavailable.", type(_exc).__name__, _exc)
        try:
            self.knowledge_manager = self._builder.build_knowledge_manager()
        except Exception as _exc:
            logger.warning("KnowledgeManager initialization failed (%s: %s); /knowledge/* endpoints will be unavailable.", type(_exc).__name__, _exc)
        try:
            self.skill_evolver = self._builder.build_skill_evolver()
            self.skill_loader = self._builder.build_skill_loader()
        except Exception as _exc:
            logger.warning("SkillEvolver/SkillLoader initialization failed (%s: %s); /skills/* endpoints will be unavailable.", type(_exc).__name__, _exc)
        try:
            self.metrics_collector = self._builder.build_metrics_collector()
        except Exception as _exc:
            logger.warning("MetricsCollector initialization failed (%s: %s); metrics endpoints will be unavailable.", type(_exc).__name__, _exc)
        try:
            self.run_context_manager = self._builder._build_run_context_manager()
        except Exception as _exc:
            logger.warning("RunContextManager initialization failed (%s: %s).", type(_exc).__name__, _exc)
        try:
            self.context_manager = self._builder.build_context_manager()
        except Exception as _exc:
            logger.warning("ContextManager initialization failed (%s: %s); /context/* endpoints will be unavailable.", type(_exc).__name__, _exc)
        try:
            from hi_agent.management.slo import SLOMonitor
            if self.metrics_collector is not None:
                self.slo_monitor = SLOMonitor(self.metrics_collector)
        except Exception as _exc:
            logger.warning("SLOMonitor initialization failed (%s: %s); SLO monitoring disabled.", type(_exc).__name__, _exc)

        # Wire plugin contributions (skill_dirs, mcp_servers) into live subsystems
        # now that all subsystems are built.
        try:
            self._builder._wire_plugin_contributions()
        except Exception as _exc:
            logger.warning("Plugin contribution wiring failed (%s: %s); plugin capabilities may be unavailable.", type(_exc).__name__, _exc)

        # Sync file-discovered skills into SkillRegistry so both subsystems
        # share the same skill set.
        try:
            if self.skill_loader is not None:
                _skill_registry = self._builder.build_skill_registry()
                self.skill_loader.sync_to_registry(_skill_registry)
        except Exception as _exc:
            logger.warning("SkillLoader→SkillRegistry sync failed (%s: %s).", type(_exc).__name__, _exc)

        # Build the Starlette app.
        self._app = build_app(self)

    @property
    def app(self) -> Starlette:
        """Return the Starlette ASGI application."""
        return self._app

    def _default_executor_factory(
        self, run_data: dict[str, Any],
    ) -> Callable[..., Any]:
        """Create a callable that runs a task to completion.

        Args:
            run_data: Dictionary with at least ``goal``; may contain any
                field from :class:`~hi_agent.contracts.task.TaskContract`
                including ``task_id``, ``run_id``, ``task_family``,
                ``risk_level``, ``constraints``, ``acceptance_criteria``,
                ``budget``, ``deadline``, ``environment_scope``,
                ``input_refs``, ``priority``, ``parent_task_id``,
                ``decomposition_strategy``, and ``profile_id``.

        Returns:
            A zero-argument callable whose invocation drives the task
            through the TRACE pipeline.
        """
        import uuid

        from hi_agent.contracts import TaskContract
        from hi_agent.contracts.task import TaskBudget

        task_id = (
            run_data.get("task_id")
            or run_data.get("run_id")
            or uuid.uuid4().hex[:12]
        )

        # Reconstruct TaskBudget from dict if the caller supplied one.
        budget: TaskBudget | None = None
        budget_data = run_data.get("budget")
        if isinstance(budget_data, dict):
            budget = TaskBudget(
                max_llm_calls=budget_data.get("max_llm_calls", 100),
                max_wall_clock_seconds=budget_data.get("max_wall_clock_seconds", 3600),
                max_actions=budget_data.get("max_actions", 50),
                max_cost_cents=budget_data.get("max_cost_cents", 1000),
            )
        elif isinstance(budget_data, TaskBudget):
            budget = budget_data

        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            constraints=run_data.get("constraints") or [],
            acceptance_criteria=run_data.get("acceptance_criteria") or [],
            task_family=run_data.get("task_family", "quick_task"),
            budget=budget,
            deadline=run_data.get("deadline"),
            risk_level=run_data.get("risk_level", "low"),
            environment_scope=run_data.get("environment_scope") or [],
            input_refs=run_data.get("input_refs") or [],
            priority=int(run_data.get("priority", 5)),
            parent_task_id=run_data.get("parent_task_id"),
            decomposition_strategy=run_data.get("decomposition_strategy"),
            profile_id=run_data.get("profile_id"),
        )
        config_patch = run_data.get("config_patch")  # optional dict, may be None
        executor = self._builder.build_executor(contract, config_patch=config_patch)

        def run() -> Any:
            return executor.execute()

        return run

    def run(self, host: str | None = None, port: int | None = None) -> None:
        """Start serving with uvicorn (blocking).

        Args:
            host: Override bind address (defaults to value from __init__).
            port: Override bind port (defaults to value from __init__).
        """
        import uvicorn

        h = host or self._host
        p = port or self._port
        print(f"hi-agent server listening on ({h!r}, {p})")
        uvicorn.run(self._app, host=h, port=p)

    def serve_forever(self) -> None:
        """Start serving (blocking). Backward-compatible alias for run()."""
        self.run()

    def start(self) -> None:
        """Start serving (blocking). Alias for run()."""
        self.run()

    def shutdown(self) -> None:
        """No-op for backward compatibility with stdlib HTTPServer."""

    async def _on_config_reload(self, new_cfg: Any) -> None:
        """Called by ConfigFileWatcher when config files change.

        Safety contract:
        - In-flight runs already hold a direct reference to their ``RunExecutor``
          instance, which was built from the *previous* builder.  Replacing
          ``self._builder`` does NOT affect those executors — they continue to
          run to completion with their original configuration.
        - Shared subsystem singletons (skill_loader, memory_manager, etc.) are
          inherited by the new builder so their cached state is preserved across
          the reload.  This prevents double-initialisation and avoids orphaning
          objects that server endpoints (e.g. ``/memory/*``) still reference.
        - The generation counter is incremented so callers can detect reloads.
        """
        old_builder = self._builder
        self._config = new_cfg
        from hi_agent.config.builder import SystemBuilder
        new_builder = SystemBuilder(config=new_cfg, config_stack=self._config_stack)
        # Inherit subsystem singletons so in-flight server-level references remain valid.
        new_builder._skill_loader = old_builder._skill_loader
        new_builder._mcp_registry = old_builder._mcp_registry
        new_builder._mcp_transport = old_builder._mcp_transport
        new_builder._plugin_loader = old_builder._plugin_loader
        self._builder = new_builder
        self._builder_generation += 1
        logger.info(
            "Config reloaded (generation=%d). New server_port=%s",
            self._builder_generation,
            getattr(new_cfg, "server_port", None),
        )


# ------------------------------------------------------------------
# Backward-compatible AgentAPIHandler shim
# ------------------------------------------------------------------

class AgentAPIHandler:
    """Backward-compatible shim for code that references AgentAPIHandler.

    This class preserves the interface used by existing tests that
    construct handler instances directly via ``__new__`` and call
    handler methods with a test ``server`` attribute.  The ``_send_json``
    and ``_send_text`` methods are available for monkey-patching in
    tests.
    """

    server: Any = None

    @property
    def _manager(self) -> RunManager:
        """Access the RunManager from the server instance."""
        return self.server.run_manager

    @property
    def _memory_manager(self) -> MemoryLifecycleManager | None:
        """Access the MemoryLifecycleManager from the server instance."""
        return self.server.memory_manager

    @property
    def _knowledge_manager(self) -> Any | None:
        """Access the KnowledgeManager from the server instance."""
        return self.server.knowledge_manager

    @property
    def _skill_evolver(self) -> Any | None:
        """Access the SkillEvolver from the server instance."""
        return self.server.skill_evolver

    @property
    def _skill_loader(self) -> Any | None:
        """Access the SkillLoader from the server instance."""
        return self.server.skill_loader

    @property
    def _context_manager(self) -> Any | None:
        """Access the ContextManager from the server instance."""
        return self.server.context_manager

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        """Send a JSON response (for test monkey-patching)."""

    def _send_text(self, status: int, text: str) -> None:
        """Send a plain-text response (for test monkey-patching)."""

    def _read_json_body(self) -> dict[str, Any]:
        """Read and parse the request body as JSON (for test monkey-patching)."""
        return {}

    # Retain handler methods that tests call directly.

    def _handle_context_health(self) -> None:
        """Return context health report."""
        cm = self._context_manager
        if cm is None:
            self._send_json(503, {"error": "context_manager_not_configured"})
            return
        try:
            report = cm.get_health_report()
            self._send_json(200, {
                "health": report.health.value,
                "utilization_pct": report.utilization_pct,
                "total_tokens": report.total_tokens,
                "budget_tokens": report.budget_tokens,
                "per_section": report.per_section,
                "compressions_total": report.compressions_total,
                "compression_failures": report.compression_failures,
                "circuit_breaker_open": report.circuit_breaker_open,
                "diminishing_returns": report.diminishing_returns,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skills_list(self) -> None:
        """List all discovered skills with eligibility status."""
        loader = self._skill_loader
        if loader is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            loader.discover()
            skills = loader.list_skills(eligible_only=False)
            items = []
            for s in skills:
                eligible, reason = s.check_eligibility()
                items.append({
                    "skill_id": s.skill_id,
                    "name": s.name,
                    "version": s.version,
                    "description": s.description,
                    "lifecycle_stage": s.lifecycle_stage,
                    "confidence": s.confidence,
                    "eligible": eligible,
                    "eligibility_reason": reason,
                    "tags": s.tags,
                })
            self._send_json(200, {"skills": items, "count": len(items)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skills_evolve(self) -> None:
        """Trigger evolution cycle, return EvolutionReport."""
        evolver = self._skill_evolver
        if evolver is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            from dataclasses import asdict
            report = evolver.evolve_cycle()
            self._send_json(200, asdict(report))
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skill_metrics(self, skill_id: str) -> None:
        """Get skill metrics from observer."""
        evolver = self._skill_evolver
        if evolver is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            from dataclasses import asdict
            metrics = evolver._observer.get_metrics(skill_id)
            self._send_json(200, asdict(metrics))
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skill_versions(self, skill_id: str) -> None:
        """List versions with champion/challenger status."""
        evolver = self._skill_evolver
        if evolver is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            versions = evolver._version_manager.list_versions(skill_id)
            items = []
            for v in versions:
                items.append({
                    "version": v.version,
                    "is_champion": v.is_champion,
                    "is_challenger": v.is_challenger,
                    "created_at": v.created_at,
                })
            self._send_json(200, {
                "skill_id": skill_id,
                "versions": items,
                "count": len(items),
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skill_optimize(self, skill_id: str) -> None:
        """Trigger prompt optimization for one skill."""
        evolver = self._skill_evolver
        if evolver is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            new_prompt = evolver.optimize_prompt(skill_id)
            if new_prompt is None:
                self._send_json(200, {
                    "skill_id": skill_id,
                    "optimized": False,
                    "reason": "no_optimization_needed",
                })
                return
            record = evolver.deploy_optimization(skill_id, new_prompt)
            self._send_json(200, {
                "skill_id": skill_id,
                "optimized": True,
                "new_version": record.version,
                "is_challenger": record.is_challenger,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skill_promote(self, skill_id: str) -> None:
        """Promote challenger to champion."""
        evolver = self._skill_evolver
        if evolver is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            promoted = evolver._version_manager.promote_challenger(skill_id)
            self._send_json(200, {
                "skill_id": skill_id,
                "promoted": promoted,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_skills_status(self) -> None:
        """Overall skill system status (counts, top performers)."""
        evolver = self._skill_evolver
        loader = self._skill_loader
        if evolver is None or loader is None:
            self._send_json(503, {"error": "skills_not_configured"})
            return
        try:
            loader.discover()
            all_skills = loader.list_skills(eligible_only=False)
            eligible = [s for s in all_skills if s.check_eligibility()[0]]
            all_metrics = evolver._observer.get_all_metrics()

            top = sorted(
                all_metrics.items(),
                key=lambda kv: kv[1].success_rate,
                reverse=True,
            )[:5]
            top_performers = [
                {
                    "skill_id": sid,
                    "success_rate": m.success_rate,
                    "total_executions": m.total_executions,
                }
                for sid, m in top
            ]

            self._send_json(200, {
                "total_skills": len(all_skills),
                "eligible_skills": len(eligible),
                "observed_skills": len(all_metrics),
                "top_performers": top_performers,
            })
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_memory_dream(self) -> None:
        """Trigger dream consolidation (short-term -> mid-term)."""
        manager = self._memory_manager
        if manager is None:
            self._send_json(503, {"error": "memory_not_configured"})
            return
        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            body = {}
        result = manager.trigger_dream(body.get("date"))
        self._send_json(200, result)

    def _handle_memory_consolidate(self) -> None:
        """Trigger consolidation (mid-term -> long-term)."""
        manager = self._memory_manager
        if manager is None:
            self._send_json(503, {"error": "memory_not_configured"})
            return
        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            body = {}
        result = manager.trigger_consolidation(body.get("days", 7))
        self._send_json(200, result)

    def _handle_memory_status(self) -> None:
        """Return memory tier status."""
        manager = self._memory_manager
        if manager is None:
            self._send_json(503, {"error": "memory_not_configured"})
            return
        result = manager.get_status()
        self._send_json(200, result)

    def _handle_resume_run(self, run_id: str) -> None:
        """Resume a run from its checkpoint file."""
        import os
        import threading

        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            body = {}

        checkpoint_path = body.get("checkpoint_path")
        if not checkpoint_path:
            candidates = [
                f"checkpoint_{run_id}.json",
                os.path.join(".hi_agent", f"checkpoint_{run_id}.json"),
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    checkpoint_path = candidate
                    break

        if not checkpoint_path or not os.path.exists(checkpoint_path):
            self._send_json(404, {
                "error": "checkpoint_not_found",
                "run_id": run_id,
            })
            return

        server = self.server

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
            except Exception:
                pass

        thread = threading.Thread(
            target=_resume_in_background, daemon=True,
        )
        thread.start()

        self._send_json(200, {
            "status": "resuming",
            "run_id": run_id,
            "checkpoint_path": checkpoint_path,
        })
