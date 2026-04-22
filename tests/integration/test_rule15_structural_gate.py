"""Unit tests for scripts/rule15_structural_gate.py helper functions.

These tests verify the gate script's logic using fake HTTP/subprocess objects.
They do NOT spawn a real server — the gate script itself is the integration
test for the real server path.

Mock usage is legitimate per CLAUDE.md P3:
  - External HTTP calls are mocked to isolate the gate helper logic.
  - subprocess.Popen is mocked so tests do not spawn real processes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# Make the scripts package importable from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.rule15_structural_gate import (
    GateConfig,
    GateEvidence,
    _build_server_command,
    _poll_run_to_terminal,
    _wait_for_health,
    run_gate,
)

# --------------------------------------------------------------------------- #
# Fake HTTP response helpers
# --------------------------------------------------------------------------- #


def _fake_response(status_code: int, payload: dict[str, Any]) -> MagicMock:
    """Build a minimal fake httpx-style response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    # Provide a fake request attribute so _response_json error path works.
    req = SimpleNamespace(method="GET", url="/fake")
    resp.request = req
    return resp


# --------------------------------------------------------------------------- #
# _wait_for_health
# --------------------------------------------------------------------------- #


class TestWaitForHealth:
    def test_returns_snapshot_on_200(self) -> None:
        """_wait_for_health returns the JSON payload when /health returns 200."""
        snapshot = {"health": "ok", "subsystems": {}}
        client = MagicMock()
        client.request.return_value = _fake_response(200, snapshot)

        result = _wait_for_health(client, timeout_s=5.0, poll_interval_s=0.01)

        assert result == snapshot
        client.request.assert_called_once_with("GET", "/health", json=None)

    def test_retries_on_non_200_then_succeeds(self) -> None:
        """_wait_for_health retries 503 responses and succeeds on 200."""
        snapshot = {"health": "ok"}
        client = MagicMock()
        client.request.side_effect = [
            _fake_response(503, {"health": "starting"}),
            _fake_response(503, {"health": "starting"}),
            _fake_response(200, snapshot),
        ]

        result = _wait_for_health(client, timeout_s=5.0, poll_interval_s=0.01)

        assert result == snapshot
        assert client.request.call_count == 3

    def test_raises_on_timeout(self) -> None:
        """_wait_for_health raises RuntimeError when timeout expires."""
        client = MagicMock()
        # Always return 503 so we never get 200.
        client.request.return_value = _fake_response(503, {"health": "starting"})

        with pytest.raises(RuntimeError, match="timed out waiting for /health"):
            _wait_for_health(client, timeout_s=0.05, poll_interval_s=0.01)

    def test_retries_on_connection_error(self) -> None:
        """_wait_for_health retries when the request raises a connection error."""
        snapshot = {"health": "ok"}
        client = MagicMock()
        client.request.side_effect = [
            ConnectionError("refused"),
            _fake_response(200, snapshot),
        ]

        result = _wait_for_health(client, timeout_s=5.0, poll_interval_s=0.01)

        assert result == snapshot


# --------------------------------------------------------------------------- #
# _poll_run_to_terminal
# --------------------------------------------------------------------------- #


