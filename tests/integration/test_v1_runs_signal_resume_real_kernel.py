"""W33-B1: real-kernel dispatch coverage for ``POST /v1/runs/{id}/signal``.

The W32-A integration suite covers cancel via the dedicated cancel
route, but the generic ``signal`` route — which RIA Phase 3+ uses for
human-gate ``resume-with-input`` flows — still has no real-kernel
binding test. The W31 stub backend always returned 200 with
``state="cancelling"`` regardless of the signal name, so a passing test
against the stub proved nothing about the real-kernel handler.

This test asserts dispatch occurred to the real :class:`RunManager`,
not the kernel-side semantics of "resume on a non-paused run". Two
behaviours separate the real backend from the W31 stub:

1. ``POST /v1/runs/{unknown_id}/signal`` returns 404 (the real
   ``RealKernelBackend.signal_run`` calls ``_record_to_dict`` for
   ownership verification, which raises ``NotFoundError`` for unknown
   ids — the stub also raises ``NotFoundError``, but the stub path is
   only reachable when ``AGENT_SERVER_BACKEND=stub``, which the
   ``real_app`` fixture explicitly disables).
2. ``POST /v1/runs/{run_id}/signal`` with ``signal=resume`` returns one
   of {200, 400, 409, 422}. The W31 stub would unconditionally set
   ``state="cancelling"`` on any signal name; the real handler keeps
   the run state untouched for unknown signals, so a "resume" call on
   a non-paused run returns 200 with the run's actual current state
   (``queued`` / ``running`` / ``completed`` — never "cancelling").

Profile validated: default-offline (no network, no real LLM, no
secrets — the recording executor stub keeps runs synchronous and the
heuristic fallback is implicit because no LLM gateway is invoked).

# tdd-red-sha: W33-B1-RED-PENDING
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers (parallels tests/integration/test_v1_runs_real_kernel_binding.py)
# ---------------------------------------------------------------------------


_TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "aborted", "queue_timeout"}
)


def _headers(
    tenant: str = "tenant-w33b1",
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    out = {"X-Tenant-Id": tenant}
    if idempotency_key:
        out["Idempotency-Key"] = idempotency_key
    return out


class _RecordingExecutorFactory:
    """Stub executor factory that records every invocation.

    Mirrors the helper in
    ``tests/integration/test_v1_runs_real_kernel_binding.py`` so the
    fixture pattern is identical. The recording stub keeps runs
    synchronous (no LLM gateway is invoked) which is what the
    default-offline profile requires.
    """

    def __init__(self, *, hold_seconds: float = 0.0) -> None:
        self.invocations: list[dict[str, Any]] = []
        self._hold_seconds = hold_seconds
        self._lock = threading.Lock()

    def __call__(self, run_data: dict[str, Any]):
        with self._lock:
            self.invocations.append(dict(run_data))

        hold = self._hold_seconds

        def _run():
            if hold > 0:
                time.sleep(hold)
            return None  # RunManager treats None as success.

        return _run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_app(tmp_path, monkeypatch):
    """Boot ``build_production_app`` under research posture.

    Sets ``AGENT_SERVER_BACKEND=real`` (default but explicit for
    hermeticity), constructs the production app, and replaces the
    AgentServer's executor factory with a recording stub so runs
    complete in milliseconds without driving any LLM gateway.
    """
    monkeypatch.setenv("AGENT_SERVER_BACKEND", "real")
    # dev posture: JWT auth middleware (W33-C.4) is passthrough; this test
    # asserts kernel dispatch, not auth boundary. Auth coverage lives in
    # tests/integration/test_v1_jwt_auth_middleware.py.
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.setenv("AGENT_SERVER_STATE_DIR", str(tmp_path / "state"))

    from agent_server.bootstrap import build_production_app

    app = build_production_app(state_dir=tmp_path / "state")
    factory = _RecordingExecutorFactory(hold_seconds=0.0)
    backend = app.state.run_backend
    # Sanity: real backend is selected (proves dispatch goes to
    # RealKernelBackend, not the W31 in-process stub).
    assert backend.__class__.__name__ == "RealKernelBackend", backend
    backend.agent_server.executor_factory = factory
    yield app, factory
    backend.aclose()


@pytest.fixture()
def real_client(real_app):
    """TestClient wrapping the real-kernel production app."""
    app, _factory = real_app
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Test 1: signal on unknown run returns 404 — proves real-kernel dispatch.
# ---------------------------------------------------------------------------


# tdd-red-sha: W33-B1-RED-PENDING
def test_signal_unknown_run_returns_404(real_client: TestClient) -> None:
    """POST /v1/runs/{unknown_id}/signal returns 404 NotFoundError.

    The real :class:`RealKernelBackend.signal_run` calls
    ``_record_to_dict`` for ownership verification before acting, which
    raises ``NotFoundError`` for unknown ids. A 404 here proves the
    request reached the real-kernel handler, not the W31 in-process
    stub (which would also 404, but the ``real_app`` fixture asserts
    the real backend is selected).
    """
    body = {"signal": "resume", "payload": {"input": "x"}}
    # Research posture mandates Idempotency-Key on /v1/runs/* mutations
    # (incl. /signal). Supply one so the request reaches the route
    # handler — without it the idempotency middleware short-circuits at
    # 400 and we never exercise the real-kernel dispatch we want to
    # assert on.
    resp = real_client.post(
        "/v1/runs/unknown-run-does-not-exist/signal",
        json=body,
        headers=_headers(idempotency_key="ria-w33b1-signal-unknown"),
    )
    assert resp.status_code == 404, resp.text
    payload = resp.json()
    assert payload.get("error") == "NotFoundError"


# ---------------------------------------------------------------------------
# Test 2: signal=resume on a real run dispatches to real-kernel handler.
# ---------------------------------------------------------------------------


# tdd-red-sha: W33-B1-RED-PENDING
def test_signal_resume_with_input_dispatches_to_real_kernel(
    real_client: TestClient,
) -> None:
    """POST /v1/runs/{run_id}/signal with signal=resume + payload reaches the real handler.

    Asserts dispatch occurred to the real :class:`RunManager`, not the
    kernel-side semantics of "resume on a non-paused run". The W31
    stub would unconditionally set ``state="cancelling"`` on any
    signal name; the real handler keeps run state untouched for
    unknown signals, so this test accepts any of {200, 400, 409, 422}
    as proof of real-kernel handler dispatch and additionally rejects
    the stub's signature behaviour (state mutated to "cancelling" by a
    non-cancel signal).
    """
    body = {
        "profile_id": "default",
        "goal": "signal-resume-dispatch",
        "idempotency_key": "ria-w33b1-signal-resume",
    }
    created = real_client.post(
        "/v1/runs",
        json=body,
        headers=_headers(idempotency_key="ria-w33b1-signal-resume"),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    # POST signal=resume with an input payload (RIA Phase 3+ shape).
    # Supply Idempotency-Key — research posture demands it on all
    # /v1/runs/* mutations.
    resume = real_client.post(
        f"/v1/runs/{run_id}/signal",
        json={"signal": "resume", "payload": {"input": "x"}},
        headers=_headers(idempotency_key="ria-w33b1-signal-resume-2"),
    )

    # Any of these status codes proves the real-kernel handler ran:
    #   200 — current real handler accepts unknown signals as no-op
    #   400 — contract validation (e.g. signal not allowed)
    #   409 — kernel-side state conflict (e.g. resume on non-paused run)
    #   422 — request shape rejected by RunManager
    # The W31 stub always returned 200 regardless of signal name, so
    # 400/409/422 here would also be a strong dispatch signal.
    assert resume.status_code in {200, 400, 409, 422}, resume.text

    # Additional differentiator: the W31 stub's signal_run mutates
    # state to "cancelling" on ANY signal. The real handler only does
    # so for signal="cancel". For signal="resume" the run state must
    # NOT be "cancelling" — it should be the run's actual current
    # lifecycle state.
    if resume.status_code == 200:
        body_out = resume.json()
        assert body_out.get("run_id") == run_id, body_out
        assert body_out.get("state") != "cancelling", (
            "real-kernel handler must not set state=cancelling on a "
            "non-cancel signal; got: " + repr(body_out)
        )
