"""Integration tests for G-8 long-running op coordinator."""

import time
from unittest.mock import MagicMock

import pytest

# OpStore tests


class TestLongRunningOpStore:
    @pytest.fixture
    def store(self, tmp_path):
        from hi_agent.experiment.op_store import LongRunningOpStore

        return LongRunningOpStore(db_path=tmp_path / "ops.db")

    def test_create_and_retrieve(self, store):
        from hi_agent.experiment.op_store import OpStatus

        h = store.create(
            op_id="op-001", backend="local", external_id="pid-1", submitted_at=time.time()
        )
        assert h.op_id == "op-001"
        retrieved = store.get("op-001")
        assert retrieved is not None
        assert retrieved.status == OpStatus.PENDING

    def test_update_status_to_running(self, store):
        from hi_agent.experiment.op_store import OpStatus

        store.create(op_id="op-002", backend="local", external_id="pid-2", submitted_at=time.time())
        store.update_status("op-002", OpStatus.RUNNING, heartbeat_at=time.time())
        h = store.get("op-002")
        assert h.status == OpStatus.RUNNING

    def test_update_status_to_succeeded_with_artifacts(self, store):
        from hi_agent.experiment.op_store import OpStatus

        store.create(op_id="op-003", backend="ssh", external_id="job-3", submitted_at=time.time())
        store.update_status(
            "op-003",
            OpStatus.SUCCEEDED,
            completed_at=time.time(),
            artifacts_uri="s3://bucket/out.tar.gz",
        )
        h = store.get("op-003")
        assert h.status == OpStatus.SUCCEEDED
        assert "s3://" in h.artifacts_uri

    def test_handle_survives_store_recreation(self, tmp_path):
        """Simulate server restart 鈥?new store instance reads existing DB."""
        from hi_agent.experiment.op_store import LongRunningOpStore

        db = tmp_path / "ops.db"
        s1 = LongRunningOpStore(db_path=db)
        s1.create(
            op_id="op-restart", backend="local", external_id="pid-99", submitted_at=time.time()
        )
        del s1  # simulate shutdown
        s2 = LongRunningOpStore(db_path=db)
        h = s2.get("op-restart")
        assert h is not None
        assert h.backend == "local"

    def test_list_active_excludes_completed(self, store):
        from hi_agent.experiment.op_store import OpStatus

        store.create(op_id="a1", backend="local", external_id="e1", submitted_at=time.time())
        store.create(op_id="a2", backend="local", external_id="e2", submitted_at=time.time())
        store.update_status("a2", OpStatus.SUCCEEDED, completed_at=time.time())
        active = store.list_active()
        ids = [h.op_id for h in active]
        assert "a1" in ids
        assert "a2" not in ids

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("does-not-exist") is None


# Coordinator tests


