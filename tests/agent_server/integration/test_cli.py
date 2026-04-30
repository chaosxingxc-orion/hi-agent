"""Integration tests for the agent-server CLI (W24 I-E).

Drives the build of:
  * agent_server/cli/main.py
  * agent_server/cli/commands/{serve,run,cancel,tail_events}.py

Each test boots a real Uvicorn server on port 9085 and shells out to
``python -m agent_server.cli.main ...`` via subprocess. This validates
the same path operators will exercise in production.

Test surface (>=5 cases):
  1. ``--help`` lists all subcommands
  2. ``run`` posts a request body and prints a success envelope
  3. ``run`` reports a non-zero exit code on connection failure
  4. ``cancel`` falls back to the /signal endpoint when /cancel is 404
  5. ``tail-events`` exits 0 once the run reaches a terminal state
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from agent_server.api.middleware.idempotency import register_idempotency_middleware
from agent_server.api.middleware.tenant_context import TenantContextMiddleware
from agent_server.api.routes_runs import build_router
from agent_server.contracts.errors import NotFoundError
from agent_server.facade.idempotency_facade import IdempotencyFacade
from agent_server.facade.run_facade import RunFacade
from fastapi import FastAPI

from agent_server import AGENT_SERVER_API_VERSION

CLI_PORT = 9085
CLI_HOST = "127.0.0.1"
CLI_BASE = f"http://{CLI_HOST}:{CLI_PORT}"


class _StubBackend:
    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self._counter = 0

    def start_run(self, **kwargs: Any) -> dict[str, Any]:
        self._counter += 1
        rid = kwargs.get("run_id") or f"run_{self._counter:04d}"
        record = {
            "tenant_id": kwargs["tenant_id"],
            "run_id": rid,
            "state": "queued",
            "current_stage": None,
            "started_at": "2026-04-30T00:00:00Z",
            "finished_at": None,
            "metadata": dict(kwargs.get("metadata", {})),
            "llm_fallback_count": 0,
        }
        self.runs[(kwargs["tenant_id"], rid)] = record
        return record

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        # Mark as terminal so tail-events finishes promptly.
        record["state"] = "succeeded"
        record["finished_at"] = "2026-04-30T00:00:01Z"
        return record

    def signal_run(
        self, *, tenant_id: str, run_id: str, signal: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        record = self.runs.get((tenant_id, run_id))
        if record is None:
            raise NotFoundError("run not found", tenant_id=tenant_id, detail=run_id)
        record["state"] = "cancelling" if signal == "cancel" else record["state"]
        return record


def _build_app(tmp_path: Path) -> tuple[FastAPI, _StubBackend]:
    backend = _StubBackend()
    facade = RunFacade(
        start_run=backend.start_run,
        get_run=backend.get_run,
        signal_run=backend.signal_run,
    )
    idem = IdempotencyFacade(db_path=tmp_path / "cli_idem.db")
    app = FastAPI(version=AGENT_SERVER_API_VERSION)
    app.add_middleware(TenantContextMiddleware)
    register_idempotency_middleware(app, facade=idem, strict=False)
    app.include_router(build_router(run_facade=facade))
    return app, backend


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _is_port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        s.close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def cli_server(tmp_path_factory: pytest.TempPathFactory):
    if not _is_port_free(CLI_HOST, CLI_PORT):
        pytest.skip(
            f"port {CLI_PORT} is already bound; skipping CLI integration tests"
        )
    tmp = tmp_path_factory.mktemp("cli_server")
    app, backend = _build_app(tmp)
    config = uvicorn.Config(
        app,
        host=CLI_HOST,
        port=CLI_PORT,
        log_level="warning",
        # Prevent uvicorn from grabbing signal handlers in the worker thread.
        lifespan="off",
    )
    server = uvicorn.Server(config)
    server.config.load()
    server.lifespan = config.lifespan_class(config)
    import threading

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not _wait_for_port(CLI_HOST, CLI_PORT, timeout=15.0):
        server.should_exit = True
        thread.join(timeout=5.0)
        pytest.fail(f"CLI test server did not bind to {CLI_HOST}:{CLI_PORT}")
    yield backend
    server.should_exit = True
    server.force_exit = True
    thread.join(timeout=10.0)


def _invoke_cli(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "agent_server.cli.main", *args]
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )


# ----------------------------------------------------------------------
# Cases
# ----------------------------------------------------------------------


def test_help_lists_all_subcommands() -> None:
    result = _invoke_cli("--help")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for sub in ("serve", "run", "cancel", "tail-events"):
        assert sub in out, f"subcommand {sub!r} missing from --help output"


def test_run_subcommand_posts_request_and_prints_response(
    cli_server: _StubBackend, tmp_path: Path
) -> None:
    request_body = {
        "profile_id": "default",
        "goal": "cli-demo",
        "idempotency_key": "cli-1",
    }
    req_path = tmp_path / "req.json"
    req_path.write_text(json.dumps(request_body), encoding="utf-8")

    result = _invoke_cli(
        "run",
        "--server", CLI_BASE,
        "--tenant", "tenant-cli",
        "--request-json", str(req_path),
        "--idempotency-key", "cli-1",
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    parsed = json.loads(result.stdout)
    assert parsed["tenant_id"] == "tenant-cli"
    assert parsed["run_id"].startswith("run_")


def test_run_subcommand_reports_connection_failure(tmp_path: Path) -> None:
    request_body = {
        "profile_id": "default",
        "goal": "cli-bad",
        "idempotency_key": "cli-bad",
    }
    req_path = tmp_path / "req.json"
    req_path.write_text(json.dumps(request_body), encoding="utf-8")
    # Use a port we know is not bound.
    result = _invoke_cli(
        "run",
        "--server", "http://127.0.0.1:9",
        "--tenant", "t",
        "--request-json", str(req_path),
        "--timeout", "2",
    )
    assert result.returncode != 0
    assert (
        "connection_failed" in result.stderr.lower()
        or "http " in result.stderr.lower()
    )


def test_cancel_falls_back_to_signal_when_cancel_route_is_404(
    cli_server: _StubBackend, tmp_path: Path
) -> None:
    # Create a run first.
    request_body = {
        "profile_id": "default",
        "goal": "to-cancel",
        "idempotency_key": "cli-cancel",
    }
    req_path = tmp_path / "req.json"
    req_path.write_text(json.dumps(request_body), encoding="utf-8")
    create = _invoke_cli(
        "run",
        "--server", CLI_BASE,
        "--tenant", "tenant-cancel",
        "--request-json", str(req_path),
        "--idempotency-key", "cli-cancel",
    )
    rid = json.loads(create.stdout)["run_id"]

    result = _invoke_cli(
        "cancel",
        "--server", CLI_BASE,
        "--tenant", "tenant-cancel",
        "--run-id", rid,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    parsed = json.loads(result.stdout)
    assert parsed["run_id"] == rid


def test_tail_events_polls_until_terminal_state(
    cli_server: _StubBackend, tmp_path: Path
) -> None:
    request_body = {
        "profile_id": "default",
        "goal": "tail-test",
        "idempotency_key": "cli-tail",
    }
    req_path = tmp_path / "req.json"
    req_path.write_text(json.dumps(request_body), encoding="utf-8")
    create = _invoke_cli(
        "run",
        "--server", CLI_BASE,
        "--tenant", "tenant-tail",
        "--request-json", str(req_path),
        "--idempotency-key", "cli-tail",
    )
    rid = json.loads(create.stdout)["run_id"]

    result = _invoke_cli(
        "tail-events",
        "--server", CLI_BASE,
        "--tenant", "tenant-tail",
        "--run-id", rid,
        "--timeout", "10",
        "--poll-interval", "0.5",
        timeout=20.0,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    # Stub backend marks the run as succeeded on read, so we should see it.
    assert "succeeded" in result.stdout
