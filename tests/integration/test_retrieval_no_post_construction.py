"""Integration coverage for retrieval construction-time embedding wiring."""

import uuid

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.knowledge.retrieval_engine import RetrievalEngine


def test_retrieval_engine_embedding_fn_at_construction_time():
    builder = SystemBuilder(
        config=TraceConfig(episodic_storage_dir=f".hi_agent/test-{uuid.uuid4().hex}/episodes")
    )

    engine = builder.build_retrieval_engine(profile_id="integration-test")
    embedding_fn = engine._embedding_fn

    assert isinstance(engine, RetrievalEngine)
    assert hasattr(engine, "_embedding_fn")
    assert engine._embedding_fn is embedding_fn
    if embedding_fn is not None:
        assert engine._tfidf is not None
