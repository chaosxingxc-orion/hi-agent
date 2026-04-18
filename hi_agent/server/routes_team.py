import json
from starlette.requests import Request
from starlette.responses import JSONResponse
from hi_agent.server.tenant_context import require_tenant_context


async def handle_list_team_events(request: Request) -> JSONResponse:
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    store = getattr(request.app.state.agent_server, "team_event_store", None)
    if store is None:
        return JSONResponse({"error": "service_unavailable"}, status_code=503)
    since_id = int(request.query_params.get("since_id", 0))
    team_space_id = ctx.team_id or ctx.tenant_id
    events = store.list_since(ctx.tenant_id, team_space_id, since_id=since_id)

    def _safe_payload(payload_json: str) -> dict:
        try:
            return json.loads(payload_json)
        except (json.JSONDecodeError, ValueError):
            return {}

    return JSONResponse({"events": [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "payload": _safe_payload(e.payload_json),
            "source_run_id": e.source_run_id,
            "source_user_id": e.source_user_id,
            "created_at": e.created_at,
            "schema_version": e.schema_version,
        }
        for e in events
    ]})
