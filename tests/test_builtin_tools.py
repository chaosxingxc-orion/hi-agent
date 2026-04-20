"""Real integration tests for builtin tool handlers.

P3 constraint: all tests use real I/O, real subprocess, real network.
No mocks allowed — test must reflect actual capability.
"""

import sys

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
        # H-6: base_dir must be passed as workspace_root kwarg, not in payload
        result = file_read_handler({"path": "hello.txt"}, workspace_root=tmp_path)
        assert result["success"] is True
        assert result["content"] == "hello world"
        assert result["size"] == 11

    def test_missing_file_returns_error(self, tmp_path):
        result = file_read_handler({"path": "nonexistent_xyz.txt"}, workspace_root=tmp_path)
        assert result["success"] is False
        assert result["error"] is not None

    def test_empty_path_returns_error(self):
        result = file_read_handler({})
        assert result["success"] is False

    def test_path_traversal_blocked(self, tmp_path):
        result = file_read_handler({"path": "../escape.txt"}, workspace_root=tmp_path)
        assert result["success"] is False
        assert "policy" in result["error"].lower()


class TestFileWrite:
    def test_writes_file(self, tmp_path):
        # H-6: base_dir must be passed as workspace_root kwarg, not in payload
        result = file_write_handler({"path": "out.txt", "content": "data"}, workspace_root=tmp_path)
        assert result["success"] is True
        assert (tmp_path / "out.txt").read_text() == "data"

    def test_creates_parent_dirs(self, tmp_path):
        result = file_write_handler({"path": "a/b/c.txt", "content": "x"}, workspace_root=tmp_path)
        assert result["success"] is True
        assert (tmp_path / "a" / "b" / "c.txt").exists()

    def test_path_traversal_blocked(self, tmp_path):
        result = file_write_handler(
            {"path": "../escape.txt", "content": "x"}, workspace_root=tmp_path
        )
        assert result["success"] is False
        assert "policy" in result["error"].lower()


class TestShellExec:
    def test_echo_command(self):
        result = shell_exec_handler({"command": [sys.executable, "-c", "print('hello')"]})
        assert result["success"] is True
        assert "hello" in result["stdout"]
        assert result["returncode"] == 0

    def test_nonzero_exit(self):
        result = shell_exec_handler(
            {"command": [sys.executable, "-c", "import sys; sys.exit(1)"], "timeout": 5.0}
        )
        assert result["success"] is False
        assert result["returncode"] != 0

    def test_timeout(self):
        # Pass argv as list to avoid shlex.split breaking Windows backslash paths
        result = shell_exec_handler(
            {"command": [sys.executable, "-c", "import time; time.sleep(100)"], "timeout": 1.0}
        )
        assert result["success"] is False
        assert "timed out" in result["error"]


class TestWebFetch:
    """web_fetch_handler enforces URLPolicy unconditionally."""

    def test_loopback_blocked_by_policy(self):
        """URLPolicy blocks loopback addresses — no network I/O attempted."""
        result = web_fetch_handler({"url": "http://127.0.0.1:19871/", "timeout": 5.0})
        assert result["success"] is False
        assert "policy" in result["error"].lower()
        assert result["status_code"] == 0

    def test_private_ip_blocked_by_policy(self):
        """URLPolicy blocks private RFC-1918 addresses."""
        result = web_fetch_handler({"url": "http://192.168.1.1/", "timeout": 2.0})
        assert result["success"] is False
        assert "policy" in result["error"].lower()

    def test_invalid_url(self):
        result = web_fetch_handler({"url": "http://127.0.0.1:19999/nonexistent", "timeout": 2.0})
        assert result["success"] is False

    def test_file_scheme_blocked(self):
        """Non-http/https scheme is rejected before any network I/O."""
        result = web_fetch_handler({"url": "file:///etc/passwd", "timeout": 2.0})
        assert result["success"] is False
        assert "policy" in result["error"].lower()


class TestRegisterBuiltinTools:
    def test_all_four_tools_registered(self, monkeypatch):
        # H-2: shell_exec requires HI_AGENT_ENABLE_SHELL_EXEC=true
        monkeypatch.setenv("HI_AGENT_ENABLE_SHELL_EXEC", "true")
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
        # H-6: pass workspace_root as kwarg, not in payload
        result = spec.handler({"path": "t.txt"}, workspace_root=tmp_path)
        assert result["success"] is True
