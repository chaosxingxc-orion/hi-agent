"""Lightweight HTTP API server for hi-agent using stdlib only.

Endpoints:
    POST /runs          -- Submit a new task (body: TaskContract JSON)
    GET  /runs/{run_id} -- Query run status
    GET  /runs          -- List active runs
    POST /runs/{run_id}/signal -- Send signal to run
    GET  /health        -- Health check
    GET  /manifest      -- System capabilities manifest
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from hi_agent.server.run_manager import RunManager

# Route patterns for path matching.
_RUN_ID_RE = re.compile(r"^/runs/([^/]+)$")
_SIGNAL_RE = re.compile(r"^/runs/([^/]+)/signal$")


class AgentAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for TRACE agent API."""

    # Override to suppress per-request stderr logging in production.
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence default request logging."""

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        """Dispatch GET requests to appropriate handler."""
        path = self.path.split("?")[0]

        if path == "/health":
            self._handle_health()
        elif path == "/manifest":
            self._handle_manifest()
        elif path == "/runs":
            self._handle_list_runs()
        else:
            match = _RUN_ID_RE.match(path)
            if match:
                self._handle_get_run(match.group(1))
            else:
                self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        """Dispatch POST requests to appropriate handler."""
        path = self.path.split("?")[0]

        if path == "/runs":
            self._handle_create_run()
        else:
            match = _SIGNAL_RE.match(path)
            if match:
                self._handle_signal_run(match.group(1))
            else:
                self._send_json(404, {"error": "not_found"})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        """Send a JSON response.

        Args:
            status: HTTP status code.
            body: JSON-serializable response body.
        """
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any]:
        """Read and parse the request body as JSON.

        Returns:
            Parsed JSON dictionary.

        Raises:
            ValueError: If the body is not valid JSON.
        """
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    @property
    def _manager(self) -> RunManager:
        """Access the RunManager from the server instance."""
        server: AgentServer = self.server  # type: ignore[assignment]
        return server.run_manager

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _handle_health(self) -> None:
        """Return server health status."""
        self._send_json(200, {"status": "ok"})

    def _handle_manifest(self) -> None:
        """Return system capabilities manifest."""
        self._send_json(200, {
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
            "endpoints": [
                "POST /runs",
                "GET /runs",
                "GET /runs/{run_id}",
                "POST /runs/{run_id}/signal",
                "GET /health",
                "GET /manifest",
            ],
        })

    def _handle_list_runs(self) -> None:
        """List all managed runs."""
        manager = self._manager
        runs = manager.list_runs()
        self._send_json(200, {"runs": [manager.to_dict(r) for r in runs]})

    def _handle_get_run(self, run_id: str) -> None:
        """Return a single run by id.

        Args:
            run_id: The run identifier from the URL path.
        """
        manager = self._manager
        run = manager.get_run(run_id)
        if run is None:
            self._send_json(404, {"error": "run_not_found", "run_id": run_id})
            return
        self._send_json(200, manager.to_dict(run))

    def _handle_create_run(self) -> None:
        """Create a new run from the POST body."""
        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return

        if "goal" not in body:
            self._send_json(400, {"error": "missing_goal"})
            return

        manager = self._manager
        run_id = manager.create_run(body)

        # If the server has an executor factory, start the run immediately.
        server: AgentServer = self.server  # type: ignore[assignment]
        if server.executor_factory is not None:
            manager.start_run(run_id, server.executor_factory)

        run = manager.get_run(run_id)
        self._send_json(201, manager.to_dict(run))  # type: ignore[arg-type]

    def _handle_signal_run(self, run_id: str) -> None:
        """Send a signal to an existing run.

        Supported signals: ``cancel``.

        Args:
            run_id: The run identifier from the URL path.
        """
        manager = self._manager
        run = manager.get_run(run_id)
        if run is None:
            self._send_json(404, {"error": "run_not_found", "run_id": run_id})
            return

        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return

        signal = body.get("signal")
        if signal == "cancel":
            ok = manager.cancel_run(run_id)
            if ok:
                self._send_json(200, {"run_id": run_id, "state": "cancelled"})
            else:
                self._send_json(409, {"error": "cannot_cancel", "run_id": run_id})
        else:
            self._send_json(400, {"error": "unknown_signal", "signal": signal})


class AgentServer(HTTPServer):
    """Extended HTTPServer that holds agent state."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Initialize the agent server.

        Args:
            host: Bind address.
            port: Bind port.
        """
        super().__init__((host, port), AgentAPIHandler)
        self.run_manager = RunManager()
        self.executor_factory: Any | None = None

    def start(self) -> None:
        """Start serving (blocking)."""
        print(f"hi-agent server listening on {self.server_address}")  # noqa: T201
        self.serve_forever()
