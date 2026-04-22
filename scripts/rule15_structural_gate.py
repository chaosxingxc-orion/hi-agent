#!/usr/bin/env python
"""Rule 15 structural gate (zero-cost, dev-mode).

Verifies the run-lifecycle wiring shape — server startup, run creation,
run-to-terminal, cancel round-trip — without real LLM calls.

The server is started in its default dev/heuristic mode (no API key
required).  Heuristic fallback is expected and is recorded as a warning,
not a failure.

Usage
-----
    python scripts/rule15_structural_gate.py --output docs/delivery/YYYY-MM-DD-rule15-structural.json

Exit codes
----------
    0  — server started, 3 runs reached terminal state, cancel round-trip OK
    1  — any structural check failed (wedge, startup failure, cancel broken)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

_logger = logging.getLogger(__name__)

# Terminal states accepted from the structural gate.
# In dev/heuristic mode any terminal is structurally valid.
_TERMINAL_STATES: frozenset[str] = frozenset({"completed", "done", "failed"})


@dataclass(frozen=True)
class GateConfig:
    base_url: str | None
    port: int
    output: Path
    profile_id: str
    startup_timeout_s: float
    poll_timeout_s: float
    poll_interval_s: float
    request_timeout_s: float


@dataclass
class RunEvidence:
    run_id: str
    create_status: int
    final_state: str
    polls: int
    duration_s: float
    fallback_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GateEvidence:
    command: list[str]
    mode: str  # "spawned" | "external"
    base_url: str
    profile_id: str
    started_at: str
    gate_mode: str = "structural"  # always "structural" for this gate
    finished_at: str | None = None
    total_duration_s: float | None = None
    health: dict[str, Any] = field(default_factory=dict)
    runs: list[RunEvidence] = field(default_factory=list)
    cancel_known: dict[str, Any] = field(default_factory=dict)
    cancel_unknown: dict[str, Any] = field(default_factory=dict)
    server_command: list[str] | None = None
    server_pid: int | None = None
    status: str = "passed"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "gate_mode": self.gate_mode,
            "mode": self.mode,
            "base_url": self.base_url,
            "profile_id": self.profile_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_s": self.total_duration_s,
            "health": self.health,
            "runs": [
                {
                    "run_id": run.run_id,
                    "create_status": run.create_status,
                    "final_state": run.final_state,
                    "polls": run.polls,
                    "duration_s": run.duration_s,
                    "fallback_events": run.fallback_events,
                }
                for run in self.runs
            ],
            "cancel_known": self.cancel_known,
            "cancel_unknown": self.cancel_unknown,
            "server_command": self.server_command,
            "server_pid": self.server_pid,
            "status": self.status,
            "error": self.error,
        }


class HttpClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rule 15 structural gate (zero-cost, dev-mode)")
    parser.add_argument("--base-url", default=None, help="Use an already-running server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile-id", default="rule15_structural")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--poll-timeout", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--request-timeout", type=float, default=10.0)
    return parser


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _build_server_command(port: int) -> list[str]:
    return [sys.executable, "-m", "hi_agent", "serve", "--port", str(port)]


def _write_minimal_llm_config(tmp_dir: str) -> str:
    """Write a minimal llm_config.json with no API keys to a temp directory.

    Returns the path to the written file.  The caller is responsible for
    cleaning up the temp directory.
    """
    import os

    config: dict[str, Any] = {
        "default_provider": "",
        "providers": {},
    }
    path = os.path.join(tmp_dir, "llm_config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    return path


def _build_server_env(minimal_config_path: str | None = None) -> dict[str, str]:
    """Build a subprocess environment that forces dev/heuristic mode.

    Sets HI_AGENT_ENV=dev.  When ``minimal_config_path`` is provided, sets
    HI_AGENT_CONFIG_FILE to that path so the server uses a no-key config and
    the cognition builder does not construct a real LLM gateway.

    Clears well-known provider API key env vars so no real LLM gateway is
    constructed, ensuring the heuristic fallback path is used regardless of
    the repo's llm_config.json contents.
    """
    import os

    env = dict(os.environ)
    env["HI_AGENT_ENV"] = "dev"
    # Clear well-known provider API key env vars.
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VOLCE_API_KEY", "DASHSCOPE_API_KEY"):
        env.pop(key, None)
    if minimal_config_path:
        env["HI_AGENT_LLM_CONFIG_FILE"] = minimal_config_path
    return env


def _build_client(base_url: str, request_timeout_s: float) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(request_timeout_s),
        follow_redirects=True,
        trust_env=False,
    )


def _response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        method = response.request.method
        url = response.request.url
        raise RuntimeError(f"non-JSON response from {method} {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object from server")
    return payload


def _request_json(
    client: HttpClient,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    response = client.request(method, path, json=body)
    status = int(getattr(response, "status_code", 0))
    return status, _response_json(response)


def _get_json(client: HttpClient, path: str) -> tuple[int, dict[str, Any]]:
    return _request_json(client, "GET", path)


def _post_json(
    client: HttpClient,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    return _request_json(client, "POST", path, body)


# --------------------------------------------------------------------------- #
# Health check
# --------------------------------------------------------------------------- #


def _wait_for_health(
    client: HttpClient,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    """Poll /health until it returns HTTP 200.

    Returns the parsed JSON payload on success.
    Raises RuntimeError on timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() <= deadline:
        try:
            status, snapshot = _get_json(client, "/health")
        except Exception as exc:
            last_error = str(exc)
            time.sleep(poll_interval_s)
            continue

        if status == 200:
            return snapshot
        time.sleep(poll_interval_s)

    raise RuntimeError(
        f"timed out waiting for /health to return 200 after {timeout_s:.1f}s"
        + (f" (last error: {last_error})" if last_error else "")
    )


