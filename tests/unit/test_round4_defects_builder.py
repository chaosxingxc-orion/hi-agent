"""Unit tests for round-4 defect fixes F-4 and F-2 in SystemBuilder.

F-4: RawMemoryStore() built without base_dir — L0 never persisted.
F-2: Memory store paths missing profile_id — cross-project contamination.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder(tmp_path):
    """Return a SystemBuilder with episodic_storage_dir pointing at tmp_path."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    cfg = TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))
    return SystemBuilder(config=cfg)


def _make_contract(profile_id: str | None = "test"):
    """Return a minimal TaskContract."""
    from hi_agent.contracts import TaskContract

    # DF-27: builder requires non-empty profile_id; default to 'test-profile'.
    return TaskContract(
        task_id="t1", goal="test goal", profile_id=profile_id or "test-profile"
    )


# ---------------------------------------------------------------------------
# F-4: RawMemoryStore base_dir wiring
# ---------------------------------------------------------------------------


class TestF4RawMemoryStoreBaseDir:
    def test_f4_raw_memory_store_has_base_dir(self, tmp_path):
        """After build_executor(), RunExecutor.raw_memory._base_dir must not be None."""
        builder = _make_builder(tmp_path)
        contract = _make_contract()
        executor = builder.build_executor(contract)
        assert executor.raw_memory._base_dir is not None

    def test_f4_l0_jsonl_created_on_append(self, tmp_path):
        """Appending a RawEventRecord and calling close() must create a .jsonl file on disk."""
        from hi_agent.memory import RawEventRecord

        builder = _make_builder(tmp_path)
        contract = _make_contract()
        executor = builder.build_executor(contract)

        store = executor.raw_memory
        store.append(RawEventRecord(event_type="test_event", payload={"key": "value"}))
        store.close()

        # The JSONL file must now exist under base_dir/logs/memory/L0/
        log_dir = store._base_dir / "logs" / "memory" / "L0"
        jsonl_files = list(log_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1


# ---------------------------------------------------------------------------
# F-2: profile_id path scoping
# ---------------------------------------------------------------------------


class TestF2ProfileIdPathScoping:
    def test_f2_profile_id_scopes_mid_term_path(self, tmp_path):
        """Two different profile_ids must produce different _storage_dir values."""
        builder = _make_builder(tmp_path)
        store_a = builder.build_mid_term_store(profile_id="proj-a")
        store_b = builder.build_mid_term_store(profile_id="proj-b")
        assert store_a._storage_dir != store_b._storage_dir

    def test_f2_profile_id_scopes_long_term_path(self, tmp_path):
        """Two different profile_ids must produce different _storage_path values."""
        builder = _make_builder(tmp_path)
        graph_a = builder.build_long_term_graph(profile_id="proj-a")
        graph_b = builder.build_long_term_graph(profile_id="proj-b")
        assert graph_a._storage_path != graph_b._storage_path