class TestPollRunToTerminal:
    def test_returns_payload_on_completed(self) -> None:
        """_poll_run_to_terminal returns (payload, polls, duration) on 'completed'."""
        payload = {"run_id": "r1", "state": "completed"}
        client = MagicMock()
        client.request.return_value = _fake_response(200, payload)

        result_payload, polls, duration = _poll_run_to_terminal(
            client, "r1", timeout_s=5.0, poll_interval_s=0.01
        )

        assert result_payload["state"] == "completed"
        assert polls >= 1
        assert duration >= 0.0

    def test_returns_payload_on_failed(self) -> None:
        """_poll_run_to_terminal accepts 'failed' as a valid terminal state."""
        payload = {"run_id": "r1", "state": "failed"}
        client = MagicMock()
        client.request.return_value = _fake_response(200, payload)

        result_payload, polls, _ = _poll_run_to_terminal(
            client, "r1", timeout_s=5.0, poll_interval_s=0.01
        )

        assert result_payload["state"] == "failed"
        assert polls >= 1

    def test_returns_payload_on_done(self) -> None:
        """_poll_run_to_terminal accepts 'done' as a valid terminal state."""
        payload = {"run_id": "r1", "state": "done"}
        client = MagicMock()
        client.request.return_value = _fake_response(200, payload)

        result_payload, _, _ = _poll_run_to_terminal(
            client, "r1", timeout_s=5.0, poll_interval_s=0.01
        )

        assert result_payload["state"] == "done"

    def test_polls_until_terminal(self) -> None:
        """_poll_run_to_terminal keeps polling while state is non-terminal."""
        client = MagicMock()
        client.request.side_effect = [
            _fake_response(200, {"run_id": "r1", "state": "running"}),
            _fake_response(200, {"run_id": "r1", "state": "running"}),
            _fake_response(200, {"run_id": "r1", "state": "completed"}),
        ]

        result_payload, polls, _ = _poll_run_to_terminal(
            client, "r1", timeout_s=5.0, poll_interval_s=0.01
        )

        assert result_payload["state"] == "completed"
        assert polls == 3

    def test_raises_on_timeout(self) -> None:
        """_poll_run_to_terminal raises RuntimeError when timeout expires."""
        client = MagicMock()
        client.request.return_value = _fake_response(200, {"run_id": "r1", "state": "running"})

        with pytest.raises(RuntimeError, match="timed out waiting for run r1"):
            _poll_run_to_terminal(client, "r1", timeout_s=0.05, poll_interval_s=0.01)

    def test_raises_when_state_missing(self) -> None:
        """_poll_run_to_terminal raises when the response has no state field."""
        client = MagicMock()
        client.request.return_value = _fake_response(200, {"run_id": "r1"})

        with pytest.raises(RuntimeError, match="missing string state"):
            _poll_run_to_terminal(client, "r1", timeout_s=5.0, poll_interval_s=0.01)


# --------------------------------------------------------------------------- #
# _build_server_command
# --------------------------------------------------------------------------- #


class TestBuildServerCommand:
    def test_contains_module_and_port(self) -> None:
        """_build_server_command returns correct Python module invocation."""
        cmd = _build_server_command(9999)
        assert cmd[0] == sys.executable
        assert "-m" in cmd
        assert "hi_agent" in cmd
        assert "serve" in cmd
        assert "--port" in cmd
        assert "9999" in cmd


# --------------------------------------------------------------------------- #
# run_gate with fake Popen and fake client
# --------------------------------------------------------------------------- #


