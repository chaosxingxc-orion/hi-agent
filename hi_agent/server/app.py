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
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi_agent.auth.operation_policy import require_operation
from hi_agent.config.posture import Posture
from hi_agent.config.stack import ConfigStack
from hi_agent.config.watcher import ConfigFileWatcher
from hi_agent.server._durable_backends import build_durable_backends
from hi_agent.server.auth_middleware import AuthMiddleware
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.event_bus import event_bus
from hi_agent.server.ops_routes import handle_diagnostics, handle_doctor, handle_release_gate
from hi_agent.server.rate_limiter import RateLimiter
from hi_agent.server.routes_artifacts import (
    artifact_routes,
)
from hi_agent.server.routes_events import handle_run_events_sse
from hi_agent.server.routes_manifest import MANIFEST_ROUTES
from hi_agent.server.routes_ops import handle_cancel_long_op, handle_get_long_op
from hi_agent.server.routes_ops_dlq import handle_list_dlq, handle_requeue_from_dlq
from hi_agent.server.routes_profiles import (
    handle_global_l3_summary,
    handle_global_skills,
)
from hi_agent.server.routes_runs import (
    handle_cancel_run,
    handle_create_run,
    handle_gate_decision,
    handle_get_feedback,
    handle_get_run,
    handle_list_runs,
    handle_reasoning_trace,
    handle_resume_run,
    handle_run_artifacts,
    handle_runs_active,
    handle_signal_run,
    handle_submit_feedback,
)
from hi_agent.server.routes_sessions import (
    handle_get_session_runs,
    handle_list_sessions,
    handle_patch_session,
)
from hi_agent.server.routes_team import handle_list_team_events
from hi_agent.server.routes_tools_mcp import (
    handle_mcp_tools,
    handle_mcp_tools_call,
    handle_mcp_tools_list,
    handle_tools_call,
    handle_tools_list,
)
from hi_agent.server.run_manager import RunManager
from hi_agent.server.session_store import SessionStore
from hi_agent.server.team_event_store import TeamEventStore

