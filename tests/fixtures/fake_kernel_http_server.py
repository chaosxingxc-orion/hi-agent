"""Fake kernel HTTP server for integration tests (W11-002).

Simulates agent-kernel run lifecycle endpoints.
"""

from __future__ import annotations

import contextlib
import json
import socketserver
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer


class _FakeKernelHandler(BaseHTTPRequestHandler):
    """Handle run lifecycle requests with deterministic in-memory state.

    Handles:
      POST /runs          -> 201 Created, returns run_id
      GET  /runs/{id}     -> 200 with status "completed"
      POST /runs/{id}/stages -> 200
      GET  /health        -> 200 {"status": "ok"}
    """

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path.startswith("/runs/"):
            run_id = self.path.split("/runs/")[1].split("/")[0]
            self._send_json(
                200,
                {
                    "run_id": run_id,
                    "status": "completed",
                    "outcome": "completed",
                },
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        self._read_body()
        if self.path == "/runs":
            run_id = uuid.uuid4().hex
            self._send_json(201, {"run_id": run_id, "status": "created"})
        elif self.path.startswith("/runs/") and self.path.endswith("/stages"):
            self._send_json(200, {"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a daemon thread."""

    daemon_threads = True


@contextlib.contextmanager
def fake_kernel_server(port: int = 0) -> Iterator[str]:
    """Yields base_url of a fake kernel server.

    Handles: POST /runs -> 201, GET /runs/{id} -> completed,
    POST /runs/{id}/stages -> 200, GET /health -> 200
    """
    server = _ThreadingHTTPServer(("127.0.0.1", port), _FakeKernelHandler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{actual_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
