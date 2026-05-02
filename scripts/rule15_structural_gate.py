#!/usr/bin/env python
"""Zero-cost Rule 15 structural gate.

Starts a local OpenAI-compatible fake LLM HTTP server and a hi-agent server,
points the Volces config at the fake server, then verifies the Rule 15 wiring
shape without external LLM calls.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_t3_gate import (
    _assert_no_fallback_events,
    _build_client,
    _build_server_command,
    _cancel_run,
    _create_run,
    _poll_run_to_terminal,
    _validate_readiness_snapshot,
)


@dataclass
class FakeLLMState:
    request_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


@dataclass(frozen=True)
class StructuralGateConfig:
    port: int
    fake_llm_port: int
    output: Path
    profile_id: str
    ready_timeout_s: float
    poll_timeout_s: float
    poll_interval_s: float
    request_timeout_s: float
    startup_timeout_s: float


class HttpClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _fake_chat_completion_payload(content: str) -> dict[str, Any]:
    return {
        "id": f"fake-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "fake-structural-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": max(1, len(content.split())),
            "total_tokens": 8 + max(1, len(content.split())),
        },
    }


def _fake_anthropic_message_payload(content: str) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content}],
        "model": "fake-structural-model",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 8,
            "output_tokens": max(1, len(content.split())),
        },
    }


def _fake_content_for_request(request_json: dict[str, Any]) -> str:
    messages = request_json.get("messages", [])
    text_parts: list[str] = []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, str):
                    text_parts.append(content)
    prompt_text = "\n".join(text_parts)

    if "memory compression engine" in prompt_text or "structured JSON summary" in prompt_text:
        return json.dumps(
            {
                "findings": ["structural_gate"],
                "decisions": [],
                "outcome": "succeeded",
                "contradiction_refs": [],
                "key_entities": ["rule15_probe"],
            }
        )
    if "identifying reusable execution patterns" in prompt_text:
        return "[]"
    if "Output JSON" in prompt_text:
        return json.dumps(
            {
                "output": "OK",
                "evidence": ["probe"],
                "score": 1.0,
                "done": True,
            }
        )
    return json.dumps({"output": "OK"})


def _build_server_env(fake_base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HI_AGENT_LLM_MODE": "real",
            "HI_AGENT_ENV": "dev",
            "VOLCE_API_KEY": "structural-test-key",
            "VOLCE_BASE_URL": fake_base_url,
        }
    )

    for key in ("NO_PROXY", "no_proxy"):
        value = env.get(key, "")
        parts = [part.strip() for part in value.split(",") if part.strip()]
        for host in ("127.0.0.1", "localhost"):
            if host not in parts:
                parts.append(host)
        env[key] = ",".join(parts)

    return env


def _extract_fake_llm_count(payload: dict[str, Any]) -> int:
    fake_llm = payload.get("fake_llm")
    if not isinstance(fake_llm, dict):
        return 0
    count = fake_llm.get("request_count", 0)
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


class _FakeLLMHandler(BaseHTTPRequestHandler):
    server_version = "FakeLLM/1.0"

    def log_message(self, format: str, *args: object) -> None:  # pragma: no cover
        pass

    def do_POST(self) -> None:
        is_openai = self.path == "/v1/chat/completions"
        is_anthropic = self.path == "/v1/messages"
        if not is_openai and not is_anthropic:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        request_json: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict):
                request_json = parsed

        state: FakeLLMState = self.server.state  # type: ignore[attr-defined]  expiry_wave: Wave 30
        with state.lock:
            state.request_count += 1
            request_number = state.request_count

        content = _fake_content_for_request(request_json)
        if is_anthropic:
            payload = _fake_anthropic_message_payload(content)
        else:
            payload = _fake_chat_completion_payload(content)
        payload["id"] = f"fake-{request_number}"
        if "model" in request_json:
            payload["model"] = request_json["model"]

        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextlib.contextmanager
def _run_fake_llm_server(port: int) -> Iterator[tuple[FakeLLMState, str]]:
    state = FakeLLMState()
    server = _ThreadingHTTPServer(("127.0.0.1", port), _FakeLLMHandler)
    server.state = state  # type: ignore[attr-defined]  expiry_wave: Wave 30
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # No /v1 suffix — AnthropicLLMGateway appends /v1/messages itself.
        yield state, f"http://127.0.0.1:{actual_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zero-cost Rule 15 structural gate")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--fake-llm-port", type=int, default=0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile-id", default="rule15_volces")
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def _spawn_hi_agent_server(
    *,
    port: int,
    fake_base_url: str,
    startup_timeout_s: float,
    popen_factory: Any = subprocess.Popen,
) -> Iterator[subprocess.Popen[Any]]:
    server_command = _build_server_command(port)
    proc = popen_factory(
        server_command,
        cwd=str(_repo_root()),
        env=_build_server_env(fake_base_url),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if getattr(proc, "poll", lambda: None)() is not None:
        raise RuntimeError("hi-agent server exited immediately after startup")
    try:
        yield proc
    finally:
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=startup_timeout_s)
        if getattr(proc, "poll", lambda: None)() is None:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)


def run_gate(
    config: StructuralGateConfig,
    *,
    client_factory: Any = _build_client,
    popen_factory: Any = subprocess.Popen,
) -> dict[str, Any]:
    base_url = f"http://127.0.0.1:{config.port}"
    command = [
        sys.executable,
        __file__,
        "--output",
        str(config.output),
        "--profile-id",
        config.profile_id,
        "--port",
        str(config.port),
        "--fake-llm-port",
        str(config.fake_llm_port),
    ]
    evidence: dict[str, Any] = {
        "command": command,
        "mode": "spawned",
        "base_url": base_url,
        "profile_id": config.profile_id,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "total_duration_s": None,
        "ready": {},
        "runs": [],
        "cancel_known": {},
        "cancel_unknown": {},
        "server_command": _build_server_command(config.port),
        "server_pid": None,
        "fake_llm": {"request_count": 0},
        "status": "passed",
        "error": None,
    }
    total_started = time.monotonic()

    try:
        with _run_fake_llm_server(config.fake_llm_port) as (
            fake_state,
            fake_base_url,
        ), _spawn_hi_agent_server(
            port=config.port,
            fake_base_url=fake_base_url,
            startup_timeout_s=config.startup_timeout_s,
            popen_factory=popen_factory,
        ) as server_process:
                evidence["server_pid"] = getattr(server_process, "pid", None)
                client = client_factory(base_url, config.request_timeout_s)
                try:
                    ready_snapshot = _wait_for_ready(
                        client,
                        config.ready_timeout_s,
                        config.poll_interval_s,
                    )
                    _validate_readiness_snapshot(ready_snapshot)
                    evidence["ready"] = ready_snapshot

                    _, cancel_target = _create_run(client, 0, config.profile_id)
                    cancel_target_run_id = cancel_target.get("run_id")
                    if not cancel_target_run_id:
                        raise RuntimeError(
                            "POST /runs for cancellation target did not return run_id"
                        )
                    known_cancel_status, known_cancel = _cancel_run(client, cancel_target_run_id)
                    evidence["cancel_known"] = {
                        "run_id": cancel_target_run_id,
                        "status_code": known_cancel_status,
                        "response": known_cancel,
                    }
                    if known_cancel_status != 200:
                        raise RuntimeError(
                            f"POST /runs/{cancel_target_run_id}/cancel expected 200, "
                            f"got {known_cancel_status}"
                        )

                    with contextlib.suppress(Exception):
                        status, payload = _get_json(client, f"/runs/{cancel_target_run_id}")
                        evidence["cancel_known"]["final_status_code"] = status
                        evidence["cancel_known"]["final_response"] = payload

                    for index in range(1, 4):
                        create_status, create_payload = _create_run(
                            client,
                            index,
                            config.profile_id,
                        )
                        run_id = create_payload.get("run_id")
                        if not run_id:
                            raise RuntimeError(f"POST /runs #{index} did not return run_id")
                        if create_status != 201:
                            raise RuntimeError(
                                f"POST /runs #{index} expected 201, got {create_status}"
                            )
                        terminal_payload, polls, duration_s = _poll_run_to_terminal(
                            client,
                            run_id,
                            config.poll_timeout_s,
                            config.poll_interval_s,
                        )
                        state = terminal_payload.get("state")
                        if state != "completed":
                            raise RuntimeError(
                                f"run {run_id} reached terminal state {state!r}; expected completed"
                            )
                        _assert_no_fallback_events(terminal_payload, label=f"run {run_id}")
                        evidence["runs"].append(
                            {
                                "run_id": run_id,
                                "create_status": create_status,
                                "final_state": state,
                                "polls": polls,
                                "duration_s": duration_s,
                                "fallback_events": terminal_payload.get("fallback_events", []),
                            }
                        )

                    unknown_run_id = "rule15-unknown-run"
                    unknown_cancel_status, unknown_cancel = _cancel_run(client, unknown_run_id)
                    evidence["cancel_unknown"] = {
                        "run_id": unknown_run_id,
                        "status_code": unknown_cancel_status,
                        "response": unknown_cancel,
                    }
                    if unknown_cancel_status != 404:
                        raise RuntimeError(
                            f"POST /runs/{unknown_run_id}/cancel expected 404 for an unknown run, "
                            f"got {unknown_cancel_status}"
                        )

                    evidence["fake_llm"] = {"request_count": fake_state.request_count}
                    fake_count = _extract_fake_llm_count(evidence)
                    if fake_count < 3:
                        raise RuntimeError(
                            f"fake LLM request_count must be >= 3, got {fake_count}"
                        )

                    evidence["finished_at"] = datetime.now(UTC).isoformat()
                    evidence["total_duration_s"] = time.monotonic() - total_started
                    return evidence
                except Exception as exc:
                    evidence["status"] = "failed"
                    evidence["error"] = str(exc)
                    raise
                finally:
                    evidence["fake_llm"] = {"request_count": fake_state.request_count}
                    if evidence["finished_at"] is None:
                        evidence["finished_at"] = datetime.now(UTC).isoformat()
                    if evidence["total_duration_s"] is None:
                        evidence["total_duration_s"] = time.monotonic() - total_started
                    with contextlib.suppress(Exception):
                        _write_evidence(config.output, evidence)
                    with contextlib.suppress(Exception):
                        client.close()
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        raise
    finally:
        if evidence["finished_at"] is None:
            evidence["finished_at"] = datetime.now(UTC).isoformat()
        if evidence["total_duration_s"] is None:
            evidence["total_duration_s"] = time.monotonic() - total_started
        with contextlib.suppress(Exception):
            _write_evidence(config.output, evidence)


def _wait_for_ready(client: HttpClient, timeout_s: float, poll_interval_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() <= deadline:
        try:
            response = client.request("GET", "/ready")
            status = int(getattr(response, "status_code", 0))
            snapshot = response.json()
            if not isinstance(snapshot, dict):
                raise RuntimeError("expected JSON object from /ready")
        except Exception as exc:
            last_error = str(exc)
            time.sleep(poll_interval_s)
            continue

        try:
            _validate_readiness_snapshot(snapshot)
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


def _get_json(client: HttpClient, path: str) -> tuple[int, dict[str, Any]]:
    response = client.request("GET", path)
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object from server")
    return int(getattr(response, "status_code", 0)), payload


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = StructuralGateConfig(
        port=args.port,
        fake_llm_port=args.fake_llm_port,
        output=Path(args.output),
        profile_id=args.profile_id,
        ready_timeout_s=args.ready_timeout,
        poll_timeout_s=args.poll_timeout,
        poll_interval_s=args.poll_interval,
        request_timeout_s=args.request_timeout,
        startup_timeout_s=args.startup_timeout,
    )
    try:
        run_gate(config)
    except Exception as exc:
        print(f"Rule 15 structural gate failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Rule 15 structural gate passed; evidence written to {config.output}")


if __name__ == "__main__":
    main()
