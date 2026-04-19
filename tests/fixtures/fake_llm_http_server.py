"""Fake LLM HTTP server for integration tests (W11-002).

Returns deterministic heuristic responses so tests run without real API keys.
"""
from __future__ import annotations

import contextlib
import json
import socketserver
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator


class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Handle POST /v1/chat/completions with a deterministic heuristic response."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Suppress default stdout logging to keep test output clean.
        pass

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
            response = {
                "id": f"fake-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "heuristic response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a daemon thread."""

    daemon_threads = True


@contextlib.contextmanager
def fake_llm_server(port: int = 0) -> Iterator[str]:
    """Context manager that starts a fake LLM HTTP server.

    Yields the base_url (e.g. "http://127.0.0.1:<port>").
    The server responds to POST /v1/chat/completions with:
    {
        "id": "fake-<uuid>",
        "choices": [{"message": {"role": "assistant", "content": "heuristic response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    """
    server = _ThreadingHTTPServer(("127.0.0.1", port), _FakeLLMHandler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{actual_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
