"""Ops HTTP route handlers: /doctor."""
from __future__ import annotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.ops.diagnostics import build_doctor_report


async def handle_doctor(request: Request) -> JSONResponse:
    """GET /doctor — return structured diagnostic report."""
    server = request.app.state.agent_server
    builder = getattr(server, "_builder", None)
    if builder is None:
        from hi_agent.config.builder import SystemBuilder
        builder = SystemBuilder(config=getattr(server, "_config", None))
    report = build_doctor_report(builder)
    status_code = 200 if report.status == "ready" else 503
    return JSONResponse(report.to_dict(), status_code=status_code)
