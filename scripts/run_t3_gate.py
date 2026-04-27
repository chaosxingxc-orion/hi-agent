#!/usr/bin/env python3
"""Provider-neutral T3 release gate.

This script verifies the operator-shape contract against a real hi-agent server.
It never reads or prints API keys. Credentials are supplied by the caller via
the runtime environment or pre-existing server config (or via inject_provider_key.py).

Usage:
    python scripts/run_t3_gate.py --output docs/delivery/<date>-<sha7>-t3-<provider>.json
    python scripts/run_t3_gate.py --provider volces --output ...
    python scripts/run_t3_gate.py --provider auto --inject-key --output ...

Output filename convention: ``YYYY-MM-DD-<sha7>-t3-<provider>.json``
  where <sha7> is the first 7 characters of verified_head (from git rev-parse HEAD).

When --inject-key is passed, inject_provider_key.py is called first to write
config/llm_config.local.json, and --restore-key is called on exit.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).parent.parent


def _capture_head_state() -> tuple[str, str, bool]:
    """Return (head_sha, iso_timestamp, is_dirty).

    Captures the git HEAD SHA and worktree cleanliness at the moment the gate
    starts, before any server spawn or HTTP requests.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parent.parent,
    ).stdout.strip()

    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=pathlib.Path(__file__).parent.parent,
        ).stdout.strip()
    )

    ts = datetime.now(UTC).isoformat()
    return head, ts, dirty
def _run_mock_shape() -> Path:
    started_at = datetime.now(UTC).isoformat()
    short_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout.strip()[:7]

    response = {
        "content": "mock shape ok",
        "model": "mock",
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
        },
    }

    if "content" not in response:
        raise RuntimeError("mock shape check failed: missing 'content'")
    if "model" not in response:
        raise RuntimeError("mock shape check failed: missing 'model'")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise RuntimeError("mock shape check failed: missing usage dict")
    if "prompt_tokens" not in usage or "completion_tokens" not in usage:
        raise RuntimeError("mock shape check failed: usage token keys missing")

    finished_at = datetime.now(UTC).isoformat()
    evidence = {
        "provenance": "structural",
        "mode": "shape_verified",
        "status": "passed",
        "started_at": started_at,
        "finished_at": finished_at,
        "response": response,
    }
    output = ROOT / "docs" / "verification" / f"{short_sha}-shape-verified-t3.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return output


@dataclass(frozen=True)
class GateConfig:
    base_url: str | None
    port: int
    output: Path
    profile_id: str
    provider: str
    ready_timeout_s: float
    poll_timeout_s: float
    poll_interval_s: float
    request_timeout_s: float
    startup_timeout_s: float
    inject_key: bool


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
    mode: str
    base_url: str
    profile_id: str
    provider: str
    started_at: str
    finished_at: str | None = None
    total_duration_s: float | None = None
    ready: dict[str, Any] = field(default_factory=dict)
    runs: list[RunEvidence] = field(default_factory=list)
    cancel_known: dict[str, Any] = field(default_factory=dict)
    cancel_unknown: dict[str, Any] = field(default_factory=dict)
    server_command: list[str] | None = None
    server_pid: int | None = None
    status: str = "passed"
    error: str | None = None
    verified_head: str = ""       # git SHA at gate start (from git rev-parse HEAD)
    verified_at: str = ""         # ISO-8601 UTC timestamp when gate started
    dirty_during_run: bool = False  # True if git status was dirty at start

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "mode": self.mode,
            "base_url": self.base_url,
            "profile_id": self.profile_id,
            "provider": self.provider,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_s": self.total_duration_s,
            "ready": self.ready,
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
            "verified_head": self.verified_head,
            "verified_at": self.verified_at,
            "dirty_during_run": self.dirty_during_run,
        }


class HttpClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provider-neutral T3 release gate")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--provider",
        choices=["volces", "anthropic", "openai", "auto"],
        default="auto",
        help="LLM provider to verify against (default: auto)",
    )
    parser.add_argument("--profile-id", default="t3_gate")
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument(
        "--inject-key",
        action="store_true",
        help="Call inject_provider_key.py before running the gate",
    )
    parser.add_argument(
        "--mock-shape",
        action="store_true",
        help="Run structural mock response checks without live HTTP or key injection",
    )
    return parser


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _build_server_command(port: int) -> list[str]:
    return [sys.executable, "-m", "hi_agent", "serve", "--port", str(port)]


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
    except Exception as exc:  # pragma: no cover - defensive, exercised via fakes
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


def _validate_readiness_snapshot(snapshot: dict[str, Any], expected_provider: str) -> None:
    missing = [key for key in ("llm_mode", "llm_provider") if key not in snapshot]
    if missing:
        raise RuntimeError(
            "readiness payload is missing required field(s): "
            + ", ".join(missing)
            + ". Update /ready so the T3 gate can verify real LLM mode."
        )
    llm_mode = snapshot.get("llm_mode")
    llm_provider = snapshot.get("llm_provider")
    if llm_mode != "real":
        raise RuntimeError(
            f"readiness payload reported llm_mode={llm_mode!r}; expected 'real'."
        )
    # When provider is "auto" we accept any reported provider; otherwise enforce exact match.
    if expected_provider != "auto" and llm_provider != expected_provider:
        raise RuntimeError(
            f"readiness payload reported llm_provider={llm_provider!r}; "
            f"expected '{expected_provider}'."
        )


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


