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

import json
import logging
import subprocess
import threading
from typing import Any

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0  # seconds to wait for a single tool response


class MCPTransportError(Exception):
    """Raised when MCP transport fails to invoke a tool."""


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
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except OSError as exc:
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
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                self._read_response("ping", request_id)
                return True
            except (MCPTransportError, OSError):
                self._proc = None
                return False

    def close(self) -> None:
        """Terminate the subprocess if running."""
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self._proc = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_running(self) -> None:
        """Spawn subprocess if not already running."""
        if self._proc is not None and self._proc.poll() is None:
            return
        import os  # noqa: PLC0415
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
            raise MCPTransportError(
                f"Failed to spawn MCP server command {self._command!r}: {exc}"
            ) from exc
        logger.debug("StdioMCPTransport: spawned subprocess pid=%s", self._proc.pid)

    def _read_response(self, server_id: str, request_id: int) -> dict[str, Any]:
        """Read lines from subprocess stdout until the matching response is found.

        Raises:
            MCPTransportError: On timeout, EOF, or JSON-RPC error response.
        """
        import select  # noqa: PLC0415
        import sys  # noqa: PLC0415

        deadline_remaining = self._timeout
        buf = self._proc.stdout

        # Windows doesn't support select on pipes; use readline with a thread.
        if sys.platform == "win32":
            return self._read_response_windows(server_id, request_id)

        while deadline_remaining > 0:
            readable, _, _ = select.select([buf], [], [], min(deadline_remaining, 1.0))
            if not readable:
                deadline_remaining -= 1.0
                if self._proc.poll() is not None:
                    raise MCPTransportError(
                        f"MCP server {server_id!r} subprocess exited unexpectedly."
                    )
                continue
            raw = buf.readline()
            if not raw:
                raise MCPTransportError(
                    f"MCP server {server_id!r} closed stdout (EOF)."
                )
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

    def _read_response_windows(self, server_id: str, request_id: int) -> dict[str, Any]:
        """Windows fallback: read response in a background thread with timeout."""
        result_holder: list[Any] = []
        exc_holder: list[Exception] = []

        def _reader() -> None:
            buf = self._proc.stdout
            while True:
                raw = buf.readline()
                if not raw:
                    exc_holder.append(
                        MCPTransportError(
                            f"MCP server {server_id!r} closed stdout (EOF)."
                        )
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
