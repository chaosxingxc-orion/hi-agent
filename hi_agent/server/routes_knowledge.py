"""Knowledge route handlers extracted from app.py (E-4 refactor)."""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi_agent.observability.log_redaction import hash_tenant_id, redact_query
from hi_agent.server.tenant_context import require_tenant_context
from hi_agent.server.tenant_scope_audit import record_tenant_scoped_access

_logger = logging.getLogger(__name__)


async def handle_knowledge_ingest(request: Request) -> JSONResponse:
    """Ingest text knowledge as a wiki page."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    tenant_id = ctx.tenant_id
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    title = body.get("title", "")
    content = body.get("content", "")
    if not title or not content:
        return JSONResponse(
            {"error": "missing_title_or_content"},
            status_code=400,
        )
    tags = body.get("tags", [])
    _logger.debug(
        "hi_agent.routes_knowledge: ingest tenant=%s title=%s",
        hash_tenant_id(tenant_id),
        redact_query(title),
    )
    page_id = km.ingest_text(title, content, tags)
    try:
        re = server.retrieval_engine
        if re is not None:
            re.mark_index_dirty()
    except Exception:  # rule7-exempt: expiry_wave="Wave 22" replacement_test: wave22-tests
        pass
    return JSONResponse({"page_id": page_id, "status": "created"}, status_code=201)


async def handle_knowledge_ingest_structured(request: Request) -> JSONResponse:
    """Ingest structured facts into the knowledge graph."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    tenant_id = ctx.tenant_id
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    facts = body.get("facts", [])
    _logger.debug(
        "hi_agent.routes_knowledge: ingest_structured tenant=%s facts=%d",
        hash_tenant_id(tenant_id),
        len(facts),
    )
    count = km.ingest_structured(facts)
    try:
        re = server.retrieval_engine
        if re is not None:
            re.mark_index_dirty()
    except Exception:  # rule7-exempt: expiry_wave="Wave 22" replacement_test: wave22-tests
        pass
    return JSONResponse(
        {"nodes_created": count, "status": "created"},
        status_code=201,
    )


async def handle_knowledge_query(request: Request) -> JSONResponse:
    """Query knowledge across all sources."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    tenant_id = ctx.tenant_id
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    q = request.query_params.get("q", "")
    limit = int(request.query_params.get("limit", "10"))
    budget = int(request.query_params.get("budget", "1500"))
    if not q:
        return JSONResponse(
            {"error": "missing_query_param_q"},
            status_code=400,
        )
    _logger.debug(
        "hi_agent.routes_knowledge: query tenant=%s q=%s",
        hash_tenant_id(tenant_id),
        redact_query(q),
    )
    context = km.query_for_context(q, budget_tokens=budget)
    result = km.query(q, limit=limit)
    return JSONResponse(
        {
            "query": q,
            "total_results": result.total_results,
            "context": context,
        }
    )


async def handle_knowledge_status(request: Request) -> JSONResponse:
    """Return knowledge system stats (global-readonly, scoped audit)."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    record_tenant_scoped_access(
        tenant_id=ctx.tenant_id, resource="knowledge", op="status"
    )
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    stats = km.get_stats()
    return JSONResponse(stats)


async def handle_knowledge_lint(request: Request) -> JSONResponse:
    """Run knowledge health check (global-readonly, scoped audit)."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    record_tenant_scoped_access(
        tenant_id=ctx.tenant_id, resource="knowledge", op="lint"
    )
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    issues = km.lint()
    return JSONResponse({"issues": issues, "count": len(issues)})


async def handle_knowledge_sync(request: Request) -> JSONResponse:
    """Sync graph nodes to wiki pages."""
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    tenant_id = ctx.tenant_id  # captured for audit/future per-tenant routing
    _logger.debug(
        "hi_agent.routes_knowledge: sync tenant=%s", hash_tenant_id(tenant_id)
    )
    server = request.app.state.agent_server
    km = server.knowledge_manager
    if km is None:
        return JSONResponse(
            {"error": "knowledge_not_configured"},
            status_code=503,
        )
    pages_synced = km.renderer.to_wiki_pages(km.wiki)
    km.wiki.rebuild_index()
    return JSONResponse(
        {
            "pages_synced": pages_synced,
            "status": "completed",
        }
    )


routes = [
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
]
