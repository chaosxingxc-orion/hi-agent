"""Tests for G-10 experiment artifact provenance."""
import hashlib
import json
from unittest.mock import MagicMock

import pytest


class TestArtifactHashing:
    def test_hash_artifact_sha256(self, tmp_path):
        """_hash_artifact must return correct SHA-256 hex digest."""
        from hi_agent.experiment.provenance import hash_artifact
        f = tmp_path / "results.json"
        content = b'{"accuracy": 0.92, "loss": 0.08}'
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert hash_artifact(f) == expected

    def test_hash_artifact_deterministic(self, tmp_path):
        """Same content always produces same hash."""
        from hi_agent.experiment.provenance import hash_artifact
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world" * 1000)
        h1 = hash_artifact(f)
        h2 = hash_artifact(f)
        assert h1 == h2

    def test_hash_artifact_different_content_different_hash(self, tmp_path):
        """Different content produces different hash."""
        from hi_agent.experiment.provenance import hash_artifact
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert hash_artifact(f1) != hash_artifact(f2)

    def test_hash_artifact_large_file(self, tmp_path):
        """Must handle files larger than a single read chunk."""
        from hi_agent.experiment.provenance import hash_artifact
        f = tmp_path / "large.bin"
        data = b"x" * (200 * 1024)  # 200 KB > 65536 chunk size
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert hash_artifact(f) == expected


class TestArtifactRecord:
    def test_artifact_record_from_path(self, tmp_path):
        """ArtifactRecord.from_path computes all fields."""
        from hi_agent.experiment.provenance import ArtifactRecord
        f = tmp_path / "metrics.json"
        f.write_text('{"loss": 0.1}', encoding="utf-8")
        record = ArtifactRecord.from_path(f)
        assert record.uri == str(f)
        assert len(record.sha256) == 64  # full hex digest
        assert record.size == f.stat().st_size
        assert record.mime  # non-empty

    def test_artifact_record_serializable(self, tmp_path):
        """ArtifactRecord must be JSON-serializable."""
        import dataclasses

        from hi_agent.experiment.provenance import ArtifactRecord
        f = tmp_path / "out.txt"
        f.write_text("done")
        record = ArtifactRecord.from_path(f)
        d = dataclasses.asdict(record)
        json.dumps(d)  # must not raise


class TestPollerArtifactIndexing:
    @pytest.mark.asyncio
    async def test_poller_emits_artifact_indexed_event(self, tmp_path):
        """On op success, poller emits experiment.artifact_indexed per artifact."""
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.op_store import LongRunningOpStore, OpStatus
        from hi_agent.experiment.poller import OpPoller

        # Create artifact files that the backend will "return"
        artifact = tmp_path / "results.json"
        artifact.write_text('{"accuracy": 0.95}', encoding="utf-8")

        backend = MagicMock()
        backend.submit.return_value = "ext-prov-01"
        backend.status.return_value = "succeeded"
        backend.fetch_artifacts.return_value = [str(artifact)]

        store = LongRunningOpStore(db_path=tmp_path / "ops.db")
        coord = LongRunningOpCoordinator(store=store)
        coord.register_backend("mock", backend)

        h = coord.submit(op_spec={}, backend_name="mock")
        store.update_status(h.op_id, OpStatus.RUNNING)

        events = []
        poller = OpPoller(
            coordinator=coord, store=store,
            poll_interval=0.01,
            on_event=lambda e: events.append(e),
        )
        await poller.poll_once()

        # Must emit experiment.artifact_indexed
        indexed = [e for e in events if e.get("type") == "experiment.artifact_indexed"]
        assert len(indexed) == 1
        assert indexed[0]["uri"] == str(artifact)
        assert len(indexed[0]["sha256"]) == 64
        assert indexed[0]["size"] > 0

    @pytest.mark.asyncio
    async def test_poller_skips_hashing_nonexistent_path(self, tmp_path):
        """Poller must not crash if an artifact path does not exist."""
        from hi_agent.experiment.coordinator import LongRunningOpCoordinator
        from hi_agent.experiment.op_store import LongRunningOpStore, OpStatus
        from hi_agent.experiment.poller import OpPoller

        backend = MagicMock()
        backend.submit.return_value = "ext-prov-02"
        backend.status.return_value = "succeeded"
        backend.fetch_artifacts.return_value = ["/does/not/exist/file.bin"]

        store = LongRunningOpStore(db_path=tmp_path / "ops.db")
        coord = LongRunningOpCoordinator(store=store)
        coord.register_backend("mock", backend)
        h = coord.submit(op_spec={}, backend_name="mock")
        store.update_status(h.op_id, OpStatus.RUNNING)

        events = []
        poller = OpPoller(
            coordinator=coord, store=store, poll_interval=0.01,
            on_event=lambda e: events.append(e),
        )
        await poller.poll_once()  # must not raise

        # result_posted still emitted even if artifact hash fails
        assert any(e.get("type") == "experiment.result_posted" for e in events)


class TestExecutionProvenanceExtension:
    def test_execution_provenance_has_experiment_artifacts(self):
        """ExecutionProvenance must accept experiment_artifacts field."""
        try:
            from hi_agent.trace.provenance import ExecutionProvenance
        except ImportError:
            pytest.skip("ExecutionProvenance not found")
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ExecutionProvenance)}
        assert "experiment_artifacts" in fields, (
            "ExecutionProvenance must have experiment_artifacts: list[dict] field"
        )
