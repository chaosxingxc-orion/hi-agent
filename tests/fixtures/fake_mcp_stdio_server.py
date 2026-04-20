"""Fake MCP stdio server process for integration tests (W11-002).

Responds to JSON-RPC initialize and tools/list over stdin/stdout.
"""
from __future__ import annotations

import contextlib
import subprocess
import sys
import textwrap
from collections.abc import Iterator

# Minimal Python script that speaks JSON-RPC 2.0 over stdin/stdout.
# Handles "initialize" and "tools/list" methods; exits on EOF.
_FAKE_MCP_SCRIPT = textwrap.dedent("""\
    import json
    import sys

    def handle(req):
        method = req.get("method", "")
        req_id = req.get("id")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.0.1"},
                },
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": []},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
""")


@contextlib.contextmanager
def fake_mcp_stdio_process() -> Iterator[subprocess.Popen]:
    """Launch a fake MCP server subprocess that speaks JSON-RPC over stdio."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _FAKE_MCP_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield proc
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.wait(timeout=5)
