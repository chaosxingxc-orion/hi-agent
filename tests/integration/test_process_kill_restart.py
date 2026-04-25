"""Cross-process restart integration test for RO-5.

Starts hi-agent serve as a real subprocess, submits a run, kills the process,
restarts it, and verifies the run record is still queryable.

Marks:
  @pytest.mark.integration — requires a real subprocess and network port.
  @pytest.mark.slow — may take up to 30 s.
  @pytest.mark.xfail — durable queue not yet wired through the full server
    boot path (requires RO-3 file-backed RunQueue plumbed into AgentServer
    with server_db_dir pointing to the HI_AGENT_DATA_DIR, which is tracked
    as DF-pending).

Layer 3 — drives through the public HTTP interface with a real subprocess.
Zero MagicMock on the server.
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

# Guard: httpx is optional in some CI environments; skip gracefully.
httpx = pytest.importorskip("httpx", reason="httpx required for subprocess E2E test")


_PORT = 18080
_BASE = f"http://127.0.0.1:{_PORT}"


def _wait_for_health(timeout: float = 20.0) -> bool:
    """Poll /health until 200 or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{_BASE}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _start_server(data_dir: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hi_agent",
            "serve",
            "--port",
            str(_PORT),
        ],
        env={
            **__import__("os").environ,
            "HI_AGENT_POSTURE": "research",
            "HI_AGENT_DATA_DIR": data_dir,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.xfail(
    reason=(
        "Durable RunQueue not yet wired through full AgentServer boot path — "
        "requires server_db_dir to point to HI_AGENT_DATA_DIR for the "
        "file-backed RunQueue to be picked up (DF-pending). "
        "Test code is correct; implementation gap in app.py boot wiring."
    ),
    strict=False,
)
def test_run_survives_process_restart(tmp_path):
    """E2E: submit a run, kill the process, restart, query the run."""
    data_dir = str(tmp_path / "data")
    __import__("os").makedirs(data_dir, exist_ok=True)

    # Start first server instance.
    proc1 = _start_server(data_dir)
    try:
        healthy = _wait_for_health(timeout=20.0)
        assert healthy, "Server did not become healthy within 20 s"

        # Submit a run.
        resp = httpx.post(
            f"{_BASE}/runs",
            json={"goal": "test restart durability", "profile_id": "default"},
            timeout=10.0,
        )
        assert resp.status_code in (200, 201, 202), f"Unexpected status: {resp.status_code}"
        body = resp.json()
        run_id = body.get("run_id")
        assert run_id, f"No run_id in response: {body}"

    finally:
        # Kill with terminate (SIGTERM on Unix; TerminateProcess on Windows).
        proc1.terminate()
        try:
            proc1.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc1.kill()

    # Restart the server with the same data directory.
    proc2 = _start_server(data_dir)
    try:
        healthy2 = _wait_for_health(timeout=20.0)
        assert healthy2, "Restarted server did not become healthy within 20 s"

        # Query the run — it should still be found.
        resp2 = httpx.get(f"{_BASE}/runs/{run_id}", timeout=10.0)
        assert resp2.status_code == 200, (
            f"Expected 200 after restart, got {resp2.status_code}: {resp2.text}"
        )
        run_data = resp2.json()
        assert run_data.get("run_id") == run_id
        assert run_data.get("state") in (
            "queued",
            "running",
            "completed",
            "cancelled",
            "failed",
        ), f"Unexpected state: {run_data.get('state')}"

    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc2.kill()