# --------------------------------------------------------------------------- #
# Run helpers
# --------------------------------------------------------------------------- #


def _extract_fallback_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    top_level = payload.get("fallback_events") or []
    if isinstance(top_level, list):
        events.extend([ev for ev in top_level if isinstance(ev, dict)])
    result = payload.get("result")
    if isinstance(result, dict):
        nested = result.get("fallback_events") or []
        if isinstance(nested, list):
            events.extend([ev for ev in nested if isinstance(ev, dict)])
    return events


def _poll_run_to_terminal(
    client: HttpClient,
    run_id: str,
    timeout_s: float,
    poll_interval_s: float,
) -> tuple[dict[str, Any], int, float]:
    """Poll GET /runs/{run_id} until the run reaches a terminal state.

    Accepted terminal states: completed, done, failed.
    In dev/heuristic mode any terminal state is structurally valid.

    Returns:
        (payload, poll_count, elapsed_seconds)

    Raises:
        RuntimeError: on timeout before a terminal state is reached.
    """
    deadline = time.monotonic() + timeout_s
    polls = 0
    started = time.monotonic()
    while time.monotonic() <= deadline:
        _status, payload = _get_json(client, f"/runs/{run_id}")
        polls += 1
        state = payload.get("state")
        if not isinstance(state, str):
            raise RuntimeError(f"run {run_id} response missing string state field")
        if state in _TERMINAL_STATES:
            return payload, polls, time.monotonic() - started
        time.sleep(poll_interval_s)
    raise RuntimeError(
        f"timed out waiting for run {run_id} to reach terminal state "
        f"after {timeout_s:.1f}s (last observed state: {state!r})"
    )


def _create_run(
    client: HttpClient,
    index: int,
    profile_id: str,
    *,
    deadline_offset_s: float = 8.0,
) -> tuple[int, dict[str, Any]]:
    # Set a short deadline so the runner terminates after the first stage.
    # In dev/heuristic mode each LLM call takes ~3 s (timeout), so one stage
    # takes ~3 s.  A deadline of 8 s after submission allows S1 to complete,
    # then the deadline check at S2 fires and the run exits as "failed".
    # We accept any terminal state, so "failed" from deadline exhaustion is
    # a valid structural pass — we just need the run to exit, not wedge.
    dl = (datetime.now(UTC) + timedelta(seconds=deadline_offset_s)).isoformat()
    return _post_json(
        client,
        "/runs",
        {
            "goal": f"Rule 15 structural gate run {index}",
            "profile_id": profile_id,
            "deadline": dl,
        },
    )


