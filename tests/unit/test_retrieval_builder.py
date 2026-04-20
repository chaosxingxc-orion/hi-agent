"""Unit tests for RetrievalBuilder extraction."""
import importlib
import inspect
import uuid

import pytest
from hi_agent.config import memory_builder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.knowledge.retrieval_engine import RetrievalEngine


def _config():
    return TraceConfig(episodic_storage_dir=f".hi_agent/test-{uuid.uuid4().hex}/episodes")


def _load_retrieval_builder():
    try:
        module = importlib.import_module("hi_agent.config.retrieval_builder")
    except ModuleNotFoundError as exc:
        pytest.fail(f"retrieval_builder module missing: {exc}")
    return module, module.RetrievalBuilder


class TestRetrievalBuilderBasic:
    def test_returns_retrieval_engine(self):
        _, RetrievalBuilder = _load_retrieval_builder()
        builder = RetrievalBuilder(_config())

        engine = builder.build_retrieval_engine()

        assert isinstance(engine, RetrievalEngine)

    def test_embedding_fn_set_at_construction(self):
        _, RetrievalBuilder = _load_retrieval_builder()
        builder = RetrievalBuilder(_config())

        engine = builder.build_retrieval_engine()

        assert hasattr(engine, "_embedding_fn")

    def test_tfidf_index_consistent_with_embedding(self):
        _, RetrievalBuilder = _load_retrieval_builder()
        builder = RetrievalBuilder(_config())

        engine = builder.build_retrieval_engine()

        if engine._embedding_fn is not None:
            assert engine._tfidf is not None

    def test_no_post_construction_mutation_needed(self, monkeypatch):
        _, RetrievalBuilder = _load_retrieval_builder()
        original_init = RetrievalEngine.__init__
        captured = {}

        def capture_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured["embedding_fn"] = self._embedding_fn

        monkeypatch.setattr(RetrievalEngine, "__init__", capture_init)
        builder = RetrievalBuilder(_config())

        engine = builder.build_retrieval_engine()

        assert captured["embedding_fn"] is engine._embedding_fn


class TestNoPostConstructionMutation:
    def test_memory_builder_no_post_assignment(self):
        source = inspect.getsource(memory_builder)

        assert "engine._embedding_fn" not in source

    def test_retrieval_builder_is_standalone(self):
        retrieval_builder, _ = _load_retrieval_builder()
        source = inspect.getsource(retrieval_builder)

        assert "MemoryBuilder" not in source
        assert "SystemBuilder" not in source
