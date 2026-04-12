"""Real integration tests for builtin tool handlers.

P3 constraint: all tests use real I/O, real subprocess, real network.
No mocks allowed — test must reflect actual capability.
"""
import http.server
import os
import sys
import threading
import time

import pytest

from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.tools.builtin import (
    file_read_handler,
    file_write_handler,
    register_builtin_tools,
    shell_exec_handler,
    web_fetch_handler,
)


class TestFileRead:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        result = file_read_handler({"path": str(f)})
        assert result["success"] is True
        assert result["content"] == "hello world"
        assert result["size"] == 11

    def test_missing_file_returns_error(self):
        result = file_read_handler({"path": "/nonexistent/path/xyz.txt"})
        assert result["success"] is False
        assert result["error"] is not None

    def test_empty_path_returns_error(self):
        result = file_read_handler({})
        assert result["success"] is False


class TestFileWrite:
    def test_writes_file(self, tmp_path):
        f = tmp_path / "out.txt"
        result = file_write_handler({"path": str(f), "content": "data"})
        assert result["success"] is True
        assert f.read_text() == "data"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = file_write_handler({"path": str(f), "content": "x"})
        assert result["success"] is True
        assert f.exists()


class TestShellExec:
    def test_echo_command(self):
        result = shell_exec_handler({"command": "echo hello"})
        assert result["success"] is True
        assert "hello" in result["stdout"]
        assert result["returncode"] == 0

    def test_nonzero_exit(self):
        result = shell_exec_handler({"command": "exit 1", "timeout": 5.0})
        assert result["success"] is False
        assert result["returncode"] != 0

    def test_timeout(self):
        cmd = f"{sys.executable} -c \"import time; time.sleep(100)\""
        result = shell_exec_handler({"command": cmd, "timeout": 1.0})
        assert result["success"] is False
        assert "timed out" in result["error"]


class TestWebFetch:
    """Uses a real local HTTP server — no mocks."""

    def _start_server(self, port: int, content: bytes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", port), Handler)
        t = threading.Thread(target=server.serve_forever)
        t.daemon = True
        t.start()
        return server

    def test_fetches_local_server(self):
        server = self._start_server(19871, b"hello from server")
        # Give the server thread a moment to bind before the first request.
        time.sleep(0.1)
        # Bypass any system HTTP proxy (e.g. 127.0.0.1:7890) for localhost.
        old_no_proxy = os.environ.get("no_proxy", "")
        old_NO_PROXY = os.environ.get("NO_PROXY", "")
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        try:
            result = web_fetch_handler({"url": "http://127.0.0.1:19871/", "timeout": 5.0})
            assert result["success"] is True
            assert "hello from server" in result["content"]
            assert result["status_code"] == 200
        finally:
            os.environ["no_proxy"] = old_no_proxy
            os.environ["NO_PROXY"] = old_NO_PROXY
            server.shutdown()

    def test_invalid_url(self):
        result = web_fetch_handler({"url": "http://127.0.0.1:19999/nonexistent", "timeout": 2.0})
        assert result["success"] is False


class TestRegisterBuiltinTools:
    def test_all_four_tools_registered(self):
        registry = CapabilityRegistry()
        register_builtin_tools(registry)
        names = registry.list_names()
        assert "file_read" in names
        assert "file_write" in names
        assert "web_fetch" in names
        assert "shell_exec" in names

    def test_invokable(self, tmp_path):
        registry = CapabilityRegistry()
        register_builtin_tools(registry)
        f = tmp_path / "t.txt"
        f.write_text("test")
        spec = registry.get("file_read")
        result = spec.handler({"path": str(f)})
        assert result["success"] is True
