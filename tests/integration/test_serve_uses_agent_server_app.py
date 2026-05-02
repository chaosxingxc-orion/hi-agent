"""W31-N1 acceptance: ``agent-server serve`` runs the agent_server FastAPI app.

Before W31, ``agent_server.cli.commands.serve.run`` shelled out via
``python -m hi_agent serve`` (the legacy hi_agent server with
``/runs``-prefixed routes). RIA cannot reach the new ``/v1/`` facade
through that legacy path. This test boots the CLI in a subprocess on a
free port and asserts that:

  1. the process exposes ``GET /v1/health`` -> 200
  2. the response was served by uvicorn (``server: uvicorn`` header)
  3. the subprocess can be cleanly terminated

Style mirrors tests/agent_server/integration/test_cli.py — same port
selection / poll-until-ready / kill pattern.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def _free_port() -> int:
    """Bind to port 0, learn the assigned port, release it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _http_get(url: str, *, headers: dict[str, str], timeout: float = 5.0):
    """GET ``url`` directly without going through the system HTTP proxy.

    The test fixture targets 127.0.0.1; system-wide HTTP proxies (e.g.
    those configured for outbound research traffic) would otherwise
    intercept the localhost connection and return 502.
    """
    req = urllib.request.Request(url, headers=headers)
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    return opener.open(req, timeout=timeout)


@pytest.mark.serial
def test_serve_subcommand_boots_agent_server_app(tmp_path) -> None:
    """``agent-server serve`` exposes /v1/health from the agent_server FastAPI app.

    The acceptance criterion for W31-N1: the CLI must route requests to
    ``agent_server.api.build_app`` (FastAPI) — not to the legacy
    ``hi_agent`` HTTP server. We assert the route ``/v1/health`` is
    answered with 200 and that the response carries an HTTP header
    advertising uvicorn (``server: uvicorn`` is the default banner).
    """
    port = _free_port()
    host = "127.0.0.1"
    env = dict(os.environ)
    env["AGENT_SERVER_STATE_DIR"] = str(tmp_path / "state")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Posture stays at the lenient default so /v1/runs without an
    # idempotency-key header would warn, but /v1/health is unaffected.
    env.setdefault("HI_AGENT_POSTURE", "dev")

    cmd = [
        sys.executable,
        "-m",
        "agent_server.cli.main",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_port(host, port, timeout=20.0):
            stdout, stderr = proc.communicate(timeout=5.0)
            pytest.fail(
                f"agent-server serve did not bind to {host}:{port}; "
                f"stdout={stdout!r} stderr={stderr!r}"
            )

        # The /v1/health route is wired directly in build_app so it
        # answers 200 even without per-tenant data, but TenantContext
        # middleware still requires X-Tenant-Id for ALL routes.
        url = f"http://{host}:{port}/v1/health"
        with _http_get(url, headers={"X-Tenant-Id": "probe"}) as resp:
            assert resp.status == 200, resp.read()
            server_header = resp.headers.get("server", "").lower()
            assert "uvicorn" in server_header, (
                f"expected uvicorn in server header; got {server_header!r}"
            )
            body = resp.read().decode("utf-8")
        assert "ok" in body, body
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


@pytest.mark.serial
def test_serve_subcommand_default_host_is_loopback(tmp_path) -> None:
    """Without ``--prod`` the CLI must default to 127.0.0.1 (most secure).

    The CLI parser defaults are inspected directly, not by booting a
    server, so this test is fast and deterministic.
    """
    from agent_server.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["serve"])
    assert args.host == "127.0.0.1", args.host
