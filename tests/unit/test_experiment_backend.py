"""Tests for G-9 ExperimentBackend protocol and LocalBackend."""
import time
import pytest
from pathlib import Path
from unittest.mock import patch


class TestExperimentBackendProtocol:
    def test_local_backend_implements_protocol(self):
        """LocalBackend must satisfy ExperimentBackend protocol."""
        from hi_agent.experiment.backend import ExperimentBackend
        from hi_agent.experiment.backend.local import LocalBackend
        import typing
        # Runtime check that LocalBackend has all required methods
        required = ["submit", "status", "fetch_artifacts", "cancel"]
        backend = LocalBackend(work_dir=Path("."))
        for method in required:
            assert hasattr(backend, method), f"LocalBackend missing method: {method}"

    def test_ssh_backend_implements_protocol(self):
        """SSHBackend must satisfy ExperimentBackend protocol."""
        from hi_agent.experiment.backend.ssh import SSHBackend
        required = ["submit", "status", "fetch_artifacts", "cancel"]
        backend = SSHBackend(host="localhost", user="test", work_dir="/tmp")
        for method in required:
            assert hasattr(backend, method), f"SSHBackend missing method: {method}"


class TestLocalBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        from hi_agent.experiment.backend.local import LocalBackend
        return LocalBackend(work_dir=tmp_path)

    def test_submit_returns_external_id(self, backend):
        """submit() must return a non-empty string external_id immediately."""
        ext_id = backend.submit({"command": "echo hello"})
        assert isinstance(ext_id, str)
        assert ext_id  # non-empty

    def test_submit_creates_run_directory(self, backend, tmp_path):
        """Each submitted op gets its own run directory."""
        ext_id = backend.submit({"command": "echo hi"})
        run_dir = tmp_path / ext_id
        assert run_dir.exists()

    def test_status_running_then_succeeded(self, backend):
        """A quick command should eventually reach 'succeeded'."""
        ext_id = backend.submit({"command": "echo done"})
        # Poll until succeeded (max 5s for a quick echo)
        deadline = time.time() + 5
        while time.time() < deadline:
            s = backend.status(ext_id)
            if s in ("succeeded", "failed"):
                break
            time.sleep(0.1)
        assert backend.status(ext_id) == "succeeded"

    def test_status_failed_for_bad_command(self, backend):
        """A failing command should reach 'failed' status."""
        import sys
        # Use a list command to avoid shell quoting issues on Windows
        ext_id = backend.submit({"command": [sys.executable, "-c", "import sys; sys.exit(1)"]})
        deadline = time.time() + 5
        while time.time() < deadline:
            s = backend.status(ext_id)
            if s in ("succeeded", "failed"):
                break
            time.sleep(0.1)
        assert backend.status(ext_id) == "failed"

    def test_fetch_artifacts_returns_list(self, backend):
        """fetch_artifacts must return a list (may be empty)."""
        ext_id = backend.submit({"command": "echo hello"})
        time.sleep(0.5)
        artifacts = backend.fetch_artifacts(ext_id)
        assert isinstance(artifacts, list)

    def test_fetch_artifacts_includes_stdout_log(self, backend, tmp_path):
        """stdout.log should be listed as an artifact."""
        ext_id = backend.submit({"command": "echo hello"})
        time.sleep(0.5)
        artifacts = backend.fetch_artifacts(ext_id)
        assert any("stdout" in str(a) for a in artifacts), f"Expected stdout in artifacts: {artifacts}"

    def test_cancel_running_process(self, backend):
        """cancel() must terminate a running process."""
        import sys
        # Use list form to avoid shell quoting issues on Windows
        ext_id = backend.submit({"command": [sys.executable, "-c", "import time; time.sleep(60)"]})
        time.sleep(0.2)
        assert backend.status(ext_id) == "running"
        backend.cancel(ext_id)
        time.sleep(0.3)
        assert backend.status(ext_id) in ("cancelled", "failed")

    def test_status_unknown_for_nonexistent_ext_id(self, backend):
        """Unknown external_id must return 'unknown'."""
        assert backend.status("does-not-exist") == "unknown"


class TestSSHBackendStub:
    def test_ssh_backend_submit_raises_not_configured(self):
        """SSHBackend stub must raise when called without real SSH setup."""
        from hi_agent.experiment.backend.ssh import SSHBackend
        backend = SSHBackend(host="localhost", user="test", work_dir="/tmp")
        with pytest.raises((NotImplementedError, RuntimeError, Exception)):
            backend.submit({"command": "echo hi"})


class TestBackendIntegrationWithCoordinator:
    @pytest.fixture
    def coord_with_local(self, tmp_path):
        from hi_agent.experiment.op_store import LongRunningOpStore
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.backend.local import LocalBackend
        store = LongRunningOpStore(db_path=tmp_path / "ops.db")
        coord = LongRunningOpCoordinator(store=store)
        coord.register_backend("local", LocalBackend(work_dir=tmp_path / "runs"))
        return coord

    def test_submit_via_coordinator_returns_handle(self, coord_with_local):
        from hi_agent.experiment.op_store import OpStatus
        h = coord_with_local.submit(op_spec={"command": "echo hello"}, backend_name="local")
        assert h.op_id
        assert h.external_id
        assert h.status == OpStatus.PENDING

    @pytest.mark.asyncio
    async def test_poller_marks_succeeded_after_echo(self, coord_with_local, tmp_path):
        """End-to-end: submit echo, poll, assert succeeded."""
        import asyncio, time
        from hi_agent.experiment.op_store import LongRunningOpStore, OpStatus
        from hi_agent.experiment.poller import OpPoller

        # Submit
        h = coord_with_local.submit(op_spec={"command": "echo result"}, backend_name="local")
        # Wait for process to finish
        await asyncio.sleep(0.8)
        # Update to RUNNING so poller processes it
        store = coord_with_local._store
        store.update_status(h.op_id, OpStatus.RUNNING)

        events = []
        poller = OpPoller(
            coordinator=coord_with_local,
            store=store,
            poll_interval=0.05,
            on_event=lambda e: events.append(e),
        )
        await poller.poll_once()

        h2 = store.get(h.op_id)
        assert h2.status == OpStatus.SUCCEEDED
        assert any(e.get("type") == "experiment.result_posted" for e in events)