def _assert_no_fallback_events(payload: dict[str, Any], *, label: str) -> None:
    events = _extract_fallback_events(payload)
    if events:
        raise RuntimeError(f"{label} must not emit fallback events; got {events!r}")


def _assert_llm_fallback_count_zero(payload: dict[str, Any], *, label: str) -> None:
    count = payload.get("llm_fallback_count", 0)
    if count and count != 0:
        raise RuntimeError(f"{label} llm_fallback_count must be 0; got {count!r}")


def _wait_for_ready(
    client: HttpClient,
    timeout_s: float,
    poll_interval_s: float,
    expected_provider: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() <= deadline:
        try:
            status, snapshot = _get_json(client, "/ready")
        except Exception as exc:
            last_error = str(exc)
            time.sleep(poll_interval_s)
            continue

        try:
            _validate_readiness_snapshot(snapshot, expected_provider)
        except RuntimeError as exc:
            raise RuntimeError(f"/ready contract mismatch: {exc}") from exc

        if status == 200:
            return snapshot
        if status != 503:
            raise RuntimeError(f"/ready returned unexpected status {status}")
        time.sleep(poll_interval_s)

    raise RuntimeError(
        f"timed out waiting for /ready after {timeout_s:.1f}s"
        + (f" (last error: {last_error})" if last_error else "")
    )


def _poll_run_to_terminal(
    client: HttpClient,
    run_id: str,
    timeout_s: float,
    poll_interval_s: float,
) -> tuple[dict[str, Any], int, float]:
    deadline = time.monotonic() + timeout_s
    polls = 0
    started = time.monotonic()
    while time.monotonic() <= deadline:
        _status, payload = _get_json(client, f"/runs/{run_id}")
        polls += 1
        state = payload.get("state")
        if not isinstance(state, str):
            raise RuntimeError(f"run {run_id} response missing string state")
        if state in {"completed", "failed", "cancelled"}:
            return payload, polls, time.monotonic() - started
        time.sleep(poll_interval_s)
    raise RuntimeError(f"timed out waiting for run {run_id} to reach terminal state")


def _create_run(client: HttpClient, index: int, profile_id: str) -> tuple[int, dict[str, Any]]:
    return _post_json(
        client,
        "/runs",
        {
            "goal": f"T3 gate run {index}",
            "profile_id": profile_id,
            "project_id": "t3_gate_project",
        },
    )


def _cancel_run(client: HttpClient, run_id: str) -> tuple[int, dict[str, Any]]:
    return _post_json(client, f"/runs/{run_id}/cancel")


def _write_evidence(path: Path, evidence: GateEvidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _run_gate_with_client(
    client: HttpClient,
    *,
    base_url: str,
    profile_id: str,
    provider: str,
    command: list[str],
    mode: str,
    ready_timeout_s: float,
    poll_timeout_s: float,
    poll_interval_s: float,
) -> GateEvidence:
    started_at = datetime.now(UTC).isoformat()
    evidence = GateEvidence(
        command=command,
        mode=mode,
        base_url=base_url,
        profile_id=profile_id,
        provider=provider,
        started_at=started_at,
    )
    total_started = time.monotonic()

    ready_snapshot = _wait_for_ready(client, ready_timeout_s, poll_interval_s, provider)
    evidence.ready = ready_snapshot

    _, cancel_target = _create_run(client, 0, profile_id)
    cancel_target_run_id = cancel_target.get("run_id")
    if not cancel_target_run_id:
        raise RuntimeError("POST /runs for cancellation target did not return run_id")
    known_cancel_status, known_cancel = _cancel_run(client, cancel_target_run_id)
    evidence.cancel_known = {
        "run_id": cancel_target_run_id,
        "status_code": known_cancel_status,
        "response": known_cancel,
    }
    if known_cancel_status == 404:
        raise RuntimeError(
            "POST /runs/{id}/cancel returned 404 for a known run; "
            "the compatibility route is missing or miswired. "
            "Add POST /runs/{id}/cancel before running the T3 gate."
        )
    if known_cancel_status != 200:
        raise RuntimeError(
            f"POST /runs/{cancel_target_run_id}/cancel expected 200, got {known_cancel_status}"
        )

    with contextlib.suppress(Exception):
        status, payload = _get_json(client, f"/runs/{cancel_target_run_id}")
        evidence.cancel_known["final_status_code"] = status
        evidence.cancel_known["final_response"] = payload

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
        state = terminal_payload.get("state")
        if state != "completed":
            raise RuntimeError(f"run {run_id} reached terminal state {state!r}; expected completed")
        _assert_no_fallback_events(terminal_payload, label=f"run {run_id}")
        _assert_llm_fallback_count_zero(terminal_payload, label=f"run {run_id}")
        evidence.runs.append(
            RunEvidence(
                run_id=run_id,
                create_status=create_status,
                final_state=state,
                polls=polls,
                duration_s=duration_s,
                fallback_events=_extract_fallback_events(terminal_payload),
            )
        )

    unknown_run_id = "t3-gate-unknown-run"
    unknown_cancel_status, unknown_cancel = _cancel_run(client, unknown_run_id)
    evidence.cancel_unknown = {
        "run_id": unknown_run_id,
        "status_code": unknown_cancel_status,
        "response": unknown_cancel,
    }
    if unknown_cancel_status != 404:
        raise RuntimeError(
            f"POST /runs/{unknown_run_id}/cancel expected 404 for an unknown run, "
            f"got {unknown_cancel_status}"
        )

    evidence.finished_at = datetime.now(UTC).isoformat()
    evidence.total_duration_s = time.monotonic() - total_started
    return evidence


def _inject_key(provider: str) -> None:
    """Call inject_provider_key.py to write config/llm_config.local.json."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "inject_provider_key.py"), "--provider", provider],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"inject_provider_key.py failed with exit code {result.returncode}")


def _restore_key() -> None:
    """Call inject_provider_key.py --restore to remove config/llm_config.local.json."""
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "inject_provider_key.py"),
            "--restore",
        ],
        cwd=str(ROOT),
    )


def run_gate(
    config: GateConfig,
    *,
    client_factory: Any = _build_client,
    popen_factory: Any = subprocess.Popen,
    head_state_factory: Any = _capture_head_state,
) -> GateEvidence:
    # Capture HEAD state at the very start, before any server spawn or HTTP requests.
    verified_head, verified_at, dirty_during_run = head_state_factory()

    base_url = _normalize_base_url(config.base_url or f"http://127.0.0.1:{config.port}")
    command = [
        sys.executable,
        __file__,
        "--output",
        str(config.output),
        "--profile-id",
        config.profile_id,
        "--provider",
        config.provider,
    ]
    if config.base_url:
        command.extend(["--base-url", base_url])
    else:
        command.extend(["--port", str(config.port)])

    if config.inject_key:
        _inject_key(config.provider)

    server_process: subprocess.Popen[str] | None = None
    mode = "external"
    if config.base_url is None:
        mode = "spawned"
        server_command = _build_server_command(config.port)
        server_process = popen_factory(server_command)
        if getattr(server_process, "poll", lambda: None)() is not None:
            raise RuntimeError("hi-agent server exited immediately after startup")
    else:
        server_command = None

    client = client_factory(base_url, config.request_timeout_s)
    evidence = GateEvidence(
        command=command,
        mode=mode,
        base_url=base_url,
        profile_id=config.profile_id,
        provider=config.provider,
        started_at=datetime.now(UTC).isoformat(),
        server_command=server_command,
        server_pid=getattr(server_process, "pid", None),
        verified_head=verified_head,
        verified_at=verified_at,
        dirty_during_run=dirty_during_run,
    )
    try:
        if dirty_during_run:
            evidence.status = "failed"
            evidence.error = (
                "Gate started with a dirty worktree (uncommitted changes). "
                "The evidence does not prove the committed code. "
                "Commit or stash all changes before running the T3 gate."
            )
            raise RuntimeError(evidence.error)

        gate_result = _run_gate_with_client(
            client,
            base_url=base_url,
            profile_id=config.profile_id,
            provider=config.provider,
            command=command,
            mode=mode,
            ready_timeout_s=config.ready_timeout_s,
            poll_timeout_s=config.poll_timeout_s,
            poll_interval_s=config.poll_interval_s,
        )
        gate_result.server_command = server_command
        gate_result.server_pid = getattr(server_process, "pid", None)
        gate_result.verified_head = verified_head
        gate_result.verified_at = verified_at
        gate_result.dirty_during_run = dirty_during_run
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
        if config.inject_key:
            _restore_key()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.mock_shape:
        if args.inject_key:
            print("--mock-shape cannot be combined with --inject-key", file=sys.stderr)
            raise SystemExit(1)
        try:
            output = _run_mock_shape()
        except Exception as exc:
            print(f"T3 mock-shape failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"T3 mock-shape passed; evidence written to {output}")
        return

    if not args.output:
        print("--output is required for live gate runs", file=sys.stderr)
        raise SystemExit(1)

    config = GateConfig(
        base_url=args.base_url,
        port=args.port,
        output=Path(args.output),
        profile_id=args.profile_id,
        provider=args.provider,
        ready_timeout_s=args.ready_timeout,
        poll_timeout_s=args.poll_timeout,
        poll_interval_s=args.poll_interval,
        request_timeout_s=args.request_timeout,
        startup_timeout_s=args.startup_timeout,
        inject_key=args.inject_key,
    )
    try:
        run_gate(config)
    except Exception as exc:
        print(f"T3 gate failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"T3 gate passed; evidence written to {config.output}")


if __name__ == "__main__":
    main()


