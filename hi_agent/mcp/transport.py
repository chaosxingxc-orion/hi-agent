"""MCP transport implementations.

Currently provides ``StdioMCPTransport`` — a JSON-RPC 2.0 client that
communicates with an MCP server subprocess over its stdin/stdout.

Protocol (MCP JSON-RPC 2.0 over stdio):
  - Each message is a single-line JSON object terminated by ``\\n``.
  - Request:  {"jsonrpc": "2.0", "id": <int>, "method": <str>, "params": <dict>}
  - Response: {"jsonrpc": "2.0", "id": <int>, "result": <any>}
               or {"jsonrpc": "2.0", "id": <int>, "error": {"code": <int>, "message": <str>}}

Usage::

    transport = StdioMCPTransport(command="npx @modelcontextprotocol/server-filesystem /tmp")
    result = transport.invoke("server_id", "read_file", {"path": "/tmp/test.txt"})
    transport.close()
"""

from __future__ import annotations

import collections
import json
import logging
import subprocess
import threading
import time
from typing import Any

from hi_agent.observability.silent_degradation import record_silent_degradation

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0  # seconds to wait for a single tool response
_MAX_RESTART_ATTEMPTS = 5  # W10-005: max restart attempts before marking unavailable
_RESTART_BACKOFF_BASE = 1.0  # seconds; doubles each attempt (1, 2, 4, 8, 16)


class MCPTransportError(Exception):
    """Raised when MCP transport fails to invoke a tool."""


class TransportClosedError(MCPTransportError):
    """HD-8: stdin / process is unavailable for writes.

    Distinguished from generic ``MCPTransportError`` so callers can
    differentiate "subprocess closed our pipe" (recoverable via restart)
    from "subprocess returned a JSON-RPC error" (a real protocol failure).
    """


def _bump_closed_fd_counter() -> None:
    """Increment ``mcp_transport_closed_fd_total`` (Rule 7 alarm bell)."""
    try:
        from hi_agent.observability.collector import get_metrics_collector

        _mc = get_metrics_collector()
        if _mc is not None:
            _mc.increment("mcp_transport_closed_fd_total")
    except Exception as exc:
        record_silent_degradation(
            component="mcp.transport._increment_closed_fd_counter",
            reason="metrics_increment_failed",
            exc=exc,
        )


