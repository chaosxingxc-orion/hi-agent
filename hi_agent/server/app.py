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
from collections.abc import Callable
from typing import Any

from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.run_manager import RunManager

# Route patterns for path matching.
_RUN_ID_RE = re.compile(r"^/runs/([^/]+)$")
_SIGNAL_RE = re.compile(r"^/runs/([^/]+)/signal$")
_MEMORY_DREAM_PATH = "/memory/dream"
_MEMORY_CONSOLIDATE_PATH = "/memory/consolidate"
_MEMORY_STATUS_PATH = "/memory/status"


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
        elif path == _MEMORY_STATUS_PATH:
            self._handle_memory_status()
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
        elif path == _MEMORY_DREAM_PATH:
            self._handle_memory_dream()
        elif path == _MEMORY_CONSOLIDATE_PATH:
            self._handle_memory_consolidate()
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
            run_data = dict(body, run_id=run_id)
            task_runner = server.executor_factory(run_data)

            def _executor_fn(_managed_run: Any) -> Any:
                return task_runner()

            manager.start_run(run_id, _executor_fn)

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

    # ------------------------------------------------------------------
    # Memory lifecycle handlers
    # ------------------------------------------------------------------

    @property
    def _memory_manager(self) -> MemoryLifecycleManager | None:
        """Access the MemoryLifecycleManager from the server instance."""
        server: AgentServer = self.server  # type: ignore[assignment]
        return server.memory_manager

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


class AgentServer(HTTPServer):
    """Extended HTTPServer that holds agent state."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        config: Any | None = None,
    ) -> None:
        """Initialize the agent server.

        Args:
            host: Bind address.
            port: Bind port.
            config: Optional TraceConfig instance. When provided, a
                :class:`SystemBuilder` is created and the default
                executor factory is wired automatically.
        """
        super().__init__((host, port), AgentAPIHandler)
        self.run_manager = RunManager()
        self.memory_manager: MemoryLifecycleManager | None = None

        # Lazy import to avoid circular dependency at module level.
        from hi_agent.config.trace_config import TraceConfig

        self._config = config if config is not None else TraceConfig()

        from hi_agent.config.builder import SystemBuilder

        self._builder = SystemBuilder(self._config)
        self.executor_factory: Callable[..., Callable[..., Any]] | None = (
            self._default_executor_factory
        )

    def _default_executor_factory(self, run_data: dict[str, Any]) -> Callable[..., Any]:
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
        executor = self._builder.build_executor(contract)

        def run() -> Any:
            return executor.execute()

        return run

    def start(self) -> None:
        """Start serving (blocking)."""
        print(f"hi-agent server listening on {self.server_address}")  # noqa: T201
        self.serve_forever()
