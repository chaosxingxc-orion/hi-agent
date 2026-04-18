"""Unit tests for routes_runs.py (Arch-7 extraction).

Tests focus on the module's own logic — each handler is tested directly
with a mocked Starlette Request. External network calls (RunExecutor,
FeedbackStore) are mocked per Production Integrity rules (unit test,
fault injection boundary).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_request(path_params: dict | None = None, json_body: dict | None = None) -> MagicMock:
    """Return a minimal fake Starlette Request."""
    req = MagicMock()
    req.app.state.agent_server = MagicMock()
    req.path_params = path_params or {}
    if json_body is not None:
        req.json = AsyncMock(return_value=json_body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))
    return req


class TestHandleListRuns:
    @pytest.mark.asyncio
    async def test_returns_run_list(self) -> None:
        from hi_agent.server.routes_runs import handle_list_runs

        req = _make_request()
        mock_run = MagicMock()
        req.app.state.agent_server.run_manager.list_runs.return_value = [mock_run]
        req.app.state.agent_server.run_manager.to_dict.return_value = {"run_id": "r1"}

        resp = await handle_list_runs(req)
        assert resp.status_code == 200
        import json
        body = json.loads(resp.body)
        assert body["runs"] == [{"run_id": "r1"}]


class TestHandleRunsActive:
    @pytest.mark.asyncio
    async def test_no_rcm_returns_not_configured(self) -> None:
        from hi_agent.server.routes_runs import handle_runs_active

        req = _make_request()
        req.app.state.agent_server.run_context_manager = None
        # getattr fallback — patch to ensure None
        del req.app.state.agent_server.run_context_manager

        resp = await handle_runs_active(req)
        import json
        body = json.loads(resp.body)
        assert body["status"] == "not_configured"
        assert body["count"] == 0

    @pytest.mark.asyncio
    async def test_returns_run_ids(self) -> None:
        from hi_agent.server.routes_runs import handle_runs_active

        req = _make_request()
        rcm = MagicMock()
        rcm.list_runs.return_value = ["r1", "r2"]
        req.app.state.agent_server.run_context_manager = rcm

        resp = await handle_runs_active(req)
        import json
        body = json.loads(resp.body)
        assert body["count"] == 2
        assert body["status"] == "ok"


class TestHandleCreateRun:
    @pytest.mark.asyncio
    async def test_missing_goal_returns_400(self) -> None:
        from hi_agent.server.routes_runs import handle_create_run

        req = _make_request(json_body={"not_goal": "x"})
        resp = await handle_create_run(req)
        assert resp.status_code == 400
        import json
        body = json.loads(resp.body)
        assert body["error"] == "missing_goal"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self) -> None:
        from hi_agent.server.routes_runs import handle_create_run

        req = _make_request()  # json() raises ValueError
        resp = await handle_create_run(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_creates_run_without_executor(self) -> None:
        from hi_agent.server.routes_runs import handle_create_run

        req = _make_request(json_body={"goal": "do something"})
        server = req.app.state.agent_server
        server.run_manager.create_run.return_value = "run-abc"
        server.run_manager.get_run.return_value = MagicMock(run_id="run-abc")
        server.run_manager.to_dict.return_value = {"run_id": "run-abc", "state": "pending"}
        server.executor_factory = None
        server.run_context_manager = None

        resp = await handle_create_run(req)
        assert resp.status_code == 201
        import json
        body = json.loads(resp.body)
        assert body["run_id"] == "run-abc"


class TestHandleGetRun:
    @pytest.mark.asyncio
    async def test_not_found_returns_404(self) -> None:
        from hi_agent.server.routes_runs import handle_get_run

        req = _make_request(path_params={"run_id": "missing"})
        req.app.state.agent_server.run_manager.get_run.return_value = None
        resp = await handle_get_run(req)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_found_returns_200(self) -> None:
        from hi_agent.server.routes_runs import handle_get_run

        req = _make_request(path_params={"run_id": "r1"})
        req.app.state.agent_server.run_manager.get_run.return_value = MagicMock()
        req.app.state.agent_server.run_manager.to_dict.return_value = {"run_id": "r1"}
        resp = await handle_get_run(req)
        assert resp.status_code == 200


class TestHandleSignalRun:
    @pytest.mark.asyncio
    async def test_run_not_found_returns_404(self) -> None:
        from hi_agent.server.routes_runs import handle_signal_run

        req = _make_request(path_params={"run_id": "x"}, json_body={"signal": "cancel"})
        req.app.state.agent_server.run_manager.get_run.return_value = None
        resp = await handle_signal_run(req)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_success(self) -> None:
        from hi_agent.server.routes_runs import handle_signal_run

        req = _make_request(path_params={"run_id": "r1"}, json_body={"signal": "cancel"})
        req.app.state.agent_server.run_manager.get_run.return_value = MagicMock()
        req.app.state.agent_server.run_manager.cancel_run.return_value = True
        resp = await handle_signal_run(req)
        assert resp.status_code == 200
        import json
        body = json.loads(resp.body)
        assert body["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_unknown_signal_returns_400(self) -> None:
        from hi_agent.server.routes_runs import handle_signal_run

        req = _make_request(path_params={"run_id": "r1"}, json_body={"signal": "destroy"})
        req.app.state.agent_server.run_manager.get_run.return_value = MagicMock()
        resp = await handle_signal_run(req)
        assert resp.status_code == 400
