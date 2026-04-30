"""Integration tests for RO-7: idempotency snapshot uses terminal state.

Verifies that a cancelled run produces a "cancelled" idempotency snapshot,
not a "completed" one.

Layer 2 — Integration: real RunManager + real IdempotencyStore.
Zero MagicMock on the subsystem under test.
"""
from __future__ import annotations

import time

import pytest
from hi_agent.server.idempotency import IdempotencyStore
from hi_agent.server.run_manager import ManagedRun, RunManager
from hi_agent.server.tenant_context import TenantContext


@pytest.fixture()
def store(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


@pytest.fixture()
def manager(store):
    rm = RunManager(idempotency_store=store)
    yield rm
    rm.shutdown()


def _noop_executor(run: ManagedRun):
    """Executor that completes successfully."""

    class _Result:
        status = "completed"
        error = None
        llm_fallback_count = 0
        finished_at = None
        fallback_events: list = []  # noqa: RUF012  expiry_wave: Wave 26

        def to_dict(self):
            return {"status": "completed"}

    return _Result()


def _failing_executor(run: ManagedRun):
    """Executor that raises to simulate a failure."""
    raise RuntimeError("simulated failure")


class TestTerminalStateMapping:
    """RO-7: mark_complete should be called with the correct terminal code."""

    def test_successful_run_stores_succeeded_terminal_state(self, manager, store):
        """A run that completes normally must record 'succeeded' in idempotency."""
        workspace = TenantContext(tenant_id="tenant-1", user_id="u1")
        payload = {"goal": "succeed", "idempotency_key": "idem-succeed-001"}

        run = manager.create_run(payload, workspace=workspace)
        assert run.outcome == "created"

        manager.start_run(run.run_id, _noop_executor)
        # Wait for the run thread to finish.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if run.state in ("completed", "failed", "cancelled"):
                break

        assert run.state == "completed"

        # Replay the key — record should show "succeeded" terminal state.
        from hi_agent.server.idempotency import _hash_payload

        hash_val = _hash_payload({k: v for k, v in payload.items() if k != "idempotency_key"})
        outcome, record = store.reserve_or_replay(
            tenant_id="tenant-1",
            idempotency_key="idem-succeed-001",
            request_hash=hash_val,
            run_id="replay-probe",
        )
        assert outcome == "replayed"
        assert record.status == "succeeded", f"Expected 'succeeded', got {record.status!r}"

    def test_failed_run_stores_failed_terminal_state(self, manager, store):
        """A run that raises an exception must record 'failed' in idempotency."""
        workspace = TenantContext(tenant_id="tenant-1", user_id="u1")
        payload = {"goal": "fail", "idempotency_key": "idem-fail-001"}

        run = manager.create_run(payload, workspace=workspace)
        manager.start_run(run.run_id, _failing_executor)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if run.state in ("completed", "failed", "cancelled"):
                break

        assert run.state == "failed"

        from hi_agent.server.idempotency import _hash_payload

        hash_val = _hash_payload({k: v for k, v in payload.items() if k != "idempotency_key"})
        outcome, record = store.reserve_or_replay(
            tenant_id="tenant-1",
            idempotency_key="idem-fail-001",
            request_hash=hash_val,
            run_id="replay-probe",
        )
        assert outcome == "replayed"
        assert record.status == "failed", f"Expected 'failed', got {record.status!r}"

    def test_cancelled_run_stores_cancelled_terminal_state(self, manager, store):
        """A cancelled run must record 'cancelled' in idempotency."""
        import threading

        started_event = threading.Event()
        cancel_event = threading.Event()

        def _blocking_executor(run: ManagedRun):
            """Executor that blocks until cancel_event is set."""
            started_event.set()
            cancel_event.wait(timeout=5.0)

            class _Result:
                status = "cancelled"
                error = "cancelled"
                llm_fallback_count = 0
                finished_at = None
                fallback_events: list = []  # noqa: RUF012  expiry_wave: Wave 26

                def to_dict(self):
                    return {"status": "cancelled"}

            return _Result()

        workspace = TenantContext(tenant_id="tenant-1", user_id="u1")
        payload = {"goal": "cancel", "idempotency_key": "idem-cancel-001"}

        run = manager.create_run(payload, workspace=workspace)
        manager.start_run(run.run_id, _blocking_executor)

        # Wait for executor to start.
        started_event.wait(timeout=5.0)
        cancel_event.set()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if run.state in ("completed", "failed", "cancelled"):
                break

        # The executor returned status="cancelled", so run.state should reflect it.
        assert run.state == "cancelled", f"Expected 'cancelled', got {run.state!r}"

        from hi_agent.server.idempotency import _hash_payload

        hash_val = _hash_payload({k: v for k, v in payload.items() if k != "idempotency_key"})
        outcome, record = store.reserve_or_replay(
            tenant_id="tenant-1",
            idempotency_key="idem-cancel-001",
            request_hash=hash_val,
            run_id="replay-probe",
        )
        assert outcome == "replayed"
        assert record.status == "cancelled", f"Expected 'cancelled', got {record.status!r}"


class TestRunStateToTerminal:
    """Unit-level test for the _run_state_to_terminal helper."""

    def test_completed_maps_to_succeeded(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("completed") == "succeeded"

    def test_succeeded_maps_to_succeeded(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("succeeded") == "succeeded"

    def test_failed_maps_to_failed(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("failed") == "failed"

    def test_cancelled_maps_to_cancelled(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("cancelled") == "cancelled"

    def test_timed_out_maps_to_timed_out(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("timed_out") == "timed_out"
        assert _run_state_to_terminal("queue_timeout") == "timed_out"

    def test_unknown_maps_to_failed(self):
        from hi_agent.server.run_manager import _run_state_to_terminal

        assert _run_state_to_terminal("unknown_state") == "failed"
