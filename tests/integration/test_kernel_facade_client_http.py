"""Integration test: KernelFacadeClient in HTTP mode.

Spins up an in-process mock HTTP server (stdlib http.server) that
simulates the agent-kernel REST API, then exercises KernelFacadeClient
in ``mode="http"`` against it.  No external processes or network
dependencies are required.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

# ---------------------------------------------------------------------------
# Minimal mock agent-kernel HTTP server
# ---------------------------------------------------------------------------

class _MockKernelHandler(BaseHTTPRequestHandler):
    """Handles the subset of agent-kernel endpoints used by KernelFacadeClient."""

    def log_message(self, fmt: str, *args: Any) -> None:  # silence access logs
        pass

    # --- helpers ---

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _ok(self, payload: dict[str, Any] | None = None) -> None:
        body = json.dumps(payload or {}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        body = json.dumps({"error": "not_found"}).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _server_error(self) -> None:
        body = json.dumps({"error": "internal_error"}).encode()
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- POST dispatcher ---

    def do_POST(self) -> None:
        body = self._read_body()
        path = self.path.split("?")[0]

        # Inject 500 for error-injection tests
        if getattr(self.server, "_inject_error", None) == path:
            self._server_error()
            return

        if path == "/runs":
            run_kind = body.get("run_kind", "task-x")
            self._ok({"run_id": f"run-{run_kind}"})
        elif re.fullmatch(r"/runs/[^/]+/stages/[^/]+/open", path):
            self._ok({"ok": True})
        elif re.fullmatch(r"/runs/[^/]+/branches", path):
            branch_id = body.get("branch_id", "branch-1")
            self._ok({"branch_id": branch_id})
        elif re.fullmatch(r"/runs/[^/]+/task-views", path):
            self._ok({"task_view_id": body.get("task_view_id", "tv-1")})
        elif re.fullmatch(r"/runs/[^/]+/human-gates", path) or re.fullmatch(r"/runs/[^/]+/approval", path) or re.fullmatch(r"/runs/[^/]+/signals", path):
            self._ok({"ok": True})
        else:
            self._not_found()

    # --- PUT dispatcher ---

    def do_PUT(self) -> None:
        body = self._read_body()
        path = self.path.split("?")[0]

        if re.fullmatch(r"/runs/[^/]+/stages/[^/]+/state", path) or re.fullmatch(r"/runs/[^/]+/branches/[^/]+/state", path) or re.fullmatch(r"/task-views/[^/]+/decision", path):
            self._ok({"ok": True})
        else:
            self._not_found()

    # --- GET dispatcher ---

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/manifest":
            self._ok({"name": "mock-kernel", "version": "test"})
        elif re.fullmatch(r"/runs/[^/]+", path):
            run_id = path.rsplit("/", 1)[-1]
            self._ok({"run_id": run_id, "status": "running"})
        elif path == "/health":
            self._ok({"status": "ok"})
        else:
            self._not_found()


# ---------------------------------------------------------------------------
# Pytest fixture: ephemeral mock server
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mock_kernel_server(monkeypatch_module):
    """Start an in-process mock server; yield (host, port); shut it down.

    Proxy env-vars are cleared for the module so urllib does not route
    loopback requests through any system HTTP proxy.
    """
    server = HTTPServer(("127.0.0.1", 0), _MockKernelHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, host, port
    server.shutdown()


@pytest.fixture(scope="module")
def monkeypatch_module(request):
    """Module-scoped monkeypatch that clears HTTP proxy env vars."""
    import os

    _PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")
    saved = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}
    yield
    os.environ.update(saved)


@pytest.fixture()
def client(mock_kernel_server) -> KernelFacadeClient:
    _, host, port = mock_kernel_server
    return KernelFacadeClient(
        mode="http",
        base_url=f"http://{host}:{port}",
        timeout_seconds=5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKernelFacadeClientHttp:
    """Validates KernelFacadeClient HTTP mode against the mock server."""

    def test_start_run_returns_run_id(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-abc")
        assert run_id == "run-task-abc"

    def test_open_stage_succeeds(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-os")
        client.open_stage(run_id, "S1_understand")

    def test_mark_stage_state(self, client: KernelFacadeClient) -> None:
        from hi_agent.contracts import StageState
        run_id = client.start_run("task-ms")
        client.mark_stage_state(run_id, "S1_understand", StageState.COMPLETED)

    def test_record_task_view(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-tv")
        result = client.record_task_view("tv-001", {"run_id": run_id, "content": "test view"})
        assert result == "tv-001"

    def test_bind_task_view_to_decision(self, client: KernelFacadeClient) -> None:
        client.bind_task_view_to_decision("tv-001", "decision-001")

    def test_get_manifest(self, client: KernelFacadeClient) -> None:
        manifest = client.get_manifest()
        assert manifest["name"] == "mock-kernel"

    def test_query_run(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-q")
        result = client.query_run(run_id)
        assert result["run_id"] == run_id

    def test_open_branch(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-b")
        client.open_branch(run_id, "S1_understand", "branch-1")

    def test_mark_branch_state(self, client: KernelFacadeClient) -> None:
        run_id = client.start_run("task-bs")
        client.mark_branch_state(
            run_id, "S1_understand", "branch-1", "completed", failure_code=None
        )

    def test_500_raises_backend_error(
        self, mock_kernel_server, client: KernelFacadeClient
    ) -> None:
        server, _, _ = mock_kernel_server
        server._inject_error = "/runs"
        try:
            with pytest.raises(RuntimeAdapterBackendError):
                client.start_run("task-err")
        finally:
            server._inject_error = None

    def test_404_raises_backend_error(self, client: KernelFacadeClient) -> None:
        """A path not implemented by the mock returns 404 → RuntimeAdapterBackendError."""
        with pytest.raises(RuntimeAdapterBackendError):
            client._http_post("/nonexistent/path", {})

    def test_constructor_rejects_invalid_mode(self) -> None:
        with pytest.raises(ValueError, match="mode must be"):
            KernelFacadeClient(mode="invalid")

    def test_multiple_sequential_runs(self, client: KernelFacadeClient) -> None:
        """Verify the client handles multiple back-to-back calls correctly."""
        for i in range(5):
            run_id = client.start_run(f"task-{i}")
            assert run_id == f"run-task-{i}"