class StdioMCPTransport:
    """JSON-RPC 2.0 transport for MCP servers running as subprocesses.

    Spawns the server command on first use (lazy init), then reuses the
    subprocess for all subsequent calls.  Thread-safe via a per-instance lock.

    Args:
        command: Shell command string or list of args to spawn the MCP server.
        timeout: Per-request timeout in seconds (default 30).
        env: Optional extra environment variables for the subprocess.
    """

    def __init__(
        self,
        command: str | list[str],
        timeout: float = _REQUEST_TIMEOUT,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._timeout = timeout
        self._env = env
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._stderr_buf: collections.deque[str] = collections.deque(maxlen=1024)
        self._stderr_thread: threading.Thread | None = None
        self._subprocess_threads: list[threading.Thread] = []
        # W10-005: crash restart tracking
        self._restart_attempts: int = 0
        self._unavailable: bool = False
        self._server_id: str = ""  # set on first invoke for audit logging

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, server_id: str, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC ``tools/call`` request and return the result dict.

        Args:
            server_id: Logical server identifier (used for logging only).
            tool_name: MCP tool name to call.
            payload: Arguments for the tool.

        Returns:
            The ``result`` dict from the JSON-RPC response.

        Raises:
            MCPTransportError: On subprocess failure, timeout, or JSON-RPC error.
        """
        with self._lock:
            self._ensure_running()
            request_id = self._next_id
            self._next_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": payload},
            }
            line = json.dumps(request, ensure_ascii=False) + "\n"
            # HD-8: explicit fd-closure guard. The lazy spawn in
            # ``_ensure_running`` may have left ``stdin`` closed if the
            # subprocess died between calls — write() would otherwise raise
            # a confusing OSError that masks the root cause. We compare
            # ``closed`` to ``True`` so a MagicMock test double (whose
            # ``closed`` attribute is itself a MagicMock — truthy by
            # default) does not accidentally trip the guard.
            stdin_handle = self._proc.stdin if self._proc is not None else None
            if (
                self._proc is None
                or stdin_handle is None
                or getattr(stdin_handle, "closed", False) is True
            ):
                _bump_closed_fd_counter()
                self._proc = None
                raise TransportClosedError(
                    f"MCP server {server_id!r} stdin closed before write (HD-8)."
                )
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except OSError as exc:
                _bump_closed_fd_counter()
                self._proc = None
                raise MCPTransportError(
                    f"Failed to write to MCP server {server_id!r}: {exc}"
                ) from exc

            return self._read_response(server_id, request_id)

    def ping(self) -> bool:
        """Send an ``initialize`` handshake and return True if server responds.

        Used by MCPHealth to verify a server is reachable without calling a tool.
        """
        with self._lock:
            try:
                self._ensure_running()
            except MCPTransportError:
                return False
            request_id = self._next_id
            self._next_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "hi-agent", "version": "1.0"},
                },
            }
            line = json.dumps(request, ensure_ascii=False) + "\n"
            # HD-8: same fd-closure guard as ``invoke``. ping() returns
            # False instead of raising because health probes treat
            # transport closure as "unreachable", not as a fatal error.
            stdin_handle = self._proc.stdin if self._proc is not None else None
            if (
                self._proc is None
                or stdin_handle is None
                or getattr(stdin_handle, "closed", False) is True
            ):
                _bump_closed_fd_counter()
                self._proc = None
                return False
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                self._read_response("ping", request_id)
                return True
            except (MCPTransportError, OSError):
                _bump_closed_fd_counter()
                self._proc = None
                return False

    def list_tools(self, server_id: str, timeout: float | None = None) -> list[dict]:
        """Send a ``tools/list`` JSON-RPC request and return the tool list.

        Args:
            server_id: Logical server identifier (used for logging only).
            timeout: Per-request timeout override in seconds. Uses instance
                default when None.

        Returns:
            List of tool dicts, each with at minimum {"name": str}.
            May also include "description" and "inputSchema".

        Raises:
            MCPTransportError: On subprocess failure, timeout, JSON-RPC error,
                or invalid response schema.
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        with self._lock:
            self._ensure_running()
            request_id = self._next_id
            self._next_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/list",
                "params": {},
            }
            line = json.dumps(request, ensure_ascii=False) + "\n"
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except OSError as exc:
                self._proc = None
                raise MCPTransportError(
                    f"Failed to write tools/list to MCP server {server_id!r}: {exc}"
                ) from exc

            # Temporarily override timeout for this call only
            orig_timeout = self._timeout
            self._timeout = effective_timeout
            try:
                response = self._read_response(server_id, request_id)
            finally:
                self._timeout = orig_timeout

        # Validate response schema
        if not isinstance(response, dict):
            raise MCPTransportError(
                f"tools/list response for {server_id!r} must be a dict, "
                f"got {type(response).__name__}"
            )
        tools = response.get("tools")
        if tools is None:
            raise MCPTransportError(
                f"tools/list response for {server_id!r} missing 'tools' key: {response!r}"
            )
        if not isinstance(tools, list):
            raise MCPTransportError(
                f"tools/list 'tools' field for {server_id!r} must be a list, "
                f"got {type(tools).__name__}"
            )
        # Validate each tool has at least a 'name'
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict) or "name" not in tool:
                raise MCPTransportError(
                    f"tools/list tool[{i}] for {server_id!r} missing 'name': {tool!r}"
                )
        return tools

    def get_stderr_tail(self, n: int = 20) -> list[str]:
        """Return the last n lines of stderr output from the subprocess.

        Returns empty list if no stderr has been captured or subprocess not started.
        Never raises.
        """
        try:
            lines = list(self._stderr_buf)
            return lines[-n:] if len(lines) > n else lines
        except Exception:
            from hi_agent.observability.collector import get_metrics_collector
            _mc = get_metrics_collector()
            if _mc is not None:
                _mc.increment("hi_agent_mcp_stderr_tail_failure_total")
            return []

    def close(self) -> None:
        """Terminate the subprocess if running and join stderr-reader threads."""
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except Exception as exc:
                    record_silent_degradation(
                        component="mcp.transport.StdioMCPTransport.close",
                        reason="subprocess_terminate_failed",
                        exc=exc,
                    )
                finally:
                    self._proc = None
            threads, self._subprocess_threads = self._subprocess_threads, []
        for t in threads:
            t.join(timeout=5)
            if t.is_alive():
                logger.warning(
                    "StdioMCPTransport: stderr-reader thread %r did not exit within 5s",
                    t.name,
                )
                try:
                    from hi_agent.observability.collector import get_metrics_collector

                    _mc = get_metrics_collector()
                    if _mc is not None:
                        _mc.increment("hi_agent_mcp_thread_join_timeout_total")
                except Exception as exc:
                    record_silent_degradation(
                        component="mcp.transport.StdioMCPTransport.close",
                        reason="thread_join_metrics_failed",
                        exc=exc,
                    )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_stderr_reader(self) -> None:
        """Start background thread draining subprocess stderr into ring buffer."""

        def _read_stderr(proc: subprocess.Popen, buf: collections.deque) -> None:
            try:
                for raw in proc.stderr:
                    if isinstance(raw, str):
                        line = raw.rstrip("\n")
                    else:
                        line = raw.rstrip(b"\n").decode("utf-8", errors="replace")
                    buf.append(line)
            except Exception as exc:
                record_silent_degradation(
                    component="mcp.transport.StdioMCPTransport._start_stderr_reader",
                    reason="stderr_read_failed",
                    exc=exc,
                )

        self._stderr_thread = threading.Thread(
            target=_read_stderr,
            args=(self._proc, self._stderr_buf),
            daemon=False,
            name=f"mcp-stderr-{id(self)}",
        )
        self._stderr_thread.start()
        self._subprocess_threads.append(self._stderr_thread)

    def _ensure_running(self) -> None:
        """Spawn subprocess if not already running.

        W10-005: on crash, retries with exponential backoff up to
        _MAX_RESTART_ATTEMPTS times.  After exhausting retries the transport
        is marked unavailable and raises MCPTransportError on every call.
        """
        if self._proc is not None and self._proc.poll() is None:
            return

        # W10-005: refuse to restart if we've exceeded the limit
        if self._unavailable:
            raise MCPTransportError(
                f"MCP server {self._command!r} is permanently unavailable "
                f"after {_MAX_RESTART_ATTEMPTS} failed restart attempts."
            )

        # Apply backoff delay for crash restarts (not the first spawn)
        if self._restart_attempts > 0:
            delay = min(
                _RESTART_BACKOFF_BASE * (2 ** (self._restart_attempts - 1)),
                _RESTART_BACKOFF_BASE * (2 ** (_MAX_RESTART_ATTEMPTS - 1)),
            )
            logger.warning(
                "StdioMCPTransport: restarting server (attempt %d/%d) after %.1fs backoff",
                self._restart_attempts + 1,
                _MAX_RESTART_ATTEMPTS,
                delay,
            )
            time.sleep(delay)

        import os

        env = os.environ.copy()
        if self._env:
            env.update(self._env)
        try:
            if isinstance(self._command, str):
                self._proc = subprocess.Popen(
                    self._command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    bufsize=1,
                )
            else:
                self._proc = subprocess.Popen(
                    self._command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    bufsize=1,
                )
        except OSError as exc:
            self._restart_attempts += 1
            if self._restart_attempts >= _MAX_RESTART_ATTEMPTS:
                self._unavailable = True
                try:
                    from hi_agent.observability.audit import emit_mcp_server_restart

                    emit_mcp_server_restart(
                        self._server_id or repr(self._command),
                        self._restart_attempts,
                        success=False,
                        error=str(exc),
                    )
                except Exception as exc2:
                    record_silent_degradation(
                        component="mcp.transport.StdioMCPTransport._ensure_running",
                        reason="audit_emit_restart_failed",
                        exc=exc2,
                    )
            raise MCPTransportError(
                f"Failed to spawn MCP server command {self._command!r}: {exc}"
            ) from exc

        logger.debug("StdioMCPTransport: spawned subprocess pid=%s", self._proc.pid)
        if self._restart_attempts > 0:
            # Emit audit event for successful restart
            try:
                from hi_agent.observability.audit import emit_mcp_server_restart

                emit_mcp_server_restart(
                    self._server_id or repr(self._command),
                    self._restart_attempts,
                    success=True,
                )
            except Exception as exc:
                record_silent_degradation(
                    component="mcp.transport.StdioMCPTransport._ensure_running",
                    reason="audit_emit_success_restart_failed",
                    exc=exc,
                )
        self._restart_attempts += 1
        if self._restart_attempts >= _MAX_RESTART_ATTEMPTS:
            self._unavailable = True
            logger.warning(
                "StdioMCPTransport: server %r reached max restart attempts (%d); "
                "marking unavailable.",
                self._command,
                _MAX_RESTART_ATTEMPTS,
            )
        self._start_stderr_reader()

    def _read_response(self, server_id: str, request_id: int) -> dict[str, Any]:
        """Read lines from subprocess stdout until the matching response is found.

        Raises:
            MCPTransportError: On timeout, EOF, or JSON-RPC error response.
        """
        import select
        import sys

        deadline_remaining = self._timeout
        buf = self._proc.stdout

        # Windows doesn't support select on pipes; also test doubles may expose
        # stdout without a valid integer fileno(). In both cases, use a
        # threaded readline fallback.
        if sys.platform == "win32":
            return self._read_response_threaded(server_id, request_id)
        try:
            fileno = buf.fileno()
            if not isinstance(fileno, int):
                return self._read_response_threaded(server_id, request_id)
        except (AttributeError, OSError, TypeError, ValueError):
            return self._read_response_threaded(server_id, request_id)

        while deadline_remaining > 0:
            try:
                readable, _, _ = select.select([buf], [], [], min(deadline_remaining, 1.0))
            except (TypeError, ValueError, OSError):
                return self._read_response_threaded(server_id, request_id)
            if not readable:
                deadline_remaining -= 1.0
                if self._proc.poll() is not None:
                    raise MCPTransportError(
                        f"MCP server {server_id!r} subprocess exited unexpectedly."
                    )
                continue
            raw = buf.readline()
            if not raw:
                raise MCPTransportError(f"MCP server {server_id!r} closed stdout (EOF).")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("StdioMCPTransport: ignoring non-JSON line: %r", raw[:200])
                continue
            if msg.get("id") != request_id:
                logger.debug(
                    "StdioMCPTransport: skipping response id=%s (waiting for %s)",
                    msg.get("id"),
                    request_id,
                )
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPTransportError(
                    f"MCP server {server_id!r} returned error: "
                    f"code={err.get('code')} message={err.get('message')!r}"
                )
            return msg.get("result", {})

        raise MCPTransportError(
            f"MCP server {server_id!r} timed out after {self._timeout}s "
            f"waiting for response to request id={request_id}."
        )

    def _read_response_threaded(self, server_id: str, request_id: int) -> dict[str, Any]:
        """Threaded fallback: read response in a background thread with timeout."""
        result_holder: list[Any] = []
        exc_holder: list[Exception] = []

        def _reader() -> None:
            buf = self._proc.stdout
            while True:
                raw = buf.readline()
                if not raw:
                    exc_holder.append(
                        MCPTransportError(f"MCP server {server_id!r} closed stdout (EOF).")
                    )
                    return
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") != request_id:
                    continue
                if "error" in msg:
                    err = msg["error"]
                    exc_holder.append(
                        MCPTransportError(
                            f"MCP server {server_id!r} returned error: "
                            f"code={err.get('code')} message={err.get('message')!r}"
                        )
                    )
                    return
                result_holder.append(msg.get("result", {}))
                return

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout=self._timeout)

        if exc_holder:
            raise exc_holder[0]
        if result_holder:
            return result_holder[0]
        raise MCPTransportError(
            f"MCP server {server_id!r} timed out after {self._timeout}s "
            f"waiting for response to request id={request_id}."
        )