def _cancel_run_via_signal(
    client: HttpClient,
    run_id: str,
) -> tuple[int, dict[str, Any]]:
    """Send cancel signal via POST /runs/{run_id}/signal with body {"signal":"cancel"}."""
    return _post_json(client, f"/runs/{run_id}/signal", {"signal": "cancel"})


# --------------------------------------------------------------------------- #
# Evidence writing
# --------------------------------------------------------------------------- #


def _write_evidence(path: Path, evidence: GateEvidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main gate logic
# --------------------------------------------------------------------------- #


def _run_gate_with_client(
    client: HttpClient,
    *,
    base_url: str,
    profile_id: str,
    command: list[str],
    mode: str,
    startup_timeout_s: float,
    poll_timeout_s: float,
    poll_interval_s: float,
) -> GateEvidence:
    started_at = datetime.now(UTC).isoformat()
    evidence = GateEvidence(
        command=command,
        mode=mode,
        base_url=base_url,
        profile_id=profile_id,
        started_at=started_at,
    )
    total_started = time.monotonic()

    # Step 1: wait for /health to return 200
    health_snapshot = _wait_for_health(client, startup_timeout_s, poll_interval_s)
    evidence.health = health_snapshot

    # Step 2: cancel round-trip on a known run
    _, cancel_target = _create_run(client, 0, profile_id)
    cancel_target_run_id = cancel_target.get("run_id")
    if not cancel_target_run_id:
        raise RuntimeError("POST /runs for cancellation target did not return run_id")

    known_cancel_status, known_cancel = _cancel_run_via_signal(client, cancel_target_run_id)
    evidence.cancel_known = {
        "run_id": cancel_target_run_id,
        "status_code": known_cancel_status,
        "response": known_cancel,
    }
    if known_cancel_status == 404:
        raise RuntimeError(
            f"POST /runs/{cancel_target_run_id}/signal returned 404 for a known run; "
            "the signal route is missing or miswired."
        )
    if known_cancel_status not in (200, 409):
        raise RuntimeError(
            f"POST /runs/{cancel_target_run_id}/signal expected 200/409, "
            f"got {known_cancel_status}"
        )

    with contextlib.suppress(Exception):
        status, payload = _get_json(client, f"/runs/{cancel_target_run_id}")
        evidence.cancel_known["final_status_code"] = status
        evidence.cancel_known["final_response"] = payload

    # Step 3: cancel round-trip on an unknown run (must return 404)
    unknown_run_id = "rule15-structural-unknown"
    unknown_cancel_status, unknown_cancel = _cancel_run_via_signal(client, unknown_run_id)
    evidence.cancel_unknown = {
        "run_id": unknown_run_id,
        "status_code": unknown_cancel_status,
        "response": unknown_cancel,
    }
    if unknown_cancel_status != 404:
        raise RuntimeError(
            f"POST /runs/{unknown_run_id}/signal expected 404 for an unknown run, "
            f"got {unknown_cancel_status}"
        )

    # Step 4: create 3 runs and poll each to a terminal state
    for index in range(1, 4):
        create_status, create_payload = _create_run(client, index, profile_id)
        run_id = create_payload.get("run_id")
        if not run_id:
            raise RuntimeError(f"POST /runs #{index} did not return run_id")
        if create_status != 201:
            raise RuntimeError(f"POST /runs #{index} expected 201, got {create_status}")

        terminal_payload, polls, duration_s = _poll_run_to_terminal(
            client,
            run_id,
            poll_timeout_s,
            poll_interval_s,
        )
        state = terminal_payload.get("state", "")
        fallback_events = _extract_fallback_events(terminal_payload)
        if fallback_events:
            # Heuristic fallback is expected in dev mode — warn, do not fail.
            warnings.warn(
                f"run {run_id} emitted {len(fallback_events)} fallback event(s); "
                "this is expected in dev/heuristic mode and does not block the structural gate.",
                stacklevel=2,
            )

        evidence.runs.append(
            RunEvidence(
                run_id=run_id,
                create_status=create_status,
                final_state=state,
                polls=polls,
                duration_s=duration_s,
                fallback_events=fallback_events,
            )
        )

    evidence.finished_at = datetime.now(UTC).isoformat()
    evidence.total_duration_s = time.monotonic() - total_started
    return evidence


def run_gate(
    config: GateConfig,
    *,
    client_factory: Any = _build_client,
    popen_factory: Any = None,
) -> GateEvidence:
    """Run the structural gate, optionally spawning a server subprocess.

    When ``config.base_url`` is None a server is spawned on ``config.port``.
    When ``config.base_url`` is provided the caller is responsible for the
    server lifecycle.

    The ``popen_factory`` callable receives ``(command: list[str], env: dict)``
    and must return a process object with a ``poll()`` method and ``pid``
    attribute.  Defaults to ``subprocess.Popen`` with those positional args.

    Returns a :class:`GateEvidence` with ``status="passed"`` on success.
    Raises on failure (evidence is written to disk before raising).
    """
    if popen_factory is None:
        def popen_factory(cmd: list[str], env: dict) -> subprocess.Popen[str]:  # type: ignore[misc]
            return subprocess.Popen(cmd, env=env)

    base_url = _normalize_base_url(config.base_url or f"http://127.0.0.1:{config.port}")
    command = [
        sys.executable,
        __file__,
        "--output",
        str(config.output),
        "--profile-id",
        config.profile_id,
    ]
    if config.base_url:
        command.extend(["--base-url", base_url])
    else:
        command.extend(["--port", str(config.port)])

    server_process: subprocess.Popen[str] | None = None
    mode = "external"
    server_command: list[str] | None = None
    _tmp_dir: tempfile.TemporaryDirectory[str] | None = None

    if config.base_url is None:
        mode = "spawned"
        server_command = _build_server_command(config.port)
        # Write a minimal no-key llm_config.json so the server ignores any real
        # provider credentials in the repo's config/llm_config.json and falls
        # back to the heuristic path.  HI_AGENT_LLM_CONFIG_FILE overrides the
        # hardcoded path in cognition_builder.py.
        _tmp_dir = tempfile.TemporaryDirectory(prefix="rule15_gate_")
        _minimal_config_path = _write_minimal_llm_config(_tmp_dir.name)
        server_process = popen_factory(
            server_command, _build_server_env(minimal_config_path=_minimal_config_path)
        )
        if getattr(server_process, "poll", lambda: None)() is not None:
            _tmp_dir.cleanup()
            raise RuntimeError("hi-agent server exited immediately after startup")

    client = client_factory(base_url, config.request_timeout_s)
    evidence = GateEvidence(
        command=command,
        mode=mode,
        base_url=base_url,
        profile_id=config.profile_id,
        started_at=datetime.now(UTC).isoformat(),
        server_command=server_command,
        server_pid=getattr(server_process, "pid", None),
    )

    try:
        gate_result = _run_gate_with_client(
            client,
            base_url=base_url,
            profile_id=config.profile_id,
            command=command,
            mode=mode,
            startup_timeout_s=config.startup_timeout_s,
            poll_timeout_s=config.poll_timeout_s,
            poll_interval_s=config.poll_interval_s,
        )
        gate_result.server_command = server_command
        gate_result.server_pid = getattr(server_process, "pid", None)
        evidence = gate_result
        return evidence
    except Exception as exc:
        evidence.status = "failed"
        evidence.error = str(exc)
        raise
    finally:
        evidence.finished_at = evidence.finished_at or datetime.now(UTC).isoformat()
        evidence.total_duration_s = evidence.total_duration_s or 0.0
        with contextlib.suppress(Exception):
            _write_evidence(config.output, evidence)
        with contextlib.suppress(Exception):
            client.close()
        if server_process is not None:
            with contextlib.suppress(Exception):
                server_process.terminate()
            with contextlib.suppress(Exception):
                server_process.wait(timeout=config.startup_timeout_s)
        if _tmp_dir is not None:
            with contextlib.suppress(Exception):
                _tmp_dir.cleanup()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = GateConfig(
        base_url=args.base_url,
        port=args.port,
        output=Path(args.output),
        profile_id=args.profile_id,
        startup_timeout_s=args.startup_timeout,
        poll_timeout_s=args.poll_timeout,
        poll_interval_s=args.poll_interval,
        request_timeout_s=args.request_timeout,
    )
    try:
        run_gate(config)
    except Exception as exc:
        print(f"Rule 15 structural gate FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Rule 15 structural gate passed; evidence written to {config.output}")


if __name__ == "__main__":
    main()