class TestRunGate:
    def _make_config(self, tmp_path: Path, port: int = 18999) -> GateConfig:
        return GateConfig(
            base_url=None,
            port=port,
            output=tmp_path / "evidence.json",
            profile_id="test_structural",
            startup_timeout_s=5.0,
            poll_timeout_s=5.0,
            poll_interval_s=0.01,
            request_timeout_s=5.0,
        )

    def _make_fake_client(self) -> MagicMock:
        """Return a fake httpx.Client that mimics a healthy server with fast runs."""
        client = MagicMock()

        _run_counter = {"n": 0}

        def _side_effect(method: str, path: str, **kwargs: Any) -> MagicMock:
            # /health
            if method == "GET" and path == "/health":
                return _fake_response(200, {"health": "ok"})

            # POST /runs -> return a new run_id each time
            if method == "POST" and path == "/runs":
                _run_counter["n"] += 1
                run_id = f"run-{_run_counter['n']:03d}"
                return _fake_response(
                    201,
                    {"run_id": run_id, "state": "created"},
                )

            # POST /runs/{id}/signal with cancel signal
            if method == "POST" and "/signal" in path:
                run_id_segment = path.split("/")[2]
                # Unknown run
                if run_id_segment == "rule15-structural-unknown":
                    return _fake_response(
                        404, {"error": "run_not_found", "run_id": run_id_segment}
                    )
                return _fake_response(200, {"run_id": run_id_segment, "state": "cancelled"})

            # GET /runs/{id}
            if method == "GET" and path.startswith("/runs/"):
                run_id_segment = path.split("/")[2]
                if run_id_segment == "rule15-structural-unknown":
                    return _fake_response(
                        404, {"error": "run_not_found", "run_id": run_id_segment}
                    )
                return _fake_response(200, {"run_id": run_id_segment, "state": "completed"})

            # Fallback
            return _fake_response(404, {"error": "not_found"})

        client.request.side_effect = _side_effect
        return client

    def test_run_gate_passes_with_fake_server(self, tmp_path: Path) -> None:
        """run_gate returns a GateEvidence with status='passed' when the fake server behaves."""
        config = self._make_config(tmp_path)
        fake_client = self._make_fake_client()

        # Fake Popen: process stays alive (poll returns None).
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 42

        def _fake_client_factory(base_url: str, timeout: float) -> MagicMock:
            return fake_client

        def _fake_popen(cmd: list[str], env: dict) -> MagicMock:
            return fake_proc

        evidence = run_gate(config, client_factory=_fake_client_factory, popen_factory=_fake_popen)

        assert isinstance(evidence, GateEvidence)
        assert evidence.status == "passed"
        assert len(evidence.runs) == 3
        assert all(r.final_state == "completed" for r in evidence.runs)
        assert evidence.cancel_known.get("status_code") == 200
        assert evidence.cancel_unknown.get("status_code") == 404

    def test_run_gate_writes_evidence_json(self, tmp_path: Path) -> None:
        """run_gate writes valid JSON evidence to the configured output path."""
        config = self._make_config(tmp_path)
        fake_client = self._make_fake_client()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 99

        run_gate(
            config,
            client_factory=lambda url, t: fake_client,
            popen_factory=lambda cmd, env: fake_proc,
        )

        assert config.output.exists()
        data = json.loads(config.output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["gate_mode"] == "structural"
        assert len(data["runs"]) == 3

    def test_run_gate_fails_when_server_exits_immediately(self, tmp_path: Path) -> None:
        """run_gate raises when the spawned server process exits immediately."""
        config = self._make_config(tmp_path)

        fake_proc = MagicMock()
        # poll() returns 1 → process exited
        fake_proc.poll.return_value = 1

        with pytest.raises(RuntimeError, match="exited immediately"):
            run_gate(
                config,
                client_factory=lambda url, t: MagicMock(),
                popen_factory=lambda cmd, env: fake_proc,
            )

    def test_run_gate_fails_when_health_times_out(self, tmp_path: Path) -> None:
        """run_gate raises and writes failed evidence when /health never returns 200."""
        config = GateConfig(
            base_url=None,
            port=18998,
            output=tmp_path / "evidence.json",
            profile_id="test_structural",
            startup_timeout_s=0.05,  # very short — will time out
            poll_timeout_s=5.0,
            poll_interval_s=0.01,
            request_timeout_s=5.0,
        )
        fake_client = MagicMock()
        fake_client.request.return_value = _fake_response(503, {"health": "starting"})

        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 77

        with pytest.raises(RuntimeError, match="timed out"):
            run_gate(
                config,
                client_factory=lambda url, t: fake_client,
                popen_factory=lambda cmd, env: fake_proc,
            )

        # Evidence should be written with status=failed
        assert config.output.exists()
        data = json.loads(config.output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    def test_run_gate_uses_external_mode_when_base_url_given(self, tmp_path: Path) -> None:
        """run_gate does not spawn a server when base_url is provided."""
        config = GateConfig(
            base_url="http://127.0.0.1:18997",
            port=18997,
            output=tmp_path / "evidence.json",
            profile_id="test_structural",
            startup_timeout_s=5.0,
            poll_timeout_s=5.0,
            poll_interval_s=0.01,
            request_timeout_s=5.0,
        )
        fake_client = self._make_fake_client()
        popen_spy = MagicMock()

        run_gate(
            config,
            client_factory=lambda url, t: fake_client,
            popen_factory=popen_spy,
        )

        # No subprocess should have been spawned.
        popen_spy.assert_not_called()