logger = logging.getLogger(__name__)


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
        kernel = getattr(
            getattr(server, "_builder", None), "_kernel", None
        )  # cached adapter; None if not yet built
        if kernel is not None and hasattr(kernel, "get_health"):
            kh = kernel.get_health()
            ka_status = kh.get("status", "ok")
            if ka_status == "unhealthy":
                overall = "degraded"
            subsystems["kernel_adapter"] = {
                "status": ka_status,
                "error_rate": kh.get("error_rate", 0.0),
                "total_calls": kh.get("total_calls", 0),
                "buffer_size": kernel.get_buffer_size()
                if hasattr(kernel, "get_buffer_size")
                else 0,
            }
        else:
            # P0-4: "not_built" previously misled operators into thinking the
            # kernel was broken. Kernel adapters are lazily built on first run;
            # surface the configured mode + lazy status instead.
            _cfg = getattr(server, "_config", None)
            _cfg_url = getattr(_cfg, "kernel_base_url", "") if _cfg is not None else ""
            _cfg_mode = "http" if _cfg_url and _cfg_url.lower() != "local" else "local-fsm"
            subsystems["kernel_adapter"] = {
                "status": "lazy",
                "configured_mode": _cfg_mode,
                "configured_base_url": _cfg_url,
            }
    except Exception:
        subsystems["kernel_adapter"] = {"status": "error"}

    return JSONResponse(
        {
            "status": overall,
            "subsystems": subsystems,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


async def handle_ready(request: Request) -> JSONResponse:
    """Return platform readiness contract.

    200 means ready (kernel + capabilities functional).
    503 means not ready (one or more blocking subsystems failed).

    Reads from the live server builder so the response reflects the same
    registries and subsystems used by actual run execution — not a
    reconstructed default snapshot.
    """
    import os as _os_rdy

    from hi_agent.server.auth_middleware import AuthMiddleware as _AM_rdy
    from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm_rdy

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

    # Augment snapshot with auth_posture.
    try:
        _env_rdy = _os_rdy.environ.get("HI_AGENT_ENV", "dev").lower()
        _runtime_mode_rdy = _rrm_rdy(_env_rdy, snapshot)
        _auth_rdy = _AM_rdy(app=lambda *a: None, runtime_mode=_runtime_mode_rdy)  # type: ignore[arg-type]
        snapshot = dict(snapshot, auth_posture=_auth_rdy.auth_posture)
    except Exception:
        snapshot = dict(snapshot, auth_posture="unknown")

    # Augment snapshot with fine-grained readiness flags.
    try:
        _subsystem_ready = bool(snapshot.get("ready", False))
        _draining = getattr(server, "_draining", False)
        _run_mgr = getattr(server, "run_manager", None)
        if _run_mgr is not None:
            _queue_saturated = _run_mgr.queue_depth() >= _run_mgr.max_queue_depth
        else:
            _queue_saturated = False
        _ready_to_accept = _subsystem_ready and not _draining and not _queue_saturated
        snapshot = dict(
            snapshot,
            flags={
                "ready_to_serve": _subsystem_ready,
                "ready_to_accept_new_runs": _ready_to_accept,
            },
        )
    except Exception:
        pass

    status_code = 200 if snapshot.get("ready") else 503
    return JSONResponse(snapshot, status_code=status_code)


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
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_cost

    try:
        _rtc_cost()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: AgentServer = request.app.state.agent_server
    collector = getattr(server, "metrics_collector", None)
    if collector is None:
        return JSONResponse(
            {
                "total_usd": 0.0,
                "per_model_breakdown": {},
                "per_tier_breakdown": {},
                "run_count": 0,
                "avg_cost_per_run": 0.0,
            }
        )
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

    return JSONResponse(
        {
            "total_usd": total_usd,
            "per_model_breakdown": per_model,
            "per_tier_breakdown": per_tier,
            "run_count": run_count,
            "avg_cost_per_run": avg_cost,
        }
    )


# ------------------------------------------------------------------
# Memory lifecycle handlers (extracted to routes_memory.py)
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Knowledge handlers (extracted to routes_knowledge.py)
# ------------------------------------------------------------------
from hi_agent.server.routes_knowledge import (
    handle_knowledge_ingest,
    handle_knowledge_ingest_structured,
    handle_knowledge_lint,
    handle_knowledge_query,
    handle_knowledge_status,
    handle_knowledge_sync,
)
from hi_agent.server.routes_memory import (
    handle_memory_consolidate,
    handle_memory_dream,
    handle_memory_status,
)

# ------------------------------------------------------------------
# Skill handlers
# ------------------------------------------------------------------


async def handle_skills_list(request: Request) -> JSONResponse:
    """List all discovered skills with eligibility status."""
    # TODO: per-tenant skill overlay needed — currently returns global registry to all tenants.
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_sl

    try:
        _rtc_sl()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: AgentServer = request.app.state.agent_server
    loader = server.skill_loader
    if loader is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        loader.discover()
        skills = loader.list_skills(eligible_only=False)
        items = []
        for s in skills:
            eligible, reason = s.check_eligibility()
            items.append(
                {
                    "skill_id": s.skill_id,
                    "name": s.name,
                    "version": s.version,
                    "description": s.description,
                    "lifecycle_stage": s.lifecycle_stage,
                    "confidence": s.confidence,
                    "eligible": eligible,
                    "eligibility_reason": reason,
                    "tags": s.tags,
                }
            )
        return JSONResponse({"skills": items, "count": len(items)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skills_status(request: Request) -> JSONResponse:
    """Overall skill system status (counts, top performers)."""
    # TODO: per-tenant skill overlay needed — currently returns global stats to all tenants.
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_ss

    try:
        _rtc_ss()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    loader = server.skill_loader
    if evolver is None or loader is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
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

        return JSONResponse(
            {
                "total_skills": len(all_skills),
                "eligible_skills": len(eligible),
                "observed_skills": len(all_metrics),
                "top_performers": top_performers,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@require_operation("skill.evolve")
async def handle_skills_evolve(request: Request) -> JSONResponse:
    """Trigger evolution cycle, return EvolutionReport."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_se

    try:
        _rtc_se()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        from dataclasses import asdict

        report = evolver.evolve_cycle()
        return JSONResponse(asdict(report))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_metrics(request: Request) -> JSONResponse:
    """Get skill metrics from observer."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_sm

    try:
        _rtc_sm()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        from dataclasses import asdict

        metrics = evolver._observer.get_metrics(skill_id)
        return JSONResponse(asdict(metrics))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_versions(request: Request) -> JSONResponse:
    """List versions with champion/challenger status."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_sv

    try:
        _rtc_sv()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        versions = evolver._version_manager.list_versions(skill_id)
        items = []
        for v in versions:
            items.append(
                {
                    "version": v.version,
                    "is_champion": v.is_champion,
                    "is_challenger": v.is_challenger,
                    "created_at": v.created_at,
                }
            )
        return JSONResponse(
            {
                "skill_id": skill_id,
                "versions": items,
                "count": len(items),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_skill_optimize(request: Request) -> JSONResponse:
    """Trigger prompt optimization for one skill."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_so

    try:
        _rtc_so()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        new_prompt = evolver.optimize_prompt(skill_id)
        if new_prompt is None:
            return JSONResponse(
                {
                    "skill_id": skill_id,
                    "optimized": False,
                    "reason": "no_optimization_needed",
                }
            )
        record = evolver.deploy_optimization(skill_id, new_prompt)
        return JSONResponse(
            {
                "skill_id": skill_id,
                "optimized": True,
                "new_version": record.version,
                "is_challenger": record.is_challenger,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@require_operation("skill.promote")
async def handle_skill_promote(request: Request) -> JSONResponse:
    """Promote challenger to champion."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_sp

    try:
        _rtc_sp()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    skill_id = request.path_params["skill_id"]
    server: AgentServer = request.app.state.agent_server
    evolver = server.skill_evolver
    if evolver is None:
        return JSONResponse(
            {"error": "skills_not_configured"},
            status_code=503,
        )
    try:
        promoted = evolver._version_manager.promote_challenger(skill_id)
        return JSONResponse(
            {
                "skill_id": skill_id,
                "promoted": promoted,
            }
        )
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
            {"error": "context_manager_not_configured"},
            status_code=503,
        )
    try:
        report = cm.get_health_report()
        return JSONResponse(
            {
                "health": report.health.value,
                "utilization_pct": report.utilization_pct,
                "total_tokens": report.total_tokens,
                "budget_tokens": report.budget_tokens,
                "per_section": report.per_section,
                "compressions_total": report.compressions_total,
                "compression_failures": report.compression_failures,
                "circuit_breaker_open": report.circuit_breaker_open,
                "diminishing_returns": report.diminishing_returns,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Replay handlers
# ------------------------------------------------------------------


async def handle_replay_trigger(request: Request) -> JSONResponse:
    """Trigger replay of a recorded run from its event JSONL file."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_rt

    try:
        _ctx_rt = _rtc_rt()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    run_id = request.path_params["run_id"]

    # Ownership gate: ensure caller owns this run
    _mgr_rt = request.app.state.agent_server.run_manager
    if _mgr_rt.get_run(run_id, workspace=_ctx_rt) is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    event_file = body.get("event_file")
    if not event_file:
        import os

        _loop = asyncio.get_running_loop()
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

        _loop2 = asyncio.get_running_loop()
        events = await _loop2.run_in_executor(None, load_event_envelopes_jsonl, event_file)
        run_events = [e for e in events if e.run_id == run_id]
        if not run_events:
            return JSONResponse(
                {"error": "no_events_for_run", "run_id": run_id},
                status_code=404,
            )
        report = ReplayEngine().replay(run_events)
        return JSONResponse(
            {
                "run_id": run_id,
                "status": "completed",
                "success": report.success,
                "stage_states": report.stage_states,
                "task_view_count": report.task_view_count,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_replay_status(request: Request) -> JSONResponse:
    """Check whether a replay event file exists for the given run."""
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_rs

    try:
        _ctx_rs = _rtc_rs()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    import os

    run_id = request.path_params["run_id"]

    # Ownership gate: ensure caller owns this run
    _mgr_rs = request.app.state.agent_server.run_manager
    if _mgr_rs.get_run(run_id, workspace=_ctx_rs) is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)
    _loop = asyncio.get_running_loop()
    candidates = [
        f"replay_{run_id}.jsonl",
        os.path.join(".hi_agent", f"replay_{run_id}.jsonl"),
    ]
    for candidate in candidates:
        if await _loop.run_in_executor(None, os.path.exists, candidate):
            return JSONResponse(
                {
                    "run_id": run_id,
                    "replay_available": True,
                    "event_file": candidate,
                }
            )
    return JSONResponse(
        {
            "run_id": run_id,
            "replay_available": False,
        }
    )


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
    from hi_agent.server.tenant_context import require_tenant_context as _rtc_ca

    try:
        _rtc_ca()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
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
            pass  # advisory telemetry — must not crash the capacity-advice handler

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
            pass  # advisory telemetry — must not crash the capacity-advice handler

        recommendations = recommend_server_capacity_tuning(health_payload, metrics_snapshot)
        return JSONResponse(
            {
                "recommendations": recommendations_to_payload(recommendations),
                "status": "ok",
            }
        )
    except Exception as exc:
        logger.warning("handle_capacity_advice error: %s", exc)
        return JSONResponse({"error": str(exc), "status": "error"}, status_code=500)


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
            with contextlib.suppress(Exception):
                tool_count = len(mcp_srv.list_tools().get("tools", []))
        # Derive transport status from a real health probe, not merely from
        # whether the transport object exists.  A server whose subprocess fails
        # to answer the JSON-RPC initialize handshake must NOT be reported as
        # "wired" or "external_provider".
        _builder = getattr(server, "_builder", None)
        _transport = getattr(_builder, "_mcp_transport", None) if _builder is not None else None
        health = MCPHealth(mcp_reg, transport=_transport)
        health_results = health.check_all()
        any_healthy = any(s in ("healthy", "degraded") for s in health_results.values())
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
        stderr_tails: dict[str, list[str]] = {}
        if _transport is not None and hasattr(_transport, "get_stderr_tail"):
            for srv in mcp_reg.list_servers():
                sid = srv["server_id"]
                try:
                    stderr_tails[sid] = _transport.get_stderr_tail()
                except TypeError:
                    try:
                        stderr_tails[sid] = _transport.get_stderr_tail(sid)
                    except Exception:
                        stderr_tails[sid] = []
                except Exception:
                    stderr_tails[sid] = []
        return JSONResponse(
            {
                "servers": mcp_reg.list_servers(),
                "health": health.snapshot(),
                "count": len(mcp_reg),
                "tool_count": tool_count,
                "transport_status": transport_status,
                "capability_mode": capability_mode,
                "note": note,
                "stderr_tails": stderr_tails,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc), "servers": [], "count": 0}, status_code=500)


# ------------------------------------------------------------------
# Plugin endpoints
# ------------------------------------------------------------------


async def handle_plugins_list(request: Request) -> JSONResponse:
    """Return list of loaded plugins."""
    # TODO: per-tenant plugin overlay needed — global plugin list returned to all callers.
    try:
        server: AgentServer = request.app.state.agent_server
        plugin_loader = server.plugin_loader
        return JSONResponse(
            {
                "plugins": plugin_loader.list_loaded(),
                "count": len(plugin_loader),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc), "plugins": [], "count": 0}, status_code=500)


async def handle_plugins_status(request: Request) -> JSONResponse:
    """Return plugin system status summary."""
    # TODO: per-tenant plugin overlay needed — global plugin status returned to all callers.
    try:
        server: AgentServer = request.app.state.agent_server
        plugin_loader = server.plugin_loader
        plugins = plugin_loader.list_loaded()
        active = sum(1 for p in plugins if p.get("status") == "active")
        return JSONResponse(
            {
                "total": len(plugins),
                "active": active,
                "inactive": len(plugins) - active,
                "plugins": [
                    {"name": p["name"], "status": p.get("status", "loaded")} for p in plugins
                ],
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ------------------------------------------------------------------
# Recovery — rehydrate lease-expired runs on startup
# ------------------------------------------------------------------


def _rehydrate_runs(agent_server: AgentServer) -> None:
    """Re-enqueue lease-expired runs according to the current posture.

    Called once during server lifespan startup.  Under research/prod posture
    this is the fail-safe default: every expired lease is re-enqueued unless
    ``HI_AGENT_RECOVERY_REENQUEUE=0`` is set (migration opt-out).
    Under dev posture only a warning is emitted.

    Double-execute prevention: each re-enqueue first claims an adoption_token
    via a CAS UPDATE.  A concurrent recovery pass that races this one will
    find the token already set and skip the run.

    Args:
        agent_server: The running AgentServer instance.
    """
    import os
    import uuid

    from hi_agent.server.recovery import RecoveryAlarm, RecoveryState, decide_recovery_action

    run_queue = agent_server._run_queue
    if run_queue is None:
        logger.debug("_rehydrate_runs: no run_queue wired; skipping recovery.")
        return

    # Opt-out: HI_AGENT_RECOVERY_REENQUEUE=0 reverts to warn-only for migration.
    reenqueue_flag = os.environ.get("HI_AGENT_RECOVERY_REENQUEUE", "1")
    opt_out = reenqueue_flag == "0"

    posture = Posture.from_env()

    try:
        expired = run_queue.expire_stale_leases()
    except Exception as exc:
        logger.warning("_rehydrate_runs: expire_stale_leases failed: %s", exc)
        return

    if not expired:
        logger.debug("_rehydrate_runs: no lease-expired runs found.")
        return

    logger.info(
        "_rehydrate_runs: found %d lease-expired run(s); posture=%s opt_out=%s",
        len(expired),
        posture,
        opt_out,
    )

    for entry in expired:
        run_id = entry["run_id"]
        tenant_id = entry["tenant_id"]
        lease_age_s = entry["lease_age_s"]

        decision = decide_recovery_action(
            run_id=run_id,
            tenant_id=tenant_id,
            current_state=RecoveryState.LEASE_EXPIRED,
            posture=posture,
        )

        # Opt-out overrides research/prod decision to warn-only.
        effective_requeue = decision.should_requeue and not opt_out

        if effective_requeue:
            token = str(uuid.uuid4())
            claimed = run_queue.claim_with_adoption_token(run_id, token)
            if not claimed:
                logger.warning(
                    "_rehydrate_runs: run_id=%s already adopted by another pass; skipping.",
                    run_id,
                )
                continue
            try:
                run_queue.reenqueue(run_id=run_id, tenant_id=tenant_id)
            except Exception as exc:
                logger.warning(
                    "_rehydrate_runs: reenqueue failed for run_id=%s: %s", run_id, exc
                )
                continue
            logger.info(
                "_rehydrate_runs: re-enqueued run_id=%s tenant_id=%s lease_age_s=%.1f reason=%r",
                run_id,
                tenant_id,
                lease_age_s,
                decision.reason,
            )
        else:
            reason = "opt_out=1" if opt_out and decision.should_requeue else decision.reason
            logger.warning(
                "_rehydrate_runs: warn-only for run_id=%s tenant_id=%s "
                "lease_age_s=%.1f reason=%r",
                run_id,
                tenant_id,
                lease_age_s,
                reason,
            )
            # Rule 7: fire alarm when reenqueue is disabled under strict posture.
            RecoveryAlarm.fire_if_needed(run_id=run_id, tenant_id=tenant_id, posture=posture)


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
        *MANIFEST_ROUTES,
        Route("/doctor", handle_doctor, methods=["GET"]),
        Route("/diagnostics", handle_diagnostics, methods=["GET"]),
        Route("/ops/release-gate", handle_release_gate, methods=["GET"]),
        Route("/ops/dlq", handle_list_dlq, methods=["GET"]),
        Route("/ops/dlq/{run_id}/requeue", handle_requeue_from_dlq, methods=["POST"]),
        # Runs
        Route("/runs", handle_list_runs, methods=["GET"]),
        Route("/runs", handle_create_run, methods=["POST"]),
        Route("/runs/active", handle_runs_active, methods=["GET"]),
        Route("/runs/{run_id}/artifacts", handle_run_artifacts, methods=["GET"]),
        Route("/runs/{run_id}", handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/signal", handle_signal_run, methods=["POST"]),
        Route("/runs/{run_id}/cancel", handle_cancel_run, methods=["POST"]),
        Route("/runs/{run_id}/feedback", handle_submit_feedback, methods=["POST"]),
        Route("/runs/{run_id}/feedback", handle_get_feedback, methods=["GET"]),
        Route("/runs/{run_id}/resume", handle_resume_run, methods=["POST"]),
        Route("/runs/{run_id}/gate_decision", handle_gate_decision, methods=["POST"]),
        Route("/runs/{run_id}/events", handle_run_events_sse, methods=["GET"]),
        Route("/runs/{run_id}/reasoning-trace", handle_reasoning_trace, methods=["GET"]),
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
        # Artifacts (routes extracted to routes_artifacts.py — includes by-project + provenance)
        *artifact_routes,
        # Sessions
        Route("/sessions", handle_list_sessions, methods=["GET"]),
        Route("/sessions/{session_id}/runs", handle_get_session_runs, methods=["GET"]),
        Route("/sessions/{session_id}", handle_patch_session, methods=["PATCH"]),
        # Team
        Route("/team/events", handle_list_team_events, methods=["GET"]),
        # Global profile read layer (G-1)
        Route("/profiles/hi_agent_global/memory/l3", handle_global_l3_summary, methods=["GET"]),
        Route("/profiles/hi_agent_global/skills", handle_global_skills, methods=["GET"]),
        # Long-running ops (G-8) — static cancel path before dynamic op_id catch-all
        Route("/long-ops/{op_id}/cancel", handle_cancel_long_op, methods=["POST"]),
        Route("/long-ops/{op_id}", handle_get_long_op, methods=["GET"]),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):  # type: ignore[misc]
        """Start/stop background subsystems around the Starlette lifespan."""
        mm: MemoryLifecycleManager | None = agent_server.memory_manager
        if mm is not None:
            await mm.start()
        try:
            retrieval_engine = agent_server.retrieval_engine
            if retrieval_engine is not None:
                doc_count = await retrieval_engine.warm_index_async()
                logger.info("RetrievalEngine index warmed: %d documents", doc_count)
        except AttributeError:
            logger.debug("No retrieval_engine on agent_server; skipping warm-up")
        except Exception as exc:
            logger.warning("RetrievalEngine warm-up failed (non-fatal): %s", exc)
        slo = agent_server.slo_monitor
        if slo is not None:
            await slo.start()
        if agent_server._config_stack._base_path:
            agent_server._watcher = ConfigFileWatcher(
                stack=agent_server._config_stack,
                on_reload=agent_server._on_config_reload,
                poll_interval_seconds=2.0,
            )
            agent_server._watcher_task = asyncio.create_task(agent_server._watcher.start())
            logger.info(
                "ConfigFileWatcher started for %s",
                agent_server._config_stack._base_path,
            )

        # C3: FeedbackStore is already constructed by build_durable_backends() in
        # AgentServer.__init__ and stored at agent_server._feedback_store.
        # Log its presence so the lifespan confirms wiring.
        if agent_server._feedback_store is not None:
            logger.info("lifespan: FeedbackStore already wired (Rule 6).")
        else:
            logger.warning(
                "lifespan: FeedbackStore is None; feedback endpoints will be unavailable."
            )

        # G-8: Long-running op coordinator + background poller
        from pathlib import Path as _Path

        from hi_agent.operations.coordinator import LongRunningOpCoordinator as _OpCoord
        from hi_agent.operations.op_store import LongRunningOpStore as _OpStore
        from hi_agent.operations.poller import OpPoller as _OpPoller

        _db_dir = getattr(agent_server._config, "server_db_dir", None)
        _op_db = _Path(_db_dir) / "ops.db" if _db_dir else _Path(".hi_agent") / "ops.db"
        _op_db.parent.mkdir(parents=True, exist_ok=True)
        _op_store = _OpStore(db_path=_op_db)
        _op_coordinator = _OpCoord(store=_op_store)
        agent_server.op_coordinator = _op_coordinator
        _op_poller = _OpPoller(coordinator=_op_coordinator, store=_op_store, poll_interval=30.0)
        _poller_task = asyncio.create_task(_op_poller.run())
        logger.info("G-8: OpPoller started (db=%s)", _op_db)

        # Recovery — re-enqueue lease-expired runs (posture-driven).
        try:
            _rehydrate_runs(agent_server)
        except Exception as _rh_exc:
            logger.warning("lifespan: _rehydrate_runs raised unexpectedly: %s", _rh_exc)

        # Install SIGTERM handler so the server drains active runs on graceful
        # termination (PM2/systemd/docker stop).  SIGTERM is available on
        # Windows via the signal module but cannot be sent by kill(); it is
        # raised by TerminateProcess.  The try/except guards against platforms
        # where SIGTERM is not a valid signal number.
        try:
            def _sigterm_handler(signum: int, frame: object) -> None:
                logger.warning("SIGTERM received — initiating graceful drain")
                agent_server.run_manager.shutdown()

            signal.signal(signal.SIGTERM, _sigterm_handler)
        except (OSError, ValueError):
            # signal.signal raises ValueError when called from a non-main thread
            # (e.g. in some test harnesses) and OSError on unsupported platforms.
            logger.debug("lifespan: SIGTERM handler not installed (non-main thread or unsupported)")

        try:
            yield
        finally:
            agent_server.run_manager.shutdown()
            if mm is not None:
                await mm.stop()
            if slo is not None:
                await slo.stop()
            if agent_server._watcher is not None:
                agent_server._watcher.stop()
            if agent_server._watcher_task is not None:
                agent_server._watcher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await agent_server._watcher_task
                agent_server._watcher_task = None
            mcp_transport = getattr(agent_server._builder, "_mcp_transport", None)
            if mcp_transport is not None and hasattr(mcp_transport, "close_all"):
                mcp_transport.close_all()
                logger.info("lifespan: MCP transport subprocesses closed.")
            evidence_store = getattr(agent_server._builder, "_evidence_store", None)
            if evidence_store is not None and hasattr(evidence_store, "close"):
                evidence_store.close()
                logger.info("lifespan: SqliteEvidenceStore connection closed.")
            # G-8: shut down poller
            _op_poller.stop()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(_poller_task, timeout=5.0)
            logger.info("G-8: OpPoller stopped.")

    app = Starlette(routes=routes, lifespan=lifespan)

    # Auth middleware (outermost — rejects unauthenticated requests before
    # they reach rate limiting or route handlers).
    # Enabled only when HI_AGENT_API_KEY env-var is set; no-op otherwise.
    import os as _os_auth

    from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm_auth

    _env_auth = _os_auth.environ.get("HI_AGENT_ENV", "dev").lower()
    _builder_auth = getattr(agent_server, "_builder", None)
    _readiness_auth: dict = {}
    if _builder_auth is not None:
        with contextlib.suppress(Exception):
            _readiness_auth = _builder_auth.readiness()
    _runtime_mode_auth = _rrm_auth(_env_auth, _readiness_auth)
    app.add_middleware(AuthMiddleware, runtime_mode=_runtime_mode_auth)

    # SessionMiddleware — must be added AFTER AuthMiddleware in add_middleware
    # calls so that Starlette's reverse execution order places it AFTER Auth
    # (i.e. Auth executes first, sets TenantContext, then SessionMiddleware runs).
    from hi_agent.server.session_middleware import SessionMiddleware

    _session_store = getattr(agent_server, "session_store", None)
    if _session_store is not None:
        app.add_middleware(SessionMiddleware, session_store=_session_store)
    # Store the resolved auth posture on app.state so route handlers can read it
    # without constructing a new AuthMiddleware instance per-request.
    _auth_posture_mw = AuthMiddleware(app=lambda *a: None, runtime_mode=_runtime_mode_auth)  # type: ignore[arg-type]
    app.state.auth_posture = _auth_posture_mw.auth_posture

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
        request: Request,
        exc: HTTPException,
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
        self.retrieval_engine: Any | None = None
        self.skill_evolver: Any | None = None
        self.skill_loader: Any | None = None
        self.context_manager: Any | None = None
        self.metrics_collector: Any | None = None
        self.run_context_manager: Any | None = None
        self.capacity_advisor: Any | None = None
        self.slo_monitor: Any | None = None
        self.session_store: SessionStore | None = None
        self.team_event_store: TeamEventStore | None = None
        self.op_coordinator: Any | None = None

        # stage_graph — the active stage topology for this server instance.
        # Business agents that inject a custom stage graph should also set this
        # attribute so the /manifest endpoint reflects the real topology.
        # Defaults to the sample TRACE S1-S5 graph; can be replaced at startup.
        from hi_agent.trajectory.stage_graph import default_trace_stage_graph

        self.stage_graph = default_trace_stage_graph()

        import os

        # Lazy import to avoid circular dependency at module level.
        from hi_agent.config.trace_config import TraceConfig

        # P0-1: when no explicit config is provided, honour HI_AGENT_* env vars
        # (kernel_base_url, openai_base_url, default_model, …) via from_env().
        # Previously defaulted to TraceConfig() which silently ignored env,
        # causing HI_AGENT_KERNEL_BASE_URL=http://… to never take effect.
        self._config = config if config is not None else TraceConfig.from_env()

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
        self._watcher_task: asyncio.Task[None] | None = None

        # Rule 6 — Single Construction Path: all durable backends are built in
        # one call. HI_AGENT_DATA_DIR takes priority over server_db_dir from config.
        _data_dir: str | None = os.environ.get("HI_AGENT_DATA_DIR") or getattr(
            self._config, "server_db_dir", None
        )
        _posture = Posture.from_env()
        try:
            _backends = build_durable_backends(_data_dir, _posture)
        except RuntimeError as _be:
            logger.warning(
                "build_durable_backends failed (%s); durable stores unavailable.",
                _be,
            )
            _backends = {
                "idempotency_store": None,
                "run_store": None,
                "run_queue": None,
                "session_store": None,
                "team_event_store": None,
                "team_run_registry": None,
                "event_store": None,
                "decision_audit_store": None,
                "gate_store": None,
                "feedback_store": None,
            }
        self._idempotency_store = _backends["idempotency_store"]
        self._run_store = _backends["run_store"]
        self._run_queue = _backends["run_queue"]
        self._session_store = _backends["session_store"]
        self._team_event_store = _backends["team_event_store"]
        self._team_run_registry = _backends["team_run_registry"]
        self._event_store = _backends["event_store"]
        self._decision_audit_store = _backends["decision_audit_store"]
        self._gate_store = _backends["gate_store"]
        self._feedback_store = _backends["feedback_store"]

        # Expose session_store and team_event_store at the old attribute names
        # so existing routes that access server.session_store / server.team_event_store
        # continue to work without change.
        self.session_store = self._session_store
        self.team_event_store = self._team_event_store

        # Inject durable event store into the module-level EventBus singleton.
        event_bus.set_event_store(self._event_store)

        self.run_manager = RunManager(
            max_concurrent=self._config.run_manager_max_concurrent,
            queue_size=self._config.run_manager_queue_size,
            idempotency_store=self._idempotency_store,
            run_store=self._run_store,
            run_queue=self._run_queue,
        )
        if self._event_store is not None:
            self.run_manager.set_event_store(self._event_store)

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

        # DF-33: Register the rule15_volces profile so scripts/rule15_volces_gate.py
        # has a real target.  Minimal live-LLM-backed single-stage profile used by
        # the Rule 15 operator-shape gate.  Idempotent: no-op if pre-registered.
        try:
            from hi_agent.profiles.rule15_volces import (
                build_rule15_volces_profile,
                register_rule15_probe_capability,
            )

            _cap_registry = self._builder.build_capability_registry()
            if _cap_registry is not None:
                register_rule15_probe_capability(
                    _cap_registry,
                    llm_gateway=self._builder.build_llm_gateway(),
                )
            _profile_registry = self._builder.build_profile_registry()
            if _profile_registry is not None and not _profile_registry.has(
                "rule15_volces"
            ):
                self._builder.register_profile(build_rule15_volces_profile())
        except Exception as _exc:
            logger.warning(
                "rule15_volces profile registration failed (%s: %s); "
                "scripts/rule15_volces_gate.py will be unable to resolve the profile.",
                type(_exc).__name__,
                _exc,
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
            logger.warning(
                "MCPServer initialization failed (%s: %s); "
                "/mcp/tools/* endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
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
        _server_profile = getattr(self._config, "active_profile", None) or "__server__"
        try:
            self.memory_manager = self._builder.build_memory_lifecycle_manager(
                profile_id=_server_profile
            )
        except Exception as _exc:
            logger.warning(
                "MemoryLifecycleManager initialization failed (%s: %s); "
                "/memory/* endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.knowledge_manager = self._builder.build_knowledge_manager(
                profile_id=_server_profile
            )
        except Exception as _exc:
            logger.warning(
                "KnowledgeManager initialization failed (%s: %s); "
                "/knowledge/* endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.retrieval_engine = self._builder.build_retrieval_engine(
                profile_id=_server_profile
            )
        except Exception as _exc:
            logger.warning(
                "RetrievalEngine initialization failed (%s: %s); "
                "knowledge retrieval will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.skill_evolver = self._builder.build_skill_evolver()
            self.skill_loader = self._builder.build_skill_loader()
        except Exception as _exc:
            logger.warning(
                "SkillEvolver/SkillLoader initialization failed (%s: %s); "
                "/skills/* endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.metrics_collector = self._builder.build_metrics_collector()
            # Register the collector as the process-wide singleton so that
            # record_fallback() and record_llm_request() can reach it from
            # deeply-nested call-sites without an explicit injection chain.
            # Without this call, get_metrics_collector() returns None at
            # serve-time and all Rule-14/Rule-15 counter increments are silently
            # lost. (Audit finding: set_metrics_collector was only called in
            # tests, never at server boot.)
            from hi_agent.observability.collector import set_metrics_collector as _set_mc

            _set_mc(self.metrics_collector)
        except Exception as _exc:
            logger.warning(
                "MetricsCollector initialization failed (%s: %s); "
                "metrics endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.run_context_manager = self._builder._build_run_context_manager()
        except Exception as _exc:
            logger.warning(
                "RunContextManager initialization failed (%s: %s).",
                type(_exc).__name__,
                _exc,
            )
        try:
            self.context_manager = self._builder.build_context_manager()
        except Exception as _exc:
            logger.warning(
                "ContextManager initialization failed (%s: %s); "
                "/context/* endpoints will be unavailable.",
                type(_exc).__name__,
                _exc,
            )
        try:
            from hi_agent.management.slo import SLOMonitor

            if self.metrics_collector is not None:
                self.slo_monitor = SLOMonitor(self.metrics_collector)
        except Exception as _exc:
            logger.warning(
                "SLOMonitor initialization failed (%s: %s); "
                "SLO monitoring disabled.",
                type(_exc).__name__,
                _exc,
            )

        # Wire plugin contributions (skill_dirs, mcp_servers) into live subsystems
        # now that all subsystems are built.
        try:
            self._builder._wire_plugin_contributions()
        except Exception as _exc:
            logger.warning(
                "Plugin contribution wiring failed (%s: %s); "
                "plugin capabilities may be unavailable.",
                type(_exc).__name__,
                _exc,
            )

        # Sync file-discovered skills into SkillRegistry so both subsystems
        # share the same skill set.
        try:
            if self.skill_loader is not None:
                _skill_registry = self._builder.build_skill_registry()
                self.skill_loader.sync_to_registry(_skill_registry)
        except Exception as _exc:
            logger.warning(
                "SkillLoader→SkillRegistry sync failed (%s: %s).", type(_exc).__name__, _exc
            )

        # Build the Starlette app.
        self._app = build_app(self)

    @property
    def app(self) -> Starlette:
        """Return the Starlette ASGI application."""
        return self._app

    def _default_executor_factory(
        self,
        run_data: dict[str, Any],
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

        task_id = run_data.get("task_id") or run_data.get("run_id") or uuid.uuid4().hex[:12]

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

        # DF-27 / Rule 14: if profile_id is absent here, apply the same loud
        # default the HTTP boundary applies.  Direct callers of the factory
        # (tests, internal retries, CLI) must behave identically.
        _pid = run_data.get("profile_id")
        if not _pid:
            from hi_agent.observability.fallback import record_fallback

            logger.warning(
                "_default_executor_factory: run_data missing profile_id; "
                "defaulting to 'default' (DF-27)."
            )
            record_fallback(
                "route",
                reason="missing_profile_id",
                run_id=run_data.get("run_id") or "unknown",
                extra={"default_assigned": "default", "source": "executor_factory"},
            )
            _pid = "default"

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
            profile_id=_pid,
            project_id=run_data.get("project_id", ""),
        )
        config_patch = run_data.get("config_patch")  # optional dict, may be None
        workspace_key = run_data.get("_workspace_key")  # injected by handle_create_run
        executor = self._builder.build_executor(
            contract, config_patch=config_patch, workspace_key=workspace_key
        )

        # P1-6: fail-fast in prod mode. build_executor() swallows several
        # subsystem-build exceptions (skill evolver, tracer, …) but MUST NOT
        # silently hand back an executor missing its kernel or LLM gateway —
        # that's exactly the state that leaves a run wedged with CPU idle and
        # current_stage=None. Surface the condition as a RuntimeError so
        # handle_create_run can return 503 instead of 201+stuck.
        import os as _os_p16

        if _os_p16.environ.get("HI_AGENT_ENV", "dev").lower() == "prod":
            _missing: list[str] = []
            if getattr(executor, "kernel", None) is None:
                _missing.append("kernel_adapter")
            _llm = getattr(executor, "llm_gateway", None) or getattr(
                executor, "_llm_gateway", None
            )
            if _llm is None:
                _missing.append("llm_gateway")
            if _missing:
                raise RuntimeError(
                    "platform_not_ready: prod mode requires "
                    + ", ".join(_missing)
                    + ". Set HI_AGENT_KERNEL_BASE_URL and a real API key "
                    "(OPENAI_API_KEY or ANTHROPIC_API_KEY)."
                )

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
        """Best-effort shutdown for backward compatibility with HTTPServer."""
        self.run_manager.shutdown()

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
            self._send_json(
                200,
                {
                    "health": report.health.value,
                    "utilization_pct": report.utilization_pct,
                    "total_tokens": report.total_tokens,
                    "budget_tokens": report.budget_tokens,
                    "per_section": report.per_section,
                    "compressions_total": report.compressions_total,
                    "compression_failures": report.compression_failures,
                    "circuit_breaker_open": report.circuit_breaker_open,
                    "diminishing_returns": report.diminishing_returns,
                },
            )
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
                items.append(
                    {
                        "skill_id": s.skill_id,
                        "name": s.name,
                        "version": s.version,
                        "description": s.description,
                        "lifecycle_stage": s.lifecycle_stage,
                        "confidence": s.confidence,
                        "eligible": eligible,
                        "eligibility_reason": reason,
                        "tags": s.tags,
                    }
                )
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
                items.append(
                    {
                        "version": v.version,
                        "is_champion": v.is_champion,
                        "is_challenger": v.is_challenger,
                        "created_at": v.created_at,
                    }
                )
            self._send_json(
                200,
                {
                    "skill_id": skill_id,
                    "versions": items,
                    "count": len(items),
                },
            )
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
                self._send_json(
                    200,
                    {
                        "skill_id": skill_id,
                        "optimized": False,
                        "reason": "no_optimization_needed",
                    },
                )
                return
            record = evolver.deploy_optimization(skill_id, new_prompt)
            self._send_json(
                200,
                {
                    "skill_id": skill_id,
                    "optimized": True,
                    "new_version": record.version,
                    "is_challenger": record.is_challenger,
                },
            )
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
            self._send_json(
                200,
                {
                    "skill_id": skill_id,
                    "promoted": promoted,
                },
            )
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

            self._send_json(
                200,
                {
                    "total_skills": len(all_skills),
                    "eligible_skills": len(eligible),
                    "observed_skills": len(all_metrics),
                    "top_performers": top_performers,
                },
            )
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
            self._send_json(
                404,
                {
                    "error": "checkpoint_not_found",
                    "run_id": run_id,
                },
            )
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
            except Exception as _exc:
                logger.warning("resume_from_checkpoint failed: %s", _exc)

        thread = threading.Thread(
            target=_resume_in_background,
            daemon=True,
        )
        thread.start()

        self._send_json(
            200,
            {
                "status": "resuming",
                "run_id": run_id,
                "checkpoint_path": checkpoint_path,
            },
        )
