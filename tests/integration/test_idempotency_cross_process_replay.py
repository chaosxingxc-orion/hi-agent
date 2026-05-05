"""Cross-process idempotency replay (W34-D, W34-IDEMPOTENCY).

Layer 3 (E2E) — boots ``agent-server serve`` in a subprocess, drives
``POST /v1/runs`` over real HTTP, terminates the process, boots a fresh
process against the SAME ``--state-dir``, and asserts that:

  1. A retry of the same ``(Idempotency-Key, body)`` pair after the
     restart returns the cached response (same ``run_id``) rather than
     creating a new run.
  2. A retry of the same key with a DIFFERENT body returns HTTP 409
     (body-mismatch behaviour from
     ``agent_server/contracts/idempotency.py``).

Cross-platform note
-------------------
The test relies on signalling a clean shutdown between subprocess
generations. ``proc.terminate()`` is the cross-platform Popen API:
on POSIX it issues SIGTERM, on Windows it calls ``TerminateProcess``.
However, the IdempotencyStore relies on SQLite WAL durability, which
requires a graceful close. Windows ``TerminateProcess`` is hard-kill
and does not give the process a chance to flush, so we skip on Windows
and rely on the dedicated POSIX-signal cross-process replay coverage
to assert the durability invariant. The single-process restart-survival
case is exercised by ``test_idempotency_restart.py``.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(120),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "cross-process replay test requires POSIX signal semantics "
            "for graceful subprocess shutdown; Windows TerminateProcess "
            "is hard-kill and breaks SQLite WAL durability"
        ),
    ),
]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_health(host: str, port: int, timeout: float = 30.0) -> bool:
    """Poll GET /v1/health until 200 or the deadline elapses."""
    url = f"http://{host}:{port}/v1/health"
    deadline = time.monotonic() + timeout
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, headers={"X-Tenant-Id": "probe"}
            )
            with opener.open(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    return False


def _http_post_json(
    url: str,
    *,
    body: dict,
    headers: dict[str, str],
    timeout: float = 10.0,
) -> tuple[int, dict]:
    """POST ``body`` as JSON; return ``(status_code, decoded_body)``.

    A non-2xx response is returned as a tuple just like a 2xx one, so
    callers can assert on 409 etc. without catching ``HTTPError``.
    """
    payload = json.dumps(body).encode("utf-8")
    full_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(
        url, data=payload, headers=full_headers, method="POST"
    )
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                decoded = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                decoded = {"__raw__": raw}
            return resp.status, decoded
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            decoded = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            decoded = {"__raw__": raw}
        return exc.code, decoded


def _spawn_serve(
    *, host: str, port: int, state_dir: Path
) -> subprocess.Popen:
    env = dict(os.environ)
    env["AGENT_SERVER_STATE_DIR"] = str(state_dir)
    env.setdefault("PYTHONIOENCODING", "utf-8")
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
        "--state-dir",
        str(state_dir),
    ]
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _terminate(proc: subprocess.Popen) -> None:
    """Signal a graceful shutdown and wait for the process to exit."""
    proc.terminate()
    try:
        proc.wait(timeout=15.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5.0)


def test_idempotency_replay_across_kernel_restart(tmp_path) -> None:
    """A retry after restart returns the cached response, same run_id.

    Drives the W34-D contract guarantee end-to-end:

    Step 1: spawn agent-server, POST /v1/runs with key K1 and body B,
            capture run_id R1 (status 201).
    Step 2: SIGTERM the process; wait for clean shutdown.
    Step 3: spawn a NEW agent-server against the SAME --state-dir.
    Step 4: POST /v1/runs again with the SAME (K1, B). Expect a status
            in {200, 201} and run_id == R1 (replayed from cache).
    Step 5: POST /v1/runs with K1 but a DIFFERENT goal (B'). Expect 409.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    host = "127.0.0.1"
    port = _free_port()

    tenant = "tenant-w34d-cross-process"
    key1 = "K1-cross-process"
    body_1 = {
        "profile_id": "default",
        "goal": "cross-process replay probe",
        "project_id": "p-w34d",
        "metadata": {"phase": "round_1"},
    }
    body_2 = {
        "profile_id": "default",
        "goal": "DIFFERENT GOAL — should mismatch",
        "project_id": "p-w34d",
        "metadata": {"phase": "round_1"},
    }
    common_headers = {
        "X-Tenant-Id": tenant,
        "Idempotency-Key": key1,
    }
    runs_url = f"http://{host}:{port}/v1/runs"

    # ------------------------------------------------------------------
    # Round 1: original request.
    # ------------------------------------------------------------------
    proc1 = _spawn_serve(host=host, port=port, state_dir=state_dir)
    try:
        if not _wait_for_health(host, port, timeout=30.0):
            stdout, stderr = proc1.communicate(timeout=5.0)
            pytest.fail(
                f"round 1 server did not become healthy; "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        status, body = _http_post_json(
            runs_url, body=body_1, headers=common_headers
        )
        assert status == 201, f"expected 201 on first POST, got {status}: {body}"
        run_id_1 = body.get("run_id")
        assert isinstance(run_id_1, str) and run_id_1, (
            f"missing/empty run_id in first response: {body!r}"
        )
    finally:
        _terminate(proc1)

    # ------------------------------------------------------------------
    # Round 2: fresh process, same state-dir, same (K1, B).
    # ------------------------------------------------------------------
    # Re-pick a port: the OS may not have released the previous one yet
    # on some kernels, and we don't depend on a fixed port.
    port_2 = _free_port()
    runs_url_2 = f"http://{host}:{port_2}/v1/runs"
    proc2 = _spawn_serve(host=host, port=port_2, state_dir=state_dir)
    try:
        if not _wait_for_health(host, port_2, timeout=30.0):
            stdout, stderr = proc2.communicate(timeout=5.0)
            pytest.fail(
                f"round 2 server did not become healthy; "
                f"stdout={stdout!r} stderr={stderr!r}"
            )

        # Replay: same (K1, B) — must return the cached response with
        # run_id == R1. The middleware replays whatever HTTP status the
        # first call produced, which was 201 here.
        status_replay, body_replay = _http_post_json(
            runs_url_2, body=body_1, headers=common_headers
        )
        assert status_replay in (200, 201), (
            f"expected 2xx replay, got {status_replay}: {body_replay}"
        )
        assert body_replay.get("run_id") == run_id_1, (
            f"replay run_id mismatch: expected {run_id_1!r}, "
            f"got {body_replay.get('run_id')!r} (full body={body_replay!r})"
        )

        # Body-mismatch: same key, different body — must return 409.
        status_conflict, body_conflict = _http_post_json(
            runs_url_2, body=body_2, headers=common_headers
        )
        assert status_conflict == 409, (
            f"expected 409 on body mismatch, got {status_conflict}: "
            f"{body_conflict}"
        )
        # Envelope shape: {error, message, tenant_id, detail} per the
        # IdempotencyMiddleware conflict branch.
        assert body_conflict.get("error") == "ConflictError", body_conflict
        assert body_conflict.get("tenant_id") == tenant, body_conflict
    finally:
        _terminate(proc2)
