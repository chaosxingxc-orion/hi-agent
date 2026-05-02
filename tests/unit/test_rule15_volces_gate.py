from __future__ import annotations

import sys
from collections import deque
from types import SimpleNamespace

import pytest
from scripts.run_t3_gate import (
    GateConfig,
    _assert_no_fallback_events,
    _build_client,
    _build_parser,
    _poll_run_to_terminal,
    _validate_readiness_snapshot,
    run_gate,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict,
        method: str = "GET",
        url: str = "/",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = SimpleNamespace(method=method, url=url)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self) -> None:
        self.ready_calls = 0
        self.run_counter = 0
        self.cancelled: list[str] = []
        self.run_bodies: list[dict] = []
        self._polls: dict[str, deque[dict]] = {}
        self.closed = False

    def request(self, method: str, url: str, **kwargs):
        path = url
        if path == "/ready":
            self.ready_calls += 1
            return FakeResponse(200, {"llm_mode": "real", "llm_provider": "volces"}, method, url)
        if path == "/runs" and method == "POST":
            self.run_bodies.append(kwargs.get("json", {}))
            self.run_counter += 1
            run_id = f"run-{self.run_counter}"
            self._polls[run_id] = deque(
                [
                    {"run_id": run_id, "state": "running", "fallback_events": []},
                    {"run_id": run_id, "state": "completed", "fallback_events": []},
                ]
            )
            return FakeResponse(201, {"run_id": run_id, "state": "created"}, method, url)
        if path.startswith("/runs/") and path.endswith("/cancel") and method == "POST":
            run_id = path.split("/runs/")[1].split("/")[0]
            if run_id in ("rule15-unknown-run", "t3-gate-unknown-run"):
                return FakeResponse(404, {"error": "run_not_found"}, method, url)
            self.cancelled.append(run_id)
            return FakeResponse(200, {"run_id": run_id, "state": "cancelled"}, method, url)
        if path.startswith("/runs/") and method == "GET":
            run_id = path.split("/runs/")[1].split("/")[0]
            queue = self._polls.get(run_id)
            if not queue:
                return FakeResponse(404, {"error": "run_not_found"}, method, url)
            payload = queue[0]
            if len(queue) > 1:
                queue.popleft()
            return FakeResponse(200, payload, method, url)
        raise AssertionError(f"unexpected request: {method} {path}")

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, cmd: list[str]) -> None:
        self.cmd = cmd
        self.pid = 4321
        self._poll = None
        self.terminated = False
        self.waited = False

    def poll(self):
        return self._poll

    def terminate(self):
        self.terminated = True
        self._poll = 0

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_validate_readiness_requires_volces_fields():
    _validate_readiness_snapshot({"llm_mode": "real", "llm_provider": "volces"}, "volces")


def test_build_client_bypasses_environment_proxies():
    client = _build_client("http://127.0.0.1:8097", request_timeout_s=2)
    try:
        assert client._trust_env is False
    finally:
        client.close()


def test_build_parser_defaults_profile_id_to_rule15_volces():
    args = _build_parser().parse_args(["--output", "evidence.json"])
    assert args.profile_id == "rule15_volces"


def test_build_parser_accepts_custom_profile_id():
    args = _build_parser().parse_args(
        ["--output", "evidence.json", "--profile-id", "custom-profile"]
    )
    assert args.profile_id == "custom-profile"


def test_validate_readiness_fails_when_fields_missing():
    with pytest.raises(RuntimeError, match="missing required field"):
        _validate_readiness_snapshot({"ready": True}, "volces")


def test_validate_readiness_fails_when_provider_or_mode_wrong():
    with pytest.raises(RuntimeError, match="expected 'real'"):
        _validate_readiness_snapshot({"llm_mode": "heuristic", "llm_provider": "openai"}, "volces")


def test_poll_run_to_terminal_returns_completed(monkeypatch):
    client = FakeClient()
    client._polls["run-1"] = deque(
        [
            {"run_id": "run-1", "state": "running", "fallback_events": []},
            {"run_id": "run-1", "state": "completed", "fallback_events": []},
        ]
    )
    monkeypatch.setattr("scripts.run_t3_gate.time.sleep", lambda *_: None)
    ticks = iter([0, 0, 1, 1, 2, 2])
    monkeypatch.setattr("scripts.run_t3_gate.time.monotonic", ticks.__next__)
    payload, polls, duration = _poll_run_to_terminal(
        client, "run-1", timeout_s=10, poll_interval_s=0
    )
    assert payload["state"] == "completed"
    assert polls == 2
    assert duration >= 0


def test_assert_no_fallback_events_rejects_nested_events():
    with pytest.raises(RuntimeError, match="must not emit fallback events"):
        _assert_no_fallback_events({"fallback_events": [{"kind": "route"}]}, label="run-1")


def _clean_head_state():
    """Stub for head_state_factory that simulates a clean git worktree."""
    return ("abc1234def567890abc1234def567890abc12345", "2026-04-27T00:00:00+00:00", False)