class TestLongRunningOpCoordinator:
    """Tests for LongRunningOpCoordinator.

    The SUT is LongRunningOpCoordinator (and LongRunningOpStore).
    ``backend`` is a MagicMock of the pluggable backend interface (e.g. slurm, ssh,
    local subprocess).  This is an external seam — the coordinator delegates
    job scheduling to the backend; the backend is not part of the subsystem
    under test.  Boundary mock: MagicMock is intentionally mocking the
    external job-scheduling backend, not the SUT.
    """

    @pytest.fixture
    def coord(self, tmp_path):
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.op_store import LongRunningOpStore

        store = LongRunningOpStore(db_path=tmp_path / "ops.db")
        return LongRunningOpCoordinator(store=store)

    def test_submit_returns_handle_immediately(self, coord):
        from hi_agent.experiment.op_store import OpStatus

        # Boundary mock: backend is an external job-scheduling adapter (slurm/ssh/local),
        # not part of the coordinator/store subsystem under test.
        backend = MagicMock()
        backend.submit.return_value = "ext-id-001"
        coord.register_backend("mock", backend)
        handle = coord.submit(op_spec={"command": "train.py"}, backend_name="mock")
        assert handle.op_id
        assert handle.status == OpStatus.PENDING
        assert handle.external_id == "ext-id-001"
        backend.submit.assert_called_once_with({"command": "train.py"})

    def test_get_returns_handle(self, coord):
        # Boundary mock: external job-scheduling backend, not the SUT.
        backend = MagicMock()
        backend.submit.return_value = "ext-002"
        coord.register_backend("mock", backend)
        h = coord.submit(op_spec={}, backend_name="mock")
        retrieved = coord.get(h.op_id)
        assert retrieved is not None
        assert retrieved.op_id == h.op_id

    def test_cancel_marks_cancelled(self, coord):
        from hi_agent.experiment.op_store import OpStatus

        # Boundary mock: external job-scheduling backend, not the SUT.
        backend = MagicMock()
        backend.submit.return_value = "ext-003"
        coord.register_backend("mock", backend)
        h = coord.submit(op_spec={}, backend_name="mock")
        result = coord.cancel(h.op_id)
        assert result is True
        backend.cancel.assert_called_once_with("ext-003")
        h2 = coord.get(h.op_id)
        assert h2.status == OpStatus.CANCELLED

    def test_cancel_nonexistent_returns_false(self, coord):
        assert coord.cancel("nonexistent") is False


# Poller tests


class TestOpPoller:
    """Tests for OpPoller.

    The SUT is OpPoller (which wraps a real LongRunningOpCoordinator and LongRunningOpStore).
    ``backend`` is a MagicMock of the external job-scheduling adapter.
    Boundary mock: MagicMock is intentionally mocking the external backend
    (status/fetch_artifacts), not the poller or coordinator subsystems under test.
    """

    @pytest.fixture
    def setup(self, tmp_path):
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.op_store import LongRunningOpStore, OpStatus
        from hi_agent.experiment.poller import OpPoller

        store = LongRunningOpStore(db_path=tmp_path / "ops.db")
        coord = LongRunningOpCoordinator(store=store)
        return store, coord, OpPoller, OpStatus

    @pytest.mark.asyncio
    async def test_poller_marks_succeeded_on_backend_done(self, setup):
        store, coord, op_poller_cls, op_status_cls = setup
        # Boundary mock: external backend (slurm/ssh/local); poller/coordinator/store are real.
        backend = MagicMock()
        backend.submit.return_value = "ext-poll-01"
        backend.status.return_value = "succeeded"
        backend.fetch_artifacts.return_value = ["file:///out/results.json"]
        coord.register_backend("mock", backend)
        h = coord.submit(op_spec={}, backend_name="mock")
        store.update_status(h.op_id, op_status_cls.RUNNING)

        events = []
        poller = op_poller_cls(
            coordinator=coord, store=store, poll_interval=0.01, on_event=lambda e: events.append(e)
        )
        await poller.poll_once()

        h2 = store.get(h.op_id)
        assert h2.status == op_status_cls.SUCCEEDED
        assert any(e.get("type") == "experiment.result_posted" for e in events)

    @pytest.mark.asyncio
    async def test_poller_emits_heartbeat_for_running(self, setup):
        store, coord, op_poller_cls, op_status_cls = setup
        # Boundary mock: external backend (slurm/ssh/local); poller/coordinator/store are real.
        backend = MagicMock()
        backend.submit.return_value = "ext-poll-02"
        backend.status.return_value = "running"
        coord.register_backend("mock", backend)
        h = coord.submit(op_spec={}, backend_name="mock")
        store.update_status(h.op_id, op_status_cls.RUNNING)

        events = []
        poller = op_poller_cls(
            coordinator=coord, store=store, poll_interval=0.01, on_event=lambda e: events.append(e)
        )
        await poller.poll_once()
        assert any(e.get("type") == "experiment.heartbeat" for e in events)
