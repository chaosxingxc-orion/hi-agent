"""HTTP API server for hi-agent using Starlette + uvicorn.

Endpoints:
    POST /runs          -- Submit a new task (body: TaskContract JSON)
    GET  /runs/{run_id} -- Query run status
    GET  /runs          -- List active runs
    GET  /runs/active   -- Active RunContext entries from RunContextManager
    POST /runs/{run_id}/signal -- Send signal to run
    POST /runs/{run_id}/resume -- Resume run from checkpoint
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

from hi_agent.config.stack import ConfigStack
from hi_agent.config.watcher import ConfigFileWatcher
from hi_agent.server.auth_middleware import AuthMiddleware
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.event_bus import event_bus
from hi_agent.server.rate_limiter import RateLimiter
from hi_agent.server.run_manager import RunManager


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

    return JSONResponse({
        "status": overall,
        "subsystems": subsystems,
        "timestamp": datetime.now(UTC).isoformat(),
    })


async def handle_ready(request: Request) -> JSONResponse:
    """Return platform readiness contract.

    200 means ready (kernel + capabilities functional).
    503 means not ready (one or more blocking subsystems failed).
    """
    server: AgentServer = request.app.state.agent_server
    try:
        from hi_agent.config.builder import SystemBuilder  # noqa: PLC0415
        builder = SystemBuilder(config=server.config if hasattr(server, "config") else None)
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
    # Build capability list from the server's wired invoker/registry if available
    capabilities: list[str] = []
    skills: list[dict] = []
    models: list[dict] = []
    try:
        skill_loader = getattr(server, "skill_loader", None)
        if skill_loader is not None and hasattr(skill_loader, "discover"):
            discovered = skill_loader.discover()
            skills = [
                {"name": getattr(s, "name", str(s)), "source": getattr(s, "source", "unknown")}
                for s in discovered
            ]
    except Exception:
        pass

    return JSONResponse({
        "name": "hi-agent",
        "version": "0.1.0",
        "framework": "TRACE",
        "stages": [
            "S1_understand",
            "S2_gather",
            "S3_build_analyze",
            "S4_synthesize",
            "S5_review_finalize",
        ],
        "capabilities": capabilities,
        "skills": skills,
        "models": models,
        "mcp_servers": [],
        "plugins": [],
        "endpoints": [
            "POST /runs",
            "GET /runs",
            "GET /runs/{run_id}",
            "POST /runs/{run_id}/signal",
            "GET /health",
            "GET /ready",
            "GET /manifest",
        ],
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

    # If the server has an executor factory, start the run immediately.
    if server.executor_factory is not None:
        run_data = dict(body, run_id=run_id)
        task_runner = server.executor_factory(run_data)

        def _executor_fn(_managed_run: Any) -> Any:
            return task_runner()

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


async def handle_resume_run(request: Request) -> JSONResponse:
    """Resume a run from its checkpoint file."""
    import os
    import threading

    run_id = request.path_params["run_id"]

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}

    # Search for checkpoint file
    checkpoint_path = body.get("checkpoint_path")
    if not checkpoint_path:
        candidates = [
            os.path.join(".checkpoint", f"checkpoint_{run_id}.json"),
            os.path.join(".hi_agent", f"checkpoint_{run_id}.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                checkpoint_path = candidate
                break

    if not checkpoint_path or not os.path.exists(checkpoint_path):
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
    manager = server.memory_manager
    if manager is None:
        return JSONResponse(
            {"error": "memory_not_configured"}, status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    result = manager.trigger_dream(body.get("date"))
    return JSONResponse(result)


async def handle_memory_consolidate(request: Request) -> JSONResponse:
    """Trigger consolidation (mid-term -> long-term)."""
    server: AgentServer = request.app.state.agent_server
    manager = server.memory_manager
    if manager is None:
        return JSONResponse(
            {"error": "memory_not_configured"}, status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    result = manager.trigger_consolidation(body.get("days", 7))
    return JSONResponse(result)


async def handle_memory_status(request: Request) -> JSONResponse:
    """Return memory tier status."""
    server: AgentServer = request.app.state.agent_server
    manager = server.memory_manager
    if manager is None:
        return JSONResponse(
            {"error": "memory_not_configured"}, status_code=503,
        )
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

        candidates = [
            f"replay_{run_id}.jsonl",
            os.path.join(".hi_agent", f"replay_{run_id}.jsonl"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                event_file = candidate
                break

    if not event_file:
        return JSONResponse(
            {"error": "event_file_not_found", "run_id": run_id},
            status_code=404,
        )

    try:
        from hi_agent.replay import ReplayEngine, load_event_envelopes_jsonl

        events = load_event_envelopes_jsonl(event_file)
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
    candidates = [
        f"replay_{run_id}.jsonl",
        os.path.join(".hi_agent", f"replay_{run_id}.jsonl"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
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
    """Return MCP server registry status."""
    try:
        from hi_agent.mcp.registry import MCPRegistry  # noqa: PLC0415
        from hi_agent.mcp.health import MCPHealth  # noqa: PLC0415
        server: AgentServer = request.app.state.agent_server
        mcp_reg = getattr(server, "mcp_registry", None) or MCPRegistry()
        health = MCPHealth(mcp_reg)
        return JSONResponse({
            "servers": mcp_reg.list_servers(),
            "health": health.snapshot(),
            "count": len(mcp_reg),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc), "servers": [], "count": 0}, status_code=500)


async def handle_mcp_tools(request: Request) -> JSONResponse:
    """Return all tools across registered MCP servers."""
    try:
        from hi_agent.mcp.registry import MCPRegistry  # noqa: PLC0415
        server: AgentServer = request.app.state.agent_server
        mcp_reg = getattr(server, "mcp_registry", None) or MCPRegistry()
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
        from hi_agent.plugin.loader import PluginLoader  # noqa: PLC0415
        server: AgentServer = request.app.state.agent_server
        plugin_loader = getattr(server, "plugin_loader", None)
        if plugin_loader is None:
            plugin_loader = PluginLoader()
            plugin_loader.load_all()
        return JSONResponse({
            "plugins": plugin_loader.list_loaded(),
            "count": len(plugin_loader),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc), "plugins": [], "count": 0}, status_code=500)


async def handle_plugins_status(request: Request) -> JSONResponse:
    """Return plugin system status summary."""
    try:
        from hi_agent.plugin.loader import PluginLoader  # noqa: PLC0415
        server: AgentServer = request.app.state.agent_server
        plugin_loader = getattr(server, "plugin_loader", None)
        if plugin_loader is None:
            plugin_loader = PluginLoader()
            plugin_loader.load_all()
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

        # Runs
        Route("/runs", handle_list_runs, methods=["GET"]),
        Route("/runs", handle_create_run, methods=["POST"]),
        Route("/runs/active", handle_runs_active, methods=["GET"]),
        Route("/runs/{run_id}", handle_get_run, methods=["GET"]),
        Route("/runs/{run_id}/signal", handle_signal_run, methods=["POST"]),
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
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):  # type: ignore[misc]
        """Start/stop background subsystems around the Starlette lifespan."""
        mm: MemoryLifecycleManager | None = agent_server.memory_manager
        if mm is not None:
            await mm.start()
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
            if agent_server._watcher is not None:
                agent_server._watcher.stop()

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

    # Catch-all for 404 on unmatched paths. Starlette by default returns
    # HTML 404; we override to return JSON.
    from starlette.middleware import Middleware
    from starlette.exceptions import HTTPException

    async def http_exception_handler(
        request: Request, exc: HTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code,
        )

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
        """
        self._host = host
        self._port = port
        self._rate_limit_rps = rate_limit_rps
        self.server_address = (host, port)
        self.run_manager = RunManager()
        self.memory_manager: MemoryLifecycleManager | None = None
        self.knowledge_manager: Any | None = None
        self.skill_evolver: Any | None = None
        self.skill_loader: Any | None = None
        self.context_manager: Any | None = None
        self.metrics_collector: Any | None = None
        self.run_context_manager: Any | None = None
        self.capacity_advisor: Any | None = None

        import os

        # Lazy import to avoid circular dependency at module level.
        from hi_agent.config.trace_config import TraceConfig

        self._config = config if config is not None else TraceConfig()

        # Config stack for hot-reload and per-run overrides.
        base_config_path = os.environ.get("HI_AGENT_CONFIG_FILE")
        self._config_stack = ConfigStack(
            base_config_path=base_config_path,
            profile=os.environ.get("HI_AGENT_PROFILE"),
            env=os.environ.get("HI_AGENT_ENV", "prod"),
        )
        if base_config_path:
            # Use stack-resolved config (incorporates file + profile + env).
            self._config = self._config_stack.resolve()
        self._watcher: ConfigFileWatcher | None = None

        from hi_agent.config.builder import SystemBuilder

        self._builder = SystemBuilder(self._config, config_stack=self._config_stack)
        self.executor_factory: Callable[..., Callable[..., Any]] | None = (
            self._default_executor_factory
        )

        # Build a shared CapabilityInvoker and wire MCPServer.
        try:
            from hi_agent.server.mcp import MCPServer  # noqa: PLC0415
            _invoker = self._builder.build_invoker()
            self._mcp_server: Any | None = MCPServer(
                registry=_invoker.registry,
                invoker=_invoker,
            )
        except Exception:
            logger.warning("MCPServer initialization failed; /mcp/tools/* endpoints will be unavailable.")
            self._mcp_server = None

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
            run_data: Dictionary with at least ``goal``; may contain
                ``task_id``, ``run_id``, ``task_family``, ``risk_level``.

        Returns:
            A zero-argument callable whose invocation drives the task
            through the TRACE pipeline.
        """
        import uuid

        from hi_agent.contracts import TaskContract

        task_id = (
            run_data.get("task_id")
            or run_data.get("run_id")
            or uuid.uuid4().hex[:12]
        )
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            task_family=run_data.get("task_family", "quick_task"),
            risk_level=run_data.get("risk_level", "low"),
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
        """Called by ConfigFileWatcher when config files change."""
        self._config = new_cfg
        from hi_agent.config.builder import SystemBuilder
        self._builder = SystemBuilder(config=new_cfg, config_stack=self._config_stack)
        logger.info(
            "Config reloaded. New server_port=%s",
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