# ---------------------------------------------------------------------------
# MultiStdioTransport — manages one StdioMCPTransport per server_id
# ---------------------------------------------------------------------------


class MultiStdioTransport:
    """Transport router that maintains one ``StdioMCPTransport`` per server_id.

    Used by ``MCPBinding`` which routes tool calls as
    ``transport.invoke(server_id, tool_name, payload)``.  The command for
    each server is resolved from the ``MCPRegistry`` on first access.

    Args:
        mcp_registry: MCPRegistry instance to look up server commands.
        timeout: Per-request timeout forwarded to each ``StdioMCPTransport``.
    """

    def __init__(self, mcp_registry: Any, timeout: float = _REQUEST_TIMEOUT) -> None:
        self._registry = mcp_registry
        self._timeout = timeout
        self._transports: dict[str, StdioMCPTransport] = {}
        self._lock = threading.Lock()

    def invoke(self, server_id: str, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke *tool_name* on *server_id*, spawning a transport if needed."""
        transport = self._get_or_create(server_id)
        return transport.invoke(server_id, tool_name, payload)

    def ping(self, server_id: str | None = None) -> bool:
        """Ping the first registered server (or *server_id* if given).

        Used by MCPHealth when the transport is a MultiStdioTransport.
        """
        if server_id is None:
            servers = self._registry.list_servers()
            if not servers:
                return False
            server_id = servers[0]["server_id"]
        try:
            transport = self._get_or_create(server_id)
            return transport.ping()
        except MCPTransportError:
            return False

    def close_all(self) -> None:
        """Terminate all managed subprocesses."""
        with self._lock:
            for t in self._transports.values():
                t.close()
            self._transports.clear()

    def _get_or_create(self, server_id: str) -> StdioMCPTransport:
        with self._lock:
            if server_id in self._transports:
                return self._transports[server_id]
            entry = self._registry.get(server_id)
            if entry is None:
                raise MCPTransportError(
                    f"MultiStdioTransport: server_id={server_id!r} not found in MCPRegistry."
                )
            if entry.transport != "stdio":
                raise MCPTransportError(
                    f"MultiStdioTransport: server_id={server_id!r} uses transport="
                    f"{entry.transport!r}; only 'stdio' is supported by this transport."
                )
            t = StdioMCPTransport(command=entry.endpoint, timeout=self._timeout)
            self._transports[server_id] = t
            return t