def test_run_gate_with_fakes_creates_evidence_and_writes_file(tmp_path, monkeypatch):
    client = FakeClient()
    process = FakeProcess(["python", "-m", "hi_agent", "serve", "--port", "8089"])
    output = tmp_path / "evidence.json"
    config = GateConfig(
        base_url=None,
        port=8089,
        output=output,
        profile_id="custom-profile",
        provider="volces",
        inject_key=False,
        ready_timeout_s=10,
        poll_timeout_s=10,
        poll_interval_s=0,
        request_timeout_s=2,
        startup_timeout_s=2,
    )
    monkeypatch.setattr("scripts.run_t3_gate.time.sleep", lambda *_: None)
    ticks = iter(range(1000))
    monkeypatch.setattr("scripts.run_t3_gate.time.monotonic", lambda: next(ticks))

    evidence = run_gate(
        config,
        client_factory=lambda base_url, timeout: client,
        popen_factory=lambda cmd: process,
        head_state_factory=_clean_head_state,
    )

    assert evidence.mode == "spawned"
    assert evidence.server_command == [sys.executable, "-m", "hi_agent", "serve", "--port", "8089"]
    assert evidence.server_pid == 4321
    assert [run.final_state for run in evidence.runs] == ["completed", "completed", "completed"]
    assert client.cancelled == ["run-1"]
    assert client.run_bodies == [
        {
            "goal": "T3 gate run 0",
            "profile_id": "custom-profile",
            "project_id": "t3_gate_project",
        },
        {
            "goal": "T3 gate run 1",
            "profile_id": "custom-profile",
            "project_id": "t3_gate_project",
        },
        {
            "goal": "T3 gate run 2",
            "profile_id": "custom-profile",
            "project_id": "t3_gate_project",
        },
        {
            "goal": "T3 gate run 3",
            "profile_id": "custom-profile",
            "project_id": "t3_gate_project",
        },
    ]
    assert process.terminated is True
    assert process.waited is True
    assert output.exists()
    payload = output.read_text(encoding="utf-8")
    assert "volces" in payload
    assert '"profile_id": "custom-profile"' in payload
    assert "fallback_events" in payload
    # Verify new verified_head fields are present in output.
    data = __import__("json").loads(payload)
    assert data["verified_head"] == "abc1234def567890abc1234def567890abc12345"
    assert data["verified_at"] == "2026-04-27T00:00:00+00:00"
    assert data["dirty_during_run"] is False


def test_run_gate_fails_cleanly_when_cancel_route_missing(tmp_path, monkeypatch):
    client = FakeClient()
    original_request = client.request

    def broken_request(method: str, url: str, **kwargs):
        if url == "/runs/run-1/cancel" and method == "POST":
            return FakeResponse(404, {"error": "run_not_found"}, method, url)
        return original_request(method, url, **kwargs)

    client.request = broken_request  # type: ignore[assignment]  expiry_wave: Wave 30
    process = FakeProcess(["python", "-m", "hi_agent", "serve", "--port", "8090"])
    output = tmp_path / "failed.json"
    config = GateConfig(
        base_url=None,
        port=8090,
        output=output,
        profile_id="t3_gate",
        provider="volces",
        inject_key=False,
        ready_timeout_s=10,
        poll_timeout_s=10,
        poll_interval_s=0,
        request_timeout_s=2,
        startup_timeout_s=2,
    )
    monkeypatch.setattr("scripts.run_t3_gate.time.sleep", lambda *_: None)
    ticks = iter(range(1000))
    monkeypatch.setattr("scripts.run_t3_gate.time.monotonic", lambda: next(ticks))

    with pytest.raises(RuntimeError, match="compatibility route is missing or miswired"):
        run_gate(
            config,
            client_factory=lambda base_url, timeout: client,
            popen_factory=lambda cmd: process,
            head_state_factory=_clean_head_state,
        )

    assert output.exists()


def test_run_gate_fails_when_worktree_is_dirty(tmp_path, monkeypatch):
    """run_gate must raise and write fail evidence when the worktree is dirty."""
    client = FakeClient()
    process = FakeProcess(["python", "-m", "hi_agent", "serve", "--port", "8091"])
    output = tmp_path / "dirty.json"
    config = GateConfig(
        base_url=None,
        port=8091,
        output=output,
        profile_id="t3_gate",
        provider="volces",
        inject_key=False,
        ready_timeout_s=10,
        poll_timeout_s=10,
        poll_interval_s=0,
        request_timeout_s=2,
        startup_timeout_s=2,
    )
    monkeypatch.setattr("scripts.run_t3_gate.time.sleep", lambda *_: None)
    ticks = iter(range(1000))
    monkeypatch.setattr("scripts.run_t3_gate.time.monotonic", lambda: next(ticks))

    def dirty_head_state():
        return ("deadbeef1234567890deadbeef1234567890dead", "2026-04-27T00:00:00+00:00", True)

    with pytest.raises(RuntimeError, match="dirty worktree"):
        run_gate(
            config,
            client_factory=lambda base_url, timeout: client,
            popen_factory=lambda cmd: process,
            head_state_factory=dirty_head_state,
        )

    # Evidence file must be written even when gate fails.
    assert output.exists()
    data = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert data["dirty_during_run"] is True
    assert data["status"] == "failed"
