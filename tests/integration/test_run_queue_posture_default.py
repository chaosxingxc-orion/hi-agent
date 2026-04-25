"""Integration tests for RO-3: RunQueue SQLite path resolves from posture.

Layer 2 — Integration: real RunQueue class instantiated under different
posture env vars.  No mocks on the subsystem under test.
"""
from __future__ import annotations

from hi_agent.server.run_queue import RunQueue


class TestRunQueuePostureDefault:
    """RO-3: verify that RunQueue selects :memory: under dev and file-backed
    under research/prod posture."""

    def test_dev_posture_uses_memory(self, monkeypatch):
        """Under dev posture (default), RunQueue should be in-memory."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        q = RunQueue()
        assert q.db_path == ":memory:"
        q.close()

    def test_research_posture_uses_file(self, monkeypatch, tmp_path):
        """Under research posture, RunQueue should be file-backed."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        q = RunQueue()
        assert q.db_path != ":memory:"
        expected = str(tmp_path / "run_queue.sqlite")
        assert q.db_path == expected
        q.close()

    def test_prod_posture_uses_file(self, monkeypatch, tmp_path):
        """Under prod posture, RunQueue should be file-backed."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        q = RunQueue()
        assert q.db_path != ":memory:"
        q.close()

    def test_explicit_memory_overrides_research_posture(self, monkeypatch):
        """Explicit db_path=':memory:' bypasses posture resolution."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        q = RunQueue(db_path=":memory:")
        assert q.db_path == ":memory:"
        q.close()

    def test_explicit_file_path_is_used_directly(self, tmp_path, monkeypatch):
        """Explicit db_path is used as-is, regardless of posture."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        explicit = str(tmp_path / "explicit.sqlite")
        q = RunQueue(db_path=explicit)
        assert q.db_path == explicit
        q.close()

    def test_research_posture_default_data_dir_fallback(self, monkeypatch, tmp_path):
        """When HI_AGENT_DATA_DIR is not set, default path is ./hi_agent_data/run_queue.sqlite."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
        # Change to tmp_path so we don't pollute the repo
        monkeypatch.chdir(tmp_path)
        q = RunQueue()
        assert "hi_agent_data" in q.db_path
        assert "run_queue.sqlite" in q.db_path
        q.close()

    def test_file_backed_queue_is_functional(self, monkeypatch, tmp_path):
        """A file-backed RunQueue under research posture can enqueue and claim."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        q = RunQueue()
        q.enqueue(run_id="run-001", priority=5, payload_json='{"goal": "x"}')
        claim = q.claim_next(worker_id="test-worker")
        assert claim is not None
        assert claim["run_id"] == "run-001"
        q.close()
